from __future__ import annotations

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from models import ResumeVersion, User
from recruitment_team.candidate_profile import CandidateEvidenceProfile
from recruitment_team.candidate_profile_store import (
    SQLAlchemyCandidateProfileStore,
)


def _session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _owner_resume(factory, email: str) -> tuple[int, int]:
    with factory() as db:
        user = User(email=email, password_hash="test-only", name="Candidate")  # pragma: allowlist secret
        db.add(user)
        db.flush()
        resume = ResumeVersion(
            user_id=user.id,
            label="Master",
            resume_text="EXPERIENCE\n- Built a validated workflow.",
        )
        db.add(resume)
        db.commit()
        return user.id, resume.id


def test_candidate_profile_store_persists_scopes_failure_and_completion():
    factory = _session_factory()
    owner_id, resume_id = _owner_resume(factory, "owner@example.com")
    checkpoint_id = "a" * 64
    scope_payload = {"fields": []}

    with factory() as db:
        store = SQLAlchemyCandidateProfileStore(
            db,
            owner_id=owner_id,
            resume_version_id=resume_id,
            model_name="model-a",
        )
        store.save(checkpoint_id, "summary_01", scope_payload)
        failed = store.fail(
            checkpoint_id,
            {
                "cause_type": "APITimeoutError",
                "failed_scope_id": "experience_01",
            },
        )

        assert failed.status == "failed"
        assert store.load(checkpoint_id) == {"summary_01": scope_payload}

        profile = CandidateEvidenceProfile(
            profile_version="candidate-evidence-profile-v3",
            resume_document_id="document-id",
            resume_revision="revision-id",
            fields=(),
            cited_resume_evidence=(),
        )
        completed = store.complete(checkpoint_id, profile)

        assert completed.status == "completed"
        assert completed.profile["resume_revision"] == "revision-id"
        assert completed.error is None
        assert store.completed(checkpoint_id).id == completed.id


def test_candidate_profile_store_keeps_retry_feedback_out_of_completed_scopes():
    factory = _session_factory()
    owner_id, resume_id = _owner_resume(factory, "retry-owner@example.com")
    checkpoint_id = "c" * 64
    feedback = {
        "failed_output": {"tool_calls": []},
        "rejected_payload": {"fields": []},
        "validation_code": "field:summary:quote_not_found",
        "next_attempt": 2,
    }

    with factory() as db:
        store = SQLAlchemyCandidateProfileStore(
            db,
            owner_id=owner_id,
            resume_version_id=resume_id,
            model_name="model-a",
        )
        store.save(checkpoint_id, "summary_01", {"fields": []})
        store.save_retry_feedback(checkpoint_id, "experience_01", feedback)

        assert store.load(checkpoint_id) == {"summary_01": {"fields": []}}
        assert store.load_retry_feedback(checkpoint_id, "experience_01") == feedback

        store.clear_retry_feedback(checkpoint_id, "experience_01")

        assert store.load_retry_feedback(checkpoint_id, "experience_01") is None
        assert store.load(checkpoint_id) == {"summary_01": {"fields": []}}


def test_candidate_profile_store_raises_a_distinct_error_on_checkpoint_mismatch():
    factory = _session_factory()
    owner_id, resume_id = _owner_resume(factory, "owner@example.com")
    checkpoint_id = "d" * 64

    with factory() as db:
        store_a = SQLAlchemyCandidateProfileStore(
            db,
            owner_id=owner_id,
            resume_version_id=resume_id,
            model_name="model-a",
        )
        store_a.save(checkpoint_id, "summary_01", {"fields": []})

        store_b = SQLAlchemyCandidateProfileStore(
            db,
            owner_id=owner_id,
            resume_version_id=resume_id,
            model_name="model-b",
        )
        # A superseded checkpoint is abandoned, not fatal. Raising here left the
        # candidate permanently unable to build a profile after any deploy that
        # changed a value inside execution_policy.
        assert store_b.load(checkpoint_id) == {}

        # And the next save starts a clean checkpoint under the new version.
        store_b.save(checkpoint_id, "summary_01", {"fields": [{"field_id": "f1"}]})
        assert store_b.load(checkpoint_id) == {"summary_01": {"fields": [{"field_id": "f1"}]}}


def test_candidate_profile_store_is_owner_isolated():
    factory = _session_factory()
    owner_id, resume_id = _owner_resume(factory, "owner@example.com")
    other_id, other_resume_id = _owner_resume(factory, "other@example.com")
    checkpoint_id = "b" * 64

    with factory() as db:
        owner_store = SQLAlchemyCandidateProfileStore(
            db,
            owner_id=owner_id,
            resume_version_id=resume_id,
            model_name="model-a",
        )
        other_store = SQLAlchemyCandidateProfileStore(
            db,
            owner_id=other_id,
            resume_version_id=other_resume_id,
            model_name="model-a",
        )
        owner_store.save(checkpoint_id, "summary_01", {"fields": []})

        assert owner_store.load(checkpoint_id) == {"summary_01": {"fields": []}}
        assert other_store.load(checkpoint_id) == {}
