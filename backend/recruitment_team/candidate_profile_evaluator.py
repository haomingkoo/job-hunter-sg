"""Independent, evidence-cited evaluation of Candidate Evidence Profile quality."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from typing import Any, Callable, Literal, Protocol

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field, ValidationError

import config
from prompt_safety import xml_data_block

from .candidate_profile import CandidateEvidenceProfile
from .prompts.candidate_profile_evaluator import (
    CANDIDATE_PROFILE_EVALUATOR_PROMPT_VERSION,
    CANDIDATE_PROFILE_EVALUATOR_SYSTEM_PROMPT,
)
from .telemetry import OpenTelemetryRecorder, RecruitmentTelemetry


QualityLabel = Literal[
    "supported",
    "partially_supported",
    "unsupported",
    "misclassified",
    "duplicated",
]


@dataclass(frozen=True)
class CandidateProfileFieldEvaluation:
    field_id: str
    label: QualityLabel
    strengths: tuple[str, ...]
    weaknesses: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    score: int
    score_reason: str


@dataclass(frozen=True)
class CandidateProfileEvaluation:
    evaluation_version: str
    profile_version: str
    field_evaluations: tuple[CandidateProfileFieldEvaluation, ...]
    strengths: tuple[str, ...]
    weaknesses: tuple[str, ...]
    score: int
    score_reason: str


@dataclass(frozen=True)
class CandidateProfileEvaluationRun:
    evaluation: CandidateProfileEvaluation
    model_name: str
    attempt_count: int
    input_tokens: int | None = None
    output_tokens: int | None = None
    validation_codes: tuple[str, ...] = ()
    group_count: int = 0
    model_call_count: int = 0


class CandidateProfileEvaluationError(ValueError):
    def __init__(self, validation_code: str, rejected_submission: dict | None):
        super().__init__(f"candidate profile evaluation failed: {validation_code}")
        self.validation_code = validation_code
        self.rejected_submission = rejected_submission


class CandidateProfileEvaluationTransportError(RuntimeError):
    def __init__(self, stage: str, attempt: int, cause_type: str):
        super().__init__(f"candidate profile evaluation transport failed in {stage}: {cause_type}")
        self.stage = stage
        self.attempt = attempt
        self.cause_type = cause_type


class CandidateProfileEvaluator(Protocol):
    def evaluate(self, profile: CandidateEvidenceProfile) -> CandidateProfileEvaluationRun: ...


class _FieldEvaluationSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_id: str = Field(min_length=1)
    label: QualityLabel
    strengths: list[str] = Field(min_length=1)
    weaknesses: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(min_length=1)
    score: int = Field(ge=0, le=100)
    score_reason: str = Field(min_length=1)


class _FieldEvaluationBatchSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_evaluations: list[_FieldEvaluationSubmission]


class _DuplicateOverrideSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_id: str = Field(min_length=1)
    duplicate_of_field_id: str = Field(min_length=1)
    weakness: str = Field(min_length=1)
    score: int = Field(ge=0, le=100)
    score_reason: str = Field(min_length=1)


class _IntegrationSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    duplicate_overrides: list[_DuplicateOverrideSubmission] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    score: int = Field(ge=0, le=100)
    score_reason: str = Field(min_length=1)


def _submit_candidate_profile_field_evaluations(**payload: Any) -> dict:
    return _FieldEvaluationBatchSubmission(**payload).model_dump()


_SUBMIT_FIELD_EVALUATIONS_TOOL = StructuredTool.from_function(
    func=_submit_candidate_profile_field_evaluations,
    name="submit_candidate_profile_field_evaluations",
    description=(
        "Submit one independent evaluation of every supplied evidence-connected candidate-profile field, "
        "including cited strengths, weaknesses, extraction-quality score, and reason. "
        "This evaluates extraction quality, never the candidate or job fit."
    ),
    args_schema=_FieldEvaluationBatchSubmission,
)


def _submit_candidate_profile_evaluation_integration(**payload: Any) -> dict:
    return _IntegrationSubmission(**payload).model_dump()


_SUBMIT_INTEGRATION_TOOL = StructuredTool.from_function(
    func=_submit_candidate_profile_evaluation_integration,
    name="submit_candidate_profile_evaluation_integration",
    description=(
        "Integrate accepted local field evaluations, detect cross-group duplicate fields, "
        "and submit profile-level strengths, weaknesses, score, and score reason."
    ),
    args_schema=_IntegrationSubmission,
)


def _response_payload(
    response: AIMessage,
    tool: StructuredTool,
    schema: type[BaseModel],
) -> tuple[dict | None, dict, str]:
    rejected = {"content": response.content, "tool_calls": response.tool_calls}
    calls = [call for call in response.tool_calls if call.get("name") == tool.name]
    if len(response.tool_calls) != 1 or len(calls) != 1:
        return None, rejected, "tool_call:required_exactly_one"
    try:
        return schema(**(calls[0].get("args") or {})).model_dump(), rejected, ""
    except ValidationError:
        return None, rejected, "schema_validation"


def _validate_field_submission(
    payload: dict,
    expected_fields: tuple,
) -> tuple[dict | None, str]:
    expected_fields = {field.field_id: field for field in expected_fields}
    field_ids = [str(item["field_id"]).strip() for item in payload["field_evaluations"]]
    if len(field_ids) != len(set(field_ids)):
        return None, "field_coverage:duplicate"
    if set(field_ids) != set(expected_fields) or len(field_ids) != len(expected_fields):
        return None, "field_coverage:mismatch"
    for item in payload["field_evaluations"]:
        field_id = str(item["field_id"]).strip()
        evidence_ids = [str(value) for value in item["evidence_ids"]]
        if len(evidence_ids) != len(set(evidence_ids)):
            return None, f"field:{field_id}:duplicate_evidence_id"
        allowed_evidence_ids = set(expected_fields[field_id].resume_evidence_ids)
        if any(evidence_id not in allowed_evidence_ids for evidence_id in evidence_ids):
            return None, f"field:{field_id}:noncanonical_evidence_id"
        if not all(str(value).strip() for value in (*item["strengths"], *item["weaknesses"])):
            return None, f"field:{field_id}:empty_finding"
    return payload, ""


def _validate_integration_submission(
    payload: dict,
    profile: CandidateEvidenceProfile,
) -> tuple[dict | None, str]:
    field_ids = {field.field_id for field in profile.fields}
    overridden: set[str] = set()
    for item in payload["duplicate_overrides"]:
        field_id = str(item["field_id"]).strip()
        duplicate_of = str(item["duplicate_of_field_id"]).strip()
        if field_id not in field_ids or duplicate_of not in field_ids:
            return None, "duplicate_override:unknown_field"
        if field_id == duplicate_of:
            return None, f"duplicate_override:self:{field_id}"
        if field_id in overridden:
            return None, f"duplicate_override:duplicate:{field_id}"
        overridden.add(field_id)
    if not all(str(value).strip() for value in (*payload["strengths"], *payload["weaknesses"])):
        return None, "integration:empty_finding"
    return payload, ""


def _evaluation_groups(profile: CandidateEvidenceProfile) -> tuple[tuple, ...]:
    """Group fields by transitive shared evidence, preserving profile order."""

    remaining = list(profile.fields)
    groups: list[tuple] = []
    while remaining:
        group = [remaining.pop(0)]
        evidence_ids = set(group[0].resume_evidence_ids)
        changed = True
        while changed:
            changed = False
            for field in list(remaining):
                if evidence_ids.intersection(field.resume_evidence_ids):
                    group.append(field)
                    evidence_ids.update(field.resume_evidence_ids)
                    remaining.remove(field)
                    changed = True
        groups.append(tuple(group))
    return tuple(groups)


class LangChainCandidateProfileEvaluator:
    def __init__(
        self,
        model=None,
        *,
        telemetry: RecruitmentTelemetry | None = None,
    ):
        if model is None:
            from resume_agent.models import create_agent_model

            model = create_agent_model(
                timeout=config.RECRUITMENT_MODEL_HTTP_TIMEOUT_SECONDS,
                max_retries=config.RECRUITMENT_MODEL_TRANSPORT_RETRIES,
            )
        if not hasattr(model, "bind_tools"):
            raise TypeError("Candidate profile evaluator model must support bind_tools")
        self._model = model
        self._telemetry = telemetry or OpenTelemetryRecorder()

    def _invoke_stage(
        self,
        *,
        stage: str,
        messages: list[SystemMessage | HumanMessage],
        tool: StructuredTool,
        schema: type[BaseModel],
        validator: Callable[[dict], tuple[dict | None, str]],
        field_count: int,
        group_index: int | None,
    ) -> tuple[dict, int, int, int, str, tuple[str, ...]]:
        bound_model = self._model.bind_tools([tool], tool_choice=tool.name)
        failed_output: dict | None = None
        failure = ""
        validation_codes: list[str] = []
        total_input_tokens = 0
        total_output_tokens = 0
        model_name = str(
            getattr(self._model, "model_name", "") or getattr(self._model, "model", "") or type(self._model).__name__
        )
        for attempt in range(1, config.CANDIDATE_PROFILE_EVALUATION_ATTEMPTS + 1):
            request = list(messages)
            if failure:
                request.append(
                    HumanMessage(
                        content="\n\n".join(
                            (
                                "Correct the rejected evaluation stage without changing supplied evidence.",
                                xml_data_block("validation_code", failure),
                                xml_data_block(
                                    "failed_candidate_profile_evaluation",
                                    json.dumps(
                                        failed_output,
                                        ensure_ascii=False,
                                        separators=(",", ":"),
                                        default=str,
                                    ),
                                ),
                            )
                        )
                    )
                )
            with self._telemetry.operation(
                "candidate_profile_evaluation.model_attempt",
                {
                    "stage": stage,
                    "attempt": attempt,
                    "max_attempts": config.CANDIDATE_PROFILE_EVALUATION_ATTEMPTS,
                    "prompt_version": CANDIDATE_PROFILE_EVALUATOR_PROMPT_VERSION,
                    "configured_timeout_seconds": config.RECRUITMENT_MODEL_HTTP_TIMEOUT_SECONDS,
                    "transport_retries": config.RECRUITMENT_MODEL_TRANSPORT_RETRIES,
                    "field_count": field_count,
                    "group_index": group_index if group_index is not None else -1,
                },
            ) as model_span:
                try:
                    response = bound_model.invoke(request)
                except Exception as error:
                    model_span.set_attribute("status", "error")
                    model_span.set_attribute("error_type", type(error).__name__)
                    raise CandidateProfileEvaluationTransportError(
                        stage,
                        attempt,
                        type(error).__name__,
                    ) from error
                usage = getattr(response, "usage_metadata", None) or {}
                response_model_name = getattr(response, "response_metadata", {}).get("model_name")
                if response_model_name:
                    model_name = str(response_model_name)
                input_tokens = int(usage.get("input_tokens") or 0)
                output_tokens = int(usage.get("output_tokens") or 0)
                total_input_tokens += input_tokens
                total_output_tokens += output_tokens
                model_span.set_attribute("model", model_name)
                model_span.set_attribute("input_tokens", input_tokens)
                model_span.set_attribute("output_tokens", output_tokens)
                model_span.set_attribute("status", "success")
            with self._telemetry.operation(
                "candidate_profile_evaluation.validation",
                {
                    "stage": stage,
                    "attempt": attempt,
                    "field_count": field_count,
                    "group_index": group_index if group_index is not None else -1,
                },
            ) as validation_span:
                payload, failed_output, failure = _response_payload(response, tool, schema)
                if payload is not None:
                    payload, failure = validator(payload)
                validation_span.set_attribute("validation_code", failure)
                validation_span.set_attribute("accepted", payload is not None)
                validation_span.set_attribute(
                    "retry_triggered",
                    payload is None and attempt < config.CANDIDATE_PROFILE_EVALUATION_ATTEMPTS,
                )
            if payload is not None:
                return (
                    payload,
                    attempt,
                    total_input_tokens,
                    total_output_tokens,
                    model_name,
                    tuple(validation_codes),
                )
            validation_codes.append(failure)
        raise CandidateProfileEvaluationError(failure, failed_output)

    def evaluate(self, profile: CandidateEvidenceProfile) -> CandidateProfileEvaluationRun:
        groups = _evaluation_groups(profile)
        field_payloads: list[dict] = []
        total_attempts = 0
        total_input_tokens = 0
        total_output_tokens = 0
        validation_codes: list[str] = []
        model_name = ""

        for group_index, group in enumerate(groups, start=1):
            group_evidence_ids = {evidence_id for field in group for evidence_id in field.resume_evidence_ids}
            group_data = {
                "stage": "local_field_evaluation",
                "profile_version": profile.profile_version,
                "fields": [asdict(field) for field in group],
                "evidence": [
                    asdict(item) for item in profile.cited_resume_evidence if item.evidence_id in group_evidence_ids
                ],
            }
            payload, attempts, input_tokens, output_tokens, stage_model, codes = self._invoke_stage(
                stage="local_field_evaluation",
                messages=[
                    SystemMessage(content=CANDIDATE_PROFILE_EVALUATOR_SYSTEM_PROMPT),
                    HumanMessage(
                        content=xml_data_block(
                            "candidate_profile_evaluation_group",
                            json.dumps(group_data, ensure_ascii=False, separators=(",", ":")),
                        )
                    ),
                ],
                tool=_SUBMIT_FIELD_EVALUATIONS_TOOL,
                schema=_FieldEvaluationBatchSubmission,
                validator=lambda value, expected=group: _validate_field_submission(
                    value,
                    expected,
                ),
                field_count=len(group),
                group_index=group_index,
            )
            field_payloads.extend(payload["field_evaluations"])
            total_attempts += attempts
            total_input_tokens += input_tokens
            total_output_tokens += output_tokens
            validation_codes.extend(f"group:{group_index}:{code}" for code in codes)
            model_name = stage_model

        local_evaluations_by_id = {item["field_id"]: item for item in field_payloads}
        ordered_local_evaluations = [local_evaluations_by_id[field.field_id] for field in profile.fields]
        integration_data = {
            "stage": "cross_profile_integration",
            "profile_version": profile.profile_version,
            "fields": [
                {
                    "field_id": field.field_id,
                    "category": field.category,
                    "statement": field.statement,
                    "evidence_ids": list(field.resume_evidence_ids),
                }
                for field in profile.fields
            ],
            "accepted_local_evaluations": ordered_local_evaluations,
        }
        integration, attempts, input_tokens, output_tokens, stage_model, codes = self._invoke_stage(
            stage="cross_profile_integration",
            messages=[
                SystemMessage(content=CANDIDATE_PROFILE_EVALUATOR_SYSTEM_PROMPT),
                HumanMessage(
                    content=xml_data_block(
                        "candidate_profile_evaluation_integration",
                        json.dumps(
                            integration_data,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                    )
                ),
            ],
            tool=_SUBMIT_INTEGRATION_TOOL,
            schema=_IntegrationSubmission,
            validator=lambda value: _validate_integration_submission(value, profile),
            field_count=len(profile.fields),
            group_index=None,
        )
        total_attempts += attempts
        total_input_tokens += input_tokens
        total_output_tokens += output_tokens
        validation_codes.extend(f"integration:{code}" for code in codes)
        model_name = stage_model

        evaluations = {
            item["field_id"]: CandidateProfileFieldEvaluation(
                field_id=item["field_id"],
                label=item["label"],
                strengths=tuple(item["strengths"]),
                weaknesses=tuple(item["weaknesses"]),
                evidence_ids=tuple(item["evidence_ids"]),
                score=int(item["score"]),
                score_reason=item["score_reason"],
            )
            for item in ordered_local_evaluations
        }
        for override in integration["duplicate_overrides"]:
            prior = evaluations[override["field_id"]]
            evaluations[override["field_id"]] = replace(
                prior,
                label="duplicated",
                weaknesses=(*prior.weaknesses, override["weakness"]),
                score=int(override["score"]),
                score_reason=override["score_reason"],
            )

        return CandidateProfileEvaluationRun(
            evaluation=CandidateProfileEvaluation(
                evaluation_version=CANDIDATE_PROFILE_EVALUATOR_PROMPT_VERSION,
                profile_version=profile.profile_version,
                field_evaluations=tuple(evaluations[field.field_id] for field in profile.fields),
                strengths=tuple(integration["strengths"]),
                weaknesses=tuple(integration["weaknesses"]),
                score=int(integration["score"]),
                score_reason=integration["score_reason"],
            ),
            model_name=model_name,
            attempt_count=total_attempts,
            input_tokens=total_input_tokens or None,
            output_tokens=total_output_tokens or None,
            validation_codes=tuple(validation_codes),
            group_count=len(groups),
            model_call_count=total_attempts,
        )
