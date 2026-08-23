"""Independent target-assessment quality gate with explicit terminal outcomes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterator, Literal

import config

from ..assessment_contracts import (
    JUDGE_TOOL,
    SYNTHESIS_CORRECTION_TOOL,
    SynthesisCorrectionSubmission,
    TargetAssessmentProgress,
    TargetAssessmentRequest,
    invoke_structured,
    render_target_synthesis,
    JudgeSubmission,
    validate_target_synthesis,
    validate_judge_submission,
)
from ..persona_packs import PersonaPackRegistry
from ..prompts.target_assessment import (
    TARGET_JUDGE_SYSTEM_PROMPT,
    TARGET_SYNTHESIS_CORRECTION_SYSTEM_PROMPT,
)
from ..telemetry import RecruitmentTelemetry
from .evidence_view import assessment_evidence_view


@dataclass(frozen=True)
class QualityGateOutcome:
    status: Literal["completed", "quality_blocked", "failed"]
    synthesis: str
    synthesis_claims: tuple[dict, ...]
    judge: dict | None
    correction: dict | None
    attempts: tuple[dict, ...]
    error: dict | None = None


QualityGateUpdate = TargetAssessmentProgress | QualityGateOutcome


def _judge_validation_guidance(code: str) -> str:
    if code == "judge:speculative_claim":
        return (
            "Rewrite every narrative field using only output-quality language. Do not mention "
            "hiring probability, market competitiveness, candidate or resume screening outcomes, "
            "screen passes or failures, or parseability, even to say the synthesis avoided them."
        )
    if code == "judge:candidate_scoring_claim":
        return (
            "Remove every candidate fit, alignment, match, shortlist, or screening score. Numeric "
            "rubric and confidence fields may describe only the quality of the synthesis."
        )
    if code == "judge:protected_status":
        return "Remove every reference to protected or sensitive personal status."
    return "Return one complete judgment that corrects the named validation failure."


class TargetAssessmentQualityGate:
    """Judge, repair once when requested, and rejudge without synthetic verdicts."""

    def __init__(
        self,
        *,
        judge_model_factory,
        correction_model_factory,
        telemetry: RecruitmentTelemetry,
        persona_registry: PersonaPackRegistry,
    ) -> None:
        self._judge_model_factory = judge_model_factory
        self._correction_model_factory = correction_model_factory
        self._telemetry = telemetry
        self._registry = persona_registry

    def review(
        self,
        request: TargetAssessmentRequest,
        specialist_runs: list[dict],
        synthesis: str,
        synthesis_claims: list[dict] | None = None,
        *,
        renew_lease: Callable[[], None] | None = None,
    ) -> Iterator[QualityGateUpdate]:
        synthesis_claims = list(synthesis_claims or [])
        judge, judge_attempts, judge_failure = yield from self._judge(
            self._judge_model_factory(),
            request,
            specialist_runs,
            synthesis,
            renew_lease=renew_lease,
            phase="initial",
        )
        attempts = list(judge_attempts)
        if judge is None:
            yield self._failed_outcome(
                synthesis,
                attempts,
                stage="target_assessment_judge",
                error_type="TargetAssessmentJudgeUnavailable",
                validation_code=judge_failure,
            )
            return

        correction = None
        if judge["disposition"] == "revise" and config.RECRUITMENT_MAX_SYNTHESIS_CORRECTIONS == 1:
            initial_judge = judge
            corrected, corrected_claims, correction, correction_attempts, correction_failure = yield from self._correct(
                self._correction_model_factory(),
                request,
                specialist_runs,
                synthesis,
                judge,
                renew_lease=renew_lease,
            )
            attempts.extend(correction_attempts)
            if corrected is None:
                yield self._failed_outcome(
                    synthesis,
                    attempts,
                    stage="target_assessment_correction",
                    error_type="TargetAssessmentCorrectionUnavailable",
                    validation_code=correction_failure,
                    judge=judge,
                    correction=correction,
                )
                return
            synthesis = corrected
            synthesis_claims = corrected_claims
            judge, rejudge_attempts, rejudge_failure = yield from self._judge(
                self._judge_model_factory(),
                request,
                specialist_runs,
                synthesis,
                renew_lease=renew_lease,
                phase="corrected",
            )
            attempts.extend(rejudge_attempts)
            if judge is None:
                yield self._failed_outcome(
                    synthesis,
                    attempts,
                    stage="target_assessment_rejudge",
                    error_type="TargetAssessmentRejudgeUnavailable",
                    validation_code=rejudge_failure,
                    judge=initial_judge,
                    correction=correction,
                )
                return
            correction["rejudge_disposition"] = judge["disposition"]

        status = "completed" if judge["disposition"] == "pass" else "quality_blocked"
        if status == "quality_blocked":
            yield TargetAssessmentProgress(
                team_member="quality_judge",
                status="quality_blocked",
                summary="The independent judge held this assessment back from the candidate.",
                detail={
                    "stage": "judge",
                    "disposition": judge["disposition"],
                    "failure_type": "business",
                    "failure_code": "quality_gate_blocked",
                    "retryable": False,
                    "recovery_action": "operator_review",
                },
            )
        yield QualityGateOutcome(
            status=status,
            synthesis=synthesis,
            synthesis_claims=tuple(synthesis_claims),
            judge=judge,
            correction=correction,
            attempts=tuple(attempts),
        )

    def _judge(
        self,
        model,
        request: TargetAssessmentRequest,
        specialist_runs: list[dict],
        synthesis: str,
        *,
        renew_lease: Callable[[], None] | None,
        phase: str,
    ):
        stage = "target_assessment_rejudge" if phase == "corrected" else "target_assessment_judge"
        completed_personas = {str(run.get("persona_id") or "") for run in specialist_runs}
        data = {
            **assessment_evidence_view(request),
            "specialist_runs": specialist_runs,
            "failures": [
                {
                    "persona_id": pack.persona_id,
                    "failure_type": "validation",
                    "failure_code": "structured_output_invalid",
                }
                for pack in self._registry.personas
                if pack.persona_id not in completed_personas
            ],
            "synthesis": synthesis,
        }
        attempts: list[dict] = []
        last_failure = ""
        for attempt in range(1, config.AGENT_JUDGE_VALIDATION_ATTEMPTS + 1):
            yield TargetAssessmentProgress(
                team_member="quality_judge",
                status="running",
                summary=f"The independent judge started attempt {attempt}.",
                detail={
                    "stage": "judge",
                    "attempt": attempt,
                    "attempt_limit": config.AGENT_JUDGE_VALIDATION_ATTEMPTS,
                    "outcome": phase,
                },
            )
            if renew_lease is not None:
                renew_lease()
            payload, failure, input_tokens, output_tokens, model_name = invoke_structured(
                model,
                JUDGE_TOOL,
                TARGET_JUDGE_SYSTEM_PROMPT,
                "open_agent_judge_data",
                data,
                telemetry=self._telemetry,
                operation="open_agent_assessment.judge_attempt",
                attempt=attempt,
                max_attempts=config.AGENT_JUDGE_VALIDATION_ATTEMPTS,
                attributes={
                    "trace_key": request.trace_key,
                    "logical_run_id": request.trace_key,
                    "stage": stage,
                },
            )
            if renew_lease is not None:
                renew_lease()
            if payload is not None:
                judge_submission = JudgeSubmission.model_validate(payload)
                validation_codes = validate_judge_submission(judge_submission)
                if validation_codes:
                    payload = None
                    failure = validation_codes[0]
            accepted = payload is not None
            attempts.append({
                "attempt_id": f"{request.trace_key}:{stage}:{attempt}",
                "stage": stage,
                "team_member": "quality_judge",
                "model": model_name,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "attempt_count": 1,
                "attempt": attempt,
                "attempt_limit": config.AGENT_JUDGE_VALIDATION_ATTEMPTS,
                "status": "success" if accepted else "validation_failed",
                "validation_code": "" if accepted else failure,
            })
            if accepted:
                judge = {
                    **payload,
                    "model_name": model_name,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "attempt_count": attempt,
                }
                yield TargetAssessmentProgress(
                    team_member="quality_judge",
                    status="completed",
                    summary="The independent judge completed its structured review.",
                    detail={
                        "stage": "judge",
                        "attempt": attempt,
                        "attempt_count": attempt,
                        "attempt_limit": config.AGENT_JUDGE_VALIDATION_ATTEMPTS,
                        "disposition": judge["disposition"],
                        "outcome": phase,
                    },
                )
                return judge, attempts, ""
            last_failure = failure
            data["previous_validation_code"] = failure
            data["previous_validation_guidance"] = _judge_validation_guidance(failure)
            terminal = attempt == config.AGENT_JUDGE_VALIDATION_ATTEMPTS
            yield TargetAssessmentProgress(
                team_member="quality_judge",
                status="failed" if terminal else "running",
                summary=(
                    "The independent judge stopped after exhausting its accepted-review attempts."
                    if terminal
                    else f"Judge attempt {attempt} did not return an accepted review."
                ),
                detail={
                    "stage": "judge",
                    "attempt": attempt,
                    "attempt_limit": config.AGENT_JUDGE_VALIDATION_ATTEMPTS,
                    "failure_type": "validation",
                    "failure_code": "structured_output_invalid",
                    "validation_code": failure,
                    "retryable": not terminal,
                    "recovery_action": (
                        "retry_quality_judge"
                        if attempt < config.AGENT_JUDGE_VALIDATION_ATTEMPTS
                        else "start_new_logical_run"
                    ),
                },
            )
        return None, attempts, last_failure

    def _correct(
        self,
        model,
        request: TargetAssessmentRequest,
        specialist_runs: list[dict],
        synthesis: str,
        judge: dict,
        *,
        renew_lease: Callable[[], None] | None,
    ):
        data = {
            **assessment_evidence_view(request),
            "specialist_runs": specialist_runs,
            "original_synthesis": synthesis,
            "judge_findings": judge,
        }
        attempts: list[dict] = []
        last_failure = ""
        for attempt in range(1, config.RECRUITMENT_SYNTHESIS_VALIDATION_ATTEMPTS + 1):
            yield TargetAssessmentProgress(
                team_member="coordinator",
                status="running",
                summary=f"The coordinator started correction attempt {attempt}.",
                detail={
                    "stage": "synthesis_correction",
                    "attempt": attempt,
                    "attempt_limit": config.RECRUITMENT_SYNTHESIS_VALIDATION_ATTEMPTS,
                },
            )
            if renew_lease is not None:
                renew_lease()
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
            if renew_lease is not None:
                renew_lease()
            corrected_submission = None
            if payload is not None:
                try:
                    corrected_submission = SynthesisCorrectionSubmission.model_validate(payload)
                except Exception:
                    payload = None
                    failure = "schema_validation"
                if corrected_submission is not None:
                    validation_codes = validate_target_synthesis(request, corrected_submission)
                    if validation_codes:
                        payload = None
                        failure = validation_codes[0]
            accepted = payload is not None
            attempts.append({
                "attempt_id": f"{request.trace_key}:target_assessment_correction:{attempt}",
                "stage": "target_assessment_correction",
                "team_member": "coordinator",
                "model": model_name,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "attempt_count": 1,
                "attempt": attempt,
                "attempt_limit": config.RECRUITMENT_SYNTHESIS_VALIDATION_ATTEMPTS,
                "status": "success" if accepted else "validation_failed",
                "validation_code": "" if accepted else failure,
            })
            if accepted:
                correction = {
                    "attempted": True,
                    "status": "completed",
                    "attempt_count": attempt,
                    "model_name": model_name,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "trigger_disposition": "revise",
                }
                yield TargetAssessmentProgress(
                    team_member="coordinator",
                    status="completed",
                    summary="The coordinator completed the evidence-grounded correction.",
                    detail={
                        "stage": "synthesis_correction",
                        "attempt": attempt,
                        "attempt_count": attempt,
                        "attempt_limit": config.RECRUITMENT_SYNTHESIS_VALIDATION_ATTEMPTS,
                    },
                )
                return (
                    render_target_synthesis(corrected_submission),
                    [claim.model_dump() for claim in corrected_submission.claims],
                    correction,
                    attempts,
                    "",
                )
            last_failure = failure
            terminal = attempt == config.RECRUITMENT_SYNTHESIS_VALIDATION_ATTEMPTS
            yield TargetAssessmentProgress(
                team_member="coordinator",
                status="failed" if terminal else "running",
                summary=(
                    "The coordinator stopped after exhausting its synthesis-correction attempts."
                    if terminal
                    else f"Correction attempt {attempt} did not return an accepted synthesis."
                ),
                detail={
                    "stage": "synthesis_correction",
                    "attempt": attempt,
                    "attempt_limit": config.RECRUITMENT_SYNTHESIS_VALIDATION_ATTEMPTS,
                    "failure_type": "validation",
                    "failure_code": "structured_output_invalid",
                    "validation_code": failure,
                    "retryable": not terminal,
                    "recovery_action": (
                        "retry_synthesis_correction"
                        if attempt < config.RECRUITMENT_SYNTHESIS_VALIDATION_ATTEMPTS
                        else "start_new_logical_run"
                    ),
                },
            )
        correction = {
            "attempted": True,
            "status": "failed",
            "attempt_count": config.RECRUITMENT_SYNTHESIS_VALIDATION_ATTEMPTS,
            "failure": last_failure,
            "trigger_disposition": "revise",
        }
        return None, [], correction, attempts, last_failure

    @staticmethod
    def _failed_outcome(
        synthesis: str,
        attempts: list[dict],
        *,
        stage: str,
        error_type: str,
        validation_code: str,
        judge: dict | None = None,
        correction: dict | None = None,
    ) -> QualityGateOutcome:
        return QualityGateOutcome(
            status="failed",
            synthesis=synthesis,
            synthesis_claims=(),
            judge=judge,
            correction=correction,
            attempts=tuple(attempts),
            error={
                "failure_type": "business",
                "failure_code": "attempt_budget_exhausted",
                "error_type": error_type,
                "retryable": False,
                "recovery_action": "start_new_logical_run",
                "stage": stage,
                "validation_codes": [validation_code] if validation_code else [],
            },
        )
