"""Role-neutral Candidate Evidence Profile over one immutable resume document."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from hashlib import sha256
from html import unescape
from typing import Any, Literal, Protocol

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field, ValidationError

import config
from prompt_safety import xml_data_block
from validation_gates import _extract_numbers

from .prompts import (
    CANDIDATE_PROFILE_PROMPT_VERSION,
    CANDIDATE_PROFILE_SYSTEM_PROMPT,
    CANDIDATE_PROFILE_VALIDATION_FEEDBACK_VERSION,
    candidate_profile_validation_feedback,
)
from .telemetry import OpenTelemetryRecorder, RecruitmentTelemetry


ProfileCategory = Literal[
    "chronology",
    "stated_skill",
    "demonstrated_capability",
    "outcome",
    "scope_seniority_signal",
    "domain",
    "credential",
    "ambiguity",
]
EvidenceKind = Literal["direct", "transferable_hypothesis"]
CANDIDATE_PROFILE_DECOMPOSITION_VERSION = "semantic-section-record-v1"


def candidate_profile_execution_policy() -> dict[str, str | int]:
    from resume_document import SCHEMA_VERSION

    return {
        "prompt_version": CANDIDATE_PROFILE_PROMPT_VERSION,
        "validation_feedback_version": CANDIDATE_PROFILE_VALIDATION_FEEDBACK_VERSION,
        "model_timeout_seconds": config.RECRUITMENT_MODEL_HTTP_TIMEOUT_SECONDS,
        "validation_attempts": config.CANDIDATE_PROFILE_VALIDATION_ATTEMPTS,
        "transport_retries": config.RECRUITMENT_MODEL_TRANSPORT_RETRIES,
        "decomposition_version": CANDIDATE_PROFILE_DECOMPOSITION_VERSION,
        "resume_document_schema_version": SCHEMA_VERSION,
    }


@dataclass(frozen=True)
class CandidateProfileField:
    field_id: str
    category: ProfileCategory
    statement: str
    resume_evidence_ids: tuple[str, ...]
    evidence_quotes: tuple[str, ...]
    evidence_kind: EvidenceKind
    evidence_support_score: int
    score_reason: str


@dataclass(frozen=True)
class CandidateProfileEvidence:
    evidence_id: str
    kind: str
    text: str
    source_locator: str
    section_key: str


@dataclass(frozen=True)
class CandidateEvidenceProfile:
    profile_version: str
    resume_document_id: str
    resume_revision: str
    fields: tuple[CandidateProfileField, ...]
    cited_resume_evidence: tuple[CandidateProfileEvidence, ...]


def candidate_profile_from_dict(item: dict[str, Any]) -> CandidateEvidenceProfile:
    """Rehydrate one validated profile at the module interface."""

    return CandidateEvidenceProfile(
        profile_version=str(item["profile_version"]),
        resume_document_id=str(item["resume_document_id"]),
        resume_revision=str(item["resume_revision"]),
        fields=tuple(
            CandidateProfileField(
                field_id=str(field["field_id"]),
                category=field["category"],
                statement=str(field["statement"]),
                resume_evidence_ids=tuple(str(value) for value in field["resume_evidence_ids"]),
                evidence_quotes=tuple(str(value) for value in field["evidence_quotes"]),
                evidence_kind=field["evidence_kind"],
                evidence_support_score=int(field["evidence_support_score"]),
                score_reason=str(field["score_reason"]),
            )
            for field in item["fields"]
        ),
        cited_resume_evidence=tuple(
            CandidateProfileEvidence(
                evidence_id=str(record["evidence_id"]),
                kind=str(record.get("kind") or ""),
                text=str(record["text"]),
                source_locator=str(record.get("source_locator") or ""),
                section_key=str(record.get("section_key") or ""),
            )
            for record in item["cited_resume_evidence"]
        ),
    )


@dataclass(frozen=True)
class CandidateProfileRun:
    profile: CandidateEvidenceProfile
    model_name: str
    attempt_count: int
    input_tokens: int | None = None
    output_tokens: int | None = None
    validation_codes: tuple[str, ...] = ()
    scope_count: int = 0
    model_call_count: int = 0
    checkpoint_hit_count: int = 0
    checkpoint_id: str = ""


class CandidateProfileValidationError(ValueError):
    def __init__(
        self,
        validation_code: str,
        rejected_submission: dict | None,
        *,
        attempt_count: int = 0,
        model_name: str = "",
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        validation_codes: tuple[str, ...] = (),
        checkpoint_id: str = "",
        completed_scope_ids: tuple[str, ...] = (),
    ):
        super().__init__(f"candidate profile validation failed: {validation_code}")
        self.validation_code = validation_code
        self.rejected_submission = rejected_submission
        self.attempt_count = attempt_count
        self.model_name = model_name
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.validation_codes = validation_codes
        self.checkpoint_id = checkpoint_id
        self.completed_scope_ids = completed_scope_ids


class CandidateProfileTransportError(RuntimeError):
    """A model transport failure with enough metadata for explicit resumption."""

    def __init__(
        self,
        *,
        scope_id: str,
        attempt: int,
        cause_type: str,
        completed_scope_ids: tuple[str, ...],
        checkpoint_id: str,
        model_call_count: int,
        input_tokens: int | None,
        output_tokens: int | None,
    ):
        super().__init__(f"candidate profile transport failed in scope {scope_id}: {cause_type}")
        self.scope_id = scope_id
        self.attempt = attempt
        self.cause_type = cause_type
        self.completed_scope_ids = completed_scope_ids
        self.checkpoint_id = checkpoint_id
        self.model_call_count = model_call_count
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class CandidateProfiler(Protocol):
    def profile(self, resume_document: dict[str, Any]) -> CandidateProfileRun: ...


class CandidateProfilerFactory(Protocol):
    model_name: str

    def create(
        self,
        checkpoint_store: CandidateProfileCheckpointStore,
    ) -> CandidateProfiler: ...


class CandidateProfileCheckpointStore(Protocol):
    """Persist validated scope results under an immutable run identity."""

    def load(self, checkpoint_id: str) -> dict[str, dict[str, Any]]: ...

    def save(
        self,
        checkpoint_id: str,
        scope_id: str,
        payload: dict[str, Any],
    ) -> None: ...

    def load_retry_feedback(
        self,
        checkpoint_id: str,
        scope_id: str,
    ) -> dict[str, Any] | None: ...

    def save_retry_feedback(
        self,
        checkpoint_id: str,
        scope_id: str,
        feedback: dict[str, Any],
    ) -> None: ...

    def clear_retry_feedback(self, checkpoint_id: str, scope_id: str) -> None: ...


@dataclass(frozen=True)
class _ProfileScope:
    scope_id: str
    section_key: str
    blocks: tuple[dict[str, Any], ...]


class _FieldSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_id: str = Field(min_length=1)
    category: ProfileCategory
    statement: str = Field(min_length=1)
    resume_evidence_ids: list[str] = Field(min_length=1)
    evidence_quotes: list[str] = Field(min_length=1)
    evidence_kind: EvidenceKind
    evidence_support_score: int = Field(ge=0, le=100)
    score_reason: str = Field(min_length=1)


class _ProfileSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fields: list[_FieldSubmission]


def _submit_candidate_evidence_profile(**payload: Any) -> dict:
    return _ProfileSubmission(**payload).model_dump()


_SUBMIT_PROFILE_TOOL = StructuredTool.from_function(
    func=_submit_candidate_evidence_profile,
    name="submit_candidate_evidence_profile",
    description=(
        "Submit the complete role-neutral Candidate Evidence Profile for the supplied "
        "immutable resume blocks. Give every field an ID unique within this supplied scope. "
        "Every field must cite canonical block IDs and include "
        "contiguous evidence quotes, an evidence kind, and a raw support score with its "
        "reason. Use for resume facts, supported transferable hypotheses, and explicit "
        "ambiguities. Do not use it for job fit, preferences, recommendations, or facts "
        "not present in the resume."
    ),
    args_schema=_ProfileSubmission,
)


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(value)).strip()


def _canonicalize_profile_fields(fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Create global stable IDs and remove only exact fact-and-provenance duplicates."""

    canonical: dict[str, dict[str, Any]] = {}
    for field in fields:
        identity = json.dumps(
            {
                "category": field["category"],
                "statement": _normalize(str(field["statement"])),
                "resume_evidence_ids": sorted(str(value) for value in field["resume_evidence_ids"]),
                "evidence_kind": field["evidence_kind"],
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        field_id = f"{field['category']}_{sha256(identity.encode()).hexdigest()}"
        candidate = {**field, "field_id": field_id}
        existing = canonical.get(field_id)
        if existing is None or int(candidate["evidence_support_score"]) < int(existing["evidence_support_score"]):
            canonical[field_id] = candidate
    return list(canonical.values())


def _scope_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") or "document_header"


def _profile_scopes(blocks: list[dict[str, Any]]) -> tuple[_ProfileScope, ...]:
    """Split on document semantics, never character or token counts."""
    grouped: list[tuple[str, list[dict[str, Any]]]] = []
    current: list[dict[str, Any]] = []
    current_section = ""
    previous_kind = ""
    for block in blocks:
        section_key = str(block.get("section_key") or "")
        kind = str(block.get("kind") or "")
        starts_scope = bool(current) and (
            section_key != current_section
            or kind == "section_heading"
            or (kind == "paragraph" and previous_kind == "bullet")
        )
        if starts_scope:
            grouped.append((current_section, current))
            current = []
        current.append(block)
        current_section = section_key
        previous_kind = kind
    if current:
        grouped.append((current_section, current))

    ordinals: dict[str, int] = {}
    scopes: list[_ProfileScope] = []
    for section_key, scope_blocks in grouped:
        slug = _scope_slug(section_key)
        ordinal = ordinals.get(slug, 0) + 1
        ordinals[slug] = ordinal
        scopes.append(
            _ProfileScope(
                scope_id=f"{slug}_{ordinal:02d}",
                section_key=section_key,
                blocks=tuple(scope_blocks),
            )
        )
    return tuple(scopes)


def _profile_checkpoint_id(
    resume_document: dict[str, Any],
    configured_model_name: str,
) -> str:
    identity = json.dumps(
        {
            "resume_document_id": resume_document["document_id"],
            "resume_revision": resume_document["revision"],
            "prompt_version": CANDIDATE_PROFILE_PROMPT_VERSION,
            "validation_feedback_version": CANDIDATE_PROFILE_VALIDATION_FEEDBACK_VERSION,
            "decomposition_version": CANDIDATE_PROFILE_DECOMPOSITION_VERSION,
            "model": configured_model_name,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(identity.encode()).hexdigest()


def _response_payload(response: AIMessage) -> tuple[dict | None, dict, str]:
    failed = {"content": response.content, "tool_calls": response.tool_calls}
    calls = [call for call in response.tool_calls if call.get("name") == _SUBMIT_PROFILE_TOOL.name]
    if len(response.tool_calls) != 1 or len(calls) != 1:
        return None, failed, "tool_call:required_exactly_one"
    try:
        return _ProfileSubmission(**(calls[0].get("args") or {})).model_dump(), failed, ""
    except ValidationError:
        return None, failed, "schema_validation"


def _validate_submission(
    payload: dict,
    blocks: dict[str, dict],
) -> tuple[dict | None, str]:
    fields = payload["fields"]
    field_ids = [str(item["field_id"]).strip() for item in fields]
    if len(field_ids) != len(set(field_ids)):
        return None, "field_id:duplicate"

    canonical_ids = set(blocks)
    block_positions = {block_id: index for index, block_id in enumerate(blocks)}
    validation_codes: list[str] = []
    for item in fields:
        field_id = str(item["field_id"]).strip()
        evidence_ids = [str(value) for value in item["resume_evidence_ids"]]
        if not evidence_ids:
            validation_codes.append(f"field:{field_id}:missing_positive_citation")
            continue
        if any(evidence_id not in canonical_ids for evidence_id in evidence_ids):
            validation_codes.append(f"field:{field_id}:noncanonical_evidence_id")
            continue
        if len(evidence_ids) != len(set(evidence_ids)):
            validation_codes.append(f"field:{field_id}:duplicate_evidence_id")
            continue

        ordered_evidence_ids = sorted(evidence_ids, key=block_positions.__getitem__)
        cited_texts = [_normalize(str(blocks[evidence_id].get("text") or "")) for evidence_id in ordered_evidence_ids]
        contiguous_runs: list[list[str]] = []
        previous_position: int | None = None
        for evidence_id, text in zip(ordered_evidence_ids, cited_texts, strict=True):
            position = block_positions[evidence_id]
            if previous_position is None or position != previous_position + 1:
                contiguous_runs.append([])
            contiguous_runs[-1].append(text)
            previous_position = position
        quote_sources = [*cited_texts, *(" ".join(run) for run in contiguous_runs)]
        quote_not_found = False
        for quote in item["evidence_quotes"]:
            normalized_quote = _normalize(str(quote))
            if not normalized_quote or not any(normalized_quote in text for text in quote_sources):
                quote_not_found = True
        if quote_not_found:
            validation_codes.append(f"field:{field_id}:quote_not_found")

        supported_numbers = _extract_numbers(" ".join(cited_texts))
        # Ground candidate facts, not the model's confidence metadata. The score
        # reason may legitimately explain its own numeric support score (for
        # example, "score is 90"); that number is not a resume claim.
        claimed_numbers = _extract_numbers(item["statement"])
        unsupported = sorted(claimed_numbers - supported_numbers)
        if unsupported:
            validation_codes.append(f"field:{field_id}:unsupported_numbers({','.join(unsupported)})")

    return (None, "|".join(validation_codes)) if validation_codes else (payload, "")


def _correction_evidence_boundary(
    validation_code: str,
    rejected_payload: dict | None,
    blocks: dict[str, dict],
) -> dict | None:
    """Return exact cited evidence for the one rejected field, without truncation."""

    if rejected_payload is None:
        return None
    boundaries = []
    for code in validation_code.split("|"):
        parts = code.split(":", 2)
        if len(parts) != 3 or parts[0] != "field":
            continue
        field_id = parts[1]
        field = next(
            (item for item in rejected_payload.get("fields", []) if item.get("field_id") == field_id),
            None,
        )
        if field is None:
            continue
        boundaries.append(
            {
                "validation_code": code,
                "field_id": field_id,
                "rejected_evidence_quotes": list(field.get("evidence_quotes") or []),
                "cited_blocks": [
                    {
                        "id": evidence_id,
                        "text": str(blocks[evidence_id].get("text") or ""),
                    }
                    for evidence_id in field.get("resume_evidence_ids", [])
                    if evidence_id in blocks
                ],
            }
        )
    return {
        "rejected_fields": boundaries,
        "instruction": (
            "Use a verbatim substring from these cited blocks, or change the cited block IDs "
            "to the canonical blocks that actually contain the intended quote. Correct every "
            "listed validation code in one resubmission."
        ),
    }


class LangChainCandidateProfiler:
    """Profile semantic resume scopes with validated, resumable model calls."""

    def __init__(
        self,
        model=None,
        *,
        telemetry: RecruitmentTelemetry | None = None,
        checkpoint_store: CandidateProfileCheckpointStore | None = None,
    ):
        if model is None:
            from resume_agent.models import create_agent_model

            model = create_agent_model(
                timeout=config.RECRUITMENT_MODEL_HTTP_TIMEOUT_SECONDS,
                max_retries=config.RECRUITMENT_MODEL_TRANSPORT_RETRIES,
            )
        if not hasattr(model, "bind_tools"):
            raise TypeError("Candidate profile model must support bind_tools")
        self._model = model
        self._telemetry = telemetry or OpenTelemetryRecorder()
        self._checkpoint_store = checkpoint_store
        self._configured_model_name = str(
            getattr(model, "model_name", "") or getattr(model, "model", "") or type(model).__name__
        )

    def _scope_request(self, scope: _ProfileScope) -> list[SystemMessage | HumanMessage]:
        block_payload = [
            {
                "id": str(block["id"]),
                "kind": block.get("kind", ""),
                "text": block.get("text", ""),
                "source_locator": (block.get("source") or {}).get("locator", ""),
                "section_key": block.get("section_key", ""),
            }
            for block in scope.blocks
        ]
        return [
            SystemMessage(content=CANDIDATE_PROFILE_SYSTEM_PROMPT),
            HumanMessage(
                content="\n\n".join(
                    (
                        xml_data_block(
                            "profile_scope",
                            json.dumps(
                                {"scope_id": scope.scope_id, "section_key": scope.section_key},
                                ensure_ascii=False,
                                separators=(",", ":"),
                            ),
                        ),
                        xml_data_block(
                            "resume_blocks",
                            json.dumps(block_payload, ensure_ascii=False, separators=(",", ":")),
                        ),
                    )
                )
            ),
        ]

    def _load_retry_feedback(
        self,
        checkpoint_id: str,
        scope_id: str,
    ) -> dict[str, Any] | None:
        if self._checkpoint_store is None or not hasattr(
            self._checkpoint_store,
            "load_retry_feedback",
        ):
            return None
        return self._checkpoint_store.load_retry_feedback(checkpoint_id, scope_id)

    def _save_retry_feedback(
        self,
        checkpoint_id: str,
        scope_id: str,
        feedback: dict[str, Any],
    ) -> None:
        if self._checkpoint_store is not None and hasattr(
            self._checkpoint_store,
            "save_retry_feedback",
        ):
            self._checkpoint_store.save_retry_feedback(
                checkpoint_id,
                scope_id,
                feedback,
            )

    def _clear_retry_feedback(self, checkpoint_id: str, scope_id: str) -> None:
        if self._checkpoint_store is not None and hasattr(
            self._checkpoint_store,
            "clear_retry_feedback",
        ):
            self._checkpoint_store.clear_retry_feedback(checkpoint_id, scope_id)

    def profile(self, resume_document: dict[str, Any]) -> CandidateProfileRun:
        ordered_blocks = [
            block for block in resume_document.get("blocks", []) if isinstance(block, dict) and block.get("id")
        ]
        blocks = {str(block["id"]): block for block in ordered_blocks}
        if not blocks or not resume_document.get("document_id") or not resume_document.get("revision"):
            raise ValueError("A canonical immutable resume document is required")

        scopes = _profile_scopes(ordered_blocks)
        checkpoint_id = _profile_checkpoint_id(resume_document, self._configured_model_name)
        checkpoints = self._checkpoint_store.load(checkpoint_id) if self._checkpoint_store is not None else {}
        bound_model = self._model.bind_tools(
            [_SUBMIT_PROFILE_TOOL],
            tool_choice=_SUBMIT_PROFILE_TOOL.name,
        )
        accepted_fields: list[dict[str, Any]] = []
        completed_scope_ids: list[str] = []
        input_tokens = 0
        output_tokens = 0
        model_call_count = 0
        checkpoint_hit_count = 0
        validation_codes: list[str] = []
        model_name = self._configured_model_name

        for scope in scopes:
            scope_blocks = {str(block["id"]): block for block in scope.blocks}
            with self._telemetry.operation(
                "candidate_profile.scope",
                {
                    "scope_id": scope.scope_id,
                    "section_key": scope.section_key,
                    "block_count": len(scope.blocks),
                },
            ) as scope_span:
                cached = checkpoints.get(scope.scope_id)
                if cached is not None:
                    payload, failure = _validate_submission(cached, scope_blocks)
                    if payload is None:
                        scope_span.set_attribute("status", "error")
                        scope_span.set_attribute("error_type", "InvalidCheckpoint")
                        raise CandidateProfileValidationError(
                            f"checkpoint:{scope.scope_id}:{failure}",
                            cached,
                            attempt_count=model_call_count,
                            model_name=model_name,
                            input_tokens=input_tokens or None,
                            output_tokens=output_tokens or None,
                            validation_codes=tuple(validation_codes),
                            checkpoint_id=checkpoint_id,
                            completed_scope_ids=tuple(completed_scope_ids),
                        )
                    accepted_fields.extend(payload["fields"])
                    completed_scope_ids.append(scope.scope_id)
                    checkpoint_hit_count += 1
                    scope_span.set_attribute("checkpoint_hit", True)
                    scope_span.set_attribute("status", "success")
                    continue

                request = self._scope_request(scope)
                retry_feedback = self._load_retry_feedback(
                    checkpoint_id,
                    scope.scope_id,
                )
                failed_output: dict | None = retry_feedback.get("failed_output") if retry_feedback else None
                rejected_payload: dict | None = retry_feedback.get("rejected_payload") if retry_feedback else None
                failure = str(retry_feedback.get("validation_code") or "") if retry_feedback else ""
                first_attempt = int(retry_feedback.get("next_attempt") or 1) if retry_feedback else 1
                if rejected_payload is not None:
                    resumed_payload, resumed_failure = _validate_submission(
                        rejected_payload,
                        scope_blocks,
                    )
                    if resumed_payload is not None:
                        self._clear_retry_feedback(checkpoint_id, scope.scope_id)
                        if self._checkpoint_store is not None:
                            self._checkpoint_store.save(
                                checkpoint_id,
                                scope.scope_id,
                                resumed_payload,
                            )
                        accepted_fields.extend(resumed_payload["fields"])
                        completed_scope_ids.append(scope.scope_id)
                        scope_span.set_attribute("checkpoint_hit", True)
                        scope_span.set_attribute("retry_payload_revalidated", True)
                        scope_span.set_attribute("status", "success")
                        continue
                    failure = resumed_failure
                if retry_feedback and retry_feedback.get("exhausted") is True:
                    scope_span.set_attribute("status", "error")
                    scope_span.set_attribute("error_type", "ValidationAttemptsExhausted")
                    raise CandidateProfileValidationError(
                        f"checkpoint:{scope.scope_id}:validation_attempts_exhausted:{failure}",
                        failed_output,
                        attempt_count=model_call_count,
                        model_name=model_name,
                        input_tokens=input_tokens or None,
                        output_tokens=output_tokens or None,
                        validation_codes=(failure,) if failure else (),
                        checkpoint_id=checkpoint_id,
                        completed_scope_ids=tuple(completed_scope_ids),
                    )
                if first_attempt < 1 or first_attempt > config.CANDIDATE_PROFILE_VALIDATION_ATTEMPTS:
                    raise CandidateProfileValidationError(
                        f"checkpoint:{scope.scope_id}:invalid_retry_attempt",
                        retry_feedback,
                        attempt_count=model_call_count,
                        model_name=model_name,
                        input_tokens=input_tokens or None,
                        output_tokens=output_tokens or None,
                        validation_codes=tuple(validation_codes),
                        checkpoint_id=checkpoint_id,
                        completed_scope_ids=tuple(completed_scope_ids),
                    )
                if failure:
                    validation_codes.append(failure)
                payload = None
                for attempt in range(
                    first_attempt,
                    config.CANDIDATE_PROFILE_VALIDATION_ATTEMPTS + 1,
                ):
                    model_call_count += 1
                    attempt_request = list(request)
                    if failure:
                        attempt_request.append(
                            HumanMessage(
                                content="\n\n".join(
                                    (
                                        "Correct the rejected submission for this scope. Return it once.",
                                        xml_data_block(
                                            "failed_candidate_profile",
                                            json.dumps(
                                                failed_output,
                                                ensure_ascii=False,
                                                separators=(",", ":"),
                                                default=str,
                                            ),
                                        ),
                                        xml_data_block("validation_code", failure),
                                        xml_data_block(
                                            "validation_feedback",
                                            candidate_profile_validation_feedback(failure),
                                        ),
                                        xml_data_block(
                                            "correction_evidence_boundary",
                                            json.dumps(
                                                _correction_evidence_boundary(
                                                    failure,
                                                    rejected_payload,
                                                    scope_blocks,
                                                ),
                                                ensure_ascii=False,
                                                separators=(",", ":"),
                                            ),
                                        ),
                                    )
                                )
                            )
                        )
                    with self._telemetry.operation(
                        "candidate_profile.model_attempt",
                        {
                            "scope_id": scope.scope_id,
                            "attempt": attempt,
                            "max_attempts": config.CANDIDATE_PROFILE_VALIDATION_ATTEMPTS,
                            "prompt_version": CANDIDATE_PROFILE_PROMPT_VERSION,
                            "configured_timeout_seconds": config.RECRUITMENT_MODEL_HTTP_TIMEOUT_SECONDS,
                            "transport_retries": config.RECRUITMENT_MODEL_TRANSPORT_RETRIES,
                        },
                    ) as attempt_span:
                        try:
                            response = bound_model.invoke(attempt_request)
                        except Exception as error:
                            attempt_span.set_attribute("status", "error")
                            attempt_span.set_attribute("error_type", type(error).__name__)
                            raise CandidateProfileTransportError(
                                scope_id=scope.scope_id,
                                attempt=attempt,
                                cause_type=type(error).__name__,
                                completed_scope_ids=tuple(completed_scope_ids),
                                checkpoint_id=checkpoint_id,
                                model_call_count=model_call_count,
                                input_tokens=input_tokens or None,
                                output_tokens=output_tokens or None,
                            ) from error
                        usage = getattr(response, "usage_metadata", None) or {}
                        response_model_name = getattr(response, "response_metadata", {}).get("model_name")
                        if response_model_name:
                            model_name = str(response_model_name)
                        attempt_span.set_attribute("model", model_name)
                        if usage.get("input_tokens") is not None:
                            attempt_span.set_attribute("input_tokens", int(usage["input_tokens"]))
                        if usage.get("output_tokens") is not None:
                            attempt_span.set_attribute("output_tokens", int(usage["output_tokens"]))
                        attempt_span.set_attribute("status", "success")
                        attempt_span.set_attribute("error_type", "")
                    input_tokens += int(usage.get("input_tokens") or 0)
                    output_tokens += int(usage.get("output_tokens") or 0)
                    with self._telemetry.operation(
                        "candidate_profile.validation",
                        {"scope_id": scope.scope_id, "attempt": attempt},
                    ) as validation_span:
                        submitted_payload, failed_output, failure = _response_payload(response)
                        rejected_payload = submitted_payload
                        payload = submitted_payload
                        if submitted_payload is not None:
                            payload, failure = _validate_submission(submitted_payload, scope_blocks)
                        validation_span.set_attribute("validation_code", failure)
                        validation_span.set_attribute("accepted", payload is not None)
                        validation_span.set_attribute(
                            "retry_triggered",
                            payload is None and attempt < config.CANDIDATE_PROFILE_VALIDATION_ATTEMPTS,
                        )
                    if failure:
                        validation_codes.append(failure)
                        exhausted = attempt == config.CANDIDATE_PROFILE_VALIDATION_ATTEMPTS
                        self._save_retry_feedback(
                            checkpoint_id,
                            scope.scope_id,
                            {
                                "failed_output": failed_output,
                                "rejected_payload": rejected_payload,
                                "validation_code": failure,
                                "next_attempt": attempt if exhausted else attempt + 1,
                                "exhausted": exhausted,
                            },
                        )
                        continue
                    break

                if payload is None:
                    scope_span.set_attribute("status", "error")
                    scope_span.set_attribute("error_type", "CandidateProfileValidationError")
                    raise CandidateProfileValidationError(
                        failure,
                        failed_output,
                        attempt_count=model_call_count,
                        model_name=model_name,
                        input_tokens=input_tokens or None,
                        output_tokens=output_tokens or None,
                        validation_codes=tuple(validation_codes),
                        checkpoint_id=checkpoint_id,
                        completed_scope_ids=tuple(completed_scope_ids),
                    )
                self._clear_retry_feedback(checkpoint_id, scope.scope_id)
                if self._checkpoint_store is not None:
                    self._checkpoint_store.save(checkpoint_id, scope.scope_id, payload)
                accepted_fields.extend(payload["fields"])
                completed_scope_ids.append(scope.scope_id)
                scope_span.set_attribute("checkpoint_hit", False)
                scope_span.set_attribute("status", "success")

        if not accepted_fields:
            raise CandidateProfileValidationError(
                "profile:empty",
                {"fields": []},
                attempt_count=model_call_count,
                model_name=model_name,
                input_tokens=input_tokens or None,
                output_tokens=output_tokens or None,
                validation_codes=tuple(validation_codes),
                checkpoint_id=checkpoint_id,
                completed_scope_ids=tuple(completed_scope_ids),
            )
        accepted_fields = _canonicalize_profile_fields(accepted_fields)

        fields = tuple(
            CandidateProfileField(
                field_id=str(item["field_id"]).strip(),
                category=item["category"],
                statement=unescape(str(item["statement"])).strip(),
                resume_evidence_ids=tuple(str(value) for value in item["resume_evidence_ids"]),
                evidence_quotes=tuple(unescape(str(value)) for value in item["evidence_quotes"]),
                evidence_kind=item["evidence_kind"],
                evidence_support_score=int(item["evidence_support_score"]),
                score_reason=unescape(str(item["score_reason"])).strip(),
            )
            for item in accepted_fields
        )
        cited_ids = {evidence_id for field in fields for evidence_id in field.resume_evidence_ids}
        cited = tuple(
            CandidateProfileEvidence(
                evidence_id=block_id,
                kind=str(blocks[block_id].get("kind") or ""),
                text=str(blocks[block_id].get("text") or ""),
                source_locator=str((blocks[block_id].get("source") or {}).get("locator") or ""),
                section_key=str(blocks[block_id].get("section_key") or ""),
            )
            for block_id in blocks
            if block_id in cited_ids
        )
        return CandidateProfileRun(
            profile=CandidateEvidenceProfile(
                profile_version=CANDIDATE_PROFILE_PROMPT_VERSION,
                resume_document_id=str(resume_document["document_id"]),
                resume_revision=str(resume_document["revision"]),
                fields=fields,
                cited_resume_evidence=cited,
            ),
            model_name=model_name,
            attempt_count=model_call_count,
            input_tokens=input_tokens or None,
            output_tokens=output_tokens or None,
            validation_codes=tuple(validation_codes),
            scope_count=len(scopes),
            model_call_count=model_call_count,
            checkpoint_hit_count=checkpoint_hit_count,
            checkpoint_id=checkpoint_id,
        )


class LangChainCandidateProfilerFactory:
    """Provider-neutral factory that binds one explicit model to durable checkpoints."""

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
        self._model = model
        self._telemetry = telemetry or OpenTelemetryRecorder()
        self.model_name = str(getattr(model, "model_name", "") or getattr(model, "model", "") or type(model).__name__)

    def create(
        self,
        checkpoint_store: CandidateProfileCheckpointStore,
    ) -> CandidateProfiler:
        return LangChainCandidateProfiler(
            self._model,
            telemetry=self._telemetry,
            checkpoint_store=checkpoint_store,
        )


class ScriptedCandidateProfilerFactory:
    """Deterministic adapter that still exercises checkpoint persistence."""

    def __init__(
        self,
        runs: list[CandidateProfileRun | Exception],
        *,
        model_name: str = "scripted-candidate-profiler",
        enforce_resume_identity: bool = False,
    ):
        self._runs = iter(runs)
        self.model_name = model_name
        self._enforce_resume_identity = enforce_resume_identity

    def create(
        self,
        checkpoint_store: CandidateProfileCheckpointStore,
    ) -> CandidateProfiler:
        runs = self._runs
        enforce_resume_identity = self._enforce_resume_identity

        class ScriptedCandidateProfiler:
            def profile(self, resume_document: dict[str, Any]) -> CandidateProfileRun:
                result = next(runs)
                if isinstance(result, Exception):
                    raise result
                if enforce_resume_identity and (
                    result.profile.resume_document_id != resume_document.get("document_id")
                    or result.profile.resume_revision != resume_document.get("revision")
                ):
                    raise CandidateProfileValidationError(
                        "profile:resume_identity_mismatch",
                        None,
                        model_name=result.model_name,
                        checkpoint_id=result.checkpoint_id,
                    )
                checkpoint_store.save(
                    result.checkpoint_id,
                    "scripted_01",
                    {
                        "fields": [
                            {
                                "field_id": field.field_id,
                                "category": field.category,
                                "statement": field.statement,
                                "resume_evidence_ids": list(field.resume_evidence_ids),
                                "evidence_quotes": list(field.evidence_quotes),
                                "evidence_kind": field.evidence_kind,
                                "evidence_support_score": field.evidence_support_score,
                                "score_reason": field.score_reason,
                            }
                            for field in result.profile.fields
                        ]
                    },
                )
                return result

        return ScriptedCandidateProfiler()
