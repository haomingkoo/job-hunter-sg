"""Native, bounded target assessment over immutable V3 artifacts."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from typing import Iterator, Literal

import config

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
from .persona_packs import PersonaPack, PersonaPackRegistry, load_persona_pack_registry
from .prompts.target_assessment import (
    TARGET_JUDGE_PROMPT_VERSION,
    TARGET_JUDGE_SYSTEM_PROMPT,
    TARGET_SPECIALIST_PROMPT_VERSION,
    TARGET_SPECIALIST_SYSTEM_PROMPT,
    TARGET_SYNTHESIS_PROMPT_VERSION,
    TARGET_SYNTHESIS_SYSTEM_PROMPT,
)
from .telemetry import OpenTelemetryRecorder, RecruitmentTelemetry


class NativeTargetAssessmentRunner:
    """Run isolated specialists, synthesis, and a fresh independent judge."""

    def __init__(
        self,
        model_factory=None,
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
        self._telemetry = telemetry or OpenTelemetryRecorder()
        self._registry = persona_registry or load_persona_pack_registry()

    def _run_specialist(self, pack: PersonaPack, request: TargetAssessmentRequest) -> dict:
        model = self._model_factory()
        total_input = 0
        total_output = 0
        validation_codes: list[str] = []
        failed_submission: dict | None = None
        model_name = "unknown"
        for attempt in range(1, config.RECRUITMENT_SPECIALIST_VALIDATION_ATTEMPTS + 1):
            data = {
                "prompt_version": TARGET_SPECIALIST_PROMPT_VERSION,
                "persona_pack_version": self._registry.pack_version,
                "persona": asdict(pack),
                "target_job": asdict(request.target_job),
                "role_success_profile": asdict(request.role_profile),
                "candidate_profile": asdict(request.candidate_profile),
            }
            if validation_codes:
                data["validation_feedback"] = {
                    "code": validation_codes[-1],
                    "failed_submission": failed_submission,
                }
            try:
                payload, failure, input_tokens, output_tokens, model_name = invoke_structured(
                    model,
                    SPECIALIST_TOOL,
                    TARGET_SPECIALIST_SYSTEM_PROMPT,
                    "target_specialist_data",
                    data,
                    telemetry=self._telemetry,
                    operation="target_assessment.specialist_attempt",
                    attempt=attempt,
                    max_attempts=config.RECRUITMENT_SPECIALIST_VALIDATION_ATTEMPTS,
                    attributes={
                        "persona_id": pack.persona_id,
                        "persona_pack_version": self._registry.pack_version,
                        "trace_key": request.trace_key,
                    },
                )
            except BaseException as error:
                return {
                    "persona_id": pack.persona_id,
                    "status": "failed",
                    "failure_type": "transport",
                    "error_type": type(error).__name__,
                    "attempt_count": attempt,
                    "validation_codes": validation_codes,
                    "input_tokens": total_input,
                    "output_tokens": total_output,
                    "alternative_approaches": ["Retry this specialist without discarding completed specialists."],
                }
            total_input += input_tokens
            total_output += output_tokens
            failed_submission = payload
            accepted, validation_failure = validate_specialist(payload, pack.persona_id, request)
            failure = failure or validation_failure
            if accepted is not None:
                return {
                    "persona_id": pack.persona_id,
                    "status": "completed",
                    "submission": accepted,
                    "model_name": model_name,
                    "attempt_count": attempt,
                    "validation_codes": validation_codes,
                    "input_tokens": total_input,
                    "output_tokens": total_output,
                }
            validation_codes.append(failure)
        return {
            "persona_id": pack.persona_id,
            "status": "failed",
            "failure_type": "validation",
            "attempt_count": config.RECRUITMENT_SPECIALIST_VALIDATION_ATTEMPTS,
            "validation_codes": validation_codes,
            "input_tokens": total_input,
            "output_tokens": total_output,
            "rejected_submission": failed_submission,
            "alternative_approaches": ["Review the rejected structured submission and validation codes."],
        }

    def _run_synthesis(
        self,
        request: TargetAssessmentRequest,
        specialist_runs: tuple[dict, ...],
        *,
        prior_synthesis: dict | None = None,
        judge: dict | None = None,
    ) -> tuple[dict, dict]:
        model = self._model_factory()
        data = {
            "prompt_version": TARGET_SYNTHESIS_PROMPT_VERSION,
            "target_job": asdict(request.target_job),
            "role_criteria": [asdict(item) for item in request.role_profile.criteria],
            "specialist_runs": list(specialist_runs),
        }
        if prior_synthesis is not None:
            data["rejected_synthesis"] = prior_synthesis
            data["judge_feedback"] = judge
        validation_codes: list[str] = []
        failed_submission = None
        total_input = 0
        total_output = 0
        for attempt in range(1, config.RECRUITMENT_SYNTHESIS_VALIDATION_ATTEMPTS + 1):
            attempt_data = dict(data)
            if validation_codes:
                attempt_data["validation_feedback"] = {
                    "code": validation_codes[-1],
                    "failed_submission": failed_submission,
                }
            payload, failure, input_tokens, output_tokens, model_name = invoke_structured(
                model,
                SYNTHESIS_TOOL,
                TARGET_SYNTHESIS_SYSTEM_PROMPT,
                "target_synthesis_data",
                attempt_data,
                telemetry=self._telemetry,
                operation="target_assessment.synthesis",
                attempt=attempt,
                max_attempts=config.RECRUITMENT_SYNTHESIS_VALIDATION_ATTEMPTS,
                attributes={
                    "trace_key": request.trace_key,
                    "specialist_completed": sum(run["status"] == "completed" for run in specialist_runs),
                    "specialist_failed": sum(run["status"] == "failed" for run in specialist_runs),
                    "correction": prior_synthesis is not None,
                },
            )
            total_input += input_tokens
            total_output += output_tokens
            failed_submission = payload
            accepted, validation_failure = validate_synthesis(payload, specialist_runs)
            failure = failure or validation_failure
            if accepted is not None:
                return accepted, {
                    "model_name": model_name,
                    "attempt_count": attempt,
                    "validation_codes": validation_codes,
                    "input_tokens": total_input,
                    "output_tokens": total_output,
                }
            validation_codes.append(failure)
        raise ValueError(f"target synthesis failed validation: {validation_codes[-1]}")

    def _run_judge(
        self,
        request: TargetAssessmentRequest,
        specialist_runs: tuple[dict, ...],
        synthesis: dict,
    ) -> dict:
        model = self._model_factory()
        validation_codes: list[str] = []
        failed_submission = None
        total_input = 0
        total_output = 0
        model_name = "unknown"
        for attempt in range(1, config.RECRUITMENT_JUDGE_VALIDATION_ATTEMPTS + 1):
            data = {
                "prompt_version": TARGET_JUDGE_PROMPT_VERSION,
                "target_job": asdict(request.target_job),
                "role_success_profile": asdict(request.role_profile),
                "candidate_profile": asdict(request.candidate_profile),
                "specialist_runs": list(specialist_runs),
                "synthesis": synthesis,
            }
            if validation_codes:
                data["validation_feedback"] = {
                    "code": validation_codes[-1],
                    "failed_submission": failed_submission,
                }
            payload, failure, input_tokens, output_tokens, model_name = invoke_structured(
                model,
                JUDGE_TOOL,
                TARGET_JUDGE_SYSTEM_PROMPT,
                "target_judge_data",
                data,
                telemetry=self._telemetry,
                operation="target_assessment.judge_attempt",
                attempt=attempt,
                max_attempts=config.RECRUITMENT_JUDGE_VALIDATION_ATTEMPTS,
                attributes={"trace_key": request.trace_key},
            )
            total_input += input_tokens
            total_output += output_tokens
            failed_submission = payload
            if payload is not None:
                return {
                    **payload,
                    "model_name": model_name,
                    "attempt_count": attempt,
                    "validation_codes": validation_codes,
                    "input_tokens": total_input,
                    "output_tokens": total_output,
                }
            validation_codes.append(failure)
        raise ValueError(f"target judge failed validation: {validation_codes[-1]}")

    def run(self, request: TargetAssessmentRequest) -> Iterator[TargetAssessmentUpdate]:
        policy = target_assessment_execution_policy()
        yield TargetAssessmentProgress(
            team_member="coordinator",
            status="running",
            summary="Running isolated target-assessment specialists.",
            detail={"phase": "specialists", "execution_policy": policy},
        )
        runs_by_persona: dict[str, dict] = {}
        worker_count = min(config.RECRUITMENT_SPECIALIST_MAX_CONCURRENCY, len(self._registry.personas))
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(self._run_specialist, pack, request): pack
                for pack in self._registry.personas
            }
            for future in as_completed(futures):
                pack = futures[future]
                run = future.result()
                runs_by_persona[pack.persona_id] = run
                completed = run["status"] == "completed"
                yield TargetAssessmentProgress(
                    team_member=pack.persona_id,
                    status="completed" if completed else "failed",
                    summary=(
                        f"{pack.display_name} completed."
                        if completed
                        else f"{pack.display_name} failed with preserved error context."
                    ),
                    detail={
                        "persona_id": pack.persona_id,
                        "status": run["status"],
                        "failure_type": run.get("failure_type"),
                        "attempt_count": run.get("attempt_count"),
                        "input_tokens": run.get("input_tokens"),
                        "output_tokens": run.get("output_tokens"),
                    },
                )
        specialist_runs = tuple(runs_by_persona[pack.persona_id] for pack in self._registry.personas)
        if not any(run["status"] == "completed" for run in specialist_runs):
            yield TargetAssessmentResult(
                status="failed",
                specialist_runs=specialist_runs,
                synthesis="",
                judge=None,
                correction=None,
                error={
                    "failure_type": "workflow",
                    "message": "No specialist produced an accepted assessment.",
                    "retryable": True,
                },
                execution_policy=policy,
            )
            return
        try:
            synthesis, synthesis_run = self._run_synthesis(request, specialist_runs)
            judge = self._run_judge(request, specialist_runs, synthesis)
            correction = None
            if (
                judge["disposition"] == "revise"
                and config.RECRUITMENT_MAX_SYNTHESIS_CORRECTIONS == 1
            ):
                revised, correction_run = self._run_synthesis(
                    request,
                    specialist_runs,
                    prior_synthesis=synthesis,
                    judge=judge,
                )
                correction = {
                    "attempted": True,
                    "original_synthesis": synthesis,
                    "revised_synthesis": revised,
                    **correction_run,
                }
                synthesis = revised
                judge = self._run_judge(request, specialist_runs, synthesis)
            status: Literal["completed", "quality_blocked", "failed"] = (
                "completed" if judge["disposition"] == "pass" else "quality_blocked"
            )
            yield TargetAssessmentProgress(
                team_member="quality_judge",
                status="completed",
                summary="Independent target-assessment quality judgment completed.",
                detail={
                    "disposition": judge["disposition"],
                    "score": judge["score"],
                    "confidence": judge["confidence"],
                    "attempt_count": judge["attempt_count"],
                },
            )
            yield TargetAssessmentResult(
                status=status,
                specialist_runs=specialist_runs,
                synthesis=render_synthesis(synthesis) if status == "completed" else "",
                judge=judge,
                correction=correction or {
                    "attempted": False,
                    "synthesis_run": synthesis_run,
                },
                error=(
                    None
                    if status == "completed"
                    else {
                        "failure_type": "quality",
                        "message": "The independent judge did not approve publication.",
                        "retryable": False,
                    }
                ),
                execution_policy=policy,
            )
        except BaseException as error:
            yield TargetAssessmentResult(
                status="failed",
                specialist_runs=specialist_runs,
                synthesis="",
                judge=None,
                correction=None,
                error={
                    "failure_type": "workflow",
                    "error_type": type(error).__name__,
                    "message": str(error),
                    "retryable": True,
                },
                execution_policy=policy,
            )


# Backward-compatible import name for the HTTP dependency; implementation is native V3.
ResumeAgentTargetAssessmentRunner = NativeTargetAssessmentRunner


class ScriptedTargetAssessmentRunner:
    def __init__(self, updates: list[TargetAssessmentUpdate]):
        self._updates = tuple(updates)
        self.call_count = 0

    def run(self, request: TargetAssessmentRequest) -> Iterator[TargetAssessmentUpdate]:
        self.call_count += 1
        yield from self._updates
