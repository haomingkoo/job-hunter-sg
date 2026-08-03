"""Open-ended orchestrator over the target-assessment tool set, streaming
progress as it goes. The independent judge is the one non-optional step,
whatever reasoning path the orchestrator took to get there."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import asdict
from typing import Iterator

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.errors import GraphRecursionError
from langgraph.types import Command

import config
from resume_agent.agent import create_resume_agent
from resume_agent.tools import search_jobs

from ..assessment_contracts import (
    JUDGE_TOOL,
    SPECIALIST_TOOL,
    SYNTHESIS_CORRECTION_TOOL,
    TargetAssessmentProgress,
    TargetAssessmentRequest,
    TargetAssessmentResult,
    TargetAssessmentUpdate,
    invoke_structured,
    target_assessment_execution_policy,
)
from ..conversation_model import ConversationReply, PreferenceUpdatePayload
from ..persona_packs import PersonaPackRegistry, load_persona_pack_registry
from ..telemetry import OpenTelemetryRecorder, RecruitmentTelemetry
from ..tool_call_guard import ToolCallGuardMiddleware
from . import context
from .streaming import describe_progress, format_questions, iter_progress_events
from .subagents import create_target_persona_subagents
from .tools import ask_candidate, propose_resume_edit, read_candidate_evidence, read_target_job


_QUESTION_LIMIT_REPLY = (
    "[System: this assessment's question limit is reached and no further question "
    "will be delivered. Finish now using the resume, the specialist reports and the "
    "answers already given: submit your assessment and call propose_resume_edit for "
    "every gap the candidate's own evidence already supports. Where a gap is missing "
    "experience rather than weak wording, report it and draft no edit for it.]"
)


def _ask_rounds_so_far(agent, run_config: dict) -> int:
    """How many times this run has already stopped to ask the candidate."""
    try:
        messages = agent.get_state(run_config).values.get("messages") or []
    except Exception:
        return 0
    return sum(
        1
        for message in messages
        for call in (getattr(message, "tool_calls", None) or [])
        if call.get("name") == "ask_candidate"
    )


# A durable checkpointer so an ask_candidate pause survives a process
# restart and can be resumed by any worker, not just the one that hit the
# pause -- LangGraph's own persistence, not a hand-rolled process-local
# cache. SqliteSaver manages its own internal lock for concurrent access.
_checkpointer_conn = sqlite3.connect(config.OPEN_AGENT_CHECKPOINT_DB_PATH, check_same_thread=False)
_CHECKPOINTER = SqliteSaver(
    _checkpointer_conn,
    serde=JsonPlusSerializer(
        allowed_msgpack_modules=(ConversationReply, PreferenceUpdatePayload),
    ),
)
_CHECKPOINTER.setup()


def delete_checkpoint(thread_id: str) -> None:
    """Delete one durable LangGraph thread by its persisted identifier."""
    _CHECKPOINTER.delete_thread(thread_id)


def _target_execution_metrics(
    request: TargetAssessmentRequest,
    model_attempts: list[dict],
    judges,
    correction: dict | None,
    latency_ms: float,
    terminal_status: str,
) -> dict:
    attempts = list(model_attempts)
    for judge in judges:
        attempts.append({
            "stage": "target_assessment_judge",
            "team_member": "quality_judge",
            "model": str(judge.get("model_name") or ""),
            "input_tokens": int(judge.get("input_tokens") or 0),
            "output_tokens": int(judge.get("output_tokens") or 0),
            "status": "success" if judge.get("disposition") else "validation_failed",
            "validation_code": str(judge.get("score_reason") or "") if not judge.get("disposition") else "",
        })
    if correction and correction.get("attempted"):
        attempts.append({
            "stage": "target_assessment_correction",
            "team_member": "coordinator",
            "model": str(correction.get("model_name") or ""),
            "input_tokens": int(correction.get("input_tokens") or 0),
            "output_tokens": int(correction.get("output_tokens") or 0),
            "attempt_count": int(correction.get("attempt_count") or 0),
            "status": str(correction.get("status") or ""),
            "validation_code": str(correction.get("failure") or ""),
        })
    models = list(dict.fromkeys(
        str(item.get("model") or "") for item in attempts if item.get("model")
    ))
    return {
        "logical_run_id": request.trace_key,
        "trace_key": request.trace_key,
        "stage": "target_assessment",
        "model_call_count": sum(int(item.get("attempt_count") or 1) for item in attempts),
        "checkpoint_hit_count": 0,
        "input_tokens": sum(int(item.get("input_tokens") or 0) for item in attempts),
        "output_tokens": sum(int(item.get("output_tokens") or 0) for item in attempts),
        "latency_ms": round(latency_ms, 3),
        "validation_codes": [
            str(item["validation_code"]) for item in attempts if item.get("validation_code")
        ],
        "models": models,
        "attempts": attempts,
        "terminal_status": terminal_status,
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
        if model_factory is None:
            from resume_agent.models import create_agent_model

            model_factory = lambda: create_agent_model(
                timeout=config.RECRUITMENT_MODEL_HTTP_TIMEOUT_SECONDS,
                max_retries=config.RECRUITMENT_MODEL_TRANSPORT_RETRIES,
            )
        self._model_factory = model_factory
        self._judge_model_factory = judge_model_factory or model_factory
        self._correction_model_factory = correction_model_factory or model_factory
        self._telemetry = telemetry or OpenTelemetryRecorder()
        self._registry = persona_registry or load_persona_pack_registry()

    def _build_agent(self, orchestrator_model):
        persona_subagents = create_target_persona_subagents(self._registry, orchestrator_model)
        return create_resume_agent(
            model=orchestrator_model,
            tools=[read_candidate_evidence, read_target_job, search_jobs, propose_resume_edit, ask_candidate],
            subagents=persona_subagents,
            checkpointer=_CHECKPOINTER,
            interrupt_on={"ask_candidate": True},
            middleware=[ToolCallGuardMiddleware()],
        )

    def run(self, request: TargetAssessmentRequest) -> Iterator[TargetAssessmentUpdate]:
        yield TargetAssessmentProgress(
            team_member="coordinator", status="running", summary="Open-agent run started.", detail={}
        )

        agent = self._build_agent(self._model_factory())
        payload = {"messages": [{
            "role": "user",
            "content": (
                "Assess this candidate against the target job. Consult whichever "
                "personas you judge useful, however many times you judge useful. "
                "Ask the candidate directly if you hit a real evidence gap.\n\n"
                "Drafting resume edits is part of this job, not an optional extra. "
                "Once the personas have reported, call propose_resume_edit for every "
                "gap where the candidate's own evidence already supports stronger "
                "wording, whether that evidence is in their resume or in an answer "
                "they gave you. Many gaps are vocabulary rather than experience: the "
                "candidate did the work but did not phrase it the way this posting "
                "does, and those are the edits worth drafting.\n\n"
                "Never invent experience. Where the gap is genuinely missing "
                "experience rather than weak wording, say so in your assessment and "
                "do not draft an edit for it. The candidate has to defend every line "
                "of their resume in an interview."
            ),
        }]}
        run_config = {
            "recursion_limit": config.AGENT_MAX_TOOL_ITERATIONS,
            "configurable": {"thread_id": str(uuid.uuid4())},
        }
        yield from self._drive(agent, payload, run_config, request, specialist_runs=[], synthesis="")

    def resume(
        self,
        pause_token: str,
        answer: str,
        request: TargetAssessmentRequest,
        specialist_runs: list[dict],
        synthesis: str,
        proposed_edits: list[dict],
        ask_candidate_call_id: str | None = None,
    ) -> Iterator[TargetAssessmentUpdate]:
        """Resume durable graph state and skip the replayed pause call."""
        agent = self._build_agent(self._model_factory())
        run_config = {
            "recursion_limit": config.AGENT_MAX_TOOL_ITERATIONS,
            "configurable": {"thread_id": pause_token},
        }
        if not agent.get_state(run_config).interrupts:
            yield TargetAssessmentResult(
                status="failed",
                specialist_runs=(),
                synthesis="",
                judge=None,
                correction=None,
                error={
                    "failure_type": "workflow",
                    "error_type": "PauseTokenNotFound",
                    "retryable": False,
                },
                execution_policy=target_assessment_execution_policy(),
            )
            return
        # Nothing else bounds ask_candidate: the guardrails only reject a materially
        # identical repeat, so a reworded question always passes and a run can
        # ping-pong until it never reaches synthesis, the judge or a single
        # proposed edit. Observed in production: three pauses across two runs and
        # zero edits. Past the cap, say so plainly in the answer the orchestrator
        # reads, since that is the only channel back into a resumed graph.
        resume_message = answer
        if _ask_rounds_so_far(agent, run_config) >= config.OPEN_AGENT_MAX_CANDIDATE_QUESTION_ROUNDS:
            resume_message = (
                f"{answer}\n\n[System: you have reached this assessment's question limit. "
                "Do not call ask_candidate again. Finish now using the resume, the "
                "specialist reports and the answers already given: submit your assessment "
                "and call propose_resume_edit for every gap the candidate's own evidence "
                "already supports. Where a gap is missing experience rather than weak "
                "wording, report it and draft no edit for it.]"
            )
        payload = Command(resume={"decisions": [{"type": "respond", "message": resume_message}]})
        yield from self._drive(
            agent,
            payload,
            run_config,
            request,
            specialist_runs=list(specialist_runs),
            synthesis=synthesis,
            initial_edits=list(proposed_edits),
            skip_tool_call_ids={ask_candidate_call_id} if ask_candidate_call_id else None,
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
        initial_edits: list[dict] | None = None,
        skip_tool_call_ids: set[str] | None = None,
    ) -> Iterator[TargetAssessmentUpdate]:
        pending_question: str | None = None
        pending_question_call_id: str | None = None
        model_attempts: list[dict] = []
        seen_model_event_ids: set[str] = set()
        drive_started = time.perf_counter()
        with context.assessment_context(request, initial_edits=initial_edits):
            try:
                for event in iter_progress_events(
                    agent, payload, run_config, skip_tool_call_ids=skip_tool_call_ids
                ):
                    if event["kind"] == "model_attempt":
                        event_id = str(event.get("id") or "")
                        if event_id and event_id in seen_model_event_ids:
                            continue
                        if event_id:
                            seen_model_event_ids.add(event_id)
                        model_attempts.append({
                            "stage": "target_assessment",
                            "team_member": event.get("team_member") or "coordinator",
                            "model": event.get("model") or "",
                            "input_tokens": int(event.get("input_tokens") or 0),
                            "output_tokens": int(event.get("output_tokens") or 0),
                            "status": "success",
                        })
                        continue
                    if event["kind"] == "tool_call" and event["tool_name"] == ask_candidate.name:
                        pending_question = format_questions(event.get("args") or {})
                        pending_question_call_id = event.get("id")

                    if (
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
                        continue

                    if event["kind"] == "message" and event["team_member"] == "coordinator":
                        synthesis = str(event["content"])
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
            except GraphRecursionError:
                # The orchestrator hit its recursion_limit before reaching a
                # natural stopping point. Whatever specialist_runs/synthesis
                # accumulated so far must still go through the judge rather
                # than being discarded, so stop consuming events and fall
                # through to the same judge-calling path a normal completion
                # takes.
                pass
            edits = context.proposed_edits() or []

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
            if agent.get_state(run_config).interrupts and _ask_rounds_so_far(
                agent, run_config
            ) > config.OPEN_AGENT_MAX_CANDIDATE_QUESTION_ROUNDS:
                yield TargetAssessmentProgress(
                    team_member="coordinator",
                    status="running",
                    summary="Question limit reached; finishing with the evidence on hand.",
                    detail={"question_limit": config.OPEN_AGENT_MAX_CANDIDATE_QUESTION_ROUNDS},
                )
                agent.invoke(
                    Command(resume={"decisions": [{"type": "respond", "message": _QUESTION_LIMIT_REPLY}]}),
                    run_config,
                )
            elif agent.get_state(run_config).interrupts:
                yield TargetAssessmentProgress(
                    team_member="coordinator",
                    status="paused",
                    summary="Run paused: waiting on the candidate to answer a question.",
                    detail={
                        "question": pending_question,
                        "pause_token": run_config["configurable"]["thread_id"],
                        "ask_candidate_call_id": pending_question_call_id,
                        # Carried by the caller onto the artifact row so a
                        # later resume() call can seed them back in -- this
                        # module has no durable storage of its own for
                        # anything the checkpointer itself doesn't persist.
                        "specialist_runs": specialist_runs,
                        "synthesis": synthesis,
                        "proposed_edits": list(edits),
                        "execution_metrics": _target_execution_metrics(
                            request,
                            model_attempts,
                            (),
                            None,
                            (time.perf_counter() - drive_started) * 1000,
                            "paused",
                        ),
                    },
                )
                return

        judge_model = self._judge_model_factory()
        judge = self._run_judge(judge_model, request, specialist_runs, synthesis)
        judge_attempts = [judge]
        correction = None
        if (
            judge["disposition"] == "revise"
            and config.RECRUITMENT_MAX_SYNTHESIS_CORRECTIONS == 1
        ):
            yield TargetAssessmentProgress(
                team_member="coordinator",
                status="running",
                summary="The coordinator is repairing the assessment from the judge's findings.",
                detail={"stage": "synthesis_correction"},
            )
            corrected_synthesis, correction = self._correct_synthesis(
                self._correction_model_factory(),
                request,
                specialist_runs,
                synthesis,
                judge,
            )
            if corrected_synthesis is not None:
                synthesis = corrected_synthesis
                judge = self._run_judge(
                    self._judge_model_factory(),
                    request,
                    specialist_runs,
                    synthesis,
                )
                judge_attempts.append(judge)
                correction["rejudge_disposition"] = judge["disposition"]
                yield TargetAssessmentProgress(
                    team_member="quality_judge",
                    status="completed",
                    summary="The independent judge reviewed the corrected assessment.",
                    detail={"disposition": judge["disposition"]},
                )
        status = "completed" if judge["disposition"] == "pass" else "quality_blocked"

        yield TargetAssessmentResult(
            status=status,
            specialist_runs=tuple(specialist_runs),
            synthesis=synthesis,
            judge=judge,
            correction=correction,
            error=None,
            execution_policy=target_assessment_execution_policy(),
            proposed_edits=tuple(edits),
            execution_metrics=_target_execution_metrics(
                request,
                model_attempts,
                judge_attempts,
                correction,
                (time.perf_counter() - drive_started) * 1000,
                status,
            ),
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

        completed_personas = {
            str(run.get("persona_id") or "") for run in specialist_runs
        }
        data = {
            "target_job": asdict(request.target_job),
            "candidate_profile": asdict(request.candidate_profile),
            "role_success_profile": asdict(request.role_profile),
            "specialist_runs": specialist_runs,
            "failures": [
                {"persona_id": pack.persona_id, "failure_type": "no_submission"}
                for pack in self._registry.personas
                if pack.persona_id not in completed_personas
            ],
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
            attributes={
                "trace_key": request.trace_key,
                "logical_run_id": request.trace_key,
                "stage": "target_assessment_judge",
            },
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

    def _correct_synthesis(
        self,
        model,
        request: TargetAssessmentRequest,
        specialist_runs: list[dict],
        synthesis: str,
        judge: dict,
    ) -> tuple[str | None, dict]:
        from ..prompts.target_assessment import TARGET_SYNTHESIS_CORRECTION_SYSTEM_PROMPT

        data = {
            "target_job": asdict(request.target_job),
            "candidate_profile": asdict(request.candidate_profile),
            "role_success_profile": asdict(request.role_profile),
            "specialist_runs": specialist_runs,
            "original_synthesis": synthesis,
            "judge_findings": judge,
        }
        last_failure = ""
        for attempt in range(1, config.RECRUITMENT_SYNTHESIS_VALIDATION_ATTEMPTS + 1):
            payload, failure, input_tokens, output_tokens, model_name = invoke_structured(
                model,
                SYNTHESIS_CORRECTION_TOOL,
                TARGET_SYNTHESIS_CORRECTION_SYSTEM_PROMPT,
                "target_assessment_correction_data",
                data,
                telemetry=self._telemetry,
                operation="open_agent_assessment.synthesis_correction_attempt",
                attempt=attempt,
                max_attempts=config.RECRUITMENT_SYNTHESIS_VALIDATION_ATTEMPTS,
                attributes={
                    "trace_key": request.trace_key,
                    "logical_run_id": request.trace_key,
                    "stage": "target_assessment_correction",
                },
            )
            if payload is not None:
                return str(payload["synthesis"]), {
                    "attempted": True,
                    "status": "completed",
                    "attempt_count": attempt,
                    "model_name": model_name,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "trigger_disposition": "revise",
                }
            last_failure = failure
        return None, {
            "attempted": True,
            "status": "failed",
            "attempt_count": config.RECRUITMENT_SYNTHESIS_VALIDATION_ATTEMPTS,
            "failure": last_failure,
            "trigger_disposition": "revise",
        }
