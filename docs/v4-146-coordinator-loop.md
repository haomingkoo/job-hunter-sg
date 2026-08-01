# V4 slice 1: the coordinator gets a loop (#146)

Design for issue #146. Companion to `docs/v4-study-first-recruitment.md` (branch
`docs/v4-study-first-prd`, not yet merged to main), slice **V1: the coordinator can see
the thread**.

This document is the contract the tests in `backend/tests/test_coordinator_loop.py`
assert against. Those tests are xfail today and are the specification.

## The bug, stated exactly

`LangChainConversationModel.respond()` is one `model.invoke()` binding one tool,
`submit_recruitment_conversation`, with `tool_choice` forcing it
(`conversation_model.py:165-196`). The loop at `conversation_model.py:171` is a
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
| constructor injection | `http_routes.py:93` builds the model through `Depends` before any thread is loaded, so per-turn construction would have to move inside `RecruitmentTeam`. That hides wiring in the orchestrator. |
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
    thread_id: int
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
    wants_experienced_roles: bool
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

`context.py` grows a second context manager alongside `assessment_context`:

```python
@contextmanager
def conversation_context(ctx: ConversationContext) -> Iterator[None]: ...
```

It sets the same four ContextVars. `_current_request` takes the union type
`TargetAssessmentRequest | ConversationContext`. `_current_document` comes from
`ctx.resume_document`, `_proposed_edits` is set to `ctx.proposed_edits` (the sink, so
edits outlive the `with` block) and `_tool_call_history` starts empty. That is what
makes `propose_resume_edit` and `has_repeated_call` work byte-identically on both
paths.

`_model_reply` drains `ctx.proposed_edits` into `ProposedResumeEdit` rows with the same
field mapping `_assess_target` uses at `recruitment_team.py:1084-1100`, so a
conversational edit reaches the same pending table and the same accept and reject
endpoints.

`_tool_call_history` resetting per turn is correct here: a repeated search on a later
turn, after the candidate has said something new, is a different call in a meaningful
sense and must be allowed.

---

## 3. Tools

Six tools bound to the coordinator loop.

| tool | source | signature |
|---|---|---|
| `read_shortlist` | **new**, `coordinator/tools.py` | `() -> dict` |
| `search_jobs` | **new**, `coordinator/tools.py` | `(query: str, exclude_junior: bool) -> dict` |
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
                      "skills": ["…"], "description": "…"}],
 "shortlisted_jobs": [ … same shape … ],
 "selected_target_job_id": 101,
 "candidate_profile_available": true}
```

This is the tool that closes the bug. Everything else is upside.

### `search_jobs`, and why `exclude_junior` is a required parameter

```python
@tool
def search_jobs(query: str, exclude_junior: bool) -> dict:
    """Search the current internal Singapore job corpus…"""
```

It calls `ctx.discovery.search_jobs(query, exclude_junior=exclude_junior)`, which is
`LangChainJobDiscovery` in production and passes `detail=True`
(`discovery.py:114-118`). It does **not** reuse `open_agent/runner.py:79`'s
`guarded_search_jobs`, which has no `exclude_junior` parameter and defaults
`detail=False`. Binding that one would silently drop the junior filter and hand the
model descriptionless payloads that `JobSnapshot.from_payload` stores as empty strings.

`has_repeated_call(history, "search_jobs", args)` runs first and returns
`{"ok": false, "reason": "identical_call_no_new_information"}` on a materially identical
repeat, then the accepted call is appended to `_tool_call_history`. Volume, never
choice.

`exclude_junior` is **required**, not derived. The command path computes it from
`_wants_experienced_roles` (`recruitment_team.py:610-613`) and applies it without
asking. Deriving it here would be an exclusion predicate this design is not allowed to
add, so the heuristic's answer is surfaced as an observable fact in the seeded thread
state and the agent decides. Two consequences, both stated rather than hidden:

- The parameter is required so the model cannot decline to fill it. An optional
  `exclude_junior=False` is the `search_query` trap again.
- The agent can now choose `False` where the command path would have chosen `True`.
  That is the point of the principle, and it is a real behaviour change from
  `_search_jobs`. If junior spam returns, the fix is better evidence in the seeded
  state, never a filter the agent cannot see.

### Persistence: how search results reach the thread

The tool appends its `JobSearchResult` to `ctx.search_results`. After `respond()`
returns, `_model_reply` drains the sink:

```python
if context.search_results:
    facts = dict(thread.case_facts)
    facts["latest_search_query"] = context.search_results[-1].query
    seen, merged = set(), []
    for result in reversed(context.search_results):        # newest search first
        for job in result.jobs:
            if job.job_id not in seen:
                seen.add(job.job_id)
                merged.append(asdict(job))
    facts["recommendations"] = merged
    thread.case_facts = facts
```

`asdict(job)` is the same shape `_search_jobs` writes at `recruitment_team.py:624`.
This is not cosmetic. `_known_job` (`recruitment_team.py:1474-1486`) resolves a
`job_id` only against `recommendations + shortlisted_jobs` and raises
`InvalidCommand` otherwise, which is a **422 on the next click**, not merely a stale
panel. A search inside the loop that does not land in `recommendations` breaks every
subsequent `ShortlistJob` and `SelectTargetJob`.

`recommendations` is replaced with this turn's searches, not appended across turns.
That matches the command path's replace semantics and still covers a turn that searched
more than once.

Draining after `respond()` rather than writing from inside the tool is deliberate: the
tool stays free of the ORM, and the write lands in the same transaction that writes the
assistant message, so a failed turn cannot leave a half-updated thread.

---

## 4. `create_resume_agent` needs a `system_prompt` seam

`resume_agent/agent.py:34` hardcodes `system_prompt=ORCHESTRATOR_SYSTEM_PROMPT`. The
coordinator's goal statement is the substance of this issue and there is no seam for it.

```python
def create_resume_agent(
    model=None, tools=None, subagents=None,
    checkpointer=None, interrupt_on=None,
    system_prompt: str | None = None,          # new, defaults to ORCHESTRATOR_SYSTEM_PROMPT
):
```

Defaulted, so the Resume Deep Agent v2 and `OpenAgentTargetAssessmentRunner` are
unaffected.

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
    def __init__(self, *, discovery=None, model_factory=None, telemetry=None): ...

    def respond(self, messages, resume_text, current_preferences=(), context=None) -> ModelReply: ...

    # The loop itself, public because respond() is only the port adapter over it.
    def drive(self, context: ConversationContext, messages: list[Message], resume_text: str) -> dict: ...
```

`drive()` returns `{"stopped": bool, "reason": str, "submission": dict | None,
"paused": bool, "question": str, "search_queries": list[str]}`. `respond()` maps that
onto `ModelReply` or raises. On the iteration cap the dict carries
`stopped=True, reason="tool_iteration_cap"`, the shape `run_agent_turn` already uses at
`resume_agent/agent.py:57-62`.

Subagents: `[]`. The coordinator delegates to no personas in this slice. Persona work is
slice V4 (study-first).

### Turn payload and the checkpoint

`run_config = {"recursion_limit": config.COORDINATOR_MAX_TOOL_ITERATIONS,
"configurable": {"thread_id": f"coordinator-{ctx.thread_id}"}}`, on the module-level
`SqliteSaver` already created at `open_agent/runner.py:103-105`.

A stable per-thread graph id, rather than the fresh uuid the assessment runner uses, is
what makes `ask_candidate` mean anything in a conversation. A pause has to survive to the
next HTTP request or the interrupt guarantees nothing.

Each turn seeds only what is new:

- Checkpoint has messages, no pending interrupt: one `HumanMessage` carrying an
  `xml_data_block("thread_state", …)` block followed by the latest user message.
- Checkpoint has a pending interrupt: `Command(resume={"decisions": [{"type": "respond",
  "message": <latest user message>}]})`. No new `HumanMessage`.
- Checkpoint is empty (new thread, or a wiped checkpoint file): the full DB transcript
  from `self._messages(thread.id)` is replayed first, then the state block and the
  latest message. **The DB is the system of record. The checkpoint is a cache and is
  never the only copy of anything.**

`thread_state` is compact on purpose: counts, the selected target's id and title, the
preference facts, `wants_experienced_roles`, and whether a candidate profile exists. The
agent calls `read_shortlist` when it wants the postings.

### Termination

The loop ends on a `submit_recruitment_conversation` tool call at coordinator level.
The existing tool and `_ConversationPayload` are reused unmodified, which is what keeps
the evidence-quoted preference contract (`preference_update_error`) and
`_merge_preference_updates` working without a line of change.

Four exits, in precedence order:

| exit | reply | thread effect |
|---|---|---|
| `submit_recruitment_conversation` seen (last one wins) | `payload.reply` | normal |
| pending interrupt after the stream ends | `_format_questions(args)` from the `ask_candidate` call | see §6 |
| `GraphRecursionError` | last submission if one was already made, otherwise `ConversationUnavailable` | run fails, 503 |
| stream ended, no submission, no interrupt | `ConversationUnavailable` | run fails, 503 |

`_drive()` returns a dict, and on the cap it is exactly
`{"stopped": True, "reason": "tool_iteration_cap"}`, matching `run_agent_turn`'s shape
at `resume_agent/agent.py:57-62`. `respond()` maps that dict to a `ModelReply` or an
error. **`GraphRecursionError` never propagates and no turn ever fabricates a reply.**
HTTP 200 is not an acceptance criterion.

New error class:

```python
class ConversationUnavailable(RecruitmentTeamError):
    def __init__(self, message: str, *, failure_type: str, retryable: bool): ...
```

It must be added to the isinstance tuple at `http_routes.py:172-181`. That mapping is by
explicit type, not by name suffix, so a new `*Unavailable` that nobody adds to the tuple
becomes a 500.

**Accepted cost.** After the submission tool returns `"submitted"`, the graph calls the
model once more before ending, so a turn costs one extra cheap completion. The
alternatives were `return_direct` (unverified against the installed `deepagents`) and
`interrupt_on={"submit_recruitment_conversation": True}` (would collide with the
`ask_candidate` interrupt). Measure the extra call before optimising it.

### `search_query` stops being a request

`DeepAgentConversationModel` **overwrites** `ModelReply.search_query` with the last query
actually passed to the `search_jobs` tool this turn, discarding whatever the model wrote
in the payload. `case_facts["search_query"]` then records a query that was really run
instead of one that was asked for. The field becomes an observation.

This does not resolve the optional-field trap for `LangChainConversationModel`. That is
slice V2 / issue #147, where the field must become required in the submission schema.

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

Frontend, `frontend/src/components/TeamActivityPanel.jsx`:
- `TOOL_PHRASES` (L62-70) gains `read_shortlist` and `search_jobs`. Without them the raw
  string `"coordinator called read_shortlist."` renders to candidates.
- The copy at L226-228, "A full assessment runs several specialists and an independent
  judge. This usually takes a few minutes.", is shown whenever `busy` and will now
  appear on ordinary chat turns. It has to become conditional on an assessment run.

---

## 8. Wiring

`http_routes.py`. The `Depends` graph does not need a thread, because the context is a
`respond()` parameter:

```python
def get_conversation_model(
    telemetry: RecruitmentTelemetry = Depends(get_recruitment_telemetry),
    discovery: DiscoveryPort = Depends(get_job_discovery),
) -> ConversationModel:
    return DeepAgentConversationModel(discovery=discovery, telemetry=telemetry)
```

The five `app.dependency_overrides[get_conversation_model]` in
`test_recruitment_team_module.py` (L2586, 2752, 2860, 2966, 3103) override the whole
callable and keep working.

`recruitment_team/__init__.py` exports `DeepAgentConversationModel` and
`ConversationContext`.

New config constant, `backend/config.py`:

```python
COORDINATOR_MAX_TOOL_ITERATIONS: int = _positive_int_env("COORDINATOR_MAX_TOOL_ITERATIONS", 12)
```

Separate from `AGENT_MAX_TOOL_ITERATIONS` (default 20), which the resume agent and the
assessment runner share. One env var tuning a chat turn and a full assessment means
tuning either one starves the other.

`_model_reply` is the only changed call site. It builds the context, passes it, drains
`search_results`, and leaves preference validation, merge and telemetry untouched.

---

## 9. What is NOT built

Stated so the absence is a decision and not an oversight.

- **No judge on conversational turns.** Invariant 6 is scoped to V3 target assessment,
  and `_assess_target` still runs it. Adding a judge pass per chat message adds a full
  model call to every message. The conversational path's durable outputs are still
  gated: `propose_resume_edit` runs `run_all_gates`, edits stay pending until accepted,
  and preference updates still fail `preference_update_error` without an exact quote.
- **No persona subagents.** `subagents=[]`. Study-first personas are slice V4.
- **No structured diff, no multi-axis ranking, no match rationale.** Slices V5 and V6.
- **No exclusion predicate, junior heuristic or ranking formula in the tool layer.**
  `exclude_junior` is an agent decision (§3). The agent ranks by reading its own results.
- **`LangChainConversationModel` is not deleted and not modified.** It stays as the
  single-shot adapter and as the thing the loop is measured against.
- **`SearchJobs`, `ShortlistJob` and `SelectTargetJob` commands are unchanged.**
  `SearchJobs` becomes a goal hint rather than the only way results reach the thread, and
  the deterministic path still works for the UI buttons.
- **`search_query` is not made required in `_ConversationPayload`.** Slice V2 / #147.
- **No queued messages.** The per-thread lock still serialises turns. Slice V7.
- **No live-model validation script.** Add one under `backend/scripts/` when the loop
  runs against SEA-LION.

---

## 10. Acceptance

The unit tests in `backend/tests/test_coordinator_loop.py` are necessary and not
sufficient. 851 tests passed while job search returned zero results for every user.

Acceptance for this slice is the V1 rule from the PRD, driven in a browser against the
real backend, asserting on rendered text:

> Search returns matches, then ask "improve my resume for these roles". The reply names
> at least one job from the shortlist by title. It must not ask the candidate to paste a
> job description.

Record the before-state first, so an inert change cannot pass.
