"""SQLAlchemy persistence for resumable target-role profiling."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from models import RoleProfileArtifact

from .role_evidence_assessor import (
    RoleEvidenceCheckpoint,
    public_role_evidence_validation_code,
)


_PUBLIC_VALIDATION_CODES = {
    "invalid_criterion_ids:duplicate",
    "invalid_criterion_ids:empty",
    "invalid_submission",
    "missing_correction_tool_call",
    "missing_criteria",
    "missing_tool_call",
    "output_truncated:length",
    "schema_validation",
    "search_result_unavailable",
    "unverified_tool_claim",
}
_PUBLIC_CRITERION_FAILURES = {
    "invalid_role_citation_path",
    "invalid_role_source",
    "missing_role_citation_fields",
    "missing_role_citations",
    "missing_role_sources",
    "missing_statement",
    "role_citation_excerpt_not_found",
    "role_citation_source_mismatch",
}


def public_role_validation_code(value: str) -> str:
    """Return a stable category without model text, IDs, quotes, or numbers."""

    code = value.strip()
    stage, separator, staged_code = code.partition(":")
    if separator and stage in {"assessor", "generator"}:
        return f"{stage}:{public_role_validation_code(staged_code)}"
    evidence_code = public_role_evidence_validation_code(code)
    if evidence_code != "role_evidence:invalid":
        return evidence_code
    if code in _PUBLIC_VALIDATION_CODES:
        return code
    if code.startswith("criterion:"):
        failure = code.rpartition(":")[2]
        if failure in _PUBLIC_CRITERION_FAILURES:
            return f"criterion:{failure}"
    return "role_profile:invalid"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _sha256(value) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def role_profile_identity(*, candidate_profile, target, comparable_jobs, profiler) -> dict:
    configuration = profiler.checkpoint_identity()
    target_payload = asdict(target)
    comparable_payload = [asdict(job) for job in comparable_jobs]
    identity = {
        "target_sha256": target.source.snapshot_sha256 or _sha256(target_payload),
        "comparable_sha256": _sha256(comparable_payload),
        "candidate_profile_sha256": _sha256(asdict(candidate_profile)),
        "prompt_sha256": _sha256(configuration["prompts"]),
        "schema_sha256": _sha256(configuration["schemas"]),
        "model_sha256": _sha256(configuration["models"]),
        "source_identity_sha256": _sha256(
            {
                "target": target_payload,
                "comparables": comparable_payload,
                "configured_sources": configuration["sources"],
            }
        ),
    }
    return {**identity, "fingerprint": _sha256(identity)}


class RoleProfileCheckpointMismatch(RuntimeError):
    def __init__(self, artifact_id: str):
        super().__init__(f"role profile checkpoint {artifact_id} has a different fingerprint")
        self.artifact_id = artifact_id


class SQLAlchemyRoleProfileStore:
    """Persist only the definition, rejected assessment, and validated result."""

    def __init__(
        self,
        db: Session,
        *,
        owner_id: int,
        thread_id: str,
        run_id: str,
        resume_version_id: int,
        target_job_id: int,
        identity: dict,
    ):
        self._db = db
        self._owner_id = owner_id
        self._thread_id = thread_id
        self._run_id = run_id
        self._resume_version_id = resume_version_id
        self._target_job_id = target_job_id
        self._identity = identity
        self._record = self._find()

    def _find(self) -> RoleProfileArtifact | None:
        record = (
            self._db.query(RoleProfileArtifact)
            .filter(
                RoleProfileArtifact.user_id == self._owner_id,
                RoleProfileArtifact.thread_id == self._thread_id,
                RoleProfileArtifact.run_id == self._run_id,
            )
            .first()
        )
        if record is not None:
            if record.identity != self._identity:
                raise RoleProfileCheckpointMismatch(record.id)
            return record
        return (
            self._db.query(RoleProfileArtifact)
            .filter(
                RoleProfileArtifact.user_id == self._owner_id,
                RoleProfileArtifact.thread_id == self._thread_id,
                RoleProfileArtifact.fingerprint == self._identity["fingerprint"],
                RoleProfileArtifact.status == "completed",
            )
            .order_by(RoleProfileArtifact.updated_at.desc())
            .first()
        )

    def _create(self) -> RoleProfileArtifact:
        record = RoleProfileArtifact(
            id=str(uuid.uuid4()),
            user_id=self._owner_id,
            thread_id=self._thread_id,
            run_id=self._run_id,
            resume_version_id=self._resume_version_id,
            target_job_id=self._target_job_id,
            fingerprint=self._identity["fingerprint"],
            identity=self._identity,
            status="running",
        )
        self._db.add(record)
        self._record = record
        return record

    def start(self) -> None:
        if self._record is None:
            self._create()
            self._db.commit()

    def completed(self) -> dict | None:
        if self._record is None or self._record.status != "completed":
            return None
        return dict(self._record.result or {}) or None

    def error_detail(self) -> dict:
        return dict(self._record.error or {}) if self._record else {}

    def definition(self) -> dict | None:
        return dict(self._record.definition) if self._record and self._record.definition else None

    def assessment(self) -> RoleEvidenceCheckpoint | None:
        payload = self._record.assessment_checkpoint if self._record else None
        if not payload:
            return None
        return RoleEvidenceCheckpoint(
            validation_code=str(payload["validation_code"]),
            rejected_submission=dict(payload["rejected_submission"]),
            validation_codes=tuple(str(value) for value in payload.get("validation_codes") or []),
            attempt_count=int(payload["attempt_count"]),
            full_attempt_count=int(payload["full_attempt_count"]),
            corrected_criterion_ids=tuple(
                str(value) for value in payload.get("corrected_criterion_ids") or []
            ),
            previous_scope=str(payload["previous_scope"]),
            input_tokens=int(payload.get("input_tokens") or 0),
            output_tokens=int(payload.get("output_tokens") or 0),
        )

    def save_definition(self, definition: dict) -> None:
        record = self._record or self._create()
        record.definition = definition
        record.status = "definition_validated"
        record.error = None
        record.updated_at = _utcnow()
        self._db.commit()

    def save_assessment(self, checkpoint: RoleEvidenceCheckpoint) -> None:
        record = self._record or self._create()
        record.assessment_checkpoint = asdict(checkpoint)
        record.status = "assessment_rejected"
        record.error = {
            "attempted_stage": "role_evidence",
            "validation_code": public_role_validation_code(checkpoint.validation_code),
            "correction_scope": checkpoint.previous_scope,
            "partial_artifact_id": record.id,
            "retryable": True,
            "alternatives": ["retry_incomplete_stage", "start_new_logical_run"],
        }
        record.updated_at = _utcnow()
        self._db.commit()

    def fail(self, detail: dict) -> None:
        record = self._record or self._create()
        if detail.get("validation_code"):
            detail = {
                **detail,
                "validation_code": public_role_validation_code(str(detail["validation_code"])),
            }
        record.error = {**(record.error or {}), **detail, "partial_artifact_id": record.id}
        record.updated_at = _utcnow()
        self._db.commit()

    def complete(self, result: dict) -> None:
        record = self._record or self._create()
        record.status = "completed"
        record.result = result
        record.assessment_checkpoint = None
        record.error = None
        record.updated_at = _utcnow()
        self._db.commit()
