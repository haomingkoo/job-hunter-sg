"""Open-ended orchestrator over the target-assessment tool set, streaming
progress as it goes. The independent judge is the one non-optional step,
whatever reasoning path the orchestrator took to get there."""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import replace
from typing import Callable, Iterator

from langgraph.errors import GraphRecursionError
from langgraph.types import Command
from langchain.agents.middleware import AgentState, before_model, wrap_model_call
from langchain_core.messages import AIMessage, ToolMessage
from pydantic import ValidationError

import config
from resume_agent.agent import create_resume_agent

from ..assessment_contracts import (
    SPECIALIST_TOOL,
    SpecialistSubmission,
    TargetAssessmentProgress,
    TargetAssessmentRequest,
    TargetAssessmentResult,
    TargetAssessmentUpdate,
    public_specialist_validation_code,
    target_assessment_execution_policy,
    validate_specialist_runs,
)
from ..fair_hiring import mentions_protected_status
from ..execution_metrics import summarize_semantic_outcomes
from ..model_transport_observer import (
    bind_transport_collector,
    collect_transport_metrics,
    create_observed_agent_model,
    current_transport_metrics,
)
from ..persona_packs import PersonaPackRegistry, load_persona_pack_registry
from ..provider_compatibility import provider_message_compatibility, require_tool_call
from ..telemetry import OpenTelemetryRecorder, RecruitmentTelemetry
from ..tool_call_guard import ToolCallGuardMiddleware
from . import context
from .checkpoint_store import CHECKPOINTER as _CHECKPOINTER
from .checkpoint_store import delete_checkpoint
from .quality_gate import QualityGateOutcome, TargetAssessmentQualityGate
from .streaming import describe_progress, format_questions, iter_progress_events, rejected_tool_result
from .subagents import create_target_persona_subagents
from .tools import (
    ask_candidate,
    propose_resume_edit,
    read_candidate_evidence,
    read_target_job,
    submit_target_assessment_synthesis,
)


_QUESTION_LIMIT_REPLY = (
    "[System: this assessment's question limit is reached and no further question "
    "will be delivered. Finish now using the resume, the specialist reports and the "
    "answers already given: submit your assessment and call propose_resume_edit for "
    "every gap the candidate's own evidence already supports. Where a gap is missing "
    "experience rather than weak wording, report it and draft no edit for it.]"
)
_ORCHESTRATOR_BUDGET_EXHAUSTED = "attempt_budget_exhausted"
_SPECIALIST_BUDGET_EXHAUSTED = "specialist_attempt_budget_exhausted"
_SPECIALIST_CONTRACT_INVALID = "structured_output_invalid"
_QUESTION_BUDGET_EXHAUSTED = "candidate_question_budget_exhausted"
_CHECKPOINT_STATE_UNAVAILABLE = "checkpoint_state_unavailable"
_PROTECTED_CANDIDATE_QUESTION = "protected_candidate_question"
def _semantic_validation_code(payload: dict) -> str:
    """Project one tool result to its content-free correction category."""
    raw_code = str(payload.get("validation_code") or "")
    if raw_code:
        return public_specialist_validation_code(raw_code)
    if payload.get("accepted") is True:
        return ""
    return str(payload.get("failure_code") or "specialist_submission_rejected")


@wrap_model_call
def _require_pending_specialist_delegation(request, handler):
    """Make the required delegation invariant part of execution policy.

    A prompt cannot guarantee that a provider will choose ``task`` before the
    final synthesis tool. While validated specialist reports are missing, the
    coordinator may choose their order and instructions but it may only make a
    delegation. Once all required reports are accepted, the full tool set is
    restored for synthesis, edits, or a candidate question.
    """
    if not context.missing_required_specialists():
        return handler(request)
    delegation_tools = [
        available_tool
        for available_tool in (getattr(request, "tools", None) or [])
        if getattr(available_tool, "name", "") == "task"
    ]
    if not delegation_tools:
        return handler(request)
    return handler(request.override(
        tools=delegation_tools,
        tool_choice={"type": "function", "function": {"name": "task"}},
    ))


@before_model(can_jump_to=["end"])
def _stop_after_terminal_specialist_failure(_state: AgentState, _runtime):
    """Let an exhausted specialist end the parent graph without another model call."""
    if context.terminal_specialist_failure() is None:
        return None
    return {
        "messages": [AIMessage(content="A specialist correction budget was exhausted.")],
        "jump_to": "end",
    }


@before_model(can_jump_to=["end"])
def _stop_after_accepted_synthesis(state: AgentState, _runtime):
    """End at the accepted synthesis instead of paying for discarded prose."""
    messages = state.get("messages") or []
    if not messages or not isinstance(messages[-1], ToolMessage):
        return None
    message = messages[-1]
    if message.name != "submit_target_assessment_synthesis":
        return None
    content = message.content
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except (TypeError, ValueError):
            return None
    if not isinstance(content, dict) or content.get("accepted") is not True:
        return None
    return {
        "messages": [AIMessage(content="Structured synthesis accepted.")],
        "jump_to": "end",
    }


class CheckpointStateUnavailable(RuntimeError):
    """The durable graph state could not be read safely."""


class TargetAssessmentExecutionError(RuntimeError):
    """Unexpected execution failure with durable checkpoint cleanup debt."""

    def __init__(self, checkpoint_cleanup_token: str):
        super().__init__("target assessment failed and checkpoint cleanup is pending")
        self.checkpoint_cleanup_token = checkpoint_cleanup_token


def _recursion_limit_from_error(error: GraphRecursionError) -> int:
    match = re.search(r"recursion limit of (\d+)", str(error), re.IGNORECASE)
    return int(match.group(1)) if match else config.TARGET_ASSESSMENT_MAX_TOOL_ITERATIONS


def _agent_attempt_limit(team_member: str) -> int:
    """Return the budget owned by the graph that produced a model step."""
    return (
        config.TARGET_ASSESSMENT_MAX_TOOL_ITERATIONS
        if team_member == "coordinator"
        else config.TARGET_SPECIALIST_MAX_TOOL_ITERATIONS
    )


def _checkpoint_state(agent, run_config: dict):
    try:
        return agent.get_state(run_config)
    except Exception as error:
        raise CheckpointStateUnavailable("target assessment checkpoint state is unavailable") from error


def _delete_terminal_checkpoint(
    run_config: dict,
    telemetry: RecruitmentTelemetry,
) -> bool:
    """Best-effort cleanup once a graph can no longer be resumed."""
    thread_id = str(run_config.get("configurable", {}).get("thread_id") or "")
    if not thread_id:
        return True
    try:
        delete_checkpoint(thread_id)
        return True
    except Exception as error:
        # Cleanup must not replace the actual assessment outcome. Account/thread
        # deletion retains a second cleanup path for any transient store failure.
        # Record metadata only: never export the checkpoint token or run content.
        try:
            with telemetry.operation(
                "checkpoint_cleanup",
                {"workflow": "target_assessment", "outcome": "failed"},
            ) as operation:
                operation.mark_error(type(error).__name__)
        except Exception:
            # Telemetry is also best-effort and must not replace the run outcome.
            pass
        return False


def _cleaned_result(
    result: TargetAssessmentResult,
    run_config: dict,
    telemetry: RecruitmentTelemetry,
) -> TargetAssessmentResult:
    if _delete_terminal_checkpoint(run_config, telemetry):
        return result
    token = str(run_config.get("configurable", {}).get("thread_id") or "")
    return replace(result, checkpoint_cleanup_token=token or None)


def _ask_rounds_so_far(state) -> int:
    """How many times this run has already stopped to ask the candidate."""
    messages = state.values.get("messages") or []
    return sum(
        1
        for message in messages
        for call in (getattr(message, "tool_calls", None) or [])
        if call.get("name") == "ask_candidate"
    )


def _target_execution_metrics(
    request: TargetAssessmentRequest,
    model_attempts: list[dict],
    quality_attempts,
    latency_ms: float,
    terminal_status: str,
    *,
    checkpoint_hit_count: int = 0,
    semantic_outcomes: list[dict] | None = None,
) -> dict:
    attempts = list(model_attempts)
    attempts.extend(quality_attempts)
    transport_metrics = current_transport_metrics()
    attempts.extend(transport_metrics.pop("nested_model_attempts", []))
    reported_model_calls = sum(int(item.get("attempt_count") or 1) for item in attempts)
    reported_input_tokens = sum(int(item.get("input_tokens") or 0) for item in attempts)
    reported_output_tokens = sum(int(item.get("output_tokens") or 0) for item in attempts)
    models = list(dict.fromkeys([
        *(str(item.get("model") or "") for item in attempts if item.get("model")),
        *(str(model) for model in transport_metrics.get("transport_models") or [] if model),
    ]))
    semantic_outcomes = list(semantic_outcomes or ())
    return {
        "logical_run_id": request.trace_key,
        "trace_key": request.trace_key,
        "stage": "target_assessment",
        "model_call_count": reported_model_calls,
        "reported_model_call_count": reported_model_calls,
        "checkpoint_hit_count": checkpoint_hit_count,
        "input_tokens": reported_input_tokens,
        "output_tokens": reported_output_tokens,
        "reported_input_tokens": reported_input_tokens,
        "reported_output_tokens": reported_output_tokens,
        "latency_ms": round(latency_ms, 3),
        "validation_codes": [str(item["validation_code"]) for item in attempts if item.get("validation_code")],
        "models": models,
        "attempts": attempts,
        "semantic_outcomes": semantic_outcomes,
        "semantic_by_role": summarize_semantic_outcomes(semantic_outcomes),
        "terminal_status": terminal_status,
        **transport_metrics,
    }


class OpenAgentTargetAssessmentRunner:
    """Drives the open-agent target assessment, then the mandatory judge."""

    def __init__(
        self,
        model_factory=None,
        judge_model_factory=None,
        correction_model_factory=None,
        telemetry: RecruitmentTelemetry | None = None,
        persona_registry: PersonaPackRegistry | None = None,
    ):
        self._telemetry = telemetry or OpenTelemetryRecorder()
        if model_factory is None:
            model_factory = lambda: create_observed_agent_model(
                self._telemetry,
                role="coordinator",
                timeout=config.RECRUITMENT_MODEL_HTTP_TIMEOUT_SECONDS,
                max_retries=config.RECRUITMENT_MODEL_TRANSPORT_RETRIES,
            )
        self._model_factory = model_factory
        self._judge_model_factory = judge_model_factory or model_factory
        self._correction_model_factory = correction_model_factory or model_factory
        self._registry = persona_registry or load_persona_pack_registry()
        self._quality_gate = TargetAssessmentQualityGate(
            judge_model_factory=self._judge_model_factory,
            correction_model_factory=self._correction_model_factory,
            telemetry=self._telemetry,
            persona_registry=self._registry,
        )

    def _build_agent(self, orchestrator_model):
        persona_subagents = create_target_persona_subagents(self._registry, orchestrator_model)
        domain_tool_names = {
            "read_candidate_evidence",
            "read_target_job",
            "propose_resume_edit",
            "ask_candidate",
            "submit_target_assessment_synthesis",
            "task",
        }
        return create_resume_agent(
            model=orchestrator_model,
            tools=[
                read_candidate_evidence,
                read_target_job,
                propose_resume_edit,
                ask_candidate,
                submit_target_assessment_synthesis,
            ],
            subagents=persona_subagents,
            checkpointer=_CHECKPOINTER,
            interrupt_on={"ask_candidate": True},
            middleware=[
                provider_message_compatibility,
                require_tool_call,
                _require_pending_specialist_delegation,
                ToolCallGuardMiddleware(
                    allowed_tools=domain_tool_names,
                    enforce_fresh_specialists=True,
                ),
                _stop_after_terminal_specialist_failure,
                _stop_after_accepted_synthesis,
            ],
        )

    def _failed_result(
        self,
        request: TargetAssessmentRequest,
        model_attempts: list[dict],
        started_at: float,
        *,
        failure_code: str,
        validation_codes: tuple[str, ...] = (),
        retry_same_run: bool = False,
        checkpoint_hit_count: int = 0,
        semantic_outcomes: list[dict] | None = None,
    ) -> TargetAssessmentResult:
        metrics = _target_execution_metrics(
            request,
            model_attempts,
            (),
            (time.perf_counter() - started_at) * 1000,
            "failed",
            checkpoint_hit_count=checkpoint_hit_count,
            semantic_outcomes=semantic_outcomes,
        )
        metrics["validation_codes"] = [*metrics["validation_codes"], *validation_codes]
        checkpoint_unavailable = failure_code == _CHECKPOINT_STATE_UNAVAILABLE
        return TargetAssessmentResult(
            status="failed",
            specialist_runs=(),
            synthesis="",
            judge=None,
            correction=None,
            error={
                "failure_type": "transient" if checkpoint_unavailable else "validation",
                "failure_code": failure_code,
                "error_type": (
                    "CheckpointStateUnavailable"
                    if checkpoint_unavailable
                    else "TargetAssessmentValidationError"
                ),
                "retryable": checkpoint_unavailable and retry_same_run,
                "recovery_action": (
                    "retry_same_run"
                    if checkpoint_unavailable and retry_same_run
                    else "start_new_logical_run"
                ),
                "validation_codes": list(validation_codes),
            },
            execution_policy=target_assessment_execution_policy(),
            execution_metrics=metrics,
        )

    def run(
        self,
        request: TargetAssessmentRequest,
        *,
        renew_lease: Callable[[], None] | None = None,
    ) -> Iterator[TargetAssessmentUpdate]:
        yield TargetAssessmentProgress(
            team_member="coordinator",
            status="running",
            summary="Open-agent run started.",
            detail={"required_specialist_count": len(self._registry.personas)},
        )

        orchestrator_model = self._model_factory()
        agent = self._build_agent(orchestrator_model)
        required_personas = ", ".join(pack.persona_id for pack in self._registry.personas)
        payload = {
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Assess this candidate against the target job. Delegate at least once "
                        "to every required specialist persona before finishing: "
                        f"{required_personas}. Choose their order yourself, use the evidence "
                        "tools you need, and revisit a specialist when new evidence warrants it. "
                        "Ask the candidate directly if you hit a real evidence gap.\n\n"
                        "Drafting resume edits is part of this job, not an optional extra. "
                        "Plan the work yourself and call propose_resume_edit for every "
                        "gap where the candidate's own evidence already supports stronger "
                        "wording, whether that evidence is in their resume or in an answer "
                        "they gave you. You may draft before or after delegation whenever the "
                        "evidence is sufficient. Many gaps are vocabulary rather than experience: the "
                        "candidate did the work but did not phrase it the way this posting "
                        "does, and those are the edits worth drafting.\n\n"
                        "Never invent experience. Where the gap is genuinely missing "
                        "experience rather than weak wording, say so in your assessment and "
                        "do not draft an edit for it. The candidate has to defend every line "
                        "of their resume in an interview.\n\n"
                        "Your final assessment is accepted only through "
                        "submit_target_assessment_synthesis. Submit evidence-linked strength, "
                        "gap, and next-step claims through that tool before ending. A plain final "
                        "message is not a synthesis."
                    ),
                }
            ]
        }
        run_config = {
            "recursion_limit": config.TARGET_ASSESSMENT_MAX_TOOL_ITERATIONS,
            "configurable": {"thread_id": str(uuid.uuid4())},
        }
        with collect_transport_metrics() as transport_metrics:
            with bind_transport_collector(orchestrator_model, transport_metrics):
                yield from self._drive(
                    agent,
                    payload,
                    run_config,
                    request,
                    specialist_runs=[],
                    synthesis="",
                    renew_lease=renew_lease,
                )

    def resume(
        self,
        pause_token: str,
        answer: str,
        request: TargetAssessmentRequest,
        specialist_runs: list[dict],
        synthesis: str,
        proposed_edits: list[dict],
        ask_candidate_call_id: str | None = None,
        renew_lease: Callable[[], None] | None = None,
        synthesis_claims: list[dict] | None = None,
    ) -> Iterator[TargetAssessmentUpdate]:
        """Resume durable graph state and skip the replayed pause call."""
        orchestrator_model = self._model_factory()
        agent = self._build_agent(orchestrator_model)
        run_config = {
            "recursion_limit": config.TARGET_ASSESSMENT_MAX_TOOL_ITERATIONS,
            "configurable": {"thread_id": pause_token},
        }
        try:
            checkpoint_state = _checkpoint_state(agent, run_config)
        except CheckpointStateUnavailable:
            yield TargetAssessmentProgress(
                team_member="coordinator",
                status="failed",
                summary="The assessment stopped because its durable checkpoint could not be read.",
                detail={
                    "failure_type": "transient",
                    "failure_code": _CHECKPOINT_STATE_UNAVAILABLE,
                    "retryable": True,
                    "recovery_action": "retry_same_run",
                },
            )
            yield self._failed_result(
                request,
                [],
                time.perf_counter(),
                failure_code=_CHECKPOINT_STATE_UNAVAILABLE,
                retry_same_run=True,
            )
            return
        if not checkpoint_state.interrupts:
            result = TargetAssessmentResult(
                status="failed",
                specialist_runs=(),
                synthesis="",
                judge=None,
                correction=None,
                error={
                    "failure_type": "business",
                    "failure_code": "pause_token_not_found",
                    "error_type": "PauseTokenNotFound",
                    "retryable": False,
                    "recovery_action": "start_new_logical_run",
                },
                execution_policy=target_assessment_execution_policy(),
            )
            yield _cleaned_result(result, run_config, self._telemetry)
            return
        # Nothing else bounds ask_candidate: the guardrails only reject a materially
        # identical repeat, so a reworded question always passes and a run can
        # ping-pong until it never reaches synthesis, the judge or a single
        # proposed edit. Observed in production: three pauses across two runs and
        # zero edits. Past the cap, say so plainly in the answer the orchestrator
        # reads, since that is the only channel back into a resumed graph.
        resume_message = answer
        if _ask_rounds_so_far(checkpoint_state) >= config.OPEN_AGENT_MAX_CANDIDATE_QUESTION_ROUNDS:
            resume_message = (
                f"{answer}\n\n[System: you have reached this assessment's question limit. "
                "Do not call ask_candidate again. Finish now using the resume, the "
                "specialist reports and the answers already given: submit your assessment "
                "and call propose_resume_edit for every gap the candidate's own evidence "
                "already supports. Where a gap is missing experience rather than weak "
                "wording, report it and draft no edit for it.]"
            )
        payload = Command(resume={"decisions": [{"type": "respond", "message": resume_message}]})
        with collect_transport_metrics() as transport_metrics:
            with bind_transport_collector(orchestrator_model, transport_metrics):
                yield from self._drive(
                    agent,
                    payload,
                    run_config,
                    request,
                    specialist_runs=list(specialist_runs),
                    synthesis=synthesis,
                    synthesis_claims=list(synthesis_claims or []),
                    initial_edits=list(proposed_edits),
                    skip_tool_call_ids={ask_candidate_call_id} if ask_candidate_call_id else None,
                    renew_lease=renew_lease,
                    resumed_from_checkpoint=True,
                )

    def _drive(
        self,
        agent,
        payload,
        run_config: dict,
        request: TargetAssessmentRequest,
        *,
        specialist_runs: list[dict],
        synthesis: str,
        synthesis_claims: list[dict] | None = None,
        initial_edits: list[dict] | None = None,
        skip_tool_call_ids: set[str] | None = None,
        renew_lease: Callable[[], None] | None = None,
        model_attempts_so_far: list[dict] | None = None,
        semantic_outcomes_so_far: list[dict] | None = None,
        question_limit_enforced: bool = False,
        resumed_from_checkpoint: bool = False,
    ) -> Iterator[TargetAssessmentUpdate]:
        pending_question: str | None = None
        pending_question_call_id: str | None = None
        model_attempts: list[dict] = list(model_attempts_so_far or ())
        semantic_outcomes: list[dict] = list(semantic_outcomes_so_far or ())
        seen_model_event_ids: set[str] = set()
        synthesis_validation_codes: tuple[str, ...] = ()
        drive_started = time.perf_counter()
        with context.assessment_context(
            request,
            initial_edits=initial_edits,
            required_specialist_ids=tuple(pack.persona_id for pack in self._registry.personas),
            initial_specialist_ids=tuple(
                str(run.get("persona_id") or "")
                for run in specialist_runs
                if run.get("status") == "completed"
            ),
            allow_completed_specialist_revisit=resumed_from_checkpoint,
        ):
            try:
                for event in iter_progress_events(agent, payload, run_config, skip_tool_call_ids=skip_tool_call_ids):
                    if event["kind"] == "model_attempt":
                        event_id = str(event.get("id") or "")
                        if event_id and event_id in seen_model_event_ids:
                            continue
                        if event_id:
                            seen_model_event_ids.add(event_id)
                        team_member = event.get("team_member") or "coordinator"
                        model_attempts.append(
                            {
                                "attempt_id": event_id,
                                "stage": "target_assessment",
                                "team_member": team_member,
                                "model": event.get("model") or "",
                                "input_tokens": int(event.get("input_tokens") or 0),
                                "output_tokens": int(event.get("output_tokens") or 0),
                                "attempt_limit": _agent_attempt_limit(team_member),
                                "status": "generated",
                            }
                        )
                        if renew_lease is not None:
                            renew_lease()
                        member_attempt = sum(
                            1 for item in model_attempts if item.get("team_member") == team_member
                        )
                        yield TargetAssessmentProgress(
                            team_member=team_member,
                            status="running",
                            summary=f"{team_member} completed a model step.",
                            detail={"stage": "model", "attempt": member_attempt},
                        )
                        continue
                    if event["kind"] == "tool_call" and event["tool_name"] == ask_candidate.name:
                        pending_question = format_questions(event.get("args") or {})
                        pending_question_call_id = event.get("id")

                    if (
                        event["kind"] == "tool_result"
                        and event["team_member"] == "coordinator"
                        and event["tool_name"] == submit_target_assessment_synthesis.name
                        and rejected_tool_result(event)
                    ):
                        tool_payload = event.get("content")
                        if isinstance(tool_payload, str):
                            try:
                                tool_payload = json.loads(tool_payload)
                            except json.JSONDecodeError:
                                tool_payload = {}
                        if isinstance(tool_payload, dict):
                            # A fixable rejection belongs to this still-live graph.
                            # Let the coordinator see the tool receipt and use the
                            # tool-owned correction budget instead of returning a
                            # terminal result whose checkpoint has already been
                            # cleaned up.
                            if tool_payload.get("retry") is True:
                                continue
                            synthesis_validation_codes = tuple(
                                str(code) for code in tool_payload.get("validation_codes") or ()
                            )
                            if not synthesis_validation_codes:
                                synthesis_validation_codes = (
                                    str(
                                        tool_payload.get("validation_code")
                                        or "synthesis:submission_rejected"
                                    ),
                                )
                        break

                    if (
                        event["kind"] == "tool_result"
                        and event["team_member"] != "coordinator"
                        and event["tool_name"] == SPECIALIST_TOOL.name
                    ):
                        tool_payload = event.get("content")
                        if isinstance(tool_payload, str):
                            try:
                                tool_payload = json.loads(tool_payload)
                            except json.JSONDecodeError:
                                tool_payload = {}
                        if not isinstance(tool_payload, dict):
                            tool_payload = {}
                        accepted = tool_payload.get("accepted") is True
                        validation_code = _semantic_validation_code(tool_payload)
                        semantic_outcomes.append({
                            "outcome_id": str(event.get("id") or ""),
                            "role": str(event["team_member"]),
                            "stage": "specialist_submission",
                            "accepted": accepted,
                            "submission_attempt": int(tool_payload.get("attempt_count") or 1),
                            "validation_code": validation_code,
                        })
                        submission = self._parse_specialist_submission(event["content"])
                        if submission is not None:
                            specialist_runs.append(
                                {"persona_id": event["team_member"], "status": "completed", "submission": submission}
                            )
                            detail = {
                                "stage": "result",
                                "tool_name": SPECIALIST_TOOL.name,
                            }
                            if event.get("id"):
                                detail["tool_call_id"] = event["id"]
                            yield TargetAssessmentProgress(
                                team_member=event["team_member"],
                                status="completed",
                                summary=f"{event['team_member']} submitted its assessment.",
                                detail=detail,
                            )
                        else:
                            described = describe_progress(event)
                            if described is not None:
                                summary, detail = described
                                yield TargetAssessmentProgress(
                                    team_member=event["team_member"],
                                    status="running",
                                    summary=summary,
                                    detail=detail,
                                )
                        continue

                    if event["kind"] == "message" and event["team_member"] == "coordinator":
                        # Plain assistant prose is not a publishable evidence contract.
                        continue

                    # Every other call and result, phrased once for both loops.
                    described = describe_progress(event)
                    if described is not None:
                        summary, detail = described
                        yield TargetAssessmentProgress(
                            team_member=event["team_member"],
                            status="running",
                            summary=summary,
                            detail=detail,
                        )
            except GraphRecursionError as error:
                exhausted_limit = _recursion_limit_from_error(error)
                specialist_exhausted = (
                    exhausted_limit == config.TARGET_SPECIALIST_MAX_TOOL_ITERATIONS
                )
                failure_code = (
                    _SPECIALIST_BUDGET_EXHAUSTED
                    if specialist_exhausted
                    else _ORCHESTRATOR_BUDGET_EXHAUSTED
                )
                yield TargetAssessmentProgress(
                    team_member="specialist_team" if specialist_exhausted else "coordinator",
                    status="failed",
                    summary=(
                        "A specialist reached its bounded execution limit."
                        if specialist_exhausted
                        else "The coordinator reached its bounded execution limit."
                    ),
                    detail={
                        "failure_type": "business",
                        "failure_code": failure_code,
                        "scope": "specialist" if specialist_exhausted else "coordinator",
                        "attempt_limit": exhausted_limit,
                    },
                )
                result = self._failed_result(
                    request,
                    model_attempts,
                    drive_started,
                    failure_code=failure_code,
                    semantic_outcomes=semantic_outcomes,
                )
                yield _cleaned_result(result, run_config, self._telemetry)
                return
            except Exception as error:
                # A resumed graph already has a persisted pause token owned by
                # the service's durable retry ledger. Preserve that checkpoint
                # until the service decides whether the transport failure may
                # retry; deleting it here makes a truthful retry impossible.
                if resumed_from_checkpoint:
                    raise
                if _delete_terminal_checkpoint(run_config, self._telemetry):
                    raise
                token = str(run_config.get("configurable", {}).get("thread_id") or "")
                raise TargetAssessmentExecutionError(token) from error
            edits = context.proposed_edits() or []
            terminal_specialist_failure = context.terminal_specialist_failure()
            specialist_validation_codes = tuple(
                str(code)
                for code in (terminal_specialist_failure or {}).get("validation_codes") or ()
            )
            accepted_synthesis = context.submitted_synthesis()
            if accepted_synthesis:
                synthesis = accepted_synthesis
                synthesis_claims = context.submitted_synthesis_claims()
            if synthesis_validation_codes:
                yield TargetAssessmentProgress(
                    team_member="coordinator",
                    status="failed",
                    summary="The synthesis stopped after exhausting its validation attempts.",
                    detail={
                        "failure_type": "validation",
                        "failure_code": _SPECIALIST_CONTRACT_INVALID,
                        "validation_code": synthesis_validation_codes[0],
                        "attempt_limit": config.RECRUITMENT_SYNTHESIS_VALIDATION_ATTEMPTS,
                    },
                )
                result = self._failed_result(
                    request,
                    model_attempts,
                    drive_started,
                    failure_code=_ORCHESTRATOR_BUDGET_EXHAUSTED,
                    validation_codes=synthesis_validation_codes,
                    semantic_outcomes=semantic_outcomes,
                )
                yield _cleaned_result(result, run_config, self._telemetry)
                return
            if specialist_validation_codes:
                yield TargetAssessmentProgress(
                    team_member="specialist_team",
                    status="failed",
                    summary="A specialist exhausted its structured correction budget.",
                    detail={
                        "failure_type": "validation",
                        "failure_code": _SPECIALIST_CONTRACT_INVALID,
                        "validation_code": specialist_validation_codes[0],
                        "attempt_limit": config.AGENT_PERSONA_VALIDATION_ATTEMPTS,
                    },
                )
                result = self._failed_result(
                    request,
                    model_attempts,
                    drive_started,
                    failure_code=_SPECIALIST_BUDGET_EXHAUSTED,
                    validation_codes=specialist_validation_codes,
                    semantic_outcomes=semantic_outcomes,
                )
                yield _cleaned_result(result, run_config, self._telemetry)
                return

            # iter_progress_events only forwards dict-shaped node
            # updates (see streaming.py's `isinstance(node_update, dict)`
            # check), so the raw `{"__interrupt__": (...)}` chunk LangGraph
            # emits when the HumanInTheLoopMiddleware pauses the graph is
            # silently dropped -- the stream loop above just ends with no
            # explicit signal. Confirmed empirically (see
            # tests/test_open_agent_runner.py's interrupt test): with a
            # checkpointer + thread_id wired, agent.get_state(run_config)
            # after the loop still exposes the pending interrupt via
            # `state.interrupts`, because the checkpointer persisted it.
            # Past the cap the pause is not surfaced at all. Appending a "do not
            # ask again" sentence to the resume message only asks the model
            # nicely, and duplicate-call rejection does not reject a reworded
            # question, so nothing actually stopped a run
            # pausing forever. Refusing to yield the pause is what bounds it.
            try:
                checkpoint_state = _checkpoint_state(agent, run_config)
            except CheckpointStateUnavailable:
                yield TargetAssessmentProgress(
                    team_member="coordinator",
                    status="failed",
                    summary="The assessment stopped because its durable checkpoint could not be read.",
                    detail={
                        "failure_type": "transient",
                        "failure_code": _CHECKPOINT_STATE_UNAVAILABLE,
                        "retryable": resumed_from_checkpoint,
                        "recovery_action": (
                            "retry_same_run" if resumed_from_checkpoint else "start_new_logical_run"
                        ),
                    },
                )
                result = self._failed_result(
                    request,
                    model_attempts,
                    drive_started,
                    failure_code=_CHECKPOINT_STATE_UNAVAILABLE,
                    retry_same_run=resumed_from_checkpoint,
                    checkpoint_hit_count=1 if resumed_from_checkpoint else 0,
                    semantic_outcomes=semantic_outcomes,
                )
                yield (
                    result
                    if resumed_from_checkpoint
                    else _cleaned_result(result, run_config, self._telemetry)
                )
                return
            if checkpoint_state.interrupts and mentions_protected_status(pending_question or ""):
                yield TargetAssessmentProgress(
                    team_member="coordinator",
                    status="failed",
                    summary="The assessment rejected a protected-status question.",
                    detail={
                        "failure_type": "validation",
                        "failure_code": _PROTECTED_CANDIDATE_QUESTION,
                        "retryable": False,
                        "recovery_action": "start_new_logical_run",
                    },
                )
                result = self._failed_result(
                    request,
                    model_attempts,
                    drive_started,
                    failure_code=_PROTECTED_CANDIDATE_QUESTION,
                    validation_codes=("candidate_question:protected_status",),
                    semantic_outcomes=semantic_outcomes,
                )
                yield _cleaned_result(result, run_config, self._telemetry)
                return
            if (
                checkpoint_state.interrupts
                and _ask_rounds_so_far(checkpoint_state) > config.OPEN_AGENT_MAX_CANDIDATE_QUESTION_ROUNDS
            ):
                if question_limit_enforced:
                    result = self._failed_result(
                        request,
                        model_attempts,
                        drive_started,
                        failure_code=_QUESTION_BUDGET_EXHAUSTED,
                        semantic_outcomes=semantic_outcomes,
                    )
                    yield _cleaned_result(result, run_config, self._telemetry)
                    return
                yield TargetAssessmentProgress(
                    team_member="coordinator",
                    status="running",
                    summary="Question limit reached; finishing with the evidence on hand.",
                    detail={"question_limit": config.OPEN_AGENT_MAX_CANDIDATE_QUESTION_ROUNDS},
                )
                if renew_lease is not None:
                    renew_lease()
                yield from self._drive(
                    agent,
                    Command(resume={"decisions": [{"type": "respond", "message": _QUESTION_LIMIT_REPLY}]}),
                    run_config,
                    request,
                    specialist_runs=list(specialist_runs),
                    synthesis=synthesis,
                    synthesis_claims=list(synthesis_claims or []),
                    initial_edits=list(edits),
                    skip_tool_call_ids={pending_question_call_id} if pending_question_call_id else None,
                    renew_lease=renew_lease,
                    model_attempts_so_far=model_attempts,
                    semantic_outcomes_so_far=semantic_outcomes,
                    question_limit_enforced=True,
                    resumed_from_checkpoint=resumed_from_checkpoint,
                )
                return
            elif checkpoint_state.interrupts:
                yield TargetAssessmentProgress(
                    team_member="coordinator",
                    status="paused",
                    summary="Run paused: waiting on the candidate to answer a question.",
                    detail={
                        "question": pending_question,
                        "question_count": len(
                            [line for line in (pending_question or "").splitlines() if line.strip()]
                        ),
                        "pause_token": run_config["configurable"]["thread_id"],
                        "ask_candidate_call_id": pending_question_call_id,
                        # Carried by the caller onto the artifact row so a
                        # later resume() call can seed them back in -- this
                        # module has no durable storage of its own for
                        # anything the checkpointer itself doesn't persist.
                        "specialist_runs": specialist_runs,
                        "synthesis": synthesis,
                        "synthesis_claims": list(synthesis_claims or []),
                        "proposed_edits": list(edits),
                        "execution_metrics": _target_execution_metrics(
                            request,
                            model_attempts,
                            (),
                            (time.perf_counter() - drive_started) * 1000,
                            "paused",
                            checkpoint_hit_count=1 if resumed_from_checkpoint else 0,
                            semantic_outcomes=semantic_outcomes,
                        ),
                    },
                )
                return

        validation_codes = validate_specialist_runs(
            request,
            specialist_runs,
            tuple(pack.persona_id for pack in self._registry.personas),
        )
        if not synthesis.strip():
            validation_codes = (*validation_codes, "synthesis:empty")
        if validation_codes:
            yield TargetAssessmentProgress(
                team_member="coordinator",
                status="failed",
                summary="The assessment stopped because its reviewer evidence was incomplete.",
                detail={
                    "failure_type": "validation",
                    "failure_code": _SPECIALIST_CONTRACT_INVALID,
                    "validation_code": validation_codes[0],
                },
            )
            result = self._failed_result(
                request,
                model_attempts,
                drive_started,
                failure_code=_SPECIALIST_CONTRACT_INVALID,
                validation_codes=validation_codes,
                semantic_outcomes=semantic_outcomes,
            )
            yield _cleaned_result(result, run_config, self._telemetry)
            return

        gate_outcome: QualityGateOutcome | None = None
        for update in self._quality_gate.review(
            request,
            specialist_runs,
            synthesis,
            list(synthesis_claims or []),
            renew_lease=renew_lease,
        ):
            if isinstance(update, TargetAssessmentProgress):
                yield update
            else:
                gate_outcome = update
        if gate_outcome is None:  # pragma: no cover - defensive generator contract guard
            raise RuntimeError("target assessment quality gate returned no outcome")

        result = TargetAssessmentResult(
            status=gate_outcome.status,
            specialist_runs=tuple(specialist_runs),
            synthesis=gate_outcome.synthesis,
            synthesis_claims=tuple(gate_outcome.synthesis_claims),
            judge=gate_outcome.judge,
            correction=gate_outcome.correction,
            error=gate_outcome.error,
            execution_policy=target_assessment_execution_policy(),
            proposed_edits=tuple(edits),
            execution_metrics=_target_execution_metrics(
                request,
                model_attempts,
                gate_outcome.attempts,
                (time.perf_counter() - drive_started) * 1000,
                gate_outcome.status,
                checkpoint_hit_count=1 if resumed_from_checkpoint else 0,
                semantic_outcomes=semantic_outcomes,
            ),
        )
        yield _cleaned_result(result, run_config, self._telemetry)

    @staticmethod
    def _parse_specialist_submission(content) -> dict | None:
        parsed = content
        if isinstance(content, str):
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError:
                return None
        if not isinstance(parsed, dict) or parsed.get("ok") is False:
            return None
        candidate = parsed.get("submission", parsed)
        try:
            return SpecialistSubmission.model_validate(candidate).model_dump()
        except ValidationError:
            return None
