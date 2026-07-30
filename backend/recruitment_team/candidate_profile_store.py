"""SQLAlchemy persistence for resumable Candidate Evidence Profiles."""

from __future__ import annotations

import logging
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from models import CandidateProfileArtifact

from .candidate_profile import (
    CANDIDATE_PROFILE_DECOMPOSITION_VERSION,
    CandidateEvidenceProfile,
    CandidateProfileCheckpointStore,
    candidate_profile_execution_policy,
)
from .prompts import CANDIDATE_PROFILE_PROMPT_VERSION

log = logging.getLogger("jobhunter.recruitment_team")


RETRY_FEEDBACK_SCOPE_KEY = "__retry_feedback__"


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
    ):
        self._db = db
        self._owner_id = owner_id
        self._resume_version_id = resume_version_id
        self._model_name = model_name

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
        """The stored checkpoint, or None when it belongs to a superseded version.

        A checkpoint exists to resume partial work. When the prompt, model,
        decomposition or execution policy has moved on, its scopes were produced
        under different rules and cannot be trusted, so it is abandoned and the
        caller starts a fresh one. Treating a stale optimisation as a hard
        failure left the candidate permanently unable to build a profile: any
        deploy that changed a validation-attempt count or a timeout, both of
        which sit inside execution_policy, bricked every existing checkpoint.
        """
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
            # Only a resumable partial checkpoint is disposable. A completed
            # artifact is the candidate's finished profile and is still read by
            # target assessment, so deleting it because a timeout constant moved
            # would destroy real work. Leave it and return None, which makes the
            # caller start a fresh checkpoint alongside it.
            if record.status == "completed":
                log.info(
                    "Superseded candidate-profile artifact %s is completed; "
                    "keeping it and starting a fresh checkpoint.",
                    checkpoint_id,
                )
                return None
            log.info(
                "Discarding partial candidate-profile checkpoint %s: built under "
                "a superseded prompt/model/decomposition/policy version.",
                checkpoint_id,
            )
            self._db.delete(record)
            self._db.flush()
            return None
        return record

    def load(self, checkpoint_id: str) -> dict[str, dict[str, Any]]:
        record = self._validated_record(checkpoint_id)
        return {
            key: value
            for key, value in (record.scopes if record is not None else {}).items()
            if key != RETRY_FEEDBACK_SCOPE_KEY
        }

    def save(
        self,
        checkpoint_id: str,
        scope_id: str,
        payload: dict[str, Any],
    ) -> None:
        record = self._validated_record(checkpoint_id) or self._create(checkpoint_id)
        scopes = dict(record.scopes)
        scopes[scope_id] = payload
        record.scopes = scopes
        record.status = "running"
        record.error = None
        record.updated_at = _utcnow()
        self._db.commit()

    def load_retry_feedback(
        self,
        checkpoint_id: str,
        scope_id: str,
    ) -> dict[str, Any] | None:
        record = self._validated_record(checkpoint_id)
        if record is None:
            return None
        retry_feedback = record.scopes.get(RETRY_FEEDBACK_SCOPE_KEY) or {}
        value = retry_feedback.get(scope_id)
        return dict(value) if isinstance(value, dict) else None

    def save_retry_feedback(
        self,
        checkpoint_id: str,
        scope_id: str,
        feedback: dict[str, Any],
    ) -> None:
        record = self._validated_record(checkpoint_id) or self._create(checkpoint_id)
        scopes = dict(record.scopes)
        retry_feedback = dict(scopes.get(RETRY_FEEDBACK_SCOPE_KEY) or {})
        retry_feedback[scope_id] = feedback
        scopes[RETRY_FEEDBACK_SCOPE_KEY] = retry_feedback
        record.scopes = scopes
        record.status = "running"
        record.error = None
        record.updated_at = _utcnow()
        self._db.commit()

    def clear_retry_feedback(self, checkpoint_id: str, scope_id: str) -> None:
        record = self._validated_record(checkpoint_id)
        if record is None:
            return
        scopes = dict(record.scopes)
        retry_feedback = dict(scopes.get(RETRY_FEEDBACK_SCOPE_KEY) or {})
        if scope_id not in retry_feedback:
            return
        retry_feedback.pop(scope_id)
        if retry_feedback:
            scopes[RETRY_FEEDBACK_SCOPE_KEY] = retry_feedback
        else:
            scopes.pop(RETRY_FEEDBACK_SCOPE_KEY, None)
        record.scopes = scopes
        record.updated_at = _utcnow()
        self._db.commit()

    def complete(
        self,
        checkpoint_id: str,
        profile: CandidateEvidenceProfile,
    ) -> CandidateProfileArtifact:
        record = self._validated_record(checkpoint_id)
        if record is None:
            raise ValueError("Candidate profile cannot complete without validated scopes")
        scopes = dict(record.scopes)
        scopes.pop(RETRY_FEEDBACK_SCOPE_KEY, None)
        record.scopes = scopes
        record.status = "completed"
        record.profile = asdict(profile)
        record.error = None
        record.updated_at = _utcnow()
        self._db.commit()
        self._db.refresh(record)
        return record

    def fail(self, checkpoint_id: str, error: dict[str, Any]) -> CandidateProfileArtifact:
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
