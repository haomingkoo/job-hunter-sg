"""Independent semantic assessment of resume evidence against role criteria."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Protocol

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field

import config
from prompt_safety import unescape_xml_data, xml_data_block
from validation_gates import _extract_numbers

from .candidate_profile import CandidateProfileField
from .prompts.role_evidence_assessor import (
    ROLE_EVIDENCE_ASSESSOR_PROMPT_VERSION,
    ROLE_EVIDENCE_ASSESSOR_SYSTEM_PROMPT,
)
from .role_success import (
    Alignment,
    CandidateEvidenceMatch,
    ResumeEvidenceRecord,
    RoleCriterion,
    RoleSource,
)
from .telemetry import OpenTelemetryRecorder, RecruitmentTelemetry


@dataclass(frozen=True)
class RoleEvidenceAssessmentRequest:
    criteria: tuple[RoleCriterion, ...]
    resume_blocks: tuple[ResumeEvidenceRecord, ...]
    role_sources: tuple[RoleSource, ...]
    candidate_profile_fields: tuple[CandidateProfileField, ...]
    proposed_evidence: tuple[CandidateEvidenceMatch, ...] = ()


@dataclass(frozen=True)
class RoleEvidenceJudgment:
    criterion_id: str
    alignment: Alignment
    resume_evidence_ids: tuple[str, ...]
    candidate_profile_field_ids: tuple[str, ...]
    supported_strength: str
    remaining_gap: str
    evidence_support_score: int
    score_reason: str


@dataclass(frozen=True)
class RoleEvidenceAssessmentRun:
    judgments: tuple[RoleEvidenceJudgment, ...]
    prompt_version: str
    model_name: str
    attempt_count: int
    input_tokens: int | None = None
    output_tokens: int | None = None
    validation_codes: tuple[str, ...] = ()


class RoleEvidenceAssessmentError(ValueError):
    def __init__(self, validation_code: str, rejected_submission: dict | None):
        super().__init__(f"role evidence assessment failed: {validation_code}")
        self.validation_code = validation_code
        self.rejected_submission = rejected_submission


class RoleEvidenceAssessor(Protocol):
    def assess(self, request: RoleEvidenceAssessmentRequest) -> RoleEvidenceAssessmentRun: ...


class _JudgmentSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criterion_id: str
    alignment: Alignment
    resume_evidence_ids: list[str] = Field(default_factory=list)
    candidate_profile_field_ids: list[str] = Field(default_factory=list)
    supported_strength: str = Field(min_length=1)
    remaining_gap: str = Field(min_length=1)
    evidence_support_score: int = Field(ge=0, le=100)
    score_reason: str = Field(min_length=1)


class _AssessmentSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    judgments: list[_JudgmentSubmission]


class _CorrectionSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    judgment: _JudgmentSubmission


def _submit_role_evidence_assessment(**payload: Any) -> dict:
    return _AssessmentSubmission(**payload).model_dump()


_SUBMIT_ASSESSMENT_TOOL = StructuredTool.from_function(
    func=_submit_role_evidence_assessment,
    name="submit_role_evidence_assessment",
    description=(
        "Submit the complete independent resume-evidence assessment for the supplied "
        "role definition. Return exactly one judgment per criterion with alignment, "
        "candidate-profile field IDs, canonical resume block IDs, supported strength, remaining gap, raw evidence-"
        "support score, and score reason. Use only after reviewing every supplied "
        "criterion and resume block. Do not define new criteria, infer preferences, "
        "or use this full-assessment tool for a single rejected judgment; use the "
        "correction tool for that."
    ),
    args_schema=_AssessmentSubmission,
)


def _submit_role_evidence_correction(**payload: Any) -> dict:
    return _CorrectionSubmission(**payload).model_dump()


_SUBMIT_CORRECTION_TOOL = StructuredTool.from_function(
    func=_submit_role_evidence_correction,
    name="submit_role_evidence_correction",
    description=(
        "Correct exactly the one supplied criterion judgment. Return no other "
        "judgments and do not alter any criterion definition or evidence block."
    ),
    args_schema=_CorrectionSubmission,
)


_QUOTED_PHRASE_RE = re.compile(r'["“]([^"”]+)["”]|(?<!\w)\'([^\'\n]+)\'(?!\w)')
_POSITIVE_ALIGNMENTS = {"direct", "partial", "transferable"}


def _normalized_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _tool_payload(response: AIMessage) -> tuple[dict | None, str]:
    call = next((call for call in response.tool_calls if call.get("name") == _SUBMIT_ASSESSMENT_TOOL.name), None)
    if call is None:
        finish_reason = str(response.response_metadata.get("finish_reason") or "")
        return None, "output_truncated:length" if finish_reason == "length" else "missing_tool_call"
    try:
        return _SUBMIT_ASSESSMENT_TOOL.invoke(call.get("args") or {}), ""
    except Exception:
        return None, "schema_validation"


def _correction_payload(response: AIMessage) -> tuple[dict | None, str]:
    call = next(
        (call for call in response.tool_calls if call.get("name") == _SUBMIT_CORRECTION_TOOL.name),
        None,
    )
    if call is None:
        return None, "missing_correction_tool_call"
    try:
        return _SUBMIT_CORRECTION_TOOL.invoke(call.get("args") or {}), ""
    except Exception:
        return None, "schema_validation"


def _target_criterion_id(failure: str, criteria: tuple[RoleCriterion, ...]) -> str | None:
    if not failure.startswith(
        (
            "literal_quote:unsupported:",
            "numeric_claim:unsupported:",
            "resume_evidence_ids:",
            "candidate_profile_field_ids:",
        )
    ):
        return None
    matches = [criterion.criterion_id for criterion in criteria if failure.endswith(f":{criterion.criterion_id}")]
    return matches[0] if len(matches) == 1 else None


def _csv_items_from_validation_code(failure: str, prefix: str) -> tuple[str, ...]:
    """Extract the comma-separated items from a "<prefix><items>:<criterion_id>"
    validation code, shared by every failure shaped this way (an id list or a
    number list ahead of the trailing criterion_id)."""
    if not failure.startswith(prefix):
        return ()
    remainder = failure[len(prefix) :]
    items_part, _, _criterion_id = remainder.rpartition(":")
    return tuple(item for item in items_part.split(",") if item)


def _orphaned_evidence_ids(failure: str) -> tuple[str, ...]:
    """Extract the orphaned resume-evidence IDs from an
    "candidate_profile_field_ids:evidence_mismatch:<ids>:<criterion_id>" code."""
    return _csv_items_from_validation_code(failure, "candidate_profile_field_ids:evidence_mismatch:")


def _unsupported_numbers(failure: str) -> tuple[str, ...]:
    """Extract the unsupported numbers from a "numeric_claim:unsupported:<numbers>:<criterion_id>" code."""
    return _csv_items_from_validation_code(failure, "numeric_claim:unsupported:")


def _targeted_correction_data(
    request: RoleEvidenceAssessmentRequest,
    failed_payload: dict,
    criterion_id: str,
    failure: str,
) -> dict:
    criterion = next(criterion for criterion in request.criteria if criterion.criterion_id == criterion_id)
    failed_judgment = next(
        judgment
        for judgment in failed_payload["judgments"]
        if str(judgment.get("criterion_id") or "").strip() == criterion_id
    )
    data = {
        "prompt_version": ROLE_EVIDENCE_ASSESSOR_PROMPT_VERSION,
        "validation_code": failure,
        "criterion": asdict(criterion),
        "candidate_profile_fields": [asdict(field) for field in request.candidate_profile_fields],
        "resume_blocks": [asdict(block) for block in request.resume_blocks],
        "failed_judgment": failed_judgment,
    }
    orphaned_ids = _orphaned_evidence_ids(failure)
    if orphaned_ids:
        # An evidence_mismatch failure means the model cited a resume block
        # without also citing a candidate_profile_field_id that contains it.
        # Finding which field(s) actually contain that block is a trivial,
        # deterministic lookup here -- but a hard search for the model across
        # 100+ hash-suffixed field IDs, which is why it was observed
        # resubmitting the identical rejected judgment unchanged rather than
        # attempting a fix. Handing over the exact valid field IDs removes
        # that search entirely.
        data["orphaned_evidence_valid_field_ids"] = {
            evidence_id: sorted(
                field.field_id
                for field in request.candidate_profile_fields
                if evidence_id in field.resume_evidence_ids
            )
            for evidence_id in orphaned_ids
        }
    unsupported_numbers = _unsupported_numbers(failure)
    if unsupported_numbers:
        # A numeric_claim failure often means the narrative states a computed
        # value (a duration, a difference, a fraction) derived from real,
        # grounded numbers rather than an invented fact -- e.g. "2 years
        # short" when the criterion requires 10 and the evidence shows 8.
        # That computed value still doesn't appear verbatim in the grounding,
        # so it still fails this check; "remove or replace" is genuinely
        # ambiguous here (replace with what?), and the model was observed
        # resubmitting the identical narrative unchanged rather than guessing.
        # There is no safe way to keep a non-grounded computed number, so the
        # correction data says so explicitly.
        data["unsupported_numbers"] = list(unsupported_numbers)
    return data


def _merge_correction(failed_payload: dict, correction: dict, criterion_id: str) -> dict:
    return {
        "judgments": [
            correction["judgment"] if item["criterion_id"].strip() == criterion_id else item
            for item in failed_payload["judgments"]
        ]
    }


def _validate_submission(
    payload: dict | None,
    request: RoleEvidenceAssessmentRequest,
) -> tuple[dict | None, str]:
    if not isinstance(payload, dict) or not isinstance(payload.get("judgments"), list):
        return None, "invalid_submission"

    expected_ids = [criterion.criterion_id for criterion in request.criteria]
    submitted_ids = [str(item.get("criterion_id") or "").strip() for item in payload["judgments"]]
    if len(submitted_ids) != len(set(submitted_ids)):
        return None, "criterion_coverage:duplicate_ids"
    if set(submitted_ids) != set(expected_ids) or len(submitted_ids) != len(expected_ids):
        return None, "criterion_coverage:mismatch"

    blocks = {block.evidence_id: block.text for block in request.resume_blocks}
    profile_fields = {field.field_id: field for field in request.candidate_profile_fields}
    criteria = {criterion.criterion_id: criterion for criterion in request.criteria}
    for judgment in payload["judgments"]:
        criterion_id = str(judgment["criterion_id"]).strip()
        cited_ids = judgment["resume_evidence_ids"]
        profile_field_ids = judgment["candidate_profile_field_ids"]
        if len(profile_field_ids) != len(set(profile_field_ids)):
            return None, f"candidate_profile_field_ids:duplicate:{criterion_id}"
        unknown_field_ids = sorted(field_id for field_id in profile_field_ids if field_id not in profile_fields)
        if unknown_field_ids:
            return None, f"candidate_profile_field_ids:unknown:{','.join(unknown_field_ids)}:{criterion_id}"
        if len(cited_ids) != len(set(cited_ids)):
            return None, f"resume_evidence_ids:duplicate:{criterion_id}"
        unknown_evidence_ids = sorted(evidence_id for evidence_id in cited_ids if evidence_id not in blocks)
        if unknown_evidence_ids:
            return None, f"resume_evidence_ids:unknown:{','.join(unknown_evidence_ids)}:{criterion_id}"
        if judgment["alignment"] in _POSITIVE_ALIGNMENTS and not cited_ids:
            return None, f"resume_evidence_ids:missing_for_positive:{criterion_id}"
        if judgment["alignment"] in _POSITIVE_ALIGNMENTS and not profile_field_ids:
            return None, f"candidate_profile_field_ids:missing_for_positive:{criterion_id}"
        supported_profile_evidence_ids = {
            evidence_id
            for field_id in profile_field_ids
            for evidence_id in profile_fields[field_id].resume_evidence_ids
        }
        orphaned_evidence_ids = sorted(
            evidence_id for evidence_id in cited_ids if evidence_id not in supported_profile_evidence_ids
        )
        if orphaned_evidence_ids:
            return (
                None,
                f"candidate_profile_field_ids:evidence_mismatch:{','.join(orphaned_evidence_ids)}:{criterion_id}",
            )

        criterion = criteria[criterion_id]
        grounding = "\n".join(
            (
                criterion.statement,
                *(citation.relevant_excerpt for citation in criterion.source_citations),
                *(blocks[evidence_id] for evidence_id in cited_ids),
            )
        )
        narrative = "\n".join(
            (
                judgment["supported_strength"],
                judgment["remaining_gap"],
                judgment["score_reason"],
            )
        )
        quoted_phrases = [next(value for value in match if value) for match in _QUOTED_PHRASE_RE.findall(narrative)]
        unsupported_quotes = [
            phrase for phrase in quoted_phrases if _normalized_text(unescape_xml_data(phrase)) not in _normalized_text(grounding)
        ]
        if unsupported_quotes:
            return None, f"literal_quote:unsupported:{unsupported_quotes[0][:80]!r}:{criterion_id}"
        unsupported_numbers = sorted(_extract_numbers(narrative) - _extract_numbers(grounding))
        if unsupported_numbers:
            return None, f"numeric_claim:unsupported:{','.join(unsupported_numbers)}:{criterion_id}"
    return payload, ""


class LangChainRoleEvidenceAssessor:
    """Assess all criteria with one model call and at most one correction retry."""

    def __init__(
        self,
        model=None,
        telemetry: RecruitmentTelemetry | None = None,
    ):
        if model is None:
            from resume_agent.models import create_agent_model

            model = create_agent_model(
                timeout=config.RECRUITMENT_MODEL_HTTP_TIMEOUT_SECONDS,
                max_retries=config.RECRUITMENT_MODEL_TRANSPORT_RETRIES,
            )
        if not hasattr(model, "bind_tools"):
            raise TypeError("Role evidence assessor model must support bind_tools")
        self._model = model
        self._telemetry = telemetry or OpenTelemetryRecorder()

    def assess(self, request: RoleEvidenceAssessmentRequest) -> RoleEvidenceAssessmentRun:
        original_evidence = {
            "prompt_version": ROLE_EVIDENCE_ASSESSOR_PROMPT_VERSION,
            "criteria": [asdict(item) for item in request.criteria],
            "resume_blocks": [asdict(item) for item in request.resume_blocks],
            "role_sources": [asdict(item) for item in request.role_sources],
            "candidate_profile_fields": [asdict(item) for item in request.candidate_profile_fields],
            "proposed_evidence": [asdict(item) for item in request.proposed_evidence],
        }
        messages = [
            SystemMessage(content=ROLE_EVIDENCE_ASSESSOR_SYSTEM_PROMPT),
            HumanMessage(
                content=xml_data_block(
                    "role_evidence_assessment_data",
                    json.dumps(original_evidence, ensure_ascii=False, separators=(",", ":")),
                )
            ),
        ]
        failure = ""
        failed_payload: dict | None = None
        validation_codes: list[str] = []
        total_input_tokens = 0
        total_output_tokens = 0
        for attempt in range(1, config.ROLE_EVIDENCE_VALIDATION_ATTEMPTS + 1):
            target_criterion_id = (
                _target_criterion_id(failure, request.criteria) if failure and failed_payload is not None else None
            )
            correction_scope = "single_criterion" if target_criterion_id else "full"
            tool = _SUBMIT_CORRECTION_TOOL if target_criterion_id else _SUBMIT_ASSESSMENT_TOOL
            if target_criterion_id:
                correction_data = _targeted_correction_data(
                    request,
                    failed_payload,
                    target_criterion_id,
                    failure,
                )
                call_messages = [
                    SystemMessage(content=ROLE_EVIDENCE_ASSESSOR_SYSTEM_PROMPT),
                    HumanMessage(
                        content="Correct only the supplied failed judgment. The validation_code names "
                        "the exact IDs, quoted phrase, or numbers that are unsupported where "
                        "applicable -- remove or replace exactly those, do not re-derive the "
                        "judgment from scratch. Resubmitting the failed_judgment unchanged will "
                        "fail again identically. If validation_code is an evidence_mismatch, "
                        "orphaned_evidence_valid_field_ids maps each unsupported resume_evidence_id "
                        "to the exact candidate_profile_field_ids that actually contain it -- for "
                        "each one, either add one of those exact field IDs to candidate_profile_field_ids, "
                        "or remove that resume_evidence_id from resume_evidence_ids if the field can't "
                        "also stay true to the criterion. If validation_code is a numeric_claim, "
                        "unsupported_numbers lists every number that must not appear anywhere in "
                        "supported_strength, remaining_gap, or score_reason -- including a computed "
                        "duration, difference, or fraction derived from real evidence, since it still "
                        "does not appear verbatim in the grounding. Describe that comparison in words "
                        "instead (e.g. \"a few years short\" rather than naming the computed gap), or "
                        "state only the underlying numbers that do appear in the grounding.\n\n"
                        + xml_data_block(
                            "role_evidence_correction_data",
                            json.dumps(correction_data, ensure_ascii=False, separators=(",", ":")),
                        )
                    ),
                ]
            else:
                call_messages = list(messages)
            if failure and not target_criterion_id:
                call_messages.append(
                    HumanMessage(
                        content="\n\n".join(
                            (
                                "Correct the rejected submission and resubmit every judgment.",
                                xml_data_block("validation_error_data", failure),
                                xml_data_block(
                                    "failed_assessment_data",
                                    json.dumps(failed_payload, ensure_ascii=False, separators=(",", ":")),
                                ),
                            )
                        )
                    )
                )
            with self._telemetry.operation(
                "role_evidence_assessment.model_attempt",
                {
                    "attempt": attempt,
                    "max_attempts": config.ROLE_EVIDENCE_VALIDATION_ATTEMPTS,
                    "prompt_version": ROLE_EVIDENCE_ASSESSOR_PROMPT_VERSION,
                    "configured_timeout_seconds": config.RECRUITMENT_MODEL_HTTP_TIMEOUT_SECONDS,
                    "transport_retries": config.RECRUITMENT_MODEL_TRANSPORT_RETRIES,
                    "correction_scope": correction_scope,
                },
            ) as attempt_span:
                try:
                    response = self._model.bind_tools(
                        [tool],
                        tool_choice=tool.name,
                    ).invoke(call_messages)
                except BaseException as error:
                    attempt_span.set_attribute("status", "error")
                    attempt_span.set_attribute("error_type", type(error).__name__)
                    raise
                usage = getattr(response, "usage_metadata", None) or {}
                model_name = str(
                    getattr(response, "response_metadata", {}).get("model_name") or type(self._model).__name__
                )
                attempt_span.set_attribute("model", model_name)
                if usage.get("input_tokens") is not None:
                    attempt_span.set_attribute("input_tokens", int(usage["input_tokens"]))
                if usage.get("output_tokens") is not None:
                    attempt_span.set_attribute("output_tokens", int(usage["output_tokens"]))
                attempt_span.set_attribute("status", "success")
                attempt_span.set_attribute("error_type", "")
            total_input_tokens += int(usage.get("input_tokens") or 0)
            total_output_tokens += int(usage.get("output_tokens") or 0)
            with self._telemetry.operation(
                "role_evidence_assessment.validation",
                {
                    "attempt": attempt,
                    "correction_scope": correction_scope,
                },
            ) as validation_span:
                if target_criterion_id:
                    correction, failure = _correction_payload(response)
                    if not failure:
                        failed_payload = _merge_correction(
                            failed_payload,
                            correction,
                            target_criterion_id,
                        )
                else:
                    failed_payload, failure = _tool_payload(response)
                accepted = None
                if not failure:
                    accepted, failure = _validate_submission(failed_payload, request)
                validation_span.set_attribute("validation_code", failure)
                validation_span.set_attribute("accepted", accepted is not None)
                validation_span.set_attribute(
                    "retry_triggered",
                    accepted is None and attempt < config.ROLE_EVIDENCE_VALIDATION_ATTEMPTS,
                )
            if accepted is not None:
                judgments = tuple(
                    RoleEvidenceJudgment(
                        criterion_id=item["criterion_id"],
                        alignment=item["alignment"],
                        resume_evidence_ids=tuple(item["resume_evidence_ids"]),
                        candidate_profile_field_ids=tuple(item["candidate_profile_field_ids"]),
                        supported_strength=item["supported_strength"],
                        remaining_gap=item["remaining_gap"],
                        evidence_support_score=int(item["evidence_support_score"]),
                        score_reason=item["score_reason"],
                    )
                    for item in accepted["judgments"]
                )
                return RoleEvidenceAssessmentRun(
                    judgments=judgments,
                    prompt_version=ROLE_EVIDENCE_ASSESSOR_PROMPT_VERSION,
                    model_name=model_name,
                    attempt_count=attempt,
                    input_tokens=total_input_tokens or None,
                    output_tokens=total_output_tokens or None,
                    validation_codes=tuple(validation_codes),
                )
            validation_codes.append(failure)
        raise RoleEvidenceAssessmentError(failure, failed_payload)


class ScriptedRoleEvidenceAssessor:
    def __init__(self, runs: list[RoleEvidenceAssessmentRun]):
        self._runs = iter(runs)
        self.call_count = 0

    def assess(self, request: RoleEvidenceAssessmentRequest) -> RoleEvidenceAssessmentRun:
        self.call_count += 1
        return next(self._runs)
