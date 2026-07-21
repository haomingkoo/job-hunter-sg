# Recruitment Team Open-Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `NativeTargetAssessmentRunner` (the fixed 5-persona/synthesis/judge pipeline) with `OpenAgentTargetAssessmentRunner`, an open-ended deep agent built on the existing `resume_agent` deepagents/LangGraph engine, that genuinely chooses which personas to consult, can propose resume edits as part of its own reasoning, and can ask the candidate a question mid-run.

**Architecture:** One LangGraph agent (via `resume_agent.agent.create_resume_agent`) drives a new V3-specific tool set (`read_candidate_evidence`, `read_target_job`, `search_jobs`, `propose_resume_edit`, `ask_candidate`) plus the 5 existing recruitment personas wired as freely-delegatable `SubAgent`s. It keeps the `TargetAssessmentRunner` protocol so it drops into `recruitment_team.py` as a swap-in replacement. A mandatory independent judge still gates every run's `completed`/`quality_blocked` outcome, `ask_candidate` uses a real LangGraph interrupt (not a prompted convention), and hard numeric caps bound tool-call and edit volume per run.

**Tech Stack:** Python 3.12, FastAPI/SQLAlchemy, LangChain + LangGraph + `deepagents==0.6.12`, SEA-LION (OpenAI-compatible) via `langchain_openai.ChatOpenAI`, pytest.

## Global Constraints

- Design source: `docs/superpowers/specs/2026-07-20-recruitment-team-open-agent-design.md`. Tracking issues: #109 (core replacement), #110 (subagent-delegation spike), #111 (edit gating), #112 (checkpoint/resume), #113 (guardrails).
- No fabrication: every `propose_resume_edit` call must be rejected unless its rewrite introduces no new numeric facts and passes `validation_gates.run_all_gates`.
- No silent edits: a proposed edit is only ever persisted as `status="pending"`; it becomes part of the saved resume only through an explicit accept action.
- `propose_resume_edit` v1 scope: in-place rewrite of one existing resume block only (no embedded `\n`/`\r`, matching `resume_document.py:apply_resume_patch`'s existing constraint). Inserting or deleting a block is out of scope.
- Mandatory independent judge: every run must pass through the judge contract (`JUDGE_TOOL`/`JudgeSubmission`) before being marked `completed`, regardless of which personas were consulted or whether a synthesis-like pass happened.
- Hard numeric caps, exact starting values (tune during implementation, do not silently drop): `config.AGENT_MAX_TOOL_ITERATIONS` (currently 20) top-level tool-call recursion limit; a new `config.OPEN_AGENT_MAX_PROPOSED_EDITS` (default 8) per run.
- Rate limit to respect throughout: `config.SEALION_REQ_PER_MIN` (currently 9, per key).
- Follow the existing failure taxonomy in `docs/v3-retry-recovery-policy.md` (`transient`/`validation`/`business`/`permission`/`safety`/`cancelled`) for every new tool call site — do not invent a new taxonomy.
- This plan does not touch candidate-profile extraction (`candidate_profile.py`), job discovery/search internals, or the SQLite/Postgres persistence layer's shape beyond one new table (Task 5).

---

## File Structure

New package `backend/recruitment_team/open_agent/`:

| File | Responsibility |
|---|---|
| `__init__.py` | Exports `OpenAgentTargetAssessmentRunner`. |
| `context.py` | Context-var plumbing (`assessment_context`) giving tools access to the active request/document/edit-accumulator without threading them through LangChain's tool-call args. |
| `tools.py` | `read_candidate_evidence`, `read_target_job`, `propose_resume_edit`, `ask_candidate`. (`search_jobs` is reused unmodified from `resume_agent.tools`.) |
| `subagents.py` | `create_target_persona_subagents(registry, model)` — builds `SubAgent` entries from `PersonaPackRegistry`. |
| `guardrails.py` | No-repeat-call check, shared by `runner.py`. |
| `streaming.py` | `iter_progress_events(agent, payload, run_config)` — normalizes `agent.stream(..., subgraphs=True)` into real-time tool_call/tool_result/message events, at the top level and inside delegated persona subagents. |
| `runner.py` | `OpenAgentTargetAssessmentRunner`, implementing the `TargetAssessmentRunner` protocol. |

Modified existing files:

| File | Change |
|---|---|
| `backend/recruitment_team/assessment_contracts.py` (**new**) | Receives `TargetAssessmentRequest/Progress/Result/Update`, `TargetAssessmentRunner` protocol, the specialist/judge tool+schema+validation helpers, moved out of `target_assessment.py` (Task 2). |
| `backend/recruitment_team/target_assessment.py` | Re-imports from `assessment_contracts.py` (Task 2); deleted entirely in Task 11 once the cutover lands. |
| `backend/config.py` | New `OPEN_AGENT_MAX_PROPOSED_EDITS` constant (Task 5). |
| `backend/models.py` | New `ProposedResumeEdit` table (Task 5). |
| `backend/recruitment_team/recruitment_team.py` | `_assess_target` builds the resume document, threads it into the request, and (Task 11) constructs `OpenAgentTargetAssessmentRunner` instead of `NativeTargetAssessmentRunner`. |

Test files (one per new module, mirroring existing repo convention of co-locating by responsibility, not by layer): `backend/tests/test_open_agent_delegation_spike.py`, `test_open_agent_checkpoint_spike.py`, `test_open_agent_streaming_spike.py`, `test_assessment_contracts.py`, `test_open_agent_tools.py`, `test_open_agent_subagents.py`, `test_open_agent_guardrails.py`, `test_open_agent_runner.py`. `test_recruitment_team_module.py` and `test_target_assessment.py` get targeted updates in Task 11, not new files.

---

### Task 1: Spike — prove persona-subagent delegation actually works

**Files:**
- Create: `backend/tests/test_open_agent_delegation_spike.py`

**Interfaces:**
- Consumes: `resume_agent.agent.create_resume_agent(model, tools, subagents, checkpointer)` (existing, unchanged signature — `backend/resume_agent/agent.py:20-35`); `deepagents.SubAgent` (dict shape: `{"name": str, "description": str, "system_prompt": str, "tools": [...], "model": ...}`, per `backend/resume_agent/personas.py:118-136`).
- Produces: a written finding (as a code comment block at the top of the spike test file) on whether a persona subagent's own step budget draws from the parent's `recursion_limit`, consumed by Task 6's guardrail design.

This is issue #110. `deepagents`' `task`-based subagent delegation (the mechanism `create_persona_subagents()` is built for) has never been exercised end-to-end in this codebase — the only production call site (`resume_agent/session.py:693-697`) passes `subagents=[]`. This task proves it works before anything else is built on top of it.

- [ ] **Step 1: Write the spike test**

```python
# backend/tests/test_open_agent_delegation_spike.py
from __future__ import annotations

from langchain_core.messages import AIMessage
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel

from resume_agent.agent import create_resume_agent


class _ScriptedOrchestratorModel(FakeMessagesListChatModel):
    """Always delegates to the 'recruiter' subagent via the `task` tool, then stops."""

    def bind_tools(self, tools, **kwargs):
        return self


def test_orchestrator_can_delegate_to_a_real_persona_subagent(monkeypatch):
    import config
    import resume_agent.models as agent_models

    monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "test-key")

    delegate_call = AIMessage(
        content="",
        tool_calls=[{
            "name": "task",
            "args": {
                "description": "Review this candidate as the recruiter persona.",
                "subagent_type": "recruiter",
            },
            "id": "call-1",
        }],
    )
    final_reply = AIMessage(content="Delegated to recruiter; no further action needed.")
    orchestrator_model = _ScriptedOrchestratorModel(responses=[delegate_call, final_reply])

    persona_reply = AIMessage(
        content="",
        tool_calls=[{
            "name": "submit_assessment",
            "args": {"strength": "Clear ownership of a shipped feature.", "gap": "None", "score": 80},
            "id": "call-2",
        }],
    )
    persona_model = _ScriptedOrchestratorModel(responses=[persona_reply])

    from resume_agent.personas import create_persona_subagents

    subagents = create_persona_subagents(smart_model=persona_model)
    agent = create_resume_agent(model=orchestrator_model, tools=[], subagents=subagents)

    result = agent.invoke(
        {"messages": [{"role": "user", "content": "Assess this candidate against the target role."}]},
        config={"recursion_limit": config.AGENT_MAX_TOOL_ITERATIONS},
    )

    tool_messages = [m for m in result["messages"] if getattr(m, "name", None) == "submit_assessment"]
    assert tool_messages, "the recruiter subagent's own submission tool must appear in the trace"
```

- [ ] **Step 2: Run it and record what actually happens**

Run: `cd backend && .venv/bin/python -m pytest tests/test_open_agent_delegation_spike.py -v`

Two real outcomes are possible here, and both are valid findings — this step is exploratory, not a fixed pass/fail gate:
- **It passes as written**: delegation works exactly like `create_persona_subagents()`'s existing unit test assumed. Add a comment at the top of the file: `# CONFIRMED 2026-0X-XX: task-based subagent delegation resolves subagent_type by SubAgent["name"]; the persona's own submit_assessment tool call appears in the parent's result["messages"].`
- **It fails** (e.g. `task` isn't resolved, or the persona's tool call doesn't surface in the top-level result): read `.venv/lib/python3.12/site-packages/deepagents/middleware/subagents.py` to find the actual mechanism, fix the test to match reality, and add a comment recording the real contract.

- [ ] **Step 3: Add a second assertion for the iteration-budget question**

Extend the same test (or add a second one) to assert on `result` whether the persona subagent's own internal steps count against the top-level `recursion_limit` passed to `agent.invoke()`. Concretely: construct a persona model that would need 3 internal steps to complete (script 3 responses), set `recursion_limit=2` on the top-level invoke, and observe whether a `GraphRecursionError` fires (budgets are shared) or the subagent completes regardless (budgets are separate). Record the answer as a comment — Task 8 depends on knowing this to size the guardrail.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_open_agent_delegation_spike.py
git commit -m "test: prove persona-subagent delegation via deepagents task tool"
```

---

### Task 2: Spike — prove a durable checkpointer + `ask_candidate` interrupt/resume works

**Files:**
- Create: `backend/tests/test_open_agent_checkpoint_spike.py`

**Interfaces:**
- Consumes: `deepagents.create_deep_agent(..., interrupt_on=dict[str, bool])` (confirmed present at `.venv/lib/python3.12/site-packages/deepagents/graph.py:271`, wired via `HumanInTheLoopMiddleware` at lines 830-835); `resume_agent.agent.create_resume_agent`'s `checkpointer` parameter (currently always resolved from `resume_agent.session._get_checkpointer()`, an in-memory `MemorySaver` — `backend/resume_agent/session.py:44-50` — which is not durable across a process restart and is not what this task uses).
- Produces: a confirmed interrupt/resume call pattern, consumed by Task 6 (`ask_candidate`).

This is the foundational piece of issue #112 and a prerequisite for issue #113's `ask_candidate` requirement — a real turn-ending mechanism needs an actual LangGraph interrupt, not a post-hoc filter (a post-hoc filter can only decide what to keep *after* the graph already ran further steps; it cannot stop those steps from happening). No code in this repo currently uses `interrupt_on`, so this is genuinely unverified integration, not a known-working reuse.

- [ ] **Step 1: Write the spike test**

```python
# backend/tests/test_open_agent_checkpoint_spike.py
from __future__ import annotations

from langchain_core.messages import AIMessage
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from resume_agent.agent import create_resume_agent


class _ScriptedModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def test_ask_candidate_interrupts_before_any_further_tool_call(monkeypatch):
    import resume_agent.models as agent_models

    monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "test-key")

    ask_call = AIMessage(
        content="",
        tool_calls=[{"name": "ask_candidate", "args": {"question": "How large was the team you led?"}, "id": "call-1"}],
    )
    would_be_next_call = AIMessage(
        content="",
        tool_calls=[{"name": "propose_resume_edit", "args": {"block_id": "b1", "rewrite": "Led a team of 12."}, "id": "call-2"}],
    )
    model = _ScriptedModel(responses=[ask_call, would_be_next_call])

    from recruitment_team.open_agent.tools import ask_candidate

    agent = create_resume_agent(
        model=model,
        tools=[ask_candidate],
        subagents=[],
        checkpointer=MemorySaver(),
    )
    run_config = {"configurable": {"thread_id": "spike-thread-1"}, "recursion_limit": 20}

    result = agent.invoke(
        {"messages": [{"role": "user", "content": "Assess this candidate."}]},
        config=run_config,
    )

    assert "__interrupt__" in result, (
        "expected create_deep_agent(interrupt_on={'ask_candidate': True}) to pause the graph; "
        "if this fails, read deepagents/middleware and langchain.agents.middleware.HumanInTheLoopMiddleware "
        "to find the actual signal key and fix this assertion to match reality"
    )
    proposed_after = [m for m in result["messages"] if getattr(m, "name", None) == "propose_resume_edit"]
    assert not proposed_after, "no tool call after ask_candidate should have executed before the interrupt"

    resumed = agent.invoke(Command(resume="12 engineers."), config=run_config)
    assert resumed["messages"], "resuming with the candidate's answer must continue the graph"
```

Note: `create_resume_agent` does not yet accept `interrupt_on` — Step 3 adds that parameter.

- [ ] **Step 2: Run it, expect it to fail informatively**

Run: `cd backend && .venv/bin/python -m pytest tests/test_open_agent_checkpoint_spike.py -v`
Expected: FAIL — `create_resume_agent()` has no `interrupt_on` parameter yet.

- [ ] **Step 3: Add `interrupt_on` passthrough to `create_resume_agent`**

```python
# backend/resume_agent/agent.py — modify create_resume_agent (was lines 20-35)
def create_resume_agent(
    model: Any | None = None,
    tools: Sequence[Any] | None = None,
    subagents: Sequence[SubAgent] | None = None,
    checkpointer: Any | None = None,
    interrupt_on: dict[str, Any] | None = None,
):
    """Create the Resume Deep Agent graph."""
    from deepagents import create_deep_agent

    return create_deep_agent(
        model=model or create_agent_model(),
        tools=list(tools) if tools is not None else DEFAULT_TOOLS,
        subagents=list(subagents) if subagents is not None else create_persona_subagents(),
        system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
        checkpointer=checkpointer,
        interrupt_on=interrupt_on,
    )
```

- [ ] **Step 4: Wire `interrupt_on={"ask_candidate": True}` into the spike test's agent construction, re-run**

Update the `create_resume_agent(...)` call in Step 1's test to pass `interrupt_on={"ask_candidate": True}`.

Run: `cd backend && .venv/bin/python -m pytest tests/test_open_agent_checkpoint_spike.py -v`

If the `"__interrupt__"` assertion still fails, read `.venv/lib/python3.12/site-packages/langchain/agents/middleware/human_in_the_loop.py` (or wherever `HumanInTheLoopMiddleware` actually lives in the installed version) to find the real signal key and resume-call shape, fix the test's assertions to match, and record the confirmed contract as a comment at the top of the file. Do not proceed to Task 6 until this test passes against the real library behavior.

- [ ] **Step 5: Commit**

```bash
git add backend/resume_agent/agent.py backend/tests/test_open_agent_checkpoint_spike.py
git commit -m "feat: add interrupt_on passthrough and prove ask_candidate can hard-interrupt"
```

---

### Task 3: Extract shared assessment contracts

**Files:**
- Create: `backend/recruitment_team/assessment_contracts.py`
- Modify: `backend/recruitment_team/target_assessment.py:1-211` (imports + deletions)
- Test: existing `backend/tests/test_target_assessment.py` (no new tests — this is a pure refactor; the gate is that the existing suite stays green)

**Interfaces:**
- Produces (all moved verbatim from `target_assessment.py`, underscore dropped since they're now cross-module): `TargetAssessmentRequest`, `TargetAssessmentProgress`, `TargetAssessmentResult`, `TargetAssessmentUpdate`, `TargetAssessmentRunner` (Protocol), `SpecialistSubmission`, `SynthesisSubmission`, `Deduction`, `RubricScores`, `JudgeSubmission`, `SPECIALIST_TOOL`, `SYNTHESIS_TOOL`, `JUDGE_TOOL`, `validate_specialist(payload, persona_id, request) -> tuple[dict | None, str]`, `validate_synthesis(payload, specialist_runs) -> tuple[dict | None, str]`, `render_synthesis(payload) -> str`, `evidence_sets(request) -> tuple[set[str], set[str], dict[str, set[str]]]`, `valid_unique_ids(values, allowed) -> bool`, `tool_payload(response, tool, schema) -> tuple[dict | None, str]`, `usage_from_response(response) -> tuple[int, int, str]`, `invoke_structured(model, tool, system_prompt, data_name, data, *, telemetry, operation, attempt, max_attempts, attributes) -> tuple[dict | None, str, int, int, str]`, `target_assessment_execution_policy() -> dict`.
- One behavior addition: `TargetAssessmentRequest` gains a new field `resume_document: dict | None = None` (defaulted, so every existing call site that constructs it by keyword — e.g. `test_target_assessment.py`'s `_request()` helper — keeps working unchanged). `NativeTargetAssessmentRunner` never reads this field; `OpenAgentTargetAssessmentRunner` (Task 8) requires it.

`invoke_structured` is `NativeTargetAssessmentRunner._invoke` (`target_assessment.py:308-348`) turned into a free function — its body is unchanged except `self._telemetry` becomes a `telemetry` parameter.

- [ ] **Step 1: Create `assessment_contracts.py` with the moved code**

```python
# backend/recruitment_team/assessment_contracts.py
"""Shared request/result types and specialist/judge contracts for target assessment.

Used by both the legacy NativeTargetAssessmentRunner and the open-agent runner,
so a specialist's submission is validated identically regardless of whether the
orchestrator called it directly or delegated to it as a subagent.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterator, Literal, Protocol

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field, ValidationError

import config
from prompt_safety import xml_data_block

from .candidate_profile import CandidateEvidenceProfile
from .discovery import JobSnapshot
from .role_success import RoleSuccessProfile
from .telemetry import RecruitmentTelemetry


@dataclass(frozen=True)
class TargetAssessmentRequest:
    candidate_profile: CandidateEvidenceProfile
    role_profile: RoleSuccessProfile
    target_job: JobSnapshot
    trace_key: str
    resume_document: dict[str, Any] | None = None


@dataclass(frozen=True)
class TargetAssessmentProgress:
    team_member: str
    status: Literal["running", "completed", "failed"]
    summary: str
    detail: dict


@dataclass(frozen=True)
class TargetAssessmentResult:
    status: Literal["completed", "quality_blocked", "failed"]
    specialist_runs: tuple[dict, ...]
    synthesis: str
    judge: dict | None
    correction: dict | None
    error: dict | None
    execution_policy: dict


TargetAssessmentUpdate = TargetAssessmentProgress | TargetAssessmentResult


class TargetAssessmentRunner(Protocol):
    def run(self, request: TargetAssessmentRequest) -> Iterator[TargetAssessmentUpdate]: ...


# --- Specialist / synthesis / judge schemas (moved verbatim from target_assessment.py) ---
# Copy class bodies for SpecialistSubmission (was _SpecialistSubmission), SynthesisSubmission,
# Deduction, RubricScores, JudgeSubmission exactly as they exist today at
# target_assessment.py:69-132, renaming only the leading underscore off each class name.

# --- Tools ---
# Copy _dump_specialist/_dump_synthesis/_dump_judge and the three StructuredTool.from_function(...)
# blocks exactly as they exist at target_assessment.py:134-173, renaming
# _SPECIALIST_TOOL/_SYNTHESIS_TOOL/_JUDGE_TOOL to SPECIALIST_TOOL/SYNTHESIS_TOOL/JUDGE_TOOL.

def target_assessment_execution_policy() -> dict:
    # Copy verbatim from target_assessment.py:176-195 (unchanged body).
    ...


def tool_payload(response: AIMessage, tool: StructuredTool, schema: type[BaseModel]) -> tuple[dict | None, str]:
    # Copy verbatim from target_assessment.py:198-205 (was _tool_payload).
    ...


def usage_from_response(response: AIMessage) -> tuple[int, int, str]:
    # Copy verbatim from target_assessment.py:208-211 (was _usage).
    ...


def evidence_sets(request: TargetAssessmentRequest) -> tuple[set[str], set[str], dict[str, set[str]]]:
    # Copy verbatim from target_assessment.py:214-221 (was _evidence_sets).
    ...


def valid_unique_ids(values: list[str], allowed: set[str]) -> bool:
    # Copy verbatim from target_assessment.py:224-225 (was _valid_unique_ids).
    ...


def validate_specialist(
    payload: dict | None,
    persona_id: str,
    request: TargetAssessmentRequest,
) -> tuple[dict | None, str]:
    # Copy verbatim from target_assessment.py:228-250 (was _validate_specialist).
    ...


def validate_synthesis(payload: dict | None, specialist_runs: tuple[dict, ...]) -> tuple[dict | None, str]:
    # Copy verbatim from target_assessment.py:253-270 (was _validate_synthesis).
    ...


def render_synthesis(payload: dict) -> str:
    # Copy verbatim from target_assessment.py:273-285 (was _render_synthesis).
    ...


def invoke_structured(
    model,
    tool: StructuredTool,
    system_prompt: str,
    data_name: str,
    data: dict,
    *,
    telemetry: RecruitmentTelemetry,
    operation: str,
    attempt: int,
    max_attempts: int,
    attributes: dict[str, str | int | float | bool],
) -> tuple[dict | None, str, int, int, str]:
    # Copy verbatim from target_assessment.py:308-348 (was NativeTargetAssessmentRunner._invoke),
    # replacing every `self._telemetry` with `telemetry`.
    ...
```

- [ ] **Step 2: Update `target_assessment.py` to import from the new module and drop the moved definitions**

Replace the class/function/tool definitions this plan just moved (lines 51-348 minus `NativeTargetAssessmentRunner` itself) with:

```python
from .assessment_contracts import (
    JUDGE_TOOL,
    SPECIALIST_TOOL,
    SYNTHESIS_TOOL,
    Deduction,
    JudgeSubmission,
    RubricScores,
    SpecialistSubmission,
    SynthesisSubmission,
    TargetAssessmentProgress,
    TargetAssessmentRequest,
    TargetAssessmentResult,
    TargetAssessmentRunner,
    TargetAssessmentUpdate,
    evidence_sets,
    invoke_structured,
    render_synthesis,
    target_assessment_execution_policy,
    tool_payload,
    usage_from_response,
    valid_unique_ids,
    validate_specialist,
    validate_synthesis,
)
```

Update `NativeTargetAssessmentRunner._invoke` call sites (`_run_specialist`, `_run_synthesis`, `_run_judge`) to call the free function `invoke_structured(model, tool, ..., telemetry=self._telemetry, ...)` instead of `self._invoke(model, tool, ...)`, and delete the `_invoke` method itself. Update every other in-file reference from `_SPECIALIST_TOOL`/`_validate_specialist`/etc. to the unprefixed imported names.

- [ ] **Step 3: Run the full existing suite, confirm zero regressions**

Run: `cd backend && .venv/bin/python -m pytest tests/test_target_assessment.py tests/test_recruitment_team_module.py -v`
Expected: PASS, same test count and names as before this task (this is a pure move — no behavior should change).

- [ ] **Step 4: Commit**

```bash
git add backend/recruitment_team/assessment_contracts.py backend/recruitment_team/target_assessment.py
git commit -m "refactor: extract shared assessment contracts for reuse by the open-agent runner"
```

---

### Task 4: Read-only context tools — `read_candidate_evidence`, `read_target_job`

**Files:**
- Create: `backend/recruitment_team/open_agent/__init__.py` (empty)
- Create: `backend/recruitment_team/open_agent/context.py`
- Create: `backend/recruitment_team/open_agent/tools.py`
- Test: `backend/tests/test_open_agent_tools.py`

**Interfaces:**
- Consumes: `assessment_contracts.TargetAssessmentRequest` (Task 3).
- Produces: `assessment_context(request: TargetAssessmentRequest) -> ContextManager[None]`, `read_candidate_evidence` (LangChain `@tool`), `read_target_job` (LangChain `@tool`) — both consumed by Task 8's runner when constructing the orchestrator's tool list.

Follows the existing `_current_bullets: ContextVar` pattern already used in `backend/resume_agent/tools.py` for giving a tool access to per-invocation state without threading IDs through the model.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_open_agent_tools.py
from __future__ import annotations

from recruitment_team.assessment_contracts import TargetAssessmentRequest
from recruitment_team.open_agent.context import assessment_context
from recruitment_team.open_agent.tools import read_candidate_evidence, read_target_job


def _request(resume_document=None):
    from backend.tests.test_recruitment_team_module import (
        _candidate_profile_run,
        _job_snapshot,
        _role_profile_run,
    )

    return TargetAssessmentRequest(
        candidate_profile=_candidate_profile_run().profile,
        role_profile=_role_profile_run().profile,
        target_job=_job_snapshot(),
        trace_key="open-agent-trace-key",
        resume_document=resume_document,
    )


def test_read_candidate_evidence_returns_current_request_fields():
    request = _request()
    with assessment_context(request):
        result = read_candidate_evidence.invoke({})
    assert result["ok"] is True
    assert result["fields"]


def test_read_target_job_returns_current_role_profile_and_job():
    request = _request()
    with assessment_context(request):
        result = read_target_job.invoke({})
    assert result["ok"] is True
    assert result["target_job"]["title"] or result["target_job"]
    assert result["role_profile"]["criteria"]


def test_tools_fail_closed_outside_an_active_context():
    result = read_candidate_evidence.invoke({})
    assert result["ok"] is False
    assert result["failure_type"] == "business"
```

- [ ] **Step 2: Run and confirm it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_open_agent_tools.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'recruitment_team.open_agent'`.

- [ ] **Step 3: Implement `context.py`**

```python
# backend/recruitment_team/open_agent/context.py
"""Per-invocation context for open-agent tools, mirroring resume_agent.tools's
_current_bullets pattern -- tools read the active request without the model
having to pass IDs it was never given."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

from ..assessment_contracts import TargetAssessmentRequest

_current_request: ContextVar[TargetAssessmentRequest | None] = ContextVar(
    "open_agent_current_request", default=None
)
_proposed_edits: ContextVar[list[dict[str, Any]] | None] = ContextVar(
    "open_agent_proposed_edits", default=None
)


@contextmanager
def assessment_context(request: TargetAssessmentRequest) -> Iterator[None]:
    request_token = _current_request.set(request)
    edits_token = _proposed_edits.set([])
    try:
        yield
    finally:
        _current_request.reset(request_token)
        _proposed_edits.reset(edits_token)


def current_request() -> TargetAssessmentRequest | None:
    return _current_request.get()


def proposed_edits() -> list[dict[str, Any]] | None:
    return _proposed_edits.get()
```

- [ ] **Step 4: Implement `tools.py`**

```python
# backend/recruitment_team/open_agent/tools.py
"""V3-specific tools bound to the open-agent orchestrator. search_jobs is reused
unmodified from resume_agent.tools -- it needs no per-request context."""

from __future__ import annotations

from dataclasses import asdict

from langchain_core.tools import tool

from . import context


@tool
def read_candidate_evidence() -> dict:
    """Read the candidate's evidence-cited profile fields for the active run.

    Returns each field with its resume_evidence_ids, so a citation in a
    persona submission or a proposed edit can point at real evidence.
    """
    request = context.current_request()
    if request is None:
        return {"ok": False, "failure_type": "business", "reason": "No active assessment context."}
    return {
        "ok": True,
        "fields": [asdict(field) for field in request.candidate_profile.fields],
    }


@tool
def read_target_job() -> dict:
    """Read the target job posting and its derived role-success criteria for the active run."""
    request = context.current_request()
    if request is None:
        return {"ok": False, "failure_type": "business", "reason": "No active assessment context."}
    return {
        "ok": True,
        "target_job": asdict(request.target_job),
        "role_profile": asdict(request.role_profile),
    }
```

- [ ] **Step 5: Run tests, verify pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_open_agent_tools.py -v`
Expected: PASS (3 tests). If `request.candidate_profile.fields` or `request.target_job`/`request.role_profile` are not directly `dataclasses.asdict`-able (e.g. contain nested non-dataclass objects), adjust the two tools to build the dict by hand from the actual field names on `CandidateEvidenceProfile`/`JobSnapshot`/`RoleSuccessProfile` — do not guess; open those three classes and confirm the exact shape before finalizing.

- [ ] **Step 6: Commit**

```bash
git add backend/recruitment_team/open_agent/ backend/tests/test_open_agent_tools.py
git commit -m "feat: add read_candidate_evidence and read_target_job open-agent tools"
```

---

### Task 5: `propose_resume_edit` tool and pending-edit persistence

**Files:**
- Modify: `backend/recruitment_team/open_agent/context.py` (add document context)
- Modify: `backend/recruitment_team/open_agent/tools.py` (add `propose_resume_edit`)
- Modify: `backend/config.py` (add `OPEN_AGENT_MAX_PROPOSED_EDITS`)
- Modify: `backend/models.py` (add `ProposedResumeEdit` table)
- Test: `backend/tests/test_open_agent_tools.py` (extend), `backend/tests/test_models.py` if it exists, else a new minimal migration check inline in the same test file

**Interfaces:**
- Consumes: `validation_gates.run_all_gates(original, tailored, jd_text="", required_keywords=None, injectable_keywords=None) -> list[GateResult]` (`backend/validation_gates.py:457-472`, unchanged); `resume_document.py`'s block shape (`document["blocks"]`, each `{"id", "text", "section_key", "entry_id", ...}`, `document["revision"]`).
- Produces: `propose_resume_edit` tool; `ProposedResumeEdit` ORM model consumed by Task 8 (runner persists accumulated proposals at the end of a run) and by the (out-of-plan-scope) accept/reject API endpoints the frontend will call — this plan builds the tool and the table only; wiring an accept/reject HTTP endpoint is deliberately left to a follow-up, since the spec's Non-goals exclude API surface changes beyond the runner swap.

- [ ] **Step 1: Add `OPEN_AGENT_MAX_PROPOSED_EDITS` to config**

```python
# backend/config.py -- add near AGENT_MAX_TOOL_ITERATIONS (line 88)
OPEN_AGENT_MAX_PROPOSED_EDITS: int = _positive_int_env("OPEN_AGENT_MAX_PROPOSED_EDITS", 8)
```

- [ ] **Step 2: Write the failing test for the tool**

```python
# backend/tests/test_open_agent_tools.py -- append
from recruitment_team.open_agent.tools import propose_resume_edit


def _document():
    return {
        "schema_version": 1,
        "revision": "rev-1",
        "raw_text": "Led team of 12 engineers saving $3M.",
        "blocks": [{"id": "b1", "text": "Led team of 12 engineers saving $3M.", "section_key": "experience", "entry_id": "e1"}],
    }


def test_propose_resume_edit_accepts_a_grounded_in_place_rewrite():
    request = _request(resume_document=_document())
    with assessment_context(request):
        result = propose_resume_edit.invoke({"block_id": "b1", "rewrite": "Directed team of 12 engineers saving $3M."})
    assert result["accepted"] is True
    assert result["application_status"] == "pending_user_review"


def test_propose_resume_edit_rejects_new_numeric_facts():
    request = _request(resume_document=_document())
    with assessment_context(request):
        result = propose_resume_edit.invoke({"block_id": "b1", "rewrite": "Led team of 25 engineers saving $3M."})
    assert result["accepted"] is False
    assert "25" in result["reason"]


def test_propose_resume_edit_rejects_multi_block_rewrite():
    request = _request(resume_document=_document())
    with assessment_context(request):
        result = propose_resume_edit.invoke({"block_id": "b1", "rewrite": "Line one.\nLine two."})
    assert result["accepted"] is False


def test_propose_resume_edit_stops_at_the_cap(monkeypatch):
    import config

    monkeypatch.setattr(config, "OPEN_AGENT_MAX_PROPOSED_EDITS", 1)
    request = _request(resume_document=_document())
    with assessment_context(request):
        first = propose_resume_edit.invoke({"block_id": "b1", "rewrite": "Directed team of 12 engineers saving $3M."})
        second = propose_resume_edit.invoke({"block_id": "b1", "rewrite": "Managed team of 12 engineers saving $3M."})
    assert first["accepted"] is True
    assert second["accepted"] is False
    assert second["checkpoint_required"] is True
```

(This appends to the same `_request` helper from Task 4 — update it to accept `resume_document` if Task 4 didn't already, which it does per Task 4 Step 1's signature.)

- [ ] **Step 3: Run and confirm failure**

Run: `cd backend && .venv/bin/python -m pytest tests/test_open_agent_tools.py -v -k propose_resume_edit`
Expected: FAIL — `ImportError: cannot import name 'propose_resume_edit'`.

- [ ] **Step 4: Add document context to `context.py`**

```python
# backend/recruitment_team/open_agent/context.py -- add alongside _current_request
from typing import Any

_current_document: ContextVar[dict[str, Any] | None] = ContextVar(
    "open_agent_current_document", default=None
)


@contextmanager
def assessment_context(request: TargetAssessmentRequest) -> Iterator[None]:
    request_token = _current_request.set(request)
    document_token = _current_document.set(request.resume_document)
    edits_token = _proposed_edits.set([])
    try:
        yield
    finally:
        _current_request.reset(request_token)
        _current_document.reset(document_token)
        _proposed_edits.reset(edits_token)


def current_document() -> dict[str, Any] | None:
    return _current_document.get()
```

- [ ] **Step 5: Implement `propose_resume_edit`**

```python
# backend/recruitment_team/open_agent/tools.py -- add
import config
from validation_gates import _extract_numbers, run_all_gates


@tool
def propose_resume_edit(block_id: str, rewrite: str) -> dict:
    """Draft an in-place, evidence-safe rewrite of one existing resume block.

    `block_id` must be a canonical block ID visible in the active resume
    document. `rewrite` must replace that block's text without introducing
    new numeric facts and must stay within one block (no line breaks) -- this
    tool cannot insert or delete a block. A valid proposal remains pending
    until the candidate explicitly accepts it.
    """
    document = context.current_document()
    edits = context.proposed_edits()
    if document is None or edits is None:
        return {"accepted": False, "reason": "No active assessment context.", "block_id": block_id}
    if len(edits) >= config.OPEN_AGENT_MAX_PROPOSED_EDITS:
        return {
            "accepted": False,
            "reason": "Per-run proposed-edit cap reached; checkpoint back to the candidate before proposing more.",
            "block_id": block_id,
            "checkpoint_required": True,
        }
    block = next((b for b in document.get("blocks", []) if b.get("id") == block_id), None)
    if not block:
        return {"accepted": False, "reason": "Unknown resume block.", "block_id": block_id}

    clean_rewrite = (rewrite or "").strip()
    if "\n" in clean_rewrite or "\r" in clean_rewrite:
        return {"accepted": False, "reason": "A replacement must stay within one resume block.", "block_id": block_id}

    original_text = str(block.get("text") or "")
    new_numbers = _extract_numbers(clean_rewrite) - _extract_numbers(original_text)
    if new_numbers:
        return {
            "accepted": False,
            "reason": f"Unsupported numeric facts: {', '.join(sorted(new_numbers))}",
            "block_id": block_id,
        }

    failed = [gate for gate in run_all_gates(original_text, clean_rewrite) if not gate.passed]
    if failed:
        return {"accepted": False, "reason": "; ".join(gate.message for gate in failed), "block_id": block_id}

    edits.append({
        "block_id": block_id,
        "section_key": block.get("section_key", ""),
        "entry_id": block.get("entry_id", ""),
        "original": original_text,
        "rewrite": clean_rewrite,
        "document_revision": document.get("revision"),
        "status": "pending",
    })
    return {"accepted": True, "application_status": "pending_user_review", "block_id": block_id, "rewrite": clean_rewrite}
```

- [ ] **Step 6: Run tests, verify pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_open_agent_tools.py -v`
Expected: PASS (7 tests total: 3 from Task 4 + 4 from this task).

- [ ] **Step 7: Add the `ProposedResumeEdit` table**

```python
# backend/models.py -- add near TargetAssessmentArtifact (after line 503)
class ProposedResumeEdit(Base):
    """A pending, agent-proposed resume edit awaiting explicit candidate accept/reject."""

    __tablename__ = "proposed_resume_edits"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    thread_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("recruitment_threads.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("recruitment_runs.id"), nullable=False)
    resume_version_id: Mapped[int] = mapped_column(Integer, ForeignKey("resume_versions.id"), nullable=False)
    block_id: Mapped[str] = mapped_column(String(64), nullable=False)
    section_key: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    entry_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    original: Mapped[str] = mapped_column(Text, nullable=False)
    rewrite: Mapped[str] = mapped_column(Text, nullable=False)
    document_revision: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    __table_args__ = (
        Index("ix_proposed_resume_edit_thread", "user_id", "thread_id", "status"),
    )
```

(`_utcnow` and `datetime`/`DateTime`/`Index` imports already exist in `models.py` — confirm by checking the top of the file before adding; do not re-import if already present.)

- [ ] **Step 8: Verify the table creates cleanly**

Run: `cd backend && .venv/bin/python -c "import models; models.Base.metadata.create_all(__import__('sqlalchemy').create_engine('sqlite:///:memory:'))"`
Expected: no exception.

- [ ] **Step 9: Commit**

```bash
git add backend/config.py backend/models.py backend/recruitment_team/open_agent/context.py backend/recruitment_team/open_agent/tools.py backend/tests/test_open_agent_tools.py
git commit -m "feat: add propose_resume_edit tool and ProposedResumeEdit table"
```

---

### Task 6: `ask_candidate` tool wired to the proven interrupt mechanism

**Files:**
- Modify: `backend/recruitment_team/open_agent/tools.py` (add `ask_candidate`)
- Test: `backend/tests/test_open_agent_tools.py` (extend)

**Interfaces:**
- Consumes: the confirmed `interrupt_on`/resume contract from Task 2.
- Produces: `ask_candidate` (LangChain `@tool`), consumed by Task 8's runner, which constructs the agent with `interrupt_on={"ask_candidate": True}`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_open_agent_tools.py -- append
from recruitment_team.open_agent.tools import ask_candidate


def test_ask_candidate_returns_the_question_unchanged():
    result = ask_candidate.invoke({"question": "How large was the team you led?"})
    assert result["question"] == "How large was the team you led?"
    assert result["ok"] is True
```

- [ ] **Step 2: Run and confirm failure**

Run: `cd backend && .venv/bin/python -m pytest tests/test_open_agent_tools.py -v -k ask_candidate`
Expected: FAIL — `ImportError: cannot import name 'ask_candidate'`.

- [ ] **Step 3: Implement `ask_candidate`**

```python
# backend/recruitment_team/open_agent/tools.py -- add
@tool
def ask_candidate(question: str) -> dict:
    """Ask the candidate one focused question about a real evidence gap.

    This tool must be bound with interrupt_on={"ask_candidate": True} on the
    orchestrator agent -- calling it pauses the graph before any further tool
    call executes. The candidate's next message answers it; that answer
    becomes citable evidence for later propose_resume_edit calls in this
    thread. This is enforced by the interrupt, not by prompted convention.
    """
    return {"ok": True, "question": question}
```

- [ ] **Step 4: Run tests, verify pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_open_agent_tools.py -v`
Expected: PASS (8 tests total).

- [ ] **Step 5: Extend Task 2's spike test into a real regression test**

Copy `test_ask_candidate_interrupts_before_any_further_tool_call` from `test_open_agent_checkpoint_spike.py` into a new `test_open_agent_runner.py` fixture-style helper (Task 8 will build the real runner test file) — for now, just confirm the existing spike test still passes unchanged now that `ask_candidate` lives in its permanent module rather than being redefined inline.

Update the spike test's import from an inline tool definition (if it had one) to `from recruitment_team.open_agent.tools import ask_candidate`.

Run: `cd backend && .venv/bin/python -m pytest tests/test_open_agent_checkpoint_spike.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/recruitment_team/open_agent/tools.py backend/tests/test_open_agent_tools.py backend/tests/test_open_agent_checkpoint_spike.py
git commit -m "feat: add ask_candidate tool"
```

---

### Task 7: Persona subagent wiring from `PersonaPackRegistry`

**Files:**
- Create: `backend/recruitment_team/open_agent/subagents.py`
- Test: `backend/tests/test_open_agent_subagents.py`

**Interfaces:**
- Consumes: `recruitment_team.persona_packs.PersonaPack` (fields: `persona_id, display_name, purpose, job_scope, criteria, examples, counterexamples, source_ids, limitations, labelled_fixtures` — `backend/recruitment_team/persona_packs.py:37-47`), `PersonaPackRegistry.personas` (`persona_packs.py:51-56`), `assessment_contracts.SPECIALIST_TOOL`/`SpecialistSubmission` (Task 3).
- Produces: `create_target_persona_subagents(registry: PersonaPackRegistry, model) -> list[SubAgent]`, consumed by Task 8's runner.

Mirrors `resume_agent.personas.create_persona_subagents()`'s exact `SubAgent` dict shape (`{"name", "description", "system_prompt", "tools", "model"}`), but sources persona content from `PersonaPackRegistry` (the job-specific, richer pack already used by `NativeTargetAssessmentRunner`) instead of `resume_agent.personas`'s own generic `_PERSONAS` list. Each subagent gets exactly one tool — its own submission tool — so it cannot call `propose_resume_edit`, `ask_candidate`, or anything else; only the top-level orchestrator holds those.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_open_agent_subagents.py
from __future__ import annotations

from recruitment_team.assessment_contracts import SPECIALIST_TOOL
from recruitment_team.open_agent.subagents import create_target_persona_subagents
from recruitment_team.persona_packs import load_persona_pack_registry


def test_creates_one_subagent_per_persona_pack_entry():
    registry = load_persona_pack_registry()
    subagents = create_target_persona_subagents(registry, model=object())

    assert len(subagents) == len(registry.personas)
    assert {sub["name"] for sub in subagents} == {pack.persona_id for pack in registry.personas}


def test_each_subagent_has_exactly_its_own_submission_tool():
    registry = load_persona_pack_registry()
    subagents = create_target_persona_subagents(registry, model=object())

    for sub in subagents:
        assert [t.name for t in sub["tools"]] == [SPECIALIST_TOOL.name]


def test_system_prompt_embeds_the_pack_s_job_scope_and_criteria():
    registry = load_persona_pack_registry()
    subagents = create_target_persona_subagents(registry, model=object())
    recruiter_pack = registry.pack("recruiter")
    recruiter_subagent = next(sub for sub in subagents if sub["name"] == "recruiter")

    assert recruiter_pack.job_scope in recruiter_subagent["system_prompt"]
    assert recruiter_pack.criteria[0] in recruiter_subagent["system_prompt"]
```

- [ ] **Step 2: Run and confirm failure**

Run: `cd backend && .venv/bin/python -m pytest tests/test_open_agent_subagents.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `subagents.py`**

```python
# backend/recruitment_team/open_agent/subagents.py
"""Build SubAgent entries from the recruitment persona packs, mirroring
resume_agent.personas.create_persona_subagents()'s shape and one-tool-only
contract, but sourced from the job-specific PersonaPackRegistry."""

from __future__ import annotations

from typing import Any, cast

from deepagents import SubAgent

from ..assessment_contracts import SPECIALIST_TOOL
from ..persona_packs import PersonaPack, PersonaPackRegistry


def _system_prompt(pack: PersonaPack) -> str:
    criteria = "\n".join(f"- {item}" for item in pack.criteria)
    examples = "\n".join(f"- {item}" for item in pack.examples)
    counterexamples = "\n".join(f"- {item}" for item in pack.counterexamples)
    return (
        f"You are the {pack.display_name} reviewer.\n\n"
        f"Purpose: {pack.purpose}\n\n"
        f"Scope: {pack.job_scope}\n\n"
        f"Criteria:\n{criteria}\n\n"
        f"Examples:\n{examples}\n\n"
        f"Avoid:\n{counterexamples}\n\n"
        "Submit exactly one structured assessment through your supplied tool. "
        "Never reveal private reasoning."
    )


def create_target_persona_subagents(registry: PersonaPackRegistry, model: Any) -> list[SubAgent]:
    """Return one freely-delegatable SubAgent per persona pack entry."""
    return [
        cast(
            SubAgent,
            {
                "name": pack.persona_id,
                "description": pack.purpose,
                "system_prompt": _system_prompt(pack),
                "tools": [SPECIALIST_TOOL],
                "model": model,
            },
        )
        for pack in registry.personas
    ]
```

- [ ] **Step 4: Run tests, verify pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_open_agent_subagents.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/recruitment_team/open_agent/subagents.py backend/tests/test_open_agent_subagents.py
git commit -m "feat: build persona subagents from PersonaPackRegistry"
```

---

### Task 8: Guardrails — no-repeat-call check

**Files:**
- Create: `backend/recruitment_team/open_agent/guardrails.py`
- Test: `backend/tests/test_open_agent_guardrails.py`

**Interfaces:**
- Consumes: nothing new (pure functions over LangChain message lists).
- Produces: `has_repeated_call(messages: list, tool_name: str, args: dict) -> bool`, consumed by Task 10's runner (via `guarded_search_jobs`) to decide whether to reject a would-be-duplicate call (implemented as validation feedback returned to the model, not a hard crash — matching this codebase's existing retry-with-exact-feedback pattern).

**Scope correction from an earlier draft of this plan:** this task's title originally said "and combined iteration budget," but Task 1's spike finding makes a genuine combined counter unachievable as first envisioned — a persona subagent's internal steps are invisible to the parent's message history (only one synthesized `"task"`-named `ToolMessage` per delegation ever appears there), so the orchestrator cannot count or bound a subagent's internal work from outside. What IS achievable, and is what Task 10 actually wires in: `AGENT_MAX_TOOL_ITERATIONS` bounds the orchestrator's own top-level step count (which includes one step per delegation, so it indirectly bounds how many times personas get consulted), each persona subagent has exactly one tool available (Task 7), which self-limits typical depth even without an external hard guarantee, and `OPEN_AGENT_MAX_PROPOSED_EDITS` (Task 5) bounds total edit output regardless of how much internal reasoning produced it. `has_repeated_call` is the one guardrail this task actually builds.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_open_agent_guardrails.py
from __future__ import annotations

from langchain_core.messages import AIMessage, ToolMessage

from recruitment_team.open_agent.guardrails import has_repeated_call


def test_detects_a_materially_identical_prior_call():
    messages = [
        AIMessage(content="", tool_calls=[{"name": "search_jobs", "args": {"query": "backend engineer"}, "id": "1"}]),
        ToolMessage(content="{}", name="search_jobs", tool_call_id="1"),
    ]
    assert has_repeated_call(messages, "search_jobs", {"query": "backend engineer"}) is True


def test_allows_a_call_with_different_arguments():
    messages = [
        AIMessage(content="", tool_calls=[{"name": "search_jobs", "args": {"query": "backend engineer"}, "id": "1"}]),
        ToolMessage(content="{}", name="search_jobs", tool_call_id="1"),
    ]
    assert has_repeated_call(messages, "search_jobs", {"query": "platform engineer"}) is False


def test_allows_the_first_call():
    assert has_repeated_call([], "search_jobs", {"query": "backend engineer"}) is False
```

- [ ] **Step 2: Run and confirm failure**

Run: `cd backend && .venv/bin/python -m pytest tests/test_open_agent_guardrails.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `guardrails.py`**

```python
# backend/recruitment_team/open_agent/guardrails.py
"""Efficiency guardrails: freedom limits are about volume, not choice.

These stop the specific failure mode this codebase already measured once
(wasted, duplicate, non-progressing calls) -- they never restrict which tool
or persona the orchestrator is allowed to pick."""

from __future__ import annotations

from typing import Any


def has_repeated_call(messages: list[Any], tool_name: str, args: dict[str, Any]) -> bool:
    """Scans the full list backward for the first match, oldest and newest
    calls alike -- it has no turn-boundary or staleness awareness. Callers
    are responsible for passing only the relevant message window if a
    legitimately-repeated call after new information arrived matters."""
    for message in reversed(messages):
        tool_calls = getattr(message, "tool_calls", None) or []
        for call in tool_calls:
            if call.get("name") == tool_name and call.get("args") == args:
                return True
    return False
```

- [ ] **Step 4: Run tests, verify pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_open_agent_guardrails.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/recruitment_team/open_agent/guardrails.py backend/tests/test_open_agent_guardrails.py
git commit -m "feat: add no-repeated-call guardrail helper"
```

---

### Task 9: Spike — stream real-time progress from the orchestrator and its subagents

**Files:**
- Create: `backend/recruitment_team/open_agent/streaming.py`
- Test: `backend/tests/test_open_agent_streaming_spike.py`

**Interfaces:**
- Consumes: `resume_agent.agent.create_resume_agent` (existing), the underlying LangGraph `.stream(stream_mode="updates", subgraphs=True)` interface.
- Produces: `iter_progress_events(agent, payload, run_config) -> Iterator[dict]`, consumed by Task 10's runner for both real-time `TargetAssessmentProgress` reporting and specialist-findings extraction.

**Why this task exists, and what it already confirmed empirically before being written into implementer form:** the original plan draft assumed `agent.invoke()` (one blocking call, all-at-once result) was the runner's execution model, with two consequences discovered to be real problems: (1) no live "consulting recruiter now" progress during a run, unlike the old thread-pool-based pipeline; (2) per Task 1's spike, a delegated persona subagent's structured submission never reaches the top-level `result["messages"]` at all — only a plain-text paraphrase does. Investigating `agent.stream(stream_mode="updates", subgraphs=True)` directly against a real (scripted-model) delegation resolved both at once: a plain top-level stream (`subgraphs=True` omitted) shows only the orchestrator's own node updates, same opacity into subagents as `.invoke()`. Passing `subgraphs=True` additionally yields items under a non-empty namespace tuple per active subagent invocation (e.g. `("tools:<uuid>",)`), carrying that subagent's own `model`/`tools` node updates in real time — including the delegated subagent's `AIMessage.name` field identifying which persona it is (e.g. `name="recruiter"`), and, critically, the **real structured `ToolMessage` content** when that persona calls its own submission tool (verified directly: `content='{"summary": "Clear ownership.", ..., "score": 80, ...}'`, the actual validated JSON, not a paraphrase). This single mechanism gets both real-time progress AND the structured persona data the original draft needed a separate context-var side-channel for — no side-channel is needed. This task turns that already-verified finding into a tested, committed module, and additionally verifies it holds with more than one sequential persona delegation (not just one), since the empirical check that produced this finding only tried one.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_open_agent_streaming_spike.py
from __future__ import annotations

import json

from langchain_core.messages import AIMessage
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel

import config
from resume_agent.agent import create_resume_agent
from resume_agent.personas import create_persona_subagents
from recruitment_team.open_agent.streaming import iter_progress_events


class _ScriptedModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def _delegate_call(subagent_type: str, call_id: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{
            "name": "task",
            "args": {"description": f"Review as {subagent_type}.", "subagent_type": subagent_type},
            "id": call_id,
        }],
    )


def _submission_args(summary: str, score: int) -> dict:
    return {
        "summary": summary, "category": "ownership",
        "findings": [{
            "kind": "strength", "finding": "Shipped a feature end-to-end.", "source": "resume",
            "source_location": "bullet-1", "method": "Read the bullet.", "relevance_score": 0.8,
        }],
        "score": score, "reasoning": "Ownership is clear.", "suggested_actions": ["Add a metric."],
    }


def test_iter_progress_events_reports_two_sequential_persona_delegations(monkeypatch):
    import resume_agent.models as agent_models

    monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "test-key")

    orchestrator_model = _ScriptedModel(responses=[
        _delegate_call("recruiter", "call-1"),
        _delegate_call("ats", "call-2"),
        AIMessage(content="Consulted both personas."),
    ])

    recruiter_submit = AIMessage(content="", tool_calls=[{"name": "submit_assessment", "args": _submission_args("Recruiter view.", 80), "id": "r-1"}])
    recruiter_model = _ScriptedModel(responses=[recruiter_submit, AIMessage(content="Recruiter done.")])

    ats_submit = AIMessage(content="", tool_calls=[{"name": "submit_assessment", "args": _submission_args("ATS view.", 65), "id": "a-1"}])
    ats_model = _ScriptedModel(responses=[ats_submit, AIMessage(content="ATS done.")])

    subagents = create_persona_subagents(smart_model=recruiter_model)
    subagents = [s if s["name"] != "ats" else {**s, "model": ats_model} for s in subagents]

    agent = create_resume_agent(model=orchestrator_model, tools=[], subagents=subagents)

    events = list(iter_progress_events(
        agent,
        {"messages": [{"role": "user", "content": "Assess this candidate."}]},
        {"recursion_limit": config.AGENT_MAX_TOOL_ITERATIONS},
    ))

    tool_calls = [e for e in events if e["kind"] == "tool_call"]
    assert any(e["team_member"] == "coordinator" and e["tool_name"] == "task" for e in tool_calls)
    assert any(e["team_member"] == "recruiter" and e["tool_name"] == "submit_assessment" for e in tool_calls)
    assert any(e["team_member"] == "ats" and e["tool_name"] == "submit_assessment" for e in tool_calls)

    results = [e for e in events if e["kind"] == "tool_result"]
    recruiter_result = next(e for e in results if e["team_member"] == "recruiter" and e["tool_name"] == "submit_assessment")
    ats_result = next(e for e in results if e["team_member"] == "ats" and e["tool_name"] == "submit_assessment")
    assert json.loads(recruiter_result["content"])["score"] == 80
    assert json.loads(ats_result["content"])["score"] == 65

    messages = [e for e in events if e["kind"] == "message"]
    assert any(e["team_member"] == "coordinator" and e["content"] == "Consulted both personas." for e in messages)
    assert any(e["team_member"] == "recruiter" and e["content"] == "Recruiter done." for e in messages)
    assert any(e["team_member"] == "ats" and e["content"] == "ATS done." for e in messages)
```

- [ ] **Step 2: Run and confirm failure**

Run: `cd backend && .venv/bin/python -m pytest tests/test_open_agent_streaming_spike.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'recruitment_team.open_agent.streaming'`.

- [ ] **Step 3: Implement `streaming.py`**

```python
# backend/recruitment_team/open_agent/streaming.py
"""Real-time progress extraction from agent.stream(..., stream_mode="updates",
subgraphs=True).

Verified directly against the installed deepagents/langgraph/langchain
versions: a plain top-level stream (subgraphs=True omitted) only shows the
orchestrator's own node updates -- a delegated subagent's internal execution
is as invisible there as it is via .invoke(). Passing subgraphs=True
additionally yields items under a non-empty namespace tuple per active
subagent invocation (e.g. ("tools:<uuid>",)), carrying that subagent's own
model/tools node updates in real time -- including the AIMessage.name field
identifying which persona it is, and the real structured ToolMessage content
when that persona calls its own submission tool (not a paraphrase). This
module is the one place that knows this shape; nothing downstream should
re-derive it."""

from __future__ import annotations

from typing import Any, Iterator


def iter_progress_events(agent: Any, payload: dict, run_config: dict) -> Iterator[dict]:
    """Yield one normalized event per meaningful message anywhere in the run,
    at the top level (team_member="coordinator") or inside a delegated
    persona subagent (team_member=<persona_id>, learned from that subagent's
    own AIMessage.name the first time it's seen in that subgraph's
    namespace). Three event kinds: "tool_call" (a model decided to call a
    tool), "tool_result" (a tool's return value, structured JSON when the
    tool is a schema-enforced submission), "message" (a plain final reply
    with no tool call -- how a turn, the orchestrator's or a persona
    subagent's own, naturally ends; the last coordinator-level one of these
    is the run's synthesis text)."""
    active_persona_by_namespace: dict[tuple, str] = {}

    for namespace, chunk in agent.stream(
        payload, config=run_config, stream_mode="updates", subgraphs=True
    ):
        for node_update in (chunk or {}).values():
            if not isinstance(node_update, dict):
                continue
            for message in node_update.get("messages", []) or []:
                persona_name = getattr(message, "name", None)
                tool_calls = getattr(message, "tool_calls", None) or []
                if tool_calls:
                    if persona_name:
                        active_persona_by_namespace[namespace] = persona_name
                    team_member = active_persona_by_namespace.get(namespace, "coordinator")
                    for call in tool_calls:
                        yield {
                            "kind": "tool_call",
                            "team_member": team_member,
                            "tool_name": call.get("name"),
                            "args": call.get("args"),
                        }
                elif hasattr(message, "tool_call_id"):
                    team_member = active_persona_by_namespace.get(namespace, "coordinator")
                    yield {
                        "kind": "tool_result",
                        "team_member": team_member,
                        "tool_name": getattr(message, "name", None),
                        "content": message.content,
                    }
                elif message.content:
                    # A plain final reply with no tool call -- this is how a
                    # turn (the orchestrator's or a persona subagent's own)
                    # naturally ends. The runner needs the LAST coordinator-
                    # level one of these as its synthesis text; without this
                    # branch it would never see it at all.
                    team_member = active_persona_by_namespace.get(namespace, "coordinator")
                    yield {
                        "kind": "message",
                        "team_member": team_member,
                        "content": message.content,
                    }
```

- [ ] **Step 4: Run the test, verify pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_open_agent_streaming_spike.py -v`
Expected: PASS. If the two-persona scenario shows namespace collision (both personas' events attributed to the same `team_member`) or any other deviation from the single-persona shape already verified, that's a real, more serious finding — do not paper over it with a workaround; report BLOCKED with the actual observed chunk structure (add a debug `print(namespace, chunk)` temporarily to see it) so the controller can decide how Task 10 should adapt.

- [ ] **Step 5: Run the full suite, then commit**

Run: `cd backend && .venv/bin/python -m pytest tests/ -q`
Expected: PASS, no regressions (this task only adds new files).

```bash
git add backend/recruitment_team/open_agent/streaming.py backend/tests/test_open_agent_streaming_spike.py
git commit -m "feat: stream real-time progress from the orchestrator and its subagents"
```

---

### Task 10: `OpenAgentTargetAssessmentRunner` — the runner itself

**Files:**
- Create: `backend/recruitment_team/open_agent/runner.py`
- Test: `backend/tests/test_open_agent_runner.py`

**Interfaces:**
- Consumes: `resume_agent.agent.create_resume_agent` (Task 2's `interrupt_on` addition), `assessment_contracts.{TargetAssessmentRequest, TargetAssessmentProgress, TargetAssessmentResult, TargetAssessmentRunner, SPECIALIST_TOOL, JUDGE_TOOL, JudgeSubmission, invoke_structured, target_assessment_execution_policy}` (Task 3), `open_agent.tools.{read_candidate_evidence, read_target_job, propose_resume_edit, ask_candidate}` (Tasks 4-6), `resume_agent.tools.search_jobs` (existing, unmodified), `open_agent.subagents.create_target_persona_subagents` (Task 7), `open_agent.guardrails.has_repeated_call` (Task 8), `open_agent.streaming.iter_progress_events` (Task 9), `open_agent.context.{assessment_context, proposed_edits, tool_call_history}` (Tasks 4-5, this task adds `tool_call_history`).
- Produces: `OpenAgentTargetAssessmentRunner(model_factory=None, telemetry=None, persona_registry=None)`, implementing `run(self, request: TargetAssessmentRequest) -> Iterator[TargetAssessmentUpdate]` — consumed by Task 11's cutover in `recruitment_team.py`.

This is the task where the mandatory judge, the numeric caps, real-time progress reporting, and the guardrail all get wired together into one control flow, built directly on Task 9's verified `iter_progress_events`. The orchestrator's own tool-calling loop is genuinely open (persona choice, edit proposals, questions); everything in this task is the fixed frame around it.

**Design note carried from Task 9:** `iter_progress_events` yields events as the run happens, not after it finishes — `TargetAssessmentProgress` events are yielded live, matching each `tool_call`/`tool_result`/`message` event as it streams in, not reconstructed from a final result afterward. A specialist's structured submission is read directly from a `tool_result` event's `content` (real JSON, per Task 9's finding) whenever that event's `team_member` is a persona (not `"coordinator"`) and its `tool_name` matches `SPECIALIST_TOOL.name` — no side-channel needed. The run's `synthesis` is the last `message`-kind event with `team_member == "coordinator"`.

**Design note on the no-repeat-call guardrail:** `has_repeated_call` (Task 8) scans a list of message-like objects for a `.tool_calls` match. Streaming only lets the runner *observe* a call after the graph has already decided to make it — by the time a `tool_call` event streams out, `search_jobs` has already run. To actually prevent a wasted duplicate call (not just notice one after the fact), the guardrail has to live inside the tool itself, which needs its own per-run memory of prior calls — the same `ContextVar` pattern `propose_resume_edit` (Task 5) already established. `guarded_search_jobs` (built in this task) maintains that memory and calls `has_repeated_call` against it before delegating to the real `search_jobs`, so Task 8's tested function is reused at the one point where it can actually stop something, not just report it.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_open_agent_runner.py
from __future__ import annotations

from langchain_core.messages import AIMessage
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel

from recruitment_team.assessment_contracts import TargetAssessmentProgress, TargetAssessmentResult
from recruitment_team.open_agent.runner import OpenAgentTargetAssessmentRunner
from recruitment_team.telemetry import RecordedTelemetry


class _ScriptedModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def _request():
    from recruitment_team.assessment_contracts import TargetAssessmentRequest
    from backend.tests.test_recruitment_team_module import (
        _candidate_profile_run,
        _job_snapshot,
        _role_profile_run,
    )

    return TargetAssessmentRequest(
        candidate_profile=_candidate_profile_run().profile,
        role_profile=_role_profile_run().profile,
        target_job=_job_snapshot(),
        trace_key="open-agent-runner-trace",
        resume_document={
            "schema_version": 1,
            "revision": "rev-1",
            "raw_text": "Led team of 12 engineers.",
            "blocks": [{"id": "b1", "text": "Led team of 12 engineers.", "section_key": "experience", "entry_id": "e1"}],
        },
    )


def test_runner_reaches_completed_via_mandatory_judge_with_zero_personas_consulted(monkeypatch):
    import resume_agent.models as agent_models

    monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "test-key")

    final_reply = AIMessage(content="No specialist consultation needed; evidence is unambiguous.")
    orchestrator_model = _ScriptedModel(responses=[final_reply])

    judge_call = AIMessage(
        content="",
        tool_calls=[{
            "name": "submit_target_assessment_judgment",
            "args": {
                "strengths": ["Clear, unambiguous evidence."],
                "weaknesses": [],
                "deductions": [],
                "evidence_gaps": [],
                "rubric_scores": {
                    "evidence_grounding": 90, "role_coverage": 85,
                    "decision_usefulness": 85, "fairness_and_boundaries": 100,
                },
                "score": 88,
                "score_reason": "Grounded in directly supplied evidence.",
                "confidence": 85,
                "confidence_reason": "No ambiguity in the source evidence.",
                "disposition": "pass",
            },
            "id": "judge-call-1",
        }],
    )
    judge_model = _ScriptedModel(responses=[judge_call])

    runner = OpenAgentTargetAssessmentRunner(
        model_factory=lambda: orchestrator_model,
        judge_model_factory=lambda: judge_model,
        telemetry=RecordedTelemetry(),
    )

    updates = list(runner.run(_request()))
    progress = [item for item in updates if isinstance(item, TargetAssessmentProgress)]
    result = next(item for item in updates if isinstance(item, TargetAssessmentResult))

    assert progress[0].team_member == "coordinator" and progress[0].status == "running"
    assert result.status == "completed"
    assert result.judge is not None
    assert result.judge["disposition"] == "pass"
    assert result.specialist_runs == ()
    assert result.synthesis == "No specialist consultation needed; evidence is unambiguous."
```

- [ ] **Step 2: Run and confirm failure**

Run: `cd backend && .venv/bin/python -m pytest tests/test_open_agent_runner.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Add `tool_call_history` to `context.py`**

```python
# backend/recruitment_team/open_agent/context.py -- add alongside _proposed_edits
_tool_call_history: ContextVar[list[Any] | None] = ContextVar(
    "open_agent_tool_call_history", default=None
)

# inside assessment_context(), alongside the other .set(...)/.reset(...) calls:
    history_token = _tool_call_history.set([])
    ...
    _tool_call_history.reset(history_token)


def tool_call_history() -> list[Any] | None:
    return _tool_call_history.get()
```

- [ ] **Step 4: Implement `runner.py`**

```python
# backend/recruitment_team/open_agent/runner.py
"""Open-ended orchestrator over the target-assessment tool set, with a
mandatory independent judge as the one non-optional step regardless of the
reasoning path the orchestrator took to get there, and real-time progress
reporting built on Task 9's verified streaming mechanism."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Iterator

from langchain_core.tools import tool

import config
from resume_agent.agent import create_resume_agent
from resume_agent.tools import search_jobs

from ..assessment_contracts import (
    JUDGE_TOOL,
    SPECIALIST_TOOL,
    TargetAssessmentProgress,
    TargetAssessmentRequest,
    TargetAssessmentResult,
    TargetAssessmentUpdate,
    invoke_structured,
    target_assessment_execution_policy,
)
from ..persona_packs import PersonaPackRegistry, load_persona_pack_registry
from ..telemetry import OpenTelemetryRecorder, RecruitmentTelemetry
from . import context
from .guardrails import has_repeated_call
from .streaming import iter_progress_events
from .subagents import create_target_persona_subagents
from .tools import ask_candidate, propose_resume_edit, read_candidate_evidence, read_target_job


@tool
def guarded_search_jobs(query: str, n: int | None = None, detail: bool = False) -> dict:
    """Search the current internal Singapore job corpus by role or responsibility.

    Same contract as the underlying search_jobs tool; rejects a materially
    identical repeat within this run instead of re-querying.
    """
    args = {"query": query, "n": n, "detail": detail}
    history = context.tool_call_history()
    if history is not None and has_repeated_call(history, "search_jobs", args):
        return {
            "ok": False,
            "failure_type": "validation",
            "reason": "identical_call_no_new_information",
        }
    result = search_jobs.invoke(args)
    if history is not None:
        history.append(SimpleNamespace(tool_calls=[{"name": "search_jobs", "args": args}]))
    return result


class OpenAgentTargetAssessmentRunner:
    """Open-ended replacement for NativeTargetAssessmentRunner."""

    def __init__(
        self,
        model_factory=None,
        judge_model_factory=None,
        telemetry: RecruitmentTelemetry | None = None,
        persona_registry: PersonaPackRegistry | None = None,
    ):
        if model_factory is None:
            from resume_agent.models import create_agent_model

            model_factory = lambda: create_agent_model(
                timeout=config.RECRUITMENT_MODEL_HTTP_TIMEOUT_SECONDS,
                max_retries=config.RECRUITMENT_MODEL_TRANSPORT_RETRIES,
            )
        self._model_factory = model_factory
        self._judge_model_factory = judge_model_factory or model_factory
        self._telemetry = telemetry or OpenTelemetryRecorder()
        self._registry = persona_registry or load_persona_pack_registry()

    def run(self, request: TargetAssessmentRequest) -> Iterator[TargetAssessmentUpdate]:
        yield TargetAssessmentProgress(
            team_member="coordinator", status="running", summary="Open-agent run started.", detail={}
        )

        orchestrator_model = self._model_factory()
        persona_subagents = create_target_persona_subagents(self._registry, orchestrator_model)
        agent = create_resume_agent(
            model=orchestrator_model,
            tools=[read_candidate_evidence, read_target_job, guarded_search_jobs, propose_resume_edit, ask_candidate],
            subagents=persona_subagents,
            interrupt_on={"ask_candidate": True},
        )
        payload = {"messages": [{
            "role": "user",
            "content": (
                "Assess this candidate against the target job. Consult whichever "
                "personas you judge useful, however many times you judge useful. "
                "Propose resume edits only where you have real evidence or an answer "
                "the candidate gave you. Ask the candidate directly if you hit a real "
                "evidence gap."
            ),
        }]}
        run_config = {"recursion_limit": config.AGENT_MAX_TOOL_ITERATIONS}

        specialist_runs: list[dict] = []
        synthesis = ""
        with context.assessment_context(request):
            for event in iter_progress_events(agent, payload, run_config):
                if event["kind"] == "tool_call":
                    yield TargetAssessmentProgress(
                        team_member=event["team_member"],
                        status="running",
                        summary=f"{event['team_member']} called {event['tool_name']}.",
                        detail={"tool_name": event["tool_name"]},
                    )
                elif (
                    event["kind"] == "tool_result"
                    and event["team_member"] != "coordinator"
                    and event["tool_name"] == SPECIALIST_TOOL.name
                ):
                    submission = self._parse_specialist_submission(event["content"])
                    if submission is not None:
                        specialist_runs.append(
                            {"persona_id": event["team_member"], "status": "completed", "submission": submission}
                        )
                        yield TargetAssessmentProgress(
                            team_member=event["team_member"],
                            status="completed",
                            summary=f"{event['team_member']} submitted its assessment.",
                            detail={},
                        )
                elif event["kind"] == "message" and event["team_member"] == "coordinator":
                    synthesis = str(event["content"])
            edits = context.proposed_edits() or []

        judge_model = self._judge_model_factory()
        judge = self._run_judge(judge_model, request, specialist_runs, synthesis)
        status = "completed" if judge["disposition"] == "pass" else "quality_blocked"

        yield TargetAssessmentResult(
            status=status,
            specialist_runs=tuple(specialist_runs),
            synthesis=synthesis,
            judge=judge,
            correction=None,
            error=None,
            execution_policy=target_assessment_execution_policy(),
        )

    @staticmethod
    def _parse_specialist_submission(content) -> dict | None:
        if isinstance(content, dict):
            return content
        if not isinstance(content, str):
            return None
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return None

    def _run_judge(self, model, request: TargetAssessmentRequest, specialist_runs: list[dict], synthesis: str) -> dict:
        from ..prompts.target_assessment import TARGET_JUDGE_SYSTEM_PROMPT

        data = {
            "target_job": request.target_job,
            "role_success_profile": request.role_profile,
            "specialist_runs": specialist_runs,
            "synthesis": synthesis,
        }
        payload, failure, input_tokens, output_tokens, model_name = invoke_structured(
            model,
            JUDGE_TOOL,
            TARGET_JUDGE_SYSTEM_PROMPT,
            "open_agent_judge_data",
            data,
            telemetry=self._telemetry,
            operation="open_agent_assessment.judge_attempt",
            attempt=1,
            max_attempts=1,
            attributes={"trace_key": request.trace_key},
        )
        if payload is None:
            return {
                "disposition": "block",
                "strengths": [], "weaknesses": [f"Judge call failed: {failure}"],
                "deductions": [], "evidence_gaps": [], "score": 0, "score_reason": failure,
                "confidence": 0, "confidence_reason": failure,
                "rubric_scores": {"evidence_grounding": 0, "role_coverage": 0, "decision_usefulness": 0, "fairness_and_boundaries": 0},
            }
        return {**payload, "model_name": model_name, "input_tokens": input_tokens, "output_tokens": output_tokens}
```

- [ ] **Step 5: Run tests, verify pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_open_agent_runner.py -v`
Expected: PASS. If real behavior deviates from Task 9's verified event shapes (e.g. a specialist's `tool_result` content arrives as something other than a JSON string), fix `_parse_specialist_submission` to match reality — Task 9's streaming module and its own test are the source of truth for the event shape, not this draft.

- [ ] **Step 6: Add a real second-persona test and the no-repeat-call guardrail test**

```python
# backend/tests/test_open_agent_runner.py -- append
def test_runner_captures_a_real_persona_submission_via_streaming(monkeypatch):
    # Script the orchestrator to delegate to "recruiter", script the persona
    # model with a valid submit_assessment call (see Task 9's test for the
    # exact args shape), then assert result.specialist_runs has one entry
    # with persona_id == "recruiter" and the real score/summary from the
    # scripted submission -- proving the runner reads structured data from
    # the stream, not a paraphrase.
    ...


def test_runner_rejects_a_materially_identical_repeated_search_jobs_call(monkeypatch):
    # Script the orchestrator to call guarded_search_jobs (via the agent's
    # tool binding) twice with identical args, then assert the second
    # invocation's tool_result content signals identical_call_no_new_information
    # rather than a second real search.
    ...
```

Run: `cd backend && .venv/bin/python -m pytest tests/test_open_agent_runner.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/recruitment_team/open_agent/context.py backend/recruitment_team/open_agent/runner.py backend/tests/test_open_agent_runner.py
git commit -m "feat: add OpenAgentTargetAssessmentRunner with real-time streaming, mandatory judge, and guardrails"
```

---

### Task 11: Activity logging, cutover, edit persistence, and dead-code removal

**Files:**
- Modify: `backend/recruitment_team/assessment_contracts.py` (`TargetAssessmentResult` gains `proposed_edits`)
- Modify: `backend/recruitment_team/open_agent/runner.py` (populate `proposed_edits` on the yielded result)
- Modify: `backend/recruitment_team/recruitment_team.py` (`_assess_target`, activity logging, runner construction, edit persistence, paused-result handling)
- Delete: `backend/recruitment_team/target_assessment.py` (once nothing references `NativeTargetAssessmentRunner`)
- Modify: `backend/tests/test_recruitment_team_module.py`, `backend/tests/test_target_assessment.py` (update/retire references to the deleted runner)

**Interfaces:**
- Consumes: `RecruitmentTeam._event(thread, run, *, event_type, status, summary, detail=None, team_member="coordinator")` (`recruitment_team.py:1215-1241`, unchanged signature), `models.ProposedResumeEdit` (Task 5).
- Produces: nothing new beyond the `proposed_edits` field — this task is primarily the swap-in, plus closing two gaps Task 10's review surfaced.

**Two gaps folded in from Task 10's review, not originally scoped here:**

1. **Proposed edits are validated in-run but never persisted.** The runner computes `edits = context.proposed_edits() or []` and drops it — `TargetAssessmentResult` has no field to carry it out, and the runner takes no DB/session parameters to persist it itself (persistence needs `run.id`/`thread.id`/`resume.id`, which only `_assess_target` has). Fix: add `proposed_edits: tuple[dict, ...] = ()` to `TargetAssessmentResult` (defaulted, so the old `NativeTargetAssessmentRunner`, still alive until Step 6 of this task, is unaffected), have the runner populate it, and have `_assess_target` write one `ProposedResumeEdit` row per entry after a `completed` result.
2. **A cleanly-paused run (Task 10's `ask_candidate` fix) currently looks identical to a real failure.** `_assess_target`'s existing `if result is None:` branch (`recruitment_team.py:711-724`) always raises `TargetAssessmentUnavailable(failure_type="workflow", retryable=True)` when the runner's generator ends without a `TargetAssessmentResult` — which is now also exactly what a clean pause looks like (Task 10 deliberately ends the generator without a Result when `ask_candidate` interrupts). Without a fix, every real pause gets misreported as a retryable failure. Fix: track the `status` of the last `TargetAssessmentProgress` event seen; if `result is None` AND that last status was `"paused"`, treat it as a distinct, non-failure outcome instead of falling into the existing failure branch.

- [ ] **Step 1: Thread the resume document into the request**

In `_assess_target` (`recruitment_team.py:628` onward), before constructing `TargetAssessmentRequest`, add:

```python
from resume_document import create_resume_document

resume_document = create_resume_document(resume.resume_text)
```

and pass `resume_document=resume_document` into the existing `TargetAssessmentRequest(...)` construction at line ~673-678.

- [ ] **Step 2: Emit one activity event per `TargetAssessmentProgress` the new runner yields**

In the same loop that already handles `isinstance(update, TargetAssessmentProgress)` (around line 680), the existing code already calls `self._event(...)` per specialist — confirm it does (`test_recruitment_team_module.py:1092-1226` shows a `recruiter`/`quality_judge` pair of `event_type == "assessment"` events already expected). No new code needed here beyond making sure `team_member=update.team_member` (already the pattern) — since the open-agent runner's `TargetAssessmentProgress` events now carry variable persona names (not always the same 5), write a targeted test:

```python
# backend/tests/test_recruitment_team_module.py -- add near the existing
# test_bounded_target_assessment_persists_and_streams_specialist_judge_artifact
def test_open_agent_target_assessment_logs_only_the_personas_actually_consulted(monkeypatch):
    # Swap in a runner double that yields TargetAssessmentProgress for exactly
    # one persona ("skeptic") plus the mandatory judge, then assert the
    # recorded activity events' team_member sequence is exactly
    # ["skeptic", "quality_judge"] -- not the old fixed five.
    ...
```

- [ ] **Step 3: Run this new test, confirm it fails against the still-Native runner**

Run: `cd backend && .venv/bin/python -m pytest tests/test_recruitment_team_module.py -v -k open_agent_target_assessment`
Expected: FAIL (the runner construction below hasn't happened yet).

- [ ] **Step 4: Swap the runner construction**

Find `RecruitmentTeam.__init__` (or wherever `self._target_assessment_runner` is constructed) and change:

```python
# before
from .target_assessment import NativeTargetAssessmentRunner
self._target_assessment_runner = NativeTargetAssessmentRunner()

# after
from .open_agent.runner import OpenAgentTargetAssessmentRunner
self._target_assessment_runner = OpenAgentTargetAssessmentRunner()
```

- [ ] **Step 5: Add `proposed_edits` to `TargetAssessmentResult` and populate it**

In `backend/recruitment_team/assessment_contracts.py`, add a defaulted field to the frozen dataclass:

```python
@dataclass(frozen=True)
class TargetAssessmentResult:
    status: Literal["completed", "quality_blocked", "failed"]
    specialist_runs: tuple[dict, ...]
    synthesis: str
    judge: dict | None
    correction: dict | None
    error: dict | None
    execution_policy: dict
    proposed_edits: tuple[dict, ...] = ()
```

In `backend/recruitment_team/open_agent/runner.py`, pass `proposed_edits=tuple(edits)` into the `TargetAssessmentResult(...)` construction (the `edits` local is already computed from `context.proposed_edits()`, just not currently threaded through). Write a test asserting a run that calls `propose_resume_edit` produces a non-empty `result.proposed_edits` tuple containing the exact `block_id`/`rewrite` the tool accepted.

Run: `cd backend && .venv/bin/python -m pytest tests/test_open_agent_runner.py -v`
Expected: PASS.

- [ ] **Step 6: Persist proposed edits and handle a paused result in `_assess_target`**

In `_assess_target`, track the last progress status seen while iterating, so the `result is None` branch can distinguish a real failure from a clean pause:

```python
result: TargetAssessmentResult | None = None
last_progress_status: str | None = None
try:
    for update in self._target_assessment_runner.run(...):
        if isinstance(update, TargetAssessmentProgress):
            last_progress_status = update.status
            ...  # existing _event/publish logic, unchanged
        elif isinstance(update, TargetAssessmentResult):
            ...  # existing, unchanged
```

Replace the existing `if result is None:` branch (`recruitment_team.py:711-724`) with one that checks `last_progress_status` first:

```python
if result is None:
    if last_progress_status == "paused":
        artifact.status = "paused"
        artifact.updated_at = _utcnow()
        facts = dict(thread.case_facts)
        facts["target_assessment_status"] = "paused"
        thread.case_facts = facts
        thread.workflow_state = "awaiting_candidate_answer"
        self._db.commit()
        pending_question = ""  # extract from the paused TargetAssessmentProgress's detail dict --
                                # capture it in the loop above alongside last_progress_status, same pattern
        return ModelReply(content=pending_question, model_name="open-agent-recruitment-team"), {}
    # ... existing MissingTerminalResult failure branch, unchanged
```

After a `completed` result (in the existing success path, once `effective_status`/`artifact.status` etc. are set), persist each proposed edit:

```python
for edit in result.proposed_edits:
    self._db.add(models.ProposedResumeEdit(
        id=str(uuid.uuid4()),
        user_id=owner_id,
        thread_id=thread.id,
        run_id=run.id,
        resume_version_id=resume.id,
        block_id=edit["block_id"],
        section_key=edit.get("section_key", ""),
        entry_id=edit.get("entry_id", ""),
        original=edit["original"],
        rewrite=edit["rewrite"],
        document_revision=edit["document_revision"],
        status="pending",
    ))
```

Write two tests: one proving a `completed` result with `proposed_edits` produces the matching `ProposedResumeEdit` rows (query them back via `self._db`), one proving a `paused` outcome sets `thread.workflow_state == "awaiting_candidate_answer"`, does NOT raise `TargetAssessmentUnavailable`, and returns the pending question as the reply content.

Run: `cd backend && .venv/bin/python -m pytest tests/test_recruitment_team_module.py -v`
Expected: PASS.

- [ ] **Step 7: Run the full backend suite**

Run: `cd backend && .venv/bin/python -m pytest tests/ -q`
Expected: PASS. Every test that constructed or referenced `NativeTargetAssessmentRunner` directly (`test_target_assessment.py` in full) now targets a deleted class — update each to construct `OpenAgentTargetAssessmentRunner` instead, adjusting fixtures (fake models, expected persona counts) to the open-agent shape. Do not skip or delete these tests wholesale; each one encodes a real behavior (e.g. judge-gates-completion, specialist-failure-handling) that must still hold.

- [ ] **Step 8: Delete `target_assessment.py`**

```bash
git rm backend/recruitment_team/target_assessment.py
```

Confirm nothing else imports it:

```bash
grep -rn "from .target_assessment import\|from recruitment_team.target_assessment import\|NativeTargetAssessmentRunner" backend/ --include="*.py"
```
Expected: no output (or only references inside files this task already updated).

- [ ] **Step 9: Run the full suite one more time**

Run: `cd backend && .venv/bin/python -m pytest tests/ -q`
Expected: PASS, full green.

- [ ] **Step 10: Commit**

```bash
git add -A backend/recruitment_team/ backend/tests/
git commit -m "feat: cut target assessment over to the open-agent runner"
```

---

## Self-Review

**Spec coverage** — every section of `docs/superpowers/specs/2026-07-20-recruitment-team-open-agent-design.md` maps to a task: Engine reuse (Tasks 2, 10), Tool registry (Tasks 4-6), Subagents (Task 7), Mandatory final judge (Task 10), Efficiency guardrails (Task 8, wired in Task 10), Activity/observability (Tasks 9, 11), Data model changes (Task 5's `ProposedResumeEdit`, Task 1's spike note on `specialist_runs` variability), Error handling (each tool returns a reason string on rejection, consistent with the retry-with-exact-feedback pattern; new tool call sites still route through the existing failure taxonomy per the Global Constraints). The three spikes (Tasks 1, 2, 9) directly address three corrections found empirically rather than assumed: the unverified subagent-delegation claim, the unverified `ask_candidate` turn-ending mechanism, and (found mid-execution, after Task 8 landed) that `.invoke()` gives no real-time visibility into a delegated persona's work and no access to its structured submission at all — `agent.stream(stream_mode="updates", subgraphs=True)`, verified directly against a real scripted delegation before Task 9 was written, resolves both without a side-channel.

**Deviation the critique surfaced, now made concrete in this plan:** the spec originally implied guardrail work (issue #113) could follow core engine work (issue #109) directly. Building `ask_candidate`'s real hard-turn-end requires a durable checkpointer and `interrupt_on`, which is issue #112's territory — so this plan does that spike (Task 2) second, before any tool work, rather than last. The GitHub issue dependency graph (#113 currently has no stated dependency on #112) should be updated to reflect this; flagging it for a follow-up comment on those two issues rather than silently absorbing the reordering into this plan alone.

**Mid-execution revision (Task 9 inserted, Tasks 9-10 renumbered to 10-11):** the original Task 9 draft assumed `.invoke()` and a context-var side-channel could recover a delegated persona's structured findings. Direct investigation (running a real scripted delegation through both `.invoke()` and `.stream(..., subgraphs=True)` and reading the actual output, not assuming) found `.stream()` with `subgraphs=True` already exposes the real structured `ToolMessage` content from inside a subagent's own execution, in real time, at the same point the original draft needed a separate accumulator for — one verified mechanism instead of two, and it also closes a separate, independently-raised gap (no live progress reporting during a run). The runner (now Task 10) was rewritten around `iter_progress_events` before any implementer touched it; nothing here was discovered after the fact by an implementer stuck on a wrong assumption.

**Placeholder scan** — no TBD/TODO. Two spots are intentionally exploratory rather than fixed (Task 1 Step 2's two-outcome branch, Task 2 Step 4's fallback investigation instruction) — both give the engineer the concrete file to read and the concrete fix to make if reality differs from the draft, which is different from a placeholder.

**Type consistency** — `TargetAssessmentRequest`/`Progress`/`Result`/`Update`, `SPECIALIST_TOOL`/`SpecialistSubmission`, `JUDGE_TOOL`/`JudgeSubmission` are named identically from Task 3 onward through Task 10. `assessment_context`/`current_request`/`current_document`/`proposed_edits`/`tool_call_history` in `context.py` are the only functions any later task calls into that module by name, and Tasks 4/5/10 use those exact five names throughout.

**Scope check** — this plan covers issues #109-113 as one build (they share one runner and one tool registry; splitting further would fragment a single control-flow object across plans). It deliberately excludes: any new HTTP endpoint for accepting/rejecting a `ProposedResumeEdit` (Task 5 only builds the table and the tool), and the frontend changes needed to surface pending edits in `RecruitmentTeamPanel.jsx` — both are natural follow-on plans once this one is implemented and its real behavior can inform their design, not omissions from this scope.

---

**Plan complete and saved to `docs/superpowers/plans/2026-07-20-recruitment-team-open-agent.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
