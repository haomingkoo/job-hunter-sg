# V4 slice 1: the coordinator gets a loop (#146)

Design for issue #146. Companion to the landed study-first design in
`docs/v4-141-study-first.md`, covering the coordinator's thread-aware tool loop.

This document is the contract the tests in `backend/tests/test_coordinator_loop.py`
assert against. They were written first as strict xfails, and they pass now.

## Revision 4: what running it changed

Four defects only a live run could show are fixed in commit `8d6ce18` and stated where
they belong below: the repeat guard became middleware over every tool (§3), `write_todos`
is no longer bound at all (§5), `read_candidate_evidence` refuses with an alternative
rather than a bare failure, and a thread with no candidate profile still sees the resume.

`write_todos` is the one worth reading twice. The model rewrote the same three-item list
eleven times, through an actionable refusal, a prompt rule and a hard guard. It plans
fine. It could not move from writing a plan to executing one, plausibly because nothing
renders the plan. Removing the tool took the turn from 23 steps and a crash to 6 steps
and an answer. Making the plan a real artifact is issue #147.

`COORDINATOR_MODEL` also defaulted to the FAST tier while v4.5-27B was unreachable on
2026-08-02, which is the model the passing trace ran on. It now defaults to the AGENT
tier again.

## Revision 3: two corrections the build forced

Revision 2 was written against the installed stack but two of its claims did not
survive contact with it. Both are corrected in the code; this section says so
here too, because a design doc asserting a mechanism that demonstrably breaks is
a trap for whoever reads it next.

**§5's stable per-thread graph id is wrong, and quietly so.** `structured_response`
is written into the checkpoint and never cleared, and
`langchain/agents/factory.py`'s `model_to_tools` edge ends the run on
`"structured_response" in state` — a key-presence check, so writing `None` over it
changes nothing (reproduced on langchain 1.3.11). On a stable graph id the first
completed turn therefore makes every later `ask_candidate` resume terminate the
instant the answer is injected: no model call, no reply, no error. Corrected:
**every turn gets its own graph id and replays the DB transcript**, and the
checkpointer holds exactly one thing, a paused graph between two HTTP requests.
The pause's graph id travels back on a new `ModelReply.pause_token` field and is
persisted as `case_facts["coordinator_pause_token"]`, mirroring
`target_assessment_pause_token`. The DB stays the system of record; the checkpoint
is no longer a cache of anything.

**§8's `COORDINATOR_MAX_TOOL_ITERATIONS = 12` bought two tool calls, not twelve.**
It is a LangGraph `recursion_limit`, which counts super-steps. Measured against
this graph: 5 steps plus 4 per tool call. The default is 45, which is ten tool
calls. `AGENT_MAX_TOOL_ITERATIONS = 20` on the assessment path buys under four by
the same arithmetic, which is worth a separate look.

Two consequences of the first correction are stated in
`coordinator/model.py`'s docstring rather than hidden: the checkpoint file gains
a graph per chat turn with nothing pruning it, and LangGraph warns that
deserializing `ConversationReply` from a checkpoint will be blocked in a future
release.

## Revision 2: what changed and why

Revision 1 survived an adversarial review. Seventeen findings held up. Every one is
applied below. The corrections that change what a build agent writes:

| # | Was | Now | Section |
|---|---|---|---|
| 1 | new `conversation_context` manager | reuse `assessment_context(ctx, initial_edits=ctx.proposed_edits)` | §2 |
| 2 | hand-scan the stream for a submission tool call, last one wins, one extra completion per turn | `response_format=ToolStrategy(ConversationReply)`, read `state["structured_response"]` | §5 |
| 3 | acceptance a 10-line prompt injection also passes | baseline recorded as a control, acceptance strengthened to a self-chosen query and a re-query | §10 |
| 4 | `DeepAgentConversationModel(discovery=…)` plus `ctx.discovery` | `ctx.discovery` only; the constructor parameter is gone | §2, §5, §8 |
| 5 | empty-checkpoint branch replays `self._messages(thread.id)` | replays the `messages` parameter `respond()` already receives | §5 |
| 6 | nothing proved the DI path reaches the loop | two wiring tests, one on `get_conversation_model`, one transport turn with no override | §8 |
| 7 | the headline scenario was not a test | a two-turn test where turn 2 does not search and still names a job | §10 |
| 8 | one empty search wiped a good shortlist | the drain replaces `recommendations` only when a search returned jobs | §3 |
| 9 | the edit test asserted on a list it built itself | driven through `RecruitmentTeam.execute`, asserts `team.proposed_edits(...)` | §2 |
| 10 | `search_query` asserted tautologically | the scripted wish differs from the executed query, both keys must equal the executed one | §5 |
| 11 | preference extraction had zero coverage on the new path | valid and invalid evidence quotes both asserted | §5 |
| 12 | the cap test passed whether or not the cap was honoured | model calls are bounded, and `calls` is separated from `consumed` | §5 |
| 13 | the merge rule had no coverage | overlapping results through `RecruitmentTeam.execute`, ordering asserted | §3 |
| 14 | the activity stream was untested | publisher summaries, sequence order, `skip_tool_call_ids` on resume, a vitest case | §7 |
| 15 | `drive()` existed only so a test could read a dict | `drive()` is gone; `ConversationUnavailable.failure_type` carries the same discrimination | §5 |
| 16 | seven dead `_get_api_key` monkeypatches | one autouse fixture that makes `create_agent_model` raise | §9 |
| 17 | `thread_id: int` against a uuid string column | `thread_id: str` | §2 |

Finding 17's second half (two discovery sources, no test able to tell them apart) is
resolved by finding 4: there is now one source.

## The bug, stated exactly

`LangChainConversationModel.respond()` is one `model.invoke()` binding one tool,
`submit_recruitment_conversation`, with `tool_choice` forcing it
(`conversation_model.py:161-192`). The loop at `conversation_model.py:167` is a
schema-validation retry. Nothing executes between attempts.

`respond(messages, resume_text, current_preferences)` has three parameters. The seven
jobs the thread found live in `thread.case_facts["recommendations"]`
(`recruitment_team.py:624`). `_model_reply` has `thread.case_facts` in scope at
`recruitment_team.py:485` and pulls only `preferences` out of it. Everything else is
discarded before the model is called.

So the observed reply is correct behaviour for the code as written:

> "I cannot ... I do not have access to the 7 job postings mentioned in the previous
> turn. Could you please paste the text of one or two specific job postings?"

## Shape

```
ConversationModel (Protocol)          one defaulted parameter added
├── ScriptedConversationModel         unchanged construction, respond() grows the same parameter
├── LangChainConversationModel        unchanged, ignores the parameter
└── DeepAgentConversationModel        new: create_deep_agent loop, requires the parameter
```

`respond()` still returns `ModelReply`, so `_model_reply`'s validation, merge and
telemetry survive intact.

---

## 1. The port

The agreed shape said "ConversationModel Protocol unchanged". That cannot hold and also
fix the bug: there is no parameter on `respond()` that can carry a shortlist. Three
routes were considered.

| route | why not |
|---|---|
| constructor injection | `http_routes.py:91` builds the model through `Depends` before any thread is loaded, so per-turn construction would have to move inside `RecruitmentTeam`. That hides wiring in the orchestrator. |
| a `ContextVar` set around the call | Keeps the Protocol literally unchanged, at the cost of making the data flow invisible. `activity_stream.stream_command` already runs commands on a spawned thread, so any future executor inside the loop breaks it silently. |
| **a fourth defaulted parameter** | Chosen. Explicit, typed, and invisible to all 31 `ScriptedConversationModel` constructions because they construct with `replies` only and never call `respond()` directly. |

```python
class ConversationModel(Protocol):
    def respond(
        self,
        messages: list[Message],
        resume_text: str,
        current_preferences: tuple[PreferenceFact, ...] = (),
        context: ConversationContext | None = None,
    ) -> ModelReply: ...
```

**The default is for the doubles, not for production.** An optional field is a request,
and this repo has already paid for one: `search_query` was added optional, merged,
deployed and never populated. So:

```python
class DeepAgentConversationModel:
    def respond(self, messages, resume_text, current_preferences=(), context=None) -> ModelReply:
        if context is None:
            raise InvalidCommand("DeepAgentConversationModel requires a ConversationContext")
```

A guard clause with a test, not a `None` check that degrades quietly back into the blind
coordinator this issue exists to kill.

`ScriptedConversationModel.respond` grows the same parameter and ignores it.
`call_count` keeps counting **turns**, because it stays in `respond()` and the loop
lives below it. The idempotent-replay assertion at
`test_recruitment_team_module.py:220` therefore keeps meaning what it means today.

---

## 2. `ConversationContext`

New module `backend/recruitment_team/coordinator/context.py`.

```python
@dataclass(frozen=True)
class ConversationContext:
    # RecruitmentThread.id is String(36) holding a uuid4 (models.py:312). An int
    # annotation here would survive forever unnoticed, because a frozen dataclass
    # does no runtime validation and f"coordinator-{thread_id}" formats either way.
    thread_id: str
    trace_key: str
    # Field names below are deliberately identical to TargetAssessmentRequest's,
    # so read_candidate_evidence / read_target_job / propose_resume_edit read one
    # attribute name whichever context is active.
    candidate_profile: CandidateEvidenceProfile | None
    role_profile: RoleSuccessProfile | None
    target_job: JobSnapshot | None
    resume_document: dict[str, Any] | None
    # Conversation-only.
    latest_search_query: str
    recommendations: tuple[JobSnapshot, ...]
    shortlisted_jobs: tuple[JobSnapshot, ...]
    preferences: tuple[PreferenceFact, ...]
    discovery: DiscoveryPort
    # Mutable sinks. The loop appends; RecruitmentTeam drains after respond() returns.
    search_results: list[JobSearchResult] = field(default_factory=list, compare=False)
    proposed_edits: list[dict] = field(default_factory=list, compare=False)
    # One normalized iter_progress_events dict per event: tool_call, tool_result,
    # message. See §7 for why results and not only calls.
    on_event: Callable[[dict], None] | None = None
```

`TargetAssessmentRequest` (`assessment_contracts.py:36-41`) makes `target_job` and
`role_profile` required, and a conversation turn has neither. Rather than loosening that
frozen contract (`_run_judge` calls `asdict(request.target_job)` and would crash on
`None`), `ConversationContext` is a separate type that is *structurally* compatible
where the shared tools touch it. The shared tools gain explicit `None` guards and
nothing else.

### No second context manager

**Corrected.** Revision 1 specified a `conversation_context` manager alongside
`assessment_context`. It would have been a copy. `assessment_context`
(`open_agent/context.py:27-49`) reads exactly one attribute off its argument,
`request.resume_document`, and otherwise sets four ContextVars, one of them to the
caller's own edits list when `initial_edits` is passed. `ConversationContext` has both
attributes, so the existing manager already works:

```python
with assessment_context(ctx, initial_edits=ctx.proposed_edits):
    ...
```

`initial_edits=ctx.proposed_edits` aliases the sink, so edits outlive the `with` block.
The only change to `context.py` is widening `_current_request`'s annotation to
`TargetAssessmentRequest | ConversationContext`, which is cosmetic: `pyproject.toml`
scopes `ty check` to `backend/schemas.py` and `backend/resume_agent`, so this module is
not type-checked at all. Do not add a second manager.

`ToolCallGuardMiddleware` is instantiated per turn, so a repeated search on a later
turn, after the candidate has said something new, is allowed.

### Draining edits into the pending table

`_model_reply` drains `ctx.proposed_edits` into `ProposedResumeEdit` rows with the same
field mapping `_assess_target` uses at `recruitment_team.py:1084-1100`, so a
conversational edit reaches the same pending table and the same accept and reject
endpoints.

**This drain is the thing that has to be tested**, not the sink. `team.proposed_edits`
(`recruitment_team.py:1323-1355`) is what a candidate can actually retrieve, and it
computes `applicable = edit.original in resume_text`. A test that asserts on
`ctx.proposed_edits` asserts on a list it constructed itself and would pass with the
drain deleted. The specification test therefore runs through `RecruitmentTeam.execute`,
builds the document with the real `create_resume_document`, and asserts one pending,
applicable row comes back from `team.proposed_edits(...)`.

---

## 3. Tools

Six tools bound to the coordinator loop.

| tool | source | signature |
|---|---|---|
| `read_shortlist` | **new**, `coordinator/tools.py` | `() -> dict` |
| `search_jobs` | **new**, `coordinator/tools.py` | `(query: str) -> dict` |
| `read_target_job` | existing, `open_agent/tools.py:50` | `() -> dict`, gains a `None` guard |
| `read_candidate_evidence` | existing, `open_agent/tools.py:34` | `() -> dict`, gains a `None` guard |
| `propose_resume_edit` | existing, `open_agent/tools.py:63` | `(block_id, rewrite) -> dict`, **unchanged** |
| `ask_candidate` | existing, `open_agent/tools.py:16` | `(questions: list[str]) -> dict`, **unchanged** |

`propose_resume_edit`'s enforcement chain is untouched and stays in this order: per-run
cap, unknown block, single block, no new numeric fact, `run_all_gates`, append with
`status="pending"`. Invariant 3 and invariant 5 hold on the conversational path for the
same reason they hold on the assessment path: it is the same function.

### `read_shortlist`

```json
{"ok": true,
 "latest_search_query": "…",
 "recommendations": [{"job_id": 101, "title": "…", "company": "…", "location": "…",
                      "salary": "…", "seniority": "…", "employment_type": "…",
                      "skills": ["…"], "description": "…",
                      "parsed_requirements": {"…": "…"}, "ats_terms": ["…"],
                      "salary_context": {"sample_count": 42, "median_salary_floor": 7000,
                                         "posting_floor_percentile": 12.0}}],
 "shortlisted_jobs": [ … same shape … ],
 "selected_target_job_id": 101,
 "candidate_profile_available": true}
```

This is the tool that closes the bug. Everything else is upside. It reads
`ctx.recommendations` and `ctx.shortlisted_jobs`, which `_model_reply` seeds from
`thread.case_facts` before the turn starts, so a shortlist built by the deterministic
`SearchJobs` button in an earlier turn is visible to a later conversational turn. That
is the exact scenario in §10.

### `search_jobs`, with facts instead of a hidden level filter

```python
@tool
def search_jobs(query: str) -> dict:
    """Search the current internal Singapore job corpus…"""
```

It calls `ctx.discovery.search_jobs(query)`, which is `LangChainJobDiscovery` in
production and requests detailed results. The discovery boundary enriches those results
with stored parsed requirements, ATS terms, sector, self-reported seniority, and observed
salary context from current visible postings in the same sector and level. Missing salary
stays missing; the market median is context, never an imputed employer offer.

**`ctx.discovery` is the only source of the port.** Revision 1 also took `discovery` in
`DeepAgentConversationModel.__init__`, which nothing could ever read, because
`ConversationContext.discovery` is required and has no default. Two sources for one
collaborator with no precedence rule is a bug waiting for its first divergent test.
`RecruitmentTeam` already holds the port at `self._discovery`, so `_model_reply` puts it
on the context and `get_conversation_model` needs no `Depends(get_job_discovery)`.

**Corrected in revision 4 and consolidated in #113.** Per-tool duplicate checks covered
only two tools and duplicated state plumbing. `ToolCallGuardMiddleware`
(`recruitment_team/tool_call_guard.py`) now wraps both agent loops and refuses a
materially identical repeat with an actionable reason. It does not restrict which tool
the agent picks. Volume, never choice.

The earlier required `exclude_junior` argument and `_wants_experienced_roles` heuristic
were removed under #148. They discarded postings before the coordinator could inspect a
mislabelled senior role's salary and responsibilities. The coordinator now sees the facts
and explains its judgment; action gates remain unchanged.

### Failures and empty results are returned, not raised

The command path raises `DiscoveryUnavailable` before it touches `case_facts`
(`recruitment_team.py:610-620`), so it can never destroy a shortlist. The tool has no
such protection and must be given one explicitly.

- `result.failure_type` set: return
  `{"ok": false, "failure_type": …, "retryable": …}`. The agent sees the failure and
  decides what to do about it. It does not raise, because a search failure mid-turn is
  information, not the end of the turn.
- `result.valid_empty`: return `{"ok": true, "jobs": [], "valid_empty": true}`. Nothing
  was wrong; nothing matched.

Every result, successful or not, is appended to `ctx.search_results`, so the turn's
search history stays observable. The drain below is what decides which of them are
allowed to change the thread.

### Persistence: how search results reach the thread

After `respond()` returns, `_model_reply` drains the sink:

```python
useful = [result for result in context.search_results if result.jobs]
if useful:
    facts = dict(thread.case_facts)
    facts["latest_search_query"] = useful[-1].query
    seen, merged = set(), []
    for result in reversed(useful):                       # newest search first
        for job in result.jobs:
            if job.job_id not in seen:
                seen.add(job.job_id)
                merged.append(asdict(job))
    facts["recommendations"] = merged
    thread.case_facts = facts
```

**Corrected.** Revision 1 replaced `recommendations` whenever the sink was non-empty. A
turn whose only search returned nothing would then have silently emptied the previous
turn's seven results, and the next Shortlist click would be a 422. `if result.jobs` is
the whole fix: a search that returned nothing, or failed, leaves the shortlist alone.

`asdict(job)` is the same shape `_search_jobs` writes at `recruitment_team.py:624`.
This is not cosmetic. `_known_job` (`recruitment_team.py:1474-1486`) resolves a
`job_id` only against `recommendations + shortlisted_jobs` and raises
`InvalidCommand` otherwise, which is a **422 on the next click**, not merely a stale
panel. A search inside the loop that does not land in `recommendations` breaks every
subsequent `ShortlistJob` and `SelectTargetJob`.

`recommendations` is replaced with this turn's useful searches, not appended across
turns. That matches the command path's replace semantics and still covers a turn that
searched more than once. Ordering is newest search first, then dedupe by `job_id`: two
searches returning `[201, 202]` then `[203, 201]` persist as `[203, 201, 202]`.

Draining after `respond()` rather than writing from inside the tool is deliberate: the
tool stays free of the ORM, and the write lands in the same transaction that writes the
assistant message, so a failed turn cannot leave a half-updated thread.

---

## 4. `create_resume_agent` needs two new seams

`resume_agent/agent.py:34` hardcodes `system_prompt=ORCHESTRATOR_SYSTEM_PROMPT`. The
coordinator's goal statement is the substance of this issue and there is no seam for it.
§5 additionally needs `response_format`.

```python
def create_resume_agent(
    model=None, tools=None, subagents=None,
    checkpointer=None, interrupt_on=None,
    system_prompt: str | None = None,          # new, defaults to ORCHESTRATOR_SYSTEM_PROMPT
    response_format: Any | None = None,        # new, passed straight through, default None
):
```

Both defaulted, so the Resume Deep Agent v2 and `OpenAgentTargetAssessmentRunner` are
unaffected. `create_deep_agent` in the installed `deepagents` 0.6.12 already accepts
`response_format`; this is pass-through, not new behaviour.

The coordinator prompt is a new versioned module,
`recruitment_team/prompts/coordinator.py`, carrying
`COORDINATOR_PROMPT_VERSION = "recruitment-coordinator-loop-v1"`. It inherits the depth
rules and preference rules verbatim from `CONVERSATION_SYSTEM_PROMPT`
(`prompts/conversation.py`), drops the search-phrase rules at lines 63-72 (the agent now
searches for itself), and adds the tool contract. `CONVERSATION_PROMPT_VERSION` and its
prompt stay where they are, because `LangChainConversationModel` still uses them.

---

## 5. The loop

New module `backend/recruitment_team/coordinator/model.py`, exported from
`recruitment_team/__init__.py` beside the other adapters.

```python
class DeepAgentConversationModel:
    def __init__(self, *, model_factory=None, telemetry=None): ...

    def respond(self, messages, resume_text, current_preferences=(), context=None) -> ModelReply: ...
```

**Corrected.** Revision 1 also exposed a public `drive()` returning a dict, whose only
justification was that a test wanted to read `reason == "tool_iteration_cap"`.
`ConversationUnavailable` carries `failure_type`, so `pytest.raises(...)` plus
`error.failure_type` gives the same discrimination without a second public entry point,
and it asserts on what a caller actually receives. `drive()` does not exist.

`model_factory` is for tests and for nothing else. When it is `None`,
`create_resume_agent(model=None, …)` falls through to `create_agent_model()` exactly as
the assessment runner does. That is the single seam the autouse fixture in §9 patches.

Subagents: `[]`. The coordinator delegates to no personas in this slice. Persona work is
slice V4 (study-first).

### Termination is `ToolStrategy`, not a hand-scan

**Corrected, and this is the largest change in revision 2.** Revision 1 scanned
`iter_progress_events` for a `submit_recruitment_conversation` tool call, applied a
last-one-wins rule, and accepted an extra model completion per turn because the graph
calls the model once more after the tool returns. LangChain 1.3.11 does all three jobs
natively.

```python
from langchain.agents.structured_output import ToolStrategy

agent = create_resume_agent(
    model=…, tools=[…], subagents=[],
    system_prompt=COORDINATOR_SYSTEM_PROMPT,
    response_format=ToolStrategy(ConversationReply),
    checkpointer=_CHECKPOINTER,
    interrupt_on={"ask_candidate": True},
)
```

Verified against the installed stack (deepagents 0.6.12, langchain 1.3.11), all four
behaviours reproduced directly:

- a one-tool plus one-structured-call script consumes exactly **2** model calls, with no
  trailing completion;
- the validated object is readable at `state["structured_response"]` as a
  `ConversationReply` instance, already parsed;
- an invalid payload (`reply=""`) is corrected **inside the loop** in 2 calls, which is
  the `RECRUITMENT_CONVERSATION_VALIDATION_ATTEMPTS` retry for free;
- `ToolStrategy` coexists with `interrupt_on={"ask_candidate": True}` plus a
  checkpointer: `iter_progress_events` streams normally, `get_state().interrupts` is
  truthy at the pause, `structured_response` is `None` at the pause and readable after
  the resume.

**The tool name is the schema class name.** `ToolStrategy` derives it from
`schema.__name__`, so the model, the activity stream and `TOOL_PHRASES` would all see
`_ConversationPayload`. Rename it: `_ConversationPayload` becomes `ConversationReply` in
`conversation_model.py`, and its docstring becomes the tool description the model reads.
`submit_recruitment_conversation` keeps its `args_schema` and is otherwise untouched,
because `LangChainConversationModel` still uses it.

One conceded loss, and it is a wash. `LangChainConversationModel` re-prompts in-loop when
`preference_update_error` fails, and `ToolStrategy` cannot, because that rule needs the
latest user message. But `preference_update_error` also runs in `_model_reply`
(`recruitment_team.py:501-506`) on both paths, and revision 1's hand-scan design
forfeited the same thing. No regression either way.

### Turn payload and the checkpoint

`run_config = {"recursion_limit": config.COORDINATOR_MAX_TOOL_ITERATIONS,
"configurable": {"thread_id": f"coordinator-{ctx.thread_id}"}}`, on the module-level
`SqliteSaver` already created at `open_agent/runner.py:103-105`.

A stable per-thread graph id, rather than the fresh uuid the assessment runner uses, is
what makes `ask_candidate` mean anything in a conversation. A pause has to survive to the
next HTTP request or the interrupt guarantees nothing. `RecruitmentThread.id` is a uuid4
string, so ids cannot collide in production.

That shared checkpoint file is not isolated under pytest today.
`config.OPEN_AGENT_CHECKPOINT_DB_PATH` defaults to a repo-relative
`open_agent_checkpoints.db` and `runner.py` opens it at import time, so a test run
accumulates state in the working tree and two runs can see each other's checkpoints. The
root `conftest.py` now points it at a temp directory the same way it already pins
`DATABASE_URL`.

Each turn seeds only what is new:

- Checkpoint has messages, no pending interrupt: one `HumanMessage` carrying an
  `xml_data_block("thread_state", …)` block followed by the latest user message.
- Checkpoint has a pending interrupt: `Command(resume={"decisions": [{"type": "respond",
  "message": <latest user message>}]})`, and `iter_progress_events` is passed
  `skip_tool_call_ids={<the interrupted ask_candidate call id>}`. No new `HumanMessage`.
  Without the skip set, the resume replays the same `ask_candidate` AIMessage as a fresh
  node update and the activity log double-counts it. This is documented at
  `streaming.py:44-50` and the assessment runner already had to fix it once.
- Checkpoint is empty (new thread, or a wiped checkpoint file): the transcript in the
  `messages` parameter is replayed first, then the state block and the latest message.
  **Corrected:** revision 1 said `self._messages(thread.id)`, which is a `RecruitmentTeam`
  method the adapter cannot reach. `respond()` already receives that exact list.
  **The DB is the system of record. The checkpoint is a cache and is never the only copy
  of anything.**

`thread_state` is compact on purpose: counts, the selected target's id and title,
preference facts, and whether a candidate profile exists. The agent calls
`read_shortlist` when it wants the postings.

**It must not carry the postings themselves**, and there is a test that fails if it
does. The headline scenario in §10 asserts that no company or job title appears in the
turn's first model request and both appear in the request after `read_shortlist`
returned. Stuffing the shortlist into `thread_state` would make `read_shortlist`
decorative and put the whole shortlist into every turn's prompt.

### Exits

| exit | reply | thread effect |
|---|---|---|
| `state["structured_response"]` is a `ConversationReply` | `reply.reply` | normal |
| pending interrupt after the stream ends | `_format_questions(args)` from the `ask_candidate` call | see §6 |
| `GraphRecursionError` | `ConversationUnavailable(failure_type="tool_iteration_cap", retryable=True)` | run fails, 503 |
| stream ended, no structured response, no interrupt | `ConversationUnavailable(failure_type="no_submission", retryable=True)` | run fails, 503 |

**`GraphRecursionError` never propagates and no turn ever fabricates a reply.** HTTP 200
is not an acceptance criterion.

New error class:

```python
class ConversationUnavailable(RecruitmentTeamError):
    def __init__(self, message: str, *, failure_type: str, retryable: bool): ...
```

It must be added to the isinstance tuple at `http_routes.py:167-181`. That mapping is by
explicit type and ends in a bare `raise error`, so a new `*Unavailable` that nobody adds
to the tuple becomes a 500. There is a test for exactly that line.

`_execute_locked` already does the rest: on any exception it marks the run `failed`,
records `detail["failure_type"]` on a failed activity event, and re-raises
(`recruitment_team.py:402-424`). No assistant message is written.

### Preference updates on the new path

**Superseded by the tool-authoritative coordinator contract.** The coordinator now writes
preferences only through `record_preferences`, which validates exact quotes before placing
updates in the conversation context. `ConversationReply` carries prose and uncertainty,
not a second preference-write channel. Adapter `ModelReply.preference_updates` remains for
non-agent conversation adapters, and the recruitment-team boundary still validates it.

The tool can reject an unevidenced batch without losing the rest of the turn. The model
may correct the call using the returned validation error, and only accepted tool output
reaches `case_facts["preferences"]`.

### `search_query` stops being a request

`DeepAgentConversationModel` sets `ModelReply.search_query` from the last query actually
passed to the `search_jobs` tool. `ConversationReply` has no search-query field, so the
model cannot create a second, unexecuted value.

Two keys, two meanings, and they can differ:

- `case_facts["search_query"]` (written by `_remember_search_query`, read by
  `_query_from_candidate` on the next `SearchJobs` command): the last query **executed**
  this turn, whatever it returned.
- `case_facts["latest_search_query"]`: the query of the last search that **returned
  jobs**, kept consistent with `recommendations` so the panel never shows a query that
  does not describe the list under it.

The specification test asserts both persisted keys equal the executed query.

---

## 6. The `ask_candidate` pause

`interrupt_on={"ask_candidate": True}`, the same binding as
`open_agent/runner.py:137`. Calling it pauses the graph **before any further tool
executes**. That guarantee is the only thing distinguishing it from simply ending a turn
with a question in the reply text, and it is worth having: it stops the agent searching
on a guess right after asking what salary the candidate wants.

Detection copies the runner exactly. `iter_progress_events` drops the raw
`{"__interrupt__": …}` chunk at `streaming.py:58-59`, so the pause is read from
`agent.get_state(run_config).interrupts` after the stream ends.

On pause:
- `ModelReply.content` is the formatted questions. The candidate sees a question.
- **`thread.workflow_state` is not touched.** Setting `awaiting_candidate_answer` would
  route the next message to `AnswerAssessmentQuestion`, which belongs to the assessment
  runner. The pause is invisible to the transport, and the next ordinary `SendMessage`
  resumes it because §5's turn payload checks `interrupts` first. Zero frontend change.
- No preference updates are merged for that turn, because no submission happened.
- The interrupted call's id is recorded on `case_facts` so the resuming turn can pass it
  as `skip_tool_call_ids`, mirroring `case_facts["target_assessment_pause_call_id"]`.

Question volume is bounded the way the runner bounds it, by
`config.OPEN_AGENT_MAX_CANDIDATE_QUESTION_ROUNDS` counted over the checkpointed
messages. Past the cap the resume message carries the same system sentence
`runner.py:224-231` uses. Prompt text is not a bound, so this is a stated limitation:
the sentence asks, and only refusing to surface a pause enforces. For a conversation the
consequence of an extra question is one more turn, not a stuck run, so the runner's
harder `refuse to yield the pause` treatment is not carried over.

---

## 7. Activity events

`respond()` returns a `ModelReply`, so streaming rides on a callback rather than a
changed return type. `ConversationContext.on_event` receives every normalized
`iter_progress_events` dict, results included, and not only `tool_call`. Forwarding
results costs nothing and is what lets a test assert that a guardrail rejection or a
gate rejection actually happened, rather than inferring it from a call count. A callback
that only carries calls would need a test-only seam on the adapter to observe results,
and a test-only seam is a worse thing to own than one wider callback.

`RecruitmentTeam` passes a closure that filters to `kind == "tool_call"` and does what
`_consume_target_assessment_updates` does at `recruitment_team.py:978-988`:

```python
event = self._event(thread, run, event_type="conversation", status="running",
                    summary=f"{item['team_member']} called {item['tool_name']}.",
                    detail={"tool_name": item["tool_name"]},
                    team_member=item["team_member"])
self._db.commit()
self._activity_publisher.publish(self._activity(event))
```

Sequence numbers keep coming from `thread.next_event_sequence`
(`recruitment_team.py:1717`), which `buildRoster` sorts on
(`TeamActivityPanel.jsx:103`).

Summary strings keep the `"{member} called {tool}."` shape that `humanize`
(`TeamActivityPanel.jsx:72-82`) parses.

**Corrected: this is tested, not assumed.** Acceptance criterion 4 in #146 is "visible in
the activity stream", and revision 1 shipped no assertion on it at all. The specification
now asserts, on `RecordedActivityPublisher.events`:

- the per-tool summaries appear in call order, between the "running" and "completed"
  run events;
- `sequence` is strictly increasing across them;
- the turn that resumes an `ask_candidate` pause does **not** publish a second
  `ask_candidate` event.

Frontend, `frontend/src/components/TeamActivityPanel.jsx`:
- `TOOL_PHRASES` (L62-70) gains `read_shortlist`, `search_jobs` and `ConversationReply`.
  `humanize` strips the subject when it finds no phrase, so without them a candidate
  reads "Called read_shortlist." A vitest case in
  `frontend/src/components/__tests__/TeamActivityPanel.test.jsx` covers all three; it is
  written with `it.fails` today and flips to `it` when this lands.
- The copy at L226-228, "A full assessment runs several specialists and an independent
  judge. This usually takes a few minutes.", is shown whenever `busy` and will now
  appear on ordinary chat turns. It has to become conditional on an assessment run.

---

## 8. Wiring

`http_routes.py`:

```python
def get_conversation_model(
    telemetry: RecruitmentTelemetry = Depends(get_recruitment_telemetry),
) -> ConversationModel:
    return DeepAgentConversationModel(telemetry=telemetry)
```

No `Depends(get_job_discovery)`: the port arrives on the context (§3).

The five `app.dependency_overrides[get_conversation_model]` in
`test_recruitment_team_module.py` (L2586, 2752, 2860, 2966, 3103) override the whole
callable and keep working.

**Corrected: the wiring is tested.** Every existing reference to
`get_conversation_model` in the suite replaces the callable, and every specification test
in §10 injects the adapter by hand. So the loop could be built, the file could go green,
and this one-line change could be forgotten with no signal. That is precisely the shape
of the `search_query` scar this design keeps citing. Two tests close it:

1. `get_conversation_model()` returns a `DeepAgentConversationModel`.
2. One transport turn through the FastAPI app that does **not** override
   `get_conversation_model`, patching only `resume_agent.agent.create_agent_model` to
   return a `ScriptedDeepAgent`. The real DI path constructs the real adapter.

`recruitment_team/__init__.py` exports `DeepAgentConversationModel` and
`ConversationContext`.

New config constant, `backend/config.py`:

```python
COORDINATOR_MAX_TOOL_ITERATIONS: int = _positive_int_env("COORDINATOR_MAX_TOOL_ITERATIONS", 45)
```

Separate from `AGENT_MAX_TOOL_ITERATIONS` (default 20), which the resume agent and the
assessment runner share. One env var tuning a chat turn and a full assessment means
tuning either one starves the other.

The default is 45, not the 12 revision 1 specified. This is a LangGraph
`recursion_limit` counting super-steps, and against this graph 12 bought two tool calls.
See revision 3 above for the arithmetic.

`_model_reply` is the only changed call site. It builds the context, passes it, drains
`search_results` and `proposed_edits`, and leaves preference validation, merge and
telemetry untouched.

---

## 9. Test harness rules

`backend/tests/scripted_deep_agent.py` scripts the **model**, never the graph. The graph,
the tools, the guardrails and the LangGraph interrupt all really run.

- **Exhaustion raises.** `FakeMessagesListChatModel` wraps to index 0 when its script
  runs out. Here that is an `AssertionError` naming the call number.
- **`consumed` and `calls` are different numbers.** `consumed` is how many scripted
  responses were used; `calls` is how many times the model was actually invoked. With
  `repeat_last=True` the first freezes and the second keeps climbing, so a test that
  bounds model calls must bound `calls`. Revision 1's cap test asserted `consumed`, which
  `repeat_last` pins at 1 whether the cap is honoured or ignored.
- **Every request is recorded.** `requests[n]` is the full message list of call n. Where
  the claim is "the agent read its own results", the assertion is on that list.

**No fake API keys.** Revision 1 opened seven tests with
`monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "test-key")`. All
seven were dead, because `create_resume_agent` short-circuits on
`model or create_agent_model()` and a model is always supplied. Worse than dead: a fake
key lets `create_agent_model` construct a live SEA-LION client successfully, so if the
loop ever did build its own model, the patch would enable a real network call rather than
fail fast. Replaced by one autouse fixture that makes `create_agent_model` raise on both
bindings, `resume_agent.agent` (imported at module level, used by `create_resume_agent`)
and `resume_agent.models` (imported lazily by `conversation_model.py` and
`role_success.py`). That is the protection those seven lines pretended to be.

**The harness guard goes through `create_deep_agent`, not `create_resume_agent`**, and
its reply schema is local. A guard has to be green today, and today the factory has
neither §4 seam and the schema still has its private name. The seams get their own
xfail test, which asserts the coordinator goal reached the model and
`state["structured_response"]` came back, rather than introspecting the signature.

**`OPEN_AGENT_CHECKPOINT_DB_PATH` is temp-scoped by the root `conftest.py`**, next to
`DATABASE_URL`. Before this, a suite run wrote LangGraph checkpoints into the working
tree and two runs could resume each other's paused graphs.

---

## 10. Acceptance

### The control

A ten-line change satisfies revision 1's acceptance criterion. `_model_reply` has
`thread.case_facts` in scope at `recruitment_team.py:485`, and
`LangChainConversationModel.respond` builds its prompt as an editable list of
`HumanMessage` blocks (`conversation_model.py:126-158`). Inject the shortlist there and
the single-shot model will name a job by title and stop asking for a pasted JD.

Build that first, on a throwaway branch, and record what it does. It is the control. An
acceptance criterion a non-loop change also passes is not evidence for a loop.

### The criteria

Necessary floor, the V1 rule from the PRD, driven in a browser against the real backend,
asserting on rendered text:

> Search returns matches, then ask "improve my resume for these roles". The reply names
> at least one job from the shortlist by title. It must not ask the candidate to paste a
> job description.

Sufficient, and passable only by a loop. All three are pure observable behaviour:

1. **A query nobody typed.** Send one chat message describing what you want and click
   nothing. The activity stream shows a `search_jobs` step whose query is not the text
   you typed, and the shortlist panel populates from that turn.
2. **A re-query after reading.** State a constraint the first result set violates, for
   example "not computer vision". In one turn the activity stream shows two `search_jobs`
   steps with different queries, and the reply explains what was wrong with the first set.
   Nothing in the code excludes computer vision. The agent noticed it by reading its own
   results.
3. **The shortlist survives the turn.** Click Shortlist on a job the agent found in its
   own loop. It must not 422.

Record the before-state for each first, so an inert change cannot pass.

### The unit tests

`backend/tests/test_coordinator_loop.py` is necessary and not sufficient. The pre-fix
suite passed while job search returned zero results for every user, so live acceptance
must also exercise the rendered workflow.

| test | what would otherwise pass while broken |
|---|---|
| `create_resume_agent` takes a prompt and a response format | the coordinator silently running under `ORCHESTRATOR_SYSTEM_PROMPT` |
| search, read, reply, persist | nothing: this is the one-turn form of the bug |
| shortlist found by the button reaches the next turn | the headline #146 scenario; a turn-1 search leaves the title in the transcript, so only a shortlist the model never saw proves `read_shortlist` was used |
| second search after reading the first results | a merge rule with no coverage; asserted against the persisted thread, not the sink |
| repeated call rejected | a guardrail that silently blocks the second, different search too |
| empty search leaves the shortlist alone | a drain that wipes seven results on one empty search |
| failed search leaves the shortlist alone | the same, via `failure_type` |
| iteration cap | a cap that is never honoured; bounded on `calls`, asserted on `failure_type` |
| `ConversationUnavailable` maps to 503 | a new error class nobody added to the isinstance tuple, returning 500 |
| `ask_candidate` pauses, then resumes | a pause that is prompt convention; and a resume that double-publishes the question |
| preference updates, valid and invalid quote | the carry from `structured_response` dropped wholesale |
| `search_query` records what ran | a tautology comparing a scripted arg to itself |
| proposed edit reaches the pending table | a drain that never ran, asserted through `team.proposed_edits` |
| `get_conversation_model` returns the loop | the one-line wiring change forgotten |
| a transport turn with no dependency override | the same, end to end |

---

## 11. What is NOT built

Stated so the absence is a decision and not an oversight.

- **No judge on conversational turns.** Invariant 6 is scoped to V3 target assessment,
  and `_assess_target` still runs it. Adding a judge pass per chat message adds a full
  model call to every message. The conversational path's durable outputs are still
  gated: `propose_resume_edit` runs `run_all_gates`, edits stay pending until accepted,
  and preference updates still fail `preference_update_error` without an exact quote.
- **No persona subagents.** `subagents=[]`. Automatic study uses the evidence profiler;
  target assessment owns its specialist roles.
- **No structured diff or match-rationale artifact yet.** This remains #142/#147 work.
- **No exclusion predicate, junior heuristic or ranking formula in the recruitment path.**
  The agent ranks by reading requirements, salary context, and candidate evidence.
- **`LangChainConversationModel` is not deleted and not modified**, beyond the
  `_ConversationPayload` to `ConversationReply` rename its `args_schema` points at. It
  stays as the single-shot adapter and as the thing the loop is measured against.
- **`ShortlistJob` and `SelectTargetJob` commands are unchanged.** `SearchJobs` remains
  the deterministic UI-button path but no longer applies the removed junior heuristic.
- **`search_query` is not made required in `_ConversationPayload`.** Slice V2 / #147.
- **No queued messages.** The per-thread lock still serialises turns. Slice V7.
- ~~**No live-model validation script.**~~ Built. The original one-turn trace script
  found four defects in revision 3. It has since been superseded by
  `backend/scripts/validate_recruitment_team_local.py --output`, which exercises the
  current end-to-end journey and records content-free activity and transport telemetry.
