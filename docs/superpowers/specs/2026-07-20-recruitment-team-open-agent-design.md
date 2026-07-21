# V3 Recruitment Team — Open-Ended Deep Agent Design

Status: design approved by user, pending write-up review before implementation planning.

## Motivation

The V3 "AI Recruitment Team" target-assessment flow (`backend/recruitment_team/target_assessment.py`)
is a fixed pipeline: always run all 5 personas (recruiter, hiring manager, ATS, skeptic,
market researcher) in parallel, always synthesize, always judge, at most one scripted
correction pass. Every model call across the entire `recruitment_team` module uses
`tool_choice=<exact tool name>` — there is no point in the system where a model
chooses which tool to call, or whether to call one at all.

This was not an evolution of this codebase's existing agent work. `backend/resume_agent/agent.py`
wraps `deepagents.create_deep_agent()`, and its defaults (`ORCHESTRATOR_TOOLS`,
`create_persona_subagents()`) describe a real, multi-tool orchestrator with genuine
LangGraph iteration (a recursion limit, not a single forced call). V3's `recruitment_team`
module does not import `deepagents` or `langgraph` at all — it is a separate, from-scratch,
fully bounded system built alongside a working deep agent, not on top of it.

**Correction from spec review:** the claim that this orchestrator engine is "tested" needs
a caveat. The only production call site, `resume_agent/session.py:693-697`, explicitly
overrides the defaults with `tools=SYNTHESIS_TOOLS, subagents=[]` — real persona review
in the shipped product happens through a separate code path
(`personas.iter_persona_worker_runs`, direct `model.bind_tools(..., tool_choice=...)`
calls in a thread pool), not through `deepagents`' subagent-delegation (`task` tool)
mechanism. No test in this repo invokes a `create_deep_agent()` graph with real subagents
and calls `.invoke()` end-to-end. What's genuinely tested and reusable is the LangGraph
tool-calling loop itself (`create_deep_agent`, `run_agent_turn`, the recursion limit) and
the accept/reject diff mechanism (`resume_agent/diffs.py`, `validation_gates.py`). Subagent
delegation via `task` is a real `deepagents` library feature this codebase has wired up
but never exercised — this design is the first thing that will actually prove it out, not
a reuse of a proven path. Implementation planning should treat "delegate to a persona
subagent and get a schema-enforced result back" as a spike to validate early, before
building the rest of the flow on top of it.

The measured lesson recorded in `~/.agent-memory/lessons/job-hunter-sg.md` ("14 calls/
53,664 tokens down to 7 calls/28,386 tokens by removing ceremonial planning/search
calls") is about wasted, repeated, non-progressing calls (the trace showed duplicate
`search_jobs` calls) at the orchestrator level — it is not evidence that giving the
orchestrator real choice over which personas to consult is itself a bad idea. The
persona review calls themselves already are, and remain, one schema-enforced
submission each; that part of the lesson does not change here.

Separately: the SEA-LION API used throughout this project is free-tier with no
per-token cost, so raw token/call volume is not a cost concern. The real constraint
is the rate limit (`SEALION_REQ_PER_MIN`, currently 9 req/min per key) — more calls cost wall-clock latency, and more
calls are more chances to hit exactly the kind of structural failure (escaping,
truncation, evidence mismatches) this session spent hours diagnosing and fixing. The
design below treats latency and reliability, not dollars, as the thing to budget for.

## Goals

- Replace the fixed 5-persona/synthesis/judge pipeline in target assessment with one
  open-ended agent that genuinely decides which personas to consult, in what order,
  how many times, and whether it needs a synthesis pass at all.
- Let the same agent propose concrete resume edits as part of its own reasoning
  (not a separate, gated-off capability) and run an interview loop that asks the
  candidate directly when it hits a real evidence gap.
- Reuse `resume_agent`'s existing, tested `deepagents`/LangGraph tool-calling engine
  as the actual runtime rather than building a new agent engine for V3, validating
  its (wired-up but not yet exercised) persona-subagent delegation pattern as part
  of this work rather than assuming it already works in production.

## Non-goals

- This does not change candidate-profile extraction (`candidate_profile.py`), job
  search/discovery, or the underlying SQLite persistence layer (threads, messages,
  activity events). Those stages are mechanical (parsing, retrieval) rather than
  reasoning, and are out of scope for this change.
- This does not remove the two hard safety boundaries below. "Genuinely free" means
  free in *how the agent reasons and what it consults*, not free to fabricate
  content or silently alter a saved resume.

## Non-negotiable boundaries

Two things stay hard-gated regardless of how open the reasoning is:

1. **No fabrication.** Every claim in a proposed edit must trace to either a literal
   resume quote already on file or something the candidate explicitly answered via
   the interview tool in this conversation. Nothing else is a valid citation.
2. **No silent edits.** A proposed edit is never applied to the saved resume without
   the candidate's explicit accept action. Rejected or unaddressed proposals never
   leak into a saved version.

### Deliberate deviation from the PRD's assessment/editing split

`docs/v3-ai-recruitment-team-prd.md` states as a hard implementation decision:
"Assessment receives no edit tool. Editing is entered only after an explicit user
action." This design puts `propose_resume_edit` in the same tool set as the
read/search/consult tools, available to the agent throughout — the two capabilities
are not gated apart by tool availability. That is a deliberate, explicit override of
the PRD's stated boundary (made by the user during this brainstorm, in favor of one
agent that reasons and edits in the same continuous flow), not an oversight.

Because that gate is gone, the two boundaries above become the entire safety net, and
the design compensates by making them stricter, not just present:
- The independent quality judge (see Architecture) stays a **mandatory** final step
  over whatever the agent produces, regardless of how open the path to get there was —
  it is not optional just because the reasoning is.
- `ask_candidate` genuinely ends the turn in code, not by prompted convention (see
  Architecture) — a model cannot invent an answer to its own question and cite it.
- There is a hard per-run cap on `propose_resume_edit` calls before the run must
  checkpoint back to the user (see Efficiency guardrails) — nothing about "genuinely
  free reasoning" extends to producing an unbounded pile of proposed edits in one run.

## Architecture

### Engine

Reuse `resume_agent.agent.create_deep_agent()` (via `deepagents.create_deep_agent`)
as the orchestrator runtime for the V3 target-job flow, replacing
`NativeTargetAssessmentRunner` in `target_assessment.py`. This is the same engine
`resume_agent/session.py` already runs in production for the classic resume-coach
flow — no new agent framework is introduced.

### Tool registry (new, V3-specific)

A new tool set (parallel to `resume_agent.tooling.registry.ORCHESTRATOR_TOOLS`),
bound to this agent instance:

- `read_candidate_evidence` — read the already-extracted, evidence-cited candidate
  profile fields for the active resume (read-only; extraction itself is unchanged).
- `read_target_job` — read the full target job description and the already-derived
  role-success criteria, so the agent can reason about fit itself rather than only
  trusting a separately-bounded extraction.
- `search_jobs` — the existing `resume_agent.tools.search_jobs` LangChain tool
  (already in `ORCHESTRATOR_TOOLS`), reused as-is, so the agent can pull in
  comparable postings on its own initiative.
- `propose_resume_edit` (new) — draft a specific, evidence-cited **in-place rewrite
  of one existing resume block** (matching what `resume_agent/tools.py:propose_edit`
  and `resume_document.py:apply_resume_patch` actually support today — a single-block
  replacement, no embedded newlines). Every call is validated against the fabrication
  boundary above before it is persisted as a pending, unaccepted diff (reusing the
  existing fact-preservation/hallucination gates in `validation_gates.py` and the
  accept/reject diff mechanism already in `resume_agent/diffs.py`). **Scope note:**
  inserting a new bullet/section entry or deleting one outright needs new document-patch
  semantics (span insertion, block deletion, renumbering) that don't exist in
  `resume_document.py` yet — that's follow-on work, not this design's v1. V1 only
  rewrites blocks that already exist.
- `ask_candidate` (new) — surface one explicit, focused question about a missing
  gap. Calling this tool **hard-ends the agent's turn in code**: any tool calls the
  model attempts in the same turn after `ask_candidate` are discarded, not executed
  (mirroring how `session.py:_collect_pending_diffs` already post-hoc inspects
  `ToolMessage`s rather than trusting the model to stop on its own). The candidate's
  next message answers it; that answer becomes citable evidence for subsequent
  `propose_resume_edit` calls in the same thread. This is enforcement, not a prompted
  convention — a model cannot invent an answer to its own question and use it as a
  citation, which would smuggle a fabrication past the no-fabrication boundary.

### Subagents

The existing 5 recruitment personas (`recruitment_team/persona_packs/v1/personas.json`,
loaded the same way `target_assessment.py` already loads them) become `SubAgent`
entries the orchestrator can freely delegate to, mirroring
`resume_agent.personas.create_persona_subagents()`. Each persona subagent keeps its
existing internal contract: one schema-enforced submission per invocation
(`tool_choice=<persona submission tool>`), matching the measured, working pattern
from the classic pipeline. What changes is *whether and how often the orchestrator
calls each one* — that decision moves from a hardcoded "always all 5, always once"
to the orchestrator's own judgment.

### Mandatory final judge

Dropping the fixed pipeline removes the guarantee that a synthesis pass always
happens, but it does not remove the independent quality judge. After the agent
reaches a stopping point (no more tool calls, or the iteration/edit cap below is
hit), whatever it has produced — its narrative assessment and any pending edits —
goes through the existing independent judge call (`recruitment_team/target_assessment.py`'s
current judge contract, reused as-is) before the run is marked `completed`. A failing
judgment still produces `quality_blocked`, exactly as it does today. This is the one
step that does not become optional just because the reasoning path to it is open.

### Efficiency guardrails (not freedom limits)

To avoid repeating the specific failure mode the "14 calls → 7 calls" lesson
actually measured (wasted, duplicate, non-progressing calls), not to constrain
choice itself:

- Hard numeric caps, enforced in code (exact values tunable during implementation,
  starting point noted here): at most `AGENT_MAX_TOOL_ITERATIONS` (currently 20)
  top-level orchestrator tool calls, **and** a cap on total calls made by every
  persona subagent combined (each `task`-delegated subagent runs its own inner
  LangGraph loop with its own step budget, which is not automatically drawn from
  the top-level count) — total work across parent and subagents must stay bounded,
  not just the parent's own call count. At most 8 `propose_resume_edit` calls per
  run before the run must checkpoint back to the user rather than silently continuing
  to accumulate proposals (the earlier "what happens with 50 edits" question this
  spec review raised — the answer is: it can't happen, the run stops and hands
  control back first). This matters concretely against the per-key rate limit
  (`SEALION_REQ_PER_MIN`, currently 9) — an unbounded run is a real latency and
  reliability risk here, not a hypothetical one.
- The orchestrator does not re-invoke a persona or `search_jobs` with materially
  identical arguments without new information having entered the conversation
  since the last call.
- A real, generous recursion/iteration limit (matching
  `config.AGENT_MAX_TOOL_ITERATIONS`, extended if needed for this flow) stops a
  genuinely looping run, without capping how many *distinct, meaningful* tool
  calls it can make.

### Activity and observability

Every tool call the orchestrator makes (which persona, which tool, with what
result) is logged to the existing `recruitment_activity_events` stream as its own
event, using the workflow-tree grouping already built into
`RecruitmentTeamPanel.jsx` tonight — so the increase in agent freedom does not
reduce activity-stream honesty; if anything there is more real activity to show,
not simulated activity.

## Data model changes

- `target_assessment_artifacts.specialist_runs` continues to record whichever
  persona subagents were actually invoked (now variable per run, not always all 5).
- A new durable record for **pending proposed edits** is needed: which resume
  version, the proposed diff content, its cited evidence, and its accept/reject
  status — this reuses the existing `resume_agent/diffs.py` accept/reject shape
  rather than inventing a new one; the recruitment-team thread links to it rather
  than duplicating it, matching the PRD's "do not introduce a separate V3 resume
  store" principle.
- Interview question/answer pairs are recorded as ordinary `recruitment_messages`
  rows (already durable, already ordered) — no new table needed.

## Error handling

- A rejected `propose_resume_edit` call (failed the fabrication check) returns the
  exact rejected content and the specific failure reason to the agent, so it can
  retry with a corrected version or fall back to `ask_candidate` — same
  retry-with-exact-feedback discipline established throughout this session's fixes.
- Model/transport failures during any tool call follow the same transient/
  validation/business failure taxonomy already defined in
  `docs/v3-retry-recovery-policy.md`; this design does not change that taxonomy,
  it only adds new tool call sites that must go through it.

## Testing

- Real end-to-end runs against real resumes and real jobs (continuing this
  session's practice), asserting: every accepted or pending edit traces to cited
  evidence, no rejected edit ever appears in a pending-diff view, and the agent's
  actual tool-call sequence is visible in the activity stream.
- Unit tests for `propose_resume_edit`'s fabrication check using the existing
  `validation_gates.py` test patterns.
- A test proving the orchestrator does not repeat an identical tool call absent
  new information (the specific failure mode the efficiency guardrail targets).
- An early spike test that delegates to at least one persona subagent via
  `deepagents`' `task` mechanism and asserts a schema-enforced result comes back —
  this validates the previously-unexercised delegation path before the rest of the
  flow is built on top of it.
- A test proving a run that hits the `propose_resume_edit` cap checkpoints back to
  the user instead of continuing to accumulate proposals.
- A test proving any tool call attempted in the same model turn after `ask_candidate`
  is discarded, not executed.
- A test proving the independent judge still runs, and can still produce
  `quality_blocked`, on a run that took an unusual or minimal reasoning path
  (e.g. zero personas consulted, or a run that only asked the candidate a question
  and proposed no edits).

## Open questions carried into implementation planning

- Exact schema for the new pending-edit persistence (reuse `resume_agent`'s diff
  shape directly, or a thin V3-specific wrapper around it).
- Whether `read_target_job` fully replaces `role_success.py`'s two-stage
  definition/evidence-assessment split, or the agent consults that existing
  output as one of its available reads alongside the raw job text.
