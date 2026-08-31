"""SQLAlchemy persistence for resumable Candidate Evidence Profiles."""

from __future__ import annotations

import logging
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from models import CandidateProfileArtifact

from .candidate_profile import (
    CANDIDATE_PROFILE_DECOMPOSITION_VERSION,
    CANDIDATE_PROFILE_PROMPT_VERSION,
    CANDIDATE_PROFILE_RECEIPT_VERSION,
    DETERMINISTIC_PROFILE_IMPLEMENTATION,
    CandidateEvidenceProfile,
    CandidateProfileCheckpointStore,
    candidate_profile_execution_policy,
    candidate_profile_sha256,
)
from .execution_metrics import merge_execution_event, merge_execution_metrics

log = logging.getLogger("jobhunter.recruitment_team")


def _profile_evidence_disposition_is_publishable(
    profile: dict | None,
    evaluation: dict | None,
) -> bool:
    """Require the stored profile to equal its validated evidence disposition."""
    if not isinstance(profile, dict) or not isinstance(evaluation, dict):
        return False
    profile_fields = profile.get("fields")
    disposition = evaluation.get("evidence_disposition")
    if (
        not isinstance(profile_fields, (list, tuple))
        or not profile_fields
        or not isinstance(disposition, dict)
        or not all(isinstance(item, dict) and item.get("field_id") for item in profile_fields)
    ):
        return False
    profile_ids = [str(item["field_id"]) for item in profile_fields]
    return (
        len(profile_ids) == len(set(profile_ids))
        and evaluation.get("receipt_version") == CANDIDATE_PROFILE_RECEIPT_VERSION
        and evaluation.get("implementation") == DETERMINISTIC_PROFILE_IMPLEMENTATION
        and evaluation.get("field_count") == len(profile_ids)
        and evaluation.get("profile_sha256") == candidate_profile_sha256(profile)
        and evaluation.get("result") == "pass"
        and disposition.get("policy") == DETERMINISTIC_PROFILE_IMPLEMENTATION
        and disposition.get("action") == "publish_exact_profile"
        and disposition.get("supported_field_ids") == profile_ids
        and disposition.get("rejected_field_ids") == []
    )


def candidate_profile_artifact_is_current(record: CandidateProfileArtifact) -> bool:
    from resume_document import SCHEMA_VERSION

    policy = record.execution_policy or {}
    evaluation = record.evaluation
    profile = record.profile
    return (
        _profile_evidence_disposition_is_publishable(profile, evaluation)
        and record.prompt_version == CANDIDATE_PROFILE_PROMPT_VERSION
        and record.decomposition_version == CANDIDATE_PROFILE_DECOMPOSITION_VERSION
        and policy.get("implementation") == DETERMINISTIC_PROFILE_IMPLEMENTATION
        and policy.get("resume_document_schema_version") == SCHEMA_VERSION
    )


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CandidateProfileCheckpointMismatch(RuntimeError):
    """A stored checkpoint no longer matches the currently configured prompt,
    model, decomposition, or execution-policy version and cannot be reused."""

    def __init__(self, checkpoint_id: str):
        super().__init__(
            f"candidate profile checkpoint {checkpoint_id} no longer matches the "
            "configured prompt, model, decomposition, or execution policy version"
        )
        self.checkpoint_id = checkpoint_id


class SQLAlchemyCandidateProfileStore(CandidateProfileCheckpointStore):
    """Persist only validated scopes, then publish one immutable profile payload."""

    def __init__(
        self,
        db: Session,
        *,
        owner_id: int,
        resume_version_id: int,
        model_name: str,
        write_fence: Callable[[], None] | None = None,
    ):
        self._db = db
        self._owner_id = owner_id
        self._resume_version_id = resume_version_id
        self._model_name = model_name
        self._write_fence = write_fence

    def _fence_write(self) -> None:
        if self._write_fence is not None:
            self._write_fence()

    def _record(self, checkpoint_id: str) -> CandidateProfileArtifact | None:
        return (
            self._db.query(CandidateProfileArtifact)
            .filter(
                CandidateProfileArtifact.user_id == self._owner_id,
                CandidateProfileArtifact.resume_version_id == self._resume_version_id,
                CandidateProfileArtifact.checkpoint_id == checkpoint_id,
            )
            .first()
        )

    def _create(self, checkpoint_id: str) -> CandidateProfileArtifact:
        existing = self._record(checkpoint_id)
        if existing is not None:
            if existing.status == "completed":
                raise CandidateProfileCheckpointMismatch(checkpoint_id)
            self._db.delete(existing)
            self._db.flush()
        record = CandidateProfileArtifact(
            id=str(uuid.uuid4()),
            user_id=self._owner_id,
            resume_version_id=self._resume_version_id,
            checkpoint_id=checkpoint_id,
            prompt_version=CANDIDATE_PROFILE_PROMPT_VERSION,
            decomposition_version=CANDIDATE_PROFILE_DECOMPOSITION_VERSION,
            model_name=self._model_name,
            execution_policy=candidate_profile_execution_policy(),
            status="running",
            scopes={},
        )
        self._db.add(record)
        return record

    def _validated_record(self, checkpoint_id: str) -> CandidateProfileArtifact | None:
        """Return a compatible partial checkpoint, otherwise start fresh."""
        record = self._record(checkpoint_id)
        if record is None:
            return None
        expected = (
            CANDIDATE_PROFILE_PROMPT_VERSION,
            CANDIDATE_PROFILE_DECOMPOSITION_VERSION,
            self._model_name,
            candidate_profile_execution_policy(),
        )
        actual = (
            record.prompt_version,
            record.decomposition_version,
            record.model_name,
            record.execution_policy,
        )
        if actual != expected:
            log.info(
                "Ignoring candidate-profile checkpoint %s built under a superseded "
                "prompt/model/decomposition/policy version.",
                checkpoint_id,
            )
            return None
        return record

    def load(self, checkpoint_id: str) -> dict[str, dict[str, Any]]:
        record = self._validated_record(checkpoint_id)
        return dict(record.scopes) if record is not None else {}

    def save(
        self,
        checkpoint_id: str,
        scope_id: str,
        payload: dict[str, Any],
    ) -> None:
        self._fence_write()
        record = self._validated_record(checkpoint_id) or self._create(checkpoint_id)
        scopes = dict(record.scopes)
        scopes[scope_id] = payload
        record.scopes = scopes
        record.status = "running"
        record.error = None
        record.updated_at = _utcnow()
        self._db.commit()

    def record_execution_event(self, checkpoint_id: str, event: dict[str, Any]) -> None:
        self._fence_write()
        record = self._validated_record(checkpoint_id) or self._create(checkpoint_id)
        record.execution_metrics = merge_execution_event(
            dict(record.execution_metrics or {}),
            {**event, "logical_run_id": checkpoint_id},
        )
        record.updated_at = _utcnow()
        self._db.commit()

    def execution_metrics(self, checkpoint_id: str) -> dict[str, Any]:
        record = self._validated_record(checkpoint_id)
        metrics = dict(record.execution_metrics or {}) if record is not None else {}
        return metrics

    def merge_execution_metrics(self, checkpoint_id: str, metrics: dict[str, Any]) -> None:
        self._fence_write()
        record = self._validated_record(checkpoint_id) or self._create(checkpoint_id)
        record.execution_metrics = merge_execution_metrics(record.execution_metrics, metrics)
        record.updated_at = _utcnow()
        self._db.commit()

    def complete(
        self,
        checkpoint_id: str,
        profile: CandidateEvidenceProfile,
        evaluation: dict | None = None,
    ) -> CandidateProfileArtifact:
        self._fence_write()
        record = self._validated_record(checkpoint_id)
        if record is None:
            raise ValueError("Candidate profile cannot complete without validated scopes")
        serialized_profile = asdict(profile)
        if not _profile_evidence_disposition_is_publishable(serialized_profile, evaluation):
            raise ValueError(
                "Candidate profile cannot complete without a publishable supported-evidence disposition"
            )
        record.status = "completed"
        record.profile = serialized_profile
        record.evaluation = evaluation
        record.error = None
        record.updated_at = _utcnow()
        self._db.commit()
        self._db.refresh(record)
        return record

    def fail(self, checkpoint_id: str, error: dict[str, Any]) -> CandidateProfileArtifact:
        self._fence_write()
        record = self._validated_record(checkpoint_id) or self._create(checkpoint_id)
        record.status = "failed"
        record.error = error
        record.updated_at = _utcnow()
        self._db.commit()
        self._db.refresh(record)
        return record

    def completed(self, checkpoint_id: str) -> CandidateProfileArtifact | None:
        record = self._validated_record(checkpoint_id)
        if record is None or record.status != "completed" or record.profile is None:
            return None
        return record
