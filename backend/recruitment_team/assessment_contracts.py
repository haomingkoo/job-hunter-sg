"""Shared request/result types and the specialist/judge contracts for target
assessment, consumed by the open-agent runner. The mandatory judge is the
single validation gate over whatever the open orchestrator produces; there is
no separate synthesis-submission or per-specialist ID-cross-check step (those
belonged to the retired, fully-bounded native runner)."""

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
from .persona_packs import load_persona_pack_registry
from .prompts.target_assessment import (
    TARGET_JUDGE_PROMPT_VERSION,
    TARGET_SPECIALIST_PROMPT_VERSION,
    TARGET_SYNTHESIS_PROMPT_VERSION,
)
from .role_success import RoleSuccessProfile
from .telemetry import RecruitmentTelemetry


TARGET_ASSESSMENT_POLICY_VERSION = "native-target-assessment-v2"


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
    status: Literal["running", "completed", "failed", "paused"]
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
    proposed_edits: tuple[dict, ...] = ()


TargetAssessmentUpdate = TargetAssessmentProgress | TargetAssessmentResult


class TargetAssessmentRunner(Protocol):
    def run(self, request: TargetAssessmentRequest) -> Iterator[TargetAssessmentUpdate]: ...


class ScriptedTargetAssessmentRunner:
    def __init__(self, updates: list[TargetAssessmentUpdate]):
        self._updates = tuple(updates)
        self.call_count = 0

    def run(self, request: TargetAssessmentRequest) -> Iterator[TargetAssessmentUpdate]:
        self.call_count += 1
        yield from self._updates


class SpecialistSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    persona_id: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    strengths: list[str]
    weaknesses: list[str]
    evidence_gaps: list[str]
    criterion_ids: list[str]
    candidate_profile_field_ids: list[str]
    resume_evidence_ids: list[str]
    score: int = Field(ge=0, le=100)
    score_reason: str = Field(min_length=1)


class Deduction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rubric: Literal[
        "evidence_grounding",
        "role_coverage",
        "decision_usefulness",
        "fairness_and_boundaries",
    ]
    reason: str = Field(min_length=1)
    points: int = Field(ge=0, le=100)


class RubricScores(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_grounding: int = Field(ge=0, le=100)
    role_coverage: int = Field(ge=0, le=100)
    decision_usefulness: int = Field(ge=0, le=100)
    fairness_and_boundaries: int = Field(ge=0, le=100)


class JudgeSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strengths: list[str]
    weaknesses: list[str]
    deductions: list[Deduction]
    evidence_gaps: list[str]
    rubric_scores: RubricScores
    score: int = Field(ge=0, le=100)
    score_reason: str = Field(min_length=1)
    confidence: int = Field(ge=0, le=100)
    confidence_reason: str = Field(min_length=1)
    disposition: Literal["pass", "revise", "block"]


def _dump_specialist(**payload: Any) -> dict:
    return SpecialistSubmission(**payload).model_dump()


def _dump_judge(**payload: Any) -> dict:
    return JudgeSubmission(**payload).model_dump()


SPECIALIST_TOOL = StructuredTool.from_function(
    func=_dump_specialist,
    name="submit_target_specialist_assessment",
    description=(
        "Submit this persona's complete bounded assessment with strengths, weaknesses, "
        "evidence gaps, raw evidence-support score, reason, and all provenance IDs."
    ),
    args_schema=SpecialistSubmission,
)
JUDGE_TOOL = StructuredTool.from_function(
    func=_dump_judge,
    name="submit_target_assessment_judgment",
    description=(
        "Submit the independent output-quality judgment with strengths, weaknesses, "
        "deductions, gaps, rubric scores, score reason, confidence basis, and disposition."
    ),
    args_schema=JudgeSubmission,
)


def target_assessment_execution_policy() -> dict:
    registry = load_persona_pack_registry()
    return {
        "policy_version": TARGET_ASSESSMENT_POLICY_VERSION,
        "persona_pack_version": registry.pack_version,
        "specialists": [pack.persona_id for pack in registry.personas],
        "specialist_validation_attempts": config.RECRUITMENT_SPECIALIST_VALIDATION_ATTEMPTS,
        "specialist_max_concurrency": config.RECRUITMENT_SPECIALIST_MAX_CONCURRENCY,
        "judge_validation_attempts": config.RECRUITMENT_JUDGE_VALIDATION_ATTEMPTS,
        "synthesis_validation_attempts": config.RECRUITMENT_SYNTHESIS_VALIDATION_ATTEMPTS,
        "maximum_synthesis_corrections": config.RECRUITMENT_MAX_SYNTHESIS_CORRECTIONS,
        "model_timeout_seconds": config.RECRUITMENT_MODEL_HTTP_TIMEOUT_SECONDS,
        "transport_retries": config.RECRUITMENT_MODEL_TRANSPORT_RETRIES,
        "specialist_prompt_version": TARGET_SPECIALIST_PROMPT_VERSION,
        "synthesis_prompt_version": TARGET_SYNTHESIS_PROMPT_VERSION,
        "judge_prompt_version": TARGET_JUDGE_PROMPT_VERSION,
        "fallback_model": None,
        "raw_resume_passed_to_assessment": False,
        "content_truncation": False,
    }


def tool_payload(response: AIMessage, tool: StructuredTool, schema: type[BaseModel]) -> tuple[dict | None, str]:
    calls = [call for call in response.tool_calls if call.get("name") == tool.name]
    if len(response.tool_calls) != 1 or len(calls) != 1:
        return None, "tool_call:required_exactly_one"
    try:
        return schema(**(calls[0].get("args") or {})).model_dump(), ""
    except ValidationError:
        return None, "schema_validation"


def usage_from_response(response: AIMessage) -> tuple[int, int, str]:
    usage = getattr(response, "usage_metadata", None) or {}
    model_name = str(getattr(response, "response_metadata", {}).get("model_name") or "unknown")
    return int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0), model_name


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
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(
            content=xml_data_block(
                data_name,
                json.dumps(data, ensure_ascii=False, separators=(",", ":")),
            )
        ),
    ]
    with telemetry.operation(
        operation,
        {
            **attributes,
            "attempt": attempt,
            "max_attempts": max_attempts,
            "configured_timeout_seconds": config.RECRUITMENT_MODEL_HTTP_TIMEOUT_SECONDS,
            "transport_retries": config.RECRUITMENT_MODEL_TRANSPORT_RETRIES,
        },
    ) as span:
        response = model.bind_tools([tool], tool_choice=tool.name).invoke(messages)
        input_tokens, output_tokens, model_name = usage_from_response(response)
        span.set_attribute("input_tokens", input_tokens)
        span.set_attribute("output_tokens", output_tokens)
        span.set_attribute("model", model_name)
        payload, failure = tool_payload(response, tool, tool.args_schema)
        span.set_attribute("validation_code", failure)
        span.set_attribute("accepted", payload is not None)
    return payload, failure, input_tokens, output_tokens, model_name
