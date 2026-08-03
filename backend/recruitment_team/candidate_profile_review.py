"""One global merge and one independent review for a candidate profile."""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, replace
from typing import Any, Callable, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field

import config
from prompt_safety import xml_data_block

from .candidate_profile import (
    CandidateEvidenceProfile,
    CandidateProfileCheckpointStore,
    CandidateProfileField,
    CandidateProfileProgress,
    CandidateProfileProgressPublisher,
    CandidateProfileRun,
    CandidateProfileTransportError,
    CandidateProfileValidationError,
    CandidateProfiler,
    EvidenceKind,
    ProfileCategory,
    _build_profile,
    _response_payload,
    _validate_submission,
)
from .prompts import (
    CANDIDATE_PROFILE_CORRECTION_PROMPT,
    CANDIDATE_PROFILE_EVALUATION_PROMPT,
    CANDIDATE_PROFILE_GLOBAL_MERGE_PROMPT,
    CANDIDATE_PROFILE_REVIEW_VERSION,
)
from .recovery import classify_exception
from .telemetry import OpenTelemetryRecorder, RecruitmentTelemetry


GLOBAL_MERGE_SCOPE = "__global_semantic_merge__"
CORRECTION_SCOPE = "__global_correction__"
EVALUATION_SCOPE = "__independent_evaluation__"
REVIEW_STAGE_COUNT = 3

QualityLabel = Literal[
    "supported",
    "partially_supported",
    "unsupported",
    "misclassified",
    "duplicated",
]
ProfileResult = Literal["pass", "revise", "block"]

_DATE_EVIDENCE = re.compile(
    r"\b(?:19|20)\d{2}\b|\b\d+\s+years?\b|\b(?:currently|present)\b|"
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|"
    r"May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|"
    r"Nov(?:ember)?|Dec(?:ember)?)\b",
    re.IGNORECASE,
)
_REALIZED_OUTCOME = re.compile(
    r"\b(?:achiev(?:ed|ing)|avoid(?:ed|ing)|boost(?:ed|ing)|cut(?:ting)?|"
    r"deliver(?:ed|ing)|decreas(?:ed|ing)|generat(?:ed|ing)|improv(?:ed|ing)|"
    r"increas(?:ed|ing)|lower(?:ed|ing)|mitigat(?:ed|ing)|prevent(?:ed|ing)|"
    r"reduc(?:ed|ing)|realis(?:ed|ing)|realiz(?:ed|ing)|sav(?:ed|ing)|won)\b",
    re.IGNORECASE,
)
_NON_REALIZED_OUTCOME = re.compile(
    r"\b(?:aim(?:ed|s|ing)? to|expected to|potential(?:ly)?|projected to|"
    r"responsible for|target(?:ed|s|ing)? to|tasked with)\b",
    re.IGNORECASE,
)
_AWARD_EVIDENCE = re.compile(
    r"\b(?:award|awarded|honou?r|prize|winner|recognition|scholarship)\b",
    re.IGNORECASE,
)
_INFERENCE_LANGUAGE = re.compile(
    r"\b(?:infer(?:red|s)?|suggests?|implies?|likely|probably|appears?|"
    r"external knowledge|known for|may (?:indicate|reflect|support|suggest|transfer)|"
    r"might (?:indicate|reflect|support|suggest|transfer))\b",
    re.IGNORECASE,
)
_TEMPORARY_FIELD_REFERENCE = re.compile(r"\bfields?\s+(?:number\s+)?#?\d+\b", re.IGNORECASE)


class _MergeDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_field_numbers: list[int] = Field(min_length=1)
    category: ProfileCategory
    statement: str = Field(min_length=1)
    evidence_kind: EvidenceKind
    evidence_support_score: int = Field(ge=0, le=100)
    score_reason: str = Field(min_length=1)


class _MergeSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decisions: list[_MergeDecision]


class _SemanticMergeDecision(_MergeDecision):
    source_field_numbers: list[int] = Field(min_length=2)


class _SemanticMergeSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviewed_field_numbers: list[int] = Field(min_length=1)
    decisions: list[_SemanticMergeDecision]


class _FieldEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_ref: str = Field(min_length=1)
    strengths: list[str]
    weaknesses: list[str]
    score: int = Field(ge=0, le=100)
    score_reason: str = Field(min_length=1)
    label: QualityLabel
    cited_evidence_ids: list[str] = Field(min_length=1)


class _ProfileEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supported_field_refs: list[str]
    field_evaluations: list[_FieldEvaluation]
    strengths: list[str]
    weaknesses: list[str]
    score: int = Field(ge=0, le=100)
    score_reason: str = Field(min_length=1)
    result: ProfileResult


def _submit_globally_merged_candidate_profile(**payload: Any) -> dict:
    return _MergeSubmission(**payload).model_dump()


_GLOBAL_MERGE_TOOL = StructuredTool.from_function(
    func=_submit_globally_merged_candidate_profile,
    name="submit_globally_merged_candidate_profile",
    description=(
        "Submit only merge or correction decisions for the role-neutral profile. "
        "Omitted fields remain unchanged. Copy field references exactly."
    ),
    args_schema=_MergeSubmission,
)

_SEMANTIC_MERGE_TOOL = StructuredTool.from_function(
    func=_submit_globally_merged_candidate_profile,
    name="submit_globally_merged_candidate_profile",
    description=(
        "Submit only decisions that merge at least two repeated role-neutral profile "
        "fields. Omitted fields remain unchanged. Copy field numbers exactly."
    ),
    args_schema=_SemanticMergeSubmission,
)


def _submit_candidate_profile_evaluation(**payload: Any) -> dict:
    return _ProfileEvaluation(**payload).model_dump()


_EVALUATION_TOOL = StructuredTool.from_function(
    func=_submit_candidate_profile_evaluation,
    name="submit_candidate_profile_evaluation",
    description=(
        "Submit one independent field-level and profile-level extraction-quality "
        "evaluation with exact candidate-profile evidence citations."
    ),
    args_schema=_ProfileEvaluation,
)


def _profile_field_refs(
    profile: CandidateEvidenceProfile,
) -> dict[str, CandidateProfileField]:
    return {f"field_{index}": field for index, field in enumerate(profile.fields, start=1)}


def _validate_global_merge(
    payload: dict,
    local_profile: CandidateEvidenceProfile,
    blocks: dict[str, dict],
    required_correction_numbers: set[int] | None = None,
    required_merge_groups: tuple[tuple[int, ...], ...] = (),
    merge_only: bool = False,
    require_complete_review: bool = False,
) -> tuple[dict | None, str]:
    fields_by_number = {number: field for number, field in enumerate(local_profile.fields, start=1)}
    if require_complete_review:
        reviewed_numbers = [int(value) for value in payload["reviewed_field_numbers"]]
        if len(reviewed_numbers) != len(set(reviewed_numbers)):
            return None, "global_merge:duplicate_reviewed_field"
        expected_numbers = set(fields_by_number)
        observed_numbers = set(reviewed_numbers)
        if observed_numbers != expected_numbers:
            missing = ",".join(map(str, sorted(expected_numbers - observed_numbers))) or "none"
            unexpected = ",".join(map(str, sorted(observed_numbers - expected_numbers))) or "none"
            return None, (f"global_merge:review_coverage_mismatch(missing={missing};unexpected={unexpected})")
    source_number_groups = [
        [int(value) for value in decision["source_field_numbers"]] for decision in payload["decisions"]
    ]
    occurrences: dict[int, int] = {}
    for source_field_numbers in source_number_groups:
        if merge_only and len(source_field_numbers) < 2:
            return None, "global_merge:singleton_decision"
        if len(source_field_numbers) != len(set(source_field_numbers)):
            return None, "global_merge:duplicate_source_in_decision"
        unknown_numbers = sorted({number for number in source_field_numbers if number not in fields_by_number})
        if unknown_numbers:
            return None, (
                f"global_merge:unknown_source_field(valid=1..{len(fields_by_number)};"
                "out_of_range=" + ",".join(map(str, unknown_numbers)) + ")"
            )
        for number in source_field_numbers:
            occurrences[number] = occurrences.get(number, 0) + 1
    reused_numbers = sorted(number for number, count in occurrences.items() if count > 1)
    warning = ""
    if reused_numbers:
        if not merge_only:
            return None, "global_merge:source_field_reused(numbers=" + ",".join(map(str, reused_numbers)) + ")"
        reused = set(reused_numbers)
        retained = [
            (decision, numbers)
            for decision, numbers in zip(payload["decisions"], source_number_groups)
            if reused.isdisjoint(numbers)
        ]
        payload = {**payload, "decisions": [decision for decision, _numbers in retained]}
        source_number_groups = [numbers for _decision, numbers in retained]
        warning = "global_merge:ambiguous_overlaps_preserved(numbers=" + ",".join(map(str, reused_numbers)) + ")"

    decisions: dict[str, dict] = {}
    consumed: set[int] = set()
    decision_groups: list[set[int]] = []
    for decision, source_field_numbers in zip(payload["decisions"], source_number_groups):
        if _TEMPORARY_FIELD_REFERENCE.search(str(decision["score_reason"])):
            return None, "global_merge:temporary_field_reference_in_score_reason"
        consumed.update(source_field_numbers)
        decision_groups.append(set(source_field_numbers))
        source_fields = [fields_by_number[number] for number in source_field_numbers]
        source_field_ids = [field.field_id for field in source_fields]
        resume_evidence_ids = list(
            dict.fromkeys(evidence_id for field in source_fields for evidence_id in field.resume_evidence_ids)
        )
        merged = {
            "field_id": source_field_ids[0],
            "category": decision["category"],
            "statement": decision["statement"],
            "resume_evidence_ids": resume_evidence_ids,
            "evidence_quotes": [blocks[evidence_id]["text"] for evidence_id in resume_evidence_ids],
            "evidence_kind": decision["evidence_kind"],
            "evidence_support_score": decision["evidence_support_score"],
            "score_reason": decision["score_reason"],
        }
        if len(source_fields) == 1:
            original = asdict(source_fields[0])
            if all(
                merged[key] == original[key]
                for key in (
                    "category",
                    "statement",
                    "evidence_kind",
                    "evidence_support_score",
                    "score_reason",
                )
            ):
                return None, "global_merge:no_op_decision"
        decisions[source_field_ids[0]] = merged
        for field_id in source_field_ids[1:]:
            decisions[field_id] = {}

    missing_corrections = (required_correction_numbers or set()) - consumed
    if missing_corrections:
        return None, "global_merge:missing_required_corrections(" + ",".join(
            map(str, sorted(missing_corrections))
        ) + ")"

    missing_merge_groups = [
        group
        for group in required_merge_groups
        if not any(set(group).issubset(decision_group) for decision_group in decision_groups)
    ]
    if missing_merge_groups:
        return None, "global_merge:missing_exact_groups(" + ";".join(
            ",".join(map(str, group)) for group in missing_merge_groups
        ) + ")"

    fields = []
    for field in local_profile.fields:
        if field.field_id not in decisions:
            fields.append(asdict(field))
        elif decisions[field.field_id]:
            fields.append(decisions[field.field_id])

    accepted, failure = _validate_submission({"fields": fields}, blocks)
    if accepted is None:
        return None, failure
    if len(accepted["fields"]) > len(local_profile.fields):
        return None, "global_merge:field_expansion"

    source_ids = {evidence_id for field in local_profile.fields for evidence_id in field.resume_evidence_ids}
    merged_ids = {str(evidence_id) for field in accepted["fields"] for evidence_id in field["resume_evidence_ids"]}
    if merged_ids != source_ids:
        return None, "global_merge:citation_coverage_mismatch"

    if not merge_only:
        codes = []
        for field in accepted["fields"]:
            field_id = str(field["field_id"])
            codes.extend(_field_boundary_codes(field, blocks, field_id))
        if codes:
            return None, "|".join(codes)
    return accepted, warning


def _field_boundary_codes(field: dict, blocks: dict[str, dict], field_id: str) -> list[str]:
    cited = [blocks[str(value)] for value in field["resume_evidence_ids"]]
    evidence_text = " ".join(str(item.get("text") or "") for item in cited)
    quoted_text = " ".join(str(value) for value in field["evidence_quotes"])
    codes = []
    if field["category"] == "chronology" and not _DATE_EVIDENCE.search(evidence_text):
        codes.append(f"field:{field_id}:chronology_without_time_evidence")
    if (
        field["category"] == "outcome"
        and _NON_REALIZED_OUTCOME.search(quoted_text)
        and not _REALIZED_OUTCOME.search(quoted_text)
    ):
        codes.append(f"field:{field_id}:outcome_without_realized_result")
    if _AWARD_EVIDENCE.search(field["statement"]) and field["category"] != "credential":
        codes.append(f"field:{field_id}:award_misclassified")
    if field["category"] == "stated_skill" and all(str(item.get("kind") or "") == "entry_heading" for item in cited):
        codes.append(f"field:{field_id}:role_identity_is_not_skill")
    if field["evidence_kind"] == "direct" and _INFERENCE_LANGUAGE.search(
        f"{field['statement']} {field['score_reason']}"
    ):
        codes.append(f"field:{field_id}:direct_evidence_admits_inference")
    return codes


def _global_review_input(
    profile: CandidateEvidenceProfile,
    blocks: dict[str, dict],
) -> tuple[dict, set[int]]:
    required_corrections = {}
    correction_evidence = {}
    compact_fields = []
    numbers_by_citation: dict[tuple[str, ...], list[int]] = {}
    numbers_by_statement: dict[str, list[int]] = {}
    for field_number, profile_field in enumerate(profile.fields, start=1):
        field = asdict(profile_field)
        codes = _field_boundary_codes(field, blocks, profile_field.field_id)
        if codes:
            required_corrections[field_number] = codes
            field.pop("field_id")
            correction_evidence[field_number] = field
        compact_fields.append(
            {
                "field_number": field_number,
                **{
                    key: field[key]
                    for key in (
                        "category",
                        "statement",
                        "resume_evidence_ids",
                        "evidence_kind",
                        "evidence_support_score",
                    )
                },
                "source_sections": list(
                    dict.fromkeys(
                        str(blocks[evidence_id].get("section_key") or "document_header")
                        for evidence_id in profile_field.resume_evidence_ids
                    )
                ),
            }
        )
        citation_key = tuple(sorted(profile_field.resume_evidence_ids))
        numbers_by_citation.setdefault(citation_key, []).append(field_number)
        statement_key = " ".join(re.findall(r"[a-z0-9]+", profile_field.statement.casefold()))
        numbers_by_statement.setdefault(statement_key, []).append(field_number)
    return {
        "review_version": CANDIDATE_PROFILE_REVIEW_VERSION,
        "required_corrections": required_corrections,
        "co_citation_groups": [numbers for numbers in numbers_by_citation.values() if len(numbers) > 1],
        "exact_statement_groups": [numbers for numbers in numbers_by_statement.values() if len(numbers) > 1],
        "fields": compact_fields,
        "correction_evidence": correction_evidence,
    }, set(required_corrections)


def _semantic_merge_input(
    profile: CandidateEvidenceProfile,
    blocks: dict[str, dict],
) -> tuple[dict, tuple[tuple[int, ...], ...]]:
    review_input, _required_corrections = _global_review_input(profile, blocks)
    payload = {
        key: review_input[key]
        for key in (
            "review_version",
            "co_citation_groups",
            "exact_statement_groups",
            "fields",
        )
    }
    fields_by_number = {number: field for number, field in enumerate(profile.fields, start=1)}
    required_groups = tuple(
        tuple(int(number) for number in group)
        for group in payload["exact_statement_groups"]
        if len({tuple(sorted(fields_by_number[int(number)].resume_evidence_ids)) for number in group}) == 1
    )
    payload["required_exact_groups"] = [list(group) for group in required_groups]
    return payload, required_groups


def _validate_evaluation(
    payload: dict,
    field_refs: dict[str, CandidateProfileField],
) -> tuple[dict | None, str]:
    rows = payload["field_evaluations"]
    detailed_refs = [str(row["field_ref"]) for row in rows]
    supported_refs = [str(value) for value in payload["supported_field_refs"]]
    if len(detailed_refs) != len(set(detailed_refs)) or len(supported_refs) != len(set(supported_refs)):
        return None, "evaluation:duplicate_field"
    if set(detailed_refs).intersection(supported_refs):
        return None, "evaluation:field_in_multiple_buckets"
    observed_refs = set(detailed_refs).union(supported_refs)
    if observed_refs != set(field_refs):
        missing = ",".join(sorted(set(field_refs) - observed_refs)) or "none"
        unexpected = ",".join(sorted(observed_refs - set(field_refs))) or "none"
        return None, (f"evaluation:field_coverage_mismatch(missing={missing};unexpected={unexpected})")

    for row in rows:
        field = field_refs[str(row["field_ref"])]
        allowed = set(field.resume_evidence_ids)
        for citation in row["cited_evidence_ids"]:
            evidence_id = str(citation)
            if evidence_id not in allowed:
                return None, f"evaluation:{field.field_id}:noncanonical_evidence_id"
        if not all(str(item).strip() for item in (*row["strengths"], *row["weaknesses"])):
            return None, f"evaluation:{field.field_id}:empty_finding"
    if not all(str(item).strip() for item in (*payload["strengths"], *payload["weaknesses"])):
        return None, "evaluation:empty_profile_finding"
    detailed = {str(row["field_ref"]): row for row in rows}
    expanded = []
    for field_ref, field in field_refs.items():
        if field_ref in detailed:
            row = dict(detailed[field_ref])
            row.pop("field_ref")
            expanded.append({"field_id": field.field_id, **row})
            continue
        expanded.append(
            {
                "field_id": field.field_id,
                "strengths": ["The independent review found exact canonical citation support."],
                "weaknesses": [],
                "score": 100,
                "score_reason": "The independent reviewer marked this field fully supported.",
                "label": "supported",
                "cited_evidence_ids": list(field.resume_evidence_ids),
            }
        )
    return {
        "field_evaluations": expanded,
        "strengths": payload["strengths"],
        "weaknesses": payload["weaknesses"],
        "score": payload["score"],
        "score_reason": payload["score_reason"],
        "result": payload["result"],
    }, ""


def _evaluation_input(
    profile: CandidateEvidenceProfile,
) -> tuple[dict, dict[str, CandidateProfileField]]:
    field_refs = _profile_field_refs(profile)
    fields = []
    for field_ref, field in field_refs.items():
        item = asdict(field)
        item.pop("field_id")
        fields.append({"field_ref": field_ref, **item})
    return {
        "profile_version": profile.profile_version,
        "field_count": len(fields),
        "fields": fields,
    }, field_refs


class GloballyReviewedCandidateProfiler:
    """Add checkpointed global merge and independent review."""

    def __init__(
        self,
        extractor: CandidateProfiler,
        model,
        *,
        checkpoint_store: CandidateProfileCheckpointStore,
        telemetry: RecruitmentTelemetry | None = None,
        progress_publisher: CandidateProfileProgressPublisher | None = None,
    ):
        if not hasattr(model, "bind_tools"):
            raise TypeError("Candidate profile review model must support bind_tools")
        self._extractor = extractor
        self._model = model
        self._store = checkpoint_store
        self._telemetry = telemetry or OpenTelemetryRecorder()
        self._progress_publisher = progress_publisher
        self._model_name = str(getattr(model, "model_name", "") or getattr(model, "model", "") or type(model).__name__)

    def _publish_progress(
        self,
        transition: Literal["start", "checkpoint", "completion", "failure"],
        stage: str,
        *,
        scope_count: int,
        completed_scope_count: int,
    ) -> None:
        if self._progress_publisher is not None:
            self._progress_publisher(
                CandidateProfileProgress(
                    transition=transition,
                    scope_id=stage,
                    scope_count=scope_count,
                    completed_scope_count=completed_scope_count,
                )
            )

    def _invoke(
        self,
        *,
        checkpoint_id: str,
        stage: str,
        messages: list,
        tool: StructuredTool,
        schema: type[BaseModel],
        validator: Callable[[dict], tuple[dict | None, str]],
    ) -> dict:
        cached = self._store.load(checkpoint_id).get(stage)
        if cached is not None:
            self._store.record_execution_event(
                checkpoint_id,
                {
                    "event": "checkpoint_hit",
                    "stage": stage.strip("_"),
                    "scope_id": stage,
                    "status": "success",
                    "model": self._model_name,
                },
            )
            return cached

        feedback = self._store.load_retry_feedback(checkpoint_id, stage) or {}
        failure = str(feedback.get("validation_code") or "")
        failed_output = feedback.get("failed_output")
        first_attempt = int(feedback.get("next_attempt") or 1)
        if feedback.get("exhausted") is True:
            raise CandidateProfileValidationError(
                failure,
                failed_output,
                checkpoint_id=checkpoint_id,
                completed_scope_ids=tuple(self._store.load(checkpoint_id)),
            )

        bound_model = self._model.bind_tools([tool], tool_choice=tool.name)
        for attempt in range(first_attempt, config.CANDIDATE_PROFILE_REVIEW_ATTEMPTS + 1):
            request = list(messages)
            if failure:
                request.append(
                    HumanMessage(
                        content="\n\n".join(
                            (
                                "Correct only the rejected review output and resubmit it once.",
                                xml_data_block("validation_error_data", failure),
                                xml_data_block(
                                    "rejected_review_output_data",
                                    json.dumps(failed_output, ensure_ascii=False, separators=(",", ":"), default=str),
                                ),
                                xml_data_block("fixability", "fixable"),
                            )
                        )
                    )
                )
            started = time.perf_counter()
            with self._telemetry.operation(
                "candidate_profile_review.model_attempt",
                {
                    "stage": stage.strip("_"),
                    "attempt": attempt,
                    "max_attempts": config.CANDIDATE_PROFILE_REVIEW_ATTEMPTS,
                    "review_version": CANDIDATE_PROFILE_REVIEW_VERSION,
                    "configured_timeout_seconds": config.RECRUITMENT_MODEL_HTTP_TIMEOUT_SECONDS,
                    "transport_retries": config.RECRUITMENT_MODEL_TRANSPORT_RETRIES,
                    "logical_run_id": checkpoint_id,
                },
            ) as model_span:
                try:
                    response = bound_model.invoke(request)
                except Exception as error:
                    decision = classify_exception(error)
                    self._store.record_execution_event(
                        checkpoint_id,
                        {
                            "event": "model_attempt",
                            "stage": stage.strip("_"),
                            "scope_id": stage,
                            "attempt": attempt,
                            "attempt_limit": config.CANDIDATE_PROFILE_REVIEW_ATTEMPTS,
                            "status": "error",
                            "model": self._model_name,
                            "latency_ms": (time.perf_counter() - started) * 1000,
                            "error_type": type(error).__name__,
                            "failure_type": decision.failure_type,
                            "failure_code": decision.failure_code,
                            "retryable": decision.retryable,
                            "recovery_action": decision.recovery_action,
                        },
                    )
                    model_span.set_attribute("status", "error")
                    model_span.set_attribute("error_type", type(error).__name__)
                    metrics = self._store.execution_metrics(checkpoint_id)
                    raise CandidateProfileTransportError(
                        scope_id=stage,
                        attempt=attempt,
                        cause_type=type(error).__name__,
                        failure_code=decision.failure_code,
                        completed_scope_ids=tuple(self._store.load(checkpoint_id)),
                        checkpoint_id=checkpoint_id,
                        model_call_count=int(metrics.get("model_call_count") or 0),
                        input_tokens=int(metrics.get("input_tokens") or 0) or None,
                        output_tokens=int(metrics.get("output_tokens") or 0) or None,
                    ) from error

                usage = getattr(response, "usage_metadata", None) or {}
                response_model = getattr(response, "response_metadata", {}).get("model_name")
                if response_model:
                    self._model_name = str(response_model)
                model_span.set_attribute("model", self._model_name)
                model_span.set_attribute("input_tokens", int(usage.get("input_tokens") or 0))
                model_span.set_attribute("output_tokens", int(usage.get("output_tokens") or 0))
                model_span.set_attribute("status", "success")
            with self._telemetry.operation(
                "candidate_profile_review.validation",
                {"stage": stage.strip("_"), "attempt": attempt},
            ) as validation_span:
                payload, failed_output, failure = _response_payload(response, tool, schema)
                if payload is not None:
                    payload, failure = validator(payload)
                validation_span.set_attribute("validation_code", failure)
                validation_span.set_attribute("accepted", payload is not None)
                validation_span.set_attribute(
                    "retry_triggered",
                    payload is None and attempt < config.CANDIDATE_PROFILE_REVIEW_ATTEMPTS,
                )
            status = "success" if payload is not None else "validation_failed"
            self._store.record_execution_event(
                checkpoint_id,
                {
                    "event": "model_attempt",
                    "stage": stage.strip("_"),
                    "scope_id": stage,
                    "attempt": attempt,
                    "attempt_limit": config.CANDIDATE_PROFILE_REVIEW_ATTEMPTS,
                    "status": status,
                    "model": self._model_name,
                    "input_tokens": int(usage.get("input_tokens") or 0),
                    "output_tokens": int(usage.get("output_tokens") or 0),
                    "latency_ms": (time.perf_counter() - started) * 1000,
                    "validation_code": failure,
                },
            )
            if payload is not None:
                self._store.clear_retry_feedback(checkpoint_id, stage)
                self._store.save(checkpoint_id, stage, payload)
                return payload
            exhausted = attempt == config.CANDIDATE_PROFILE_REVIEW_ATTEMPTS
            self._store.save_retry_feedback(
                checkpoint_id,
                stage,
                {
                    "original_input": messages[-1].content,
                    "failed_output": failed_output,
                    "validation_code": failure,
                    "fixability": "fixable",
                    "next_attempt": attempt if exhausted else attempt + 1,
                    "exhausted": exhausted,
                },
            )

        raise CandidateProfileValidationError(
            failure,
            failed_output,
            checkpoint_id=checkpoint_id,
            completed_scope_ids=tuple(self._store.load(checkpoint_id)),
        )

    def _run_stage(
        self,
        *,
        checkpoint_id: str,
        stage: str,
        messages: list,
        tool: StructuredTool,
        schema: type[BaseModel],
        validator: Callable[[dict], tuple[dict | None, str]],
        scope_count: int,
        completed_scope_count: int,
    ) -> dict:
        self._publish_progress(
            "start",
            stage,
            scope_count=scope_count,
            completed_scope_count=completed_scope_count,
        )
        try:
            result = self._invoke(
                checkpoint_id=checkpoint_id,
                stage=stage,
                messages=messages,
                tool=tool,
                schema=schema,
                validator=validator,
            )
        except Exception:
            self._publish_progress(
                "failure",
                stage,
                scope_count=scope_count,
                completed_scope_count=completed_scope_count,
            )
            raise
        self._publish_progress(
            "checkpoint",
            stage,
            scope_count=scope_count,
            completed_scope_count=completed_scope_count,
        )
        self._publish_progress(
            "completion",
            stage,
            scope_count=scope_count,
            completed_scope_count=completed_scope_count + 1,
        )
        return result

    def profile(self, resume_document: dict[str, Any]) -> CandidateProfileRun:
        local = self._extractor.profile(resume_document)
        blocks = {
            str(block["id"]): block
            for block in resume_document.get("blocks", [])
            if isinstance(block, dict) and block.get("id")
        }
        merge_input, required_merge_groups = _semantic_merge_input(
            local.profile,
            blocks,
        )
        scope_count = local.scope_count + REVIEW_STAGE_COUNT
        completed_scope_count = local.scope_count
        merged = self._run_stage(
            checkpoint_id=local.checkpoint_id,
            stage=GLOBAL_MERGE_SCOPE,
            messages=[
                SystemMessage(content=CANDIDATE_PROFILE_GLOBAL_MERGE_PROMPT),
                HumanMessage(
                    content=xml_data_block(
                        "candidate_profile_global_merge_data",
                        json.dumps(merge_input, ensure_ascii=False, separators=(",", ":")),
                    )
                ),
            ],
            tool=_SEMANTIC_MERGE_TOOL,
            schema=_SemanticMergeSubmission,
            validator=lambda payload: _validate_global_merge(
                payload,
                local.profile,
                blocks,
                required_merge_groups=required_merge_groups,
                merge_only=True,
                require_complete_review=True,
            ),
            scope_count=scope_count,
            completed_scope_count=completed_scope_count,
        )
        completed_scope_count += 1
        merged_profile = _build_profile(resume_document, merged["fields"])
        correction_input, required_correction_numbers = _global_review_input(
            merged_profile,
            blocks,
        )
        corrected = self._run_stage(
            checkpoint_id=local.checkpoint_id,
            stage=CORRECTION_SCOPE,
            messages=[
                SystemMessage(content=CANDIDATE_PROFILE_CORRECTION_PROMPT),
                HumanMessage(
                    content=xml_data_block(
                        "candidate_profile_correction_data",
                        json.dumps(correction_input, ensure_ascii=False, separators=(",", ":")),
                    )
                ),
            ],
            tool=_GLOBAL_MERGE_TOOL,
            schema=_MergeSubmission,
            validator=lambda payload: _validate_global_merge(
                payload,
                merged_profile,
                blocks,
                required_correction_numbers,
            ),
            scope_count=scope_count,
            completed_scope_count=completed_scope_count,
        )
        completed_scope_count += 1
        profile = _build_profile(resume_document, corrected["fields"])
        evaluation_input, field_refs = _evaluation_input(profile)
        evaluation = self._run_stage(
            checkpoint_id=local.checkpoint_id,
            stage=EVALUATION_SCOPE,
            messages=[
                SystemMessage(content=CANDIDATE_PROFILE_EVALUATION_PROMPT),
                HumanMessage(
                    content=xml_data_block(
                        "candidate_profile_evaluation_data",
                        json.dumps(evaluation_input, ensure_ascii=False, separators=(",", ":")),
                    )
                ),
            ],
            tool=_EVALUATION_TOOL,
            schema=_ProfileEvaluation,
            validator=lambda payload: _validate_evaluation(payload, field_refs),
            scope_count=scope_count,
            completed_scope_count=completed_scope_count,
        )
        evaluation = {
            "evaluation_version": CANDIDATE_PROFILE_REVIEW_VERSION,
            "profile_version": profile.profile_version,
            **evaluation,
        }
        metrics = self._store.execution_metrics(local.checkpoint_id)
        return replace(
            local,
            profile=profile,
            evaluation=evaluation,
            attempt_count=int(metrics.get("model_call_count") or local.attempt_count),
            model_call_count=int(metrics.get("model_call_count") or local.model_call_count),
            checkpoint_hit_count=int(metrics.get("checkpoint_hit_count") or local.checkpoint_hit_count),
            input_tokens=int(metrics.get("input_tokens") or 0) or None,
            output_tokens=int(metrics.get("output_tokens") or 0) or None,
            validation_codes=tuple(metrics.get("validation_codes") or local.validation_codes),
            scope_count=local.scope_count + REVIEW_STAGE_COUNT,
            model_name=str((metrics.get("models") or [self._model_name])[-1]),
        )
