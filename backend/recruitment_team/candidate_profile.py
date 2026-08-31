"""Role-neutral Candidate Evidence Profile over one immutable resume document."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from hashlib import sha256
from html import unescape
from typing import Any, Literal, Protocol
from uuid import uuid4

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
CANDIDATE_PROFILE_PROMPT_VERSION = "candidate-evidence-profile-v4"
CANDIDATE_PROFILE_RECEIPT_VERSION = "exact-extraction-receipt-v1"
CANDIDATE_PROFILE_DECOMPOSITION_VERSION = "extractive-whole-document-v5"
DETERMINISTIC_PROFILE_SCOPE = "deterministic_resume_evidence_v1"
DETERMINISTIC_PROFILE_MODEL = "deterministic-resume-index-v1"
DETERMINISTIC_PROFILE_IMPLEMENTATION = "deterministic_exact_extract_v1"
DETERMINISTIC_PROFILE_MAX_FIELDS = 48
EXACT_EXTRACTION_REASON = "Exact text from canonical resume evidence."
_CONTACT_BLOCK = re.compile(
    r"(?:[\w.+-]+@[\w-]+\.[\w.-]+|https?://|linkedin\.com|"
    r"\b(?:phone|mobile|tel)\b|\+\d[\d().\s-]{6,}\d|\b\d{4}\s\d{4}\b|\b[689]\d{7}\b)",
    re.IGNORECASE,
)


def candidate_profile_execution_policy() -> dict[str, str | int]:
    from resume_document import SCHEMA_VERSION

    return {
        "prompt_version": CANDIDATE_PROFILE_PROMPT_VERSION,
        "implementation": DETERMINISTIC_PROFILE_IMPLEMENTATION,
        "field_cap": DETERMINISTIC_PROFILE_MAX_FIELDS,
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
    evaluation: dict | None = None


@dataclass(frozen=True)
class CandidateProfileProgress:
    """Safe lifecycle metadata for one semantic resume scope."""

    transition: Literal["start", "checkpoint", "completion", "failure"]
    scope_id: str
    scope_count: int
    completed_scope_count: int
    attempt: int | None = None


CandidateProfileProgressPublisher = Callable[[CandidateProfileProgress], None]

_PROGRESS_SUMMARIES = {
    "start": "The candidate profiler started a resume scope.",
    "checkpoint": "The candidate profiler saved a validated scope checkpoint.",
    "completion": "The candidate profiler completed a resume scope.",
    "failure": "The candidate profiler stopped on a resume scope.",
}


def candidate_profile_progress_event(progress: CandidateProfileProgress) -> tuple[str, str, dict]:
    """Map internal progress to user-safe activity without resume or model content."""
    detail: dict[str, int | str] = {
        "transition": progress.transition,
        "scope_id": progress.scope_id,
        "scope_count": progress.scope_count,
        "completed_scope_count": progress.completed_scope_count,
    }
    if progress.attempt is not None:
        detail["attempt"] = progress.attempt
    status = "failed" if progress.transition == "failure" else "running"
    return status, _PROGRESS_SUMMARIES[progress.transition], detail


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


class CandidateProfiler(Protocol):
    def profile(self, resume_document: dict[str, Any]) -> CandidateProfileRun: ...


class CandidateProfilerFactory(Protocol):
    model_name: str

    def create(
        self,
        checkpoint_store: CandidateProfileCheckpointStore,
        progress_publisher: CandidateProfileProgressPublisher | None = None,
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

    def record_execution_event(self, checkpoint_id: str, event: dict[str, Any]) -> None: ...

    def execution_metrics(self, checkpoint_id: str) -> dict[str, Any]: ...


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(value)).strip()


def _canonical_field_id(
    *,
    category: str,
    statement: str,
    resume_evidence_ids: list[str] | tuple[str, ...],
    evidence_kind: str,
) -> str:
    identity = json.dumps(
        {
            "category": category,
            "statement": _normalize(statement),
            "resume_evidence_ids": sorted(str(value) for value in resume_evidence_ids),
            "evidence_kind": evidence_kind,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return f"{category}_{sha256(identity.encode()).hexdigest()}"


def _looks_like_unsectioned_header(block: dict[str, Any], index: int) -> bool:
    text = str(block.get("text") or "").strip()
    if not text or _CONTACT_BLOCK.search(text):
        return True
    words = [word.strip(",.") for word in text.split()]
    return bool(
        index == 0
        and 1 < len(words) <= 7
        and not re.search(r"[!?;:@|]", text)
        and all(word.replace("-", "").isalpha() for word in words)
        and all(word.istitle() or word.isupper() for word in words)
    )


def _profile_checkpoint_id(
    resume_document: dict[str, Any],
    configured_model_name: str,
) -> str:
    identity = json.dumps(
        {
            "resume_document_id": resume_document["document_id"],
            "resume_revision": resume_document["revision"],
            "prompt_version": CANDIDATE_PROFILE_PROMPT_VERSION,
            "decomposition_version": CANDIDATE_PROFILE_DECOMPOSITION_VERSION,
            "model": configured_model_name,
            "execution_policy": candidate_profile_execution_policy(),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(identity.encode()).hexdigest()


def _build_profile(
    resume_document: dict[str, Any],
    accepted_fields: list[dict[str, Any]],
) -> CandidateEvidenceProfile:
    blocks = {
        str(block["id"]): block
        for block in resume_document.get("blocks", [])
        if isinstance(block, dict) and block.get("id")
    }
    fields = tuple(
        CandidateProfileField(
            field_id=str(item["field_id"]).strip(),
            category=item["category"],
            statement=str(item["statement"]).strip(),
            resume_evidence_ids=tuple(str(value) for value in item["resume_evidence_ids"]),
            evidence_quotes=tuple(str(value) for value in item["evidence_quotes"]),
            evidence_kind=item["evidence_kind"],
            evidence_support_score=int(item["evidence_support_score"]),
            score_reason=str(item["score_reason"]).strip(),
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
    return CandidateEvidenceProfile(
        profile_version=CANDIDATE_PROFILE_PROMPT_VERSION,
        resume_document_id=str(resume_document["document_id"]),
        resume_revision=str(resume_document["revision"]),
        fields=fields,
        cited_resume_evidence=cited,
    )


def _whole_resume_blocks(ordered_blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return bounded, meaningful evidence blocks once, in source order."""

    from .fair_hiring import mentions_protected_status

    first_section_index = next(
        (index for index, block in enumerate(ordered_blocks) if block.get("section_key")),
        None,
    )
    selected = []
    for index, block in enumerate(ordered_blocks):
        text = str(block.get("text") or "").strip()
        if (
            block.get("kind") == "section_heading"
            or (first_section_index is not None and index < first_section_index)
            or (first_section_index is None and _looks_like_unsectioned_header(block, index))
            or str(block.get("section_key") or "") in {"summary", "objective", "personal"}
            or (
                not block.get("section_key")
                and text == text.upper()
                and len(text.split()) <= 3
            )
            or not text
            or _CONTACT_BLOCK.search(text)
            or mentions_protected_status(text)
        ):
            continue
        selected.append(block)
        if len(selected) == DETERMINISTIC_PROFILE_MAX_FIELDS:
            break
    return selected


def _deterministic_category(block: dict[str, Any]) -> ProfileCategory:
    section = str(block.get("section_key") or "")
    text = str(block.get("text") or "")
    kind = str(block.get("kind") or "")
    if section in {"education", "certifications", "awards"}:
        return "credential"
    if section in {"skills", "languages"}:
        return "stated_skill"
    if kind == "entry_heading" or re.search(
        r"\b(?:19|20)\d{2}\s*[-–—]|\b(?:present|current)\b",
        text,
        re.IGNORECASE,
    ):
        return "chronology"
    if section in {"experience", "projects", "activities", "career_break"}:
        return "demonstrated_capability"
    return "domain"


def _deterministic_fields(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map immutable source blocks to the existing profile wire contract."""

    fields = []
    seen: set[tuple[str, str]] = set()
    for block in blocks:
        statement = str(block.get("text") or "").strip()
        category = _deterministic_category(block)
        identity = (category, _normalize(statement))
        if identity in seen:
            continue
        seen.add(identity)
        evidence_id = str(block["id"])
        field_id = _canonical_field_id(
            category=category,
            statement=statement,
            resume_evidence_ids=[evidence_id],
            evidence_kind="direct",
        )
        fields.append(
            {
                "field_id": field_id,
                "category": category,
                "statement": statement,
                "resume_evidence_ids": [evidence_id],
                "evidence_quotes": [statement],
                "evidence_kind": "direct",
                "evidence_support_score": 100,
                "score_reason": EXACT_EXTRACTION_REASON,
            }
        )
    return fields


def _validated_deterministic_payload(
    resume_document: dict[str, Any],
    payload: dict[str, Any],
) -> tuple[dict[str, Any] | None, str]:
    ordered_blocks = [
        block
        for block in resume_document.get("blocks", [])
        if isinstance(block, dict) and block.get("id")
    ]
    expected = {"fields": _deterministic_fields(_whole_resume_blocks(ordered_blocks))}
    if payload != expected:
        return None, "profile:not_exact_deterministic_extraction"
    return expected, ""


def exact_extraction_receipt(profile: CandidateEvidenceProfile) -> dict:
    supported_ids = [field.field_id for field in profile.fields]
    return {
        "receipt_version": CANDIDATE_PROFILE_RECEIPT_VERSION,
        "implementation": DETERMINISTIC_PROFILE_IMPLEMENTATION,
        "result": "pass",
        "field_count": len(supported_ids),
        "profile_sha256": candidate_profile_sha256(profile),
        "evidence_disposition": {
            "policy": DETERMINISTIC_PROFILE_IMPLEMENTATION,
            "action": "publish_exact_profile",
            "supported_field_ids": supported_ids,
            "rejected_field_ids": [],
        },
    }


def candidate_profile_sha256(profile: CandidateEvidenceProfile | dict[str, Any]) -> str:
    payload = asdict(profile) if isinstance(profile, CandidateEvidenceProfile) else profile
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return sha256(canonical.encode()).hexdigest()


class DeterministicCandidateProfiler:
    """Index immutable resume evidence without a candidate-profile model call."""

    def __init__(
        self,
        *,
        checkpoint_store: CandidateProfileCheckpointStore,
        progress_publisher: CandidateProfileProgressPublisher | None = None,
    ):
        self._store = checkpoint_store
        self._progress_publisher = progress_publisher

    def _progress(self, transition: Literal["start", "checkpoint", "completion", "failure"]) -> None:
        if self._progress_publisher is not None:
            self._progress_publisher(
                CandidateProfileProgress(
                    transition=transition,
                    scope_id=DETERMINISTIC_PROFILE_SCOPE,
                    scope_count=1,
                    completed_scope_count=1 if transition == "completion" else 0,
                )
            )

    def profile(self, resume_document: dict[str, Any]) -> CandidateProfileRun:
        ordered_blocks = [
            block
            for block in resume_document.get("blocks", [])
            if isinstance(block, dict) and block.get("id")
        ]
        if not ordered_blocks or not resume_document.get("document_id") or not resume_document.get("revision"):
            raise ValueError("A canonical immutable resume document is required")

        checkpoint_id = _profile_checkpoint_id(resume_document, DETERMINISTIC_PROFILE_MODEL)
        self._progress("start")
        cached = self._store.load(checkpoint_id).get(DETERMINISTIC_PROFILE_SCOPE)
        checkpoint_hit_count = 0
        if cached is None:
            fields = _deterministic_fields(_whole_resume_blocks(ordered_blocks))
            if not fields:
                self._progress("failure")
                raise CandidateProfileValidationError(
                    "profile:empty",
                    {"fields": []},
                    model_name=DETERMINISTIC_PROFILE_MODEL,
                    checkpoint_id=checkpoint_id,
                )
            payload = {"fields": fields}
            accepted, failure = _validated_deterministic_payload(resume_document, payload)
            if accepted is None:
                self._progress("failure")
                raise CandidateProfileValidationError(
                    failure,
                    payload,
                    model_name=DETERMINISTIC_PROFILE_MODEL,
                    checkpoint_id=checkpoint_id,
                )
            self._store.save(checkpoint_id, DETERMINISTIC_PROFILE_SCOPE, accepted)
            self._store.record_execution_event(
                checkpoint_id,
                {
                    "event": "deterministic_extract",
                    "attempt_id": uuid4().hex,
                    "stage": "candidate_profile",
                    "scope_id": DETERMINISTIC_PROFILE_SCOPE,
                    "status": "success",
                    "implementation": DETERMINISTIC_PROFILE_IMPLEMENTATION,
                },
            )
            self._progress("checkpoint")
        else:
            accepted, failure = _validated_deterministic_payload(resume_document, cached)
            if accepted is None:
                self._progress("failure")
                raise CandidateProfileValidationError(
                    f"checkpoint:{DETERMINISTIC_PROFILE_SCOPE}:{failure}",
                    cached,
                    model_name=DETERMINISTIC_PROFILE_MODEL,
                    checkpoint_id=checkpoint_id,
                )
            checkpoint_hit_count = 1
            self._store.record_execution_event(
                checkpoint_id,
                {
                    "event": "checkpoint_hit",
                    "attempt_id": uuid4().hex,
                    "stage": "candidate_profile",
                    "scope_id": DETERMINISTIC_PROFILE_SCOPE,
                    "status": "success",
                    "implementation": DETERMINISTIC_PROFILE_IMPLEMENTATION,
                },
            )
            self._progress("checkpoint")

        profile = _build_profile(resume_document, accepted["fields"])
        self._progress("completion")
        return CandidateProfileRun(
            profile=profile,
            model_name=DETERMINISTIC_PROFILE_MODEL,
            attempt_count=0,
            validation_codes=(),
            scope_count=1,
            model_call_count=0,
            checkpoint_hit_count=checkpoint_hit_count,
            checkpoint_id=checkpoint_id,
            evaluation=exact_extraction_receipt(profile),
        )


class DeterministicCandidateProfilerFactory:
    """Production factory for the zero-model candidate evidence indexer."""

    model_name = DETERMINISTIC_PROFILE_MODEL

    def create(
        self,
        checkpoint_store: CandidateProfileCheckpointStore,
        progress_publisher: CandidateProfileProgressPublisher | None = None,
    ) -> CandidateProfiler:
        return DeterministicCandidateProfiler(
            checkpoint_store=checkpoint_store,
            progress_publisher=progress_publisher,
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
        progress_publisher: CandidateProfileProgressPublisher | None = None,
    ) -> CandidateProfiler:
        runs = self._runs
        enforce_resume_identity = self._enforce_resume_identity

        class ScriptedCandidateProfiler:
            def profile(self, resume_document: dict[str, Any]) -> CandidateProfileRun:
                result = next(runs)
                if isinstance(result, Exception):
                    raise result
                if progress_publisher is not None:
                    progress_publisher(
                        CandidateProfileProgress(
                            transition="start",
                            scope_id="scripted_01",
                            scope_count=1,
                            completed_scope_count=0,
                        )
                    )
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
                if progress_publisher is not None:
                    progress_publisher(
                        CandidateProfileProgress(
                            transition="checkpoint",
                            scope_id="scripted_01",
                            scope_count=1,
                            completed_scope_count=0,
                        )
                    )
                    progress_publisher(
                        CandidateProfileProgress(
                            transition="completion",
                            scope_id="scripted_01",
                            scope_count=1,
                            completed_scope_count=1,
                        )
                    )
                return result

        return ScriptedCandidateProfiler()
