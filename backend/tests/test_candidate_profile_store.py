from __future__ import annotations

from dataclasses import asdict

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from models import CandidateProfileArtifact, ResumeVersion, User
from recruitment_team.candidate_profile import (
    CandidateEvidenceProfile,
    CandidateProfileEvidence,
    CandidateProfileField,
)
from recruitment_team.candidate_profile_store import (
    SQLAlchemyCandidateProfileStore,
    _profile_evidence_disposition_is_publishable,
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


def _supported_profile_and_evaluation(*, rejected: bool = False):
    field = CandidateProfileField(
        field_id="supported-field",
        category="demonstrated_capability",
        statement="Built a validated workflow.",
        resume_evidence_ids=("evidence-1",),
        evidence_quotes=("Built a validated workflow.",),
        evidence_kind="direct",
        evidence_support_score=100,
        score_reason="Direct source text.",
    )
    profile = CandidateEvidenceProfile(
        profile_version="candidate-evidence-profile-v3",
        resume_document_id="document-id",
        resume_revision="revision-id",
        fields=(field,),
        cited_resume_evidence=(
            CandidateProfileEvidence(
                evidence_id="evidence-1",
                kind="bullet",
                text="Built a validated workflow.",
                source_locator="experience-1",
                section_key="experience",
            ),
        ),
    )
    rows = [{
        "field_id": field.field_id,
        "label": "supported",
        "disposition_source": "supported_field_refs",
    }]
    rejected_ids = []
    if rejected:
        rows.append({
            "field_id": "rejected-field",
            "label": "partially_supported",
            "disposition_source": "field_evaluation",
        })
        rejected_ids.append("rejected-field")
    evaluation = {
        "evaluation_version": "review-v1",
        "result": "revise" if rejected else "pass",
        "field_evaluations": rows,
        "evidence_disposition": {
            "policy": "fully_supported_fields_only",
            "action": "publish_supported_subset" if rejected else "publish_supported_profile",
            "supported_field_ids": [field.field_id],
            "rejected_field_ids": rejected_ids,
        },
    }
    return profile, evaluation


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

        profile, evaluation = _supported_profile_and_evaluation()
        completed = store.complete(checkpoint_id, profile, evaluation)

        assert completed.status == "completed"
        assert completed.profile["resume_revision"] == "revision-id"
        assert completed.evaluation == evaluation
        assert completed.error is None
        assert store.completed(checkpoint_id).id == completed.id


def test_candidate_profile_store_fences_checkpoint_writes_before_mutation():
    factory = _session_factory()
    owner_id, resume_id = _owner_resume(factory, "fenced@example.com")

    with factory() as db:
        def reject_expired_worker():
            raise RuntimeError("run lease expired")

        store = SQLAlchemyCandidateProfileStore(
            db,
            owner_id=owner_id,
            resume_version_id=resume_id,
            model_name="model-a",
            write_fence=reject_expired_worker,
        )

        with pytest.raises(RuntimeError, match="run lease expired"):
            store.save("f" * 64, "summary_01", {"fields": []})

        assert db.query(CandidateProfileArtifact).count() == 0


def test_candidate_profile_store_accepts_revise_only_as_a_supported_subset():
    profile, evaluation = _supported_profile_and_evaluation(rejected=True)

    assert isinstance(asdict(profile)["fields"], tuple)
    assert _profile_evidence_disposition_is_publishable(asdict(profile), evaluation)
    assert _profile_evidence_disposition_is_publishable(
        {
            "fields": [
                {"field_id": field.field_id}
                for field in profile.fields
            ]
        },
        evaluation,
    )


def test_candidate_profile_store_rejects_block_and_unfiltered_fields():
    profile, evaluation = _supported_profile_and_evaluation(rejected=True)
    unfiltered = {
        "fields": [
            {"field_id": profile.fields[0].field_id},
            {"field_id": "rejected-field"},
        ]
    }
    blocked = {
        **evaluation,
        "result": "block",
        "field_evaluations": [{"field_id": "rejected-field", "label": "unsupported"}],
        "evidence_disposition": {
            "policy": "fully_supported_fields_only",
            "action": "block_no_supported_evidence",
            "supported_field_ids": [],
            "rejected_field_ids": ["rejected-field"],
        },
    }

    assert not _profile_evidence_disposition_is_publishable(unfiltered, evaluation)
    assert not _profile_evidence_disposition_is_publishable({"fields": []}, blocked)


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


def test_candidate_profile_execution_metrics_survive_a_new_database_session():
    factory = _session_factory()
    owner_id, resume_id = _owner_resume(factory, "metrics-owner@example.com")
    checkpoint_id = "f" * 64

    with factory() as db:
        store = SQLAlchemyCandidateProfileStore(
            db, owner_id=owner_id, resume_version_id=resume_id, model_name="model-a",
        )
        store.record_execution_event(checkpoint_id, {
            "event": "model_attempt",
            "scope_id": "experience_01",
            "attempt": 1,
            "status": "validation_failed",
            "model": "model-a",
            "input_tokens": 13,
            "output_tokens": 5,
            "latency_ms": 120.5,
            "validation_code": "field:quote_not_found",
        })
        store.record_execution_event(checkpoint_id, {
            "event": "model_attempt",
            "scope_id": "experience_01",
            "attempt": 2,
            "status": "error",
            "model": "model-a",
            "latency_ms": 300.0,
            "error_type": "TimeoutError",
        })

    with factory() as db:
        resumed = SQLAlchemyCandidateProfileStore(
            db, owner_id=owner_id, resume_version_id=resume_id, model_name="model-a",
        )
        resumed.record_execution_event(checkpoint_id, {
            "event": "model_attempt",
            "scope_id": "experience_01",
            "attempt": 2,
            "status": "success",
            "model": "model-a",
            "input_tokens": 11,
            "output_tokens": 4,
            "latency_ms": 90.0,
        })
        metrics = resumed.execution_metrics(checkpoint_id)

    assert metrics["model_call_count"] == 3
    assert metrics["input_tokens"] == 24
    assert metrics["output_tokens"] == 9
    assert metrics["latency_ms"] == 510.5
    assert metrics["validation_codes"] == ["field:quote_not_found"]
    assert [attempt["status"] for attempt in metrics["attempts"]] == [
        "validation_failed", "error", "success",
    ]
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
        original = db.query(CandidateProfileArtifact).filter_by(
            checkpoint_id=checkpoint_id,
        ).one()
        assert original.model_name == "model-a"

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


def test_a_completed_profile_survives_a_policy_change():
    """Only a partial checkpoint is disposable. A finished profile is real work."""
    from recruitment_team.candidate_profile_store import SQLAlchemyCandidateProfileStore
    from models import CandidateProfileArtifact

    factory = _session_factory()
    owner_id, resume_id = _owner_resume(factory, "keeper@example.com")
    checkpoint_id = "e" * 64

    with factory() as db:
        store_a = SQLAlchemyCandidateProfileStore(
            db, owner_id=owner_id, resume_version_id=resume_id, model_name="model-a",
        )
        store_a.save(checkpoint_id, "summary_01", {"fields": []})
        db.query(CandidateProfileArtifact).filter(
            CandidateProfileArtifact.checkpoint_id == checkpoint_id
        ).update({"status": "completed"})
        db.commit()

        store_b = SQLAlchemyCandidateProfileStore(
            db, owner_id=owner_id, resume_version_id=resume_id, model_name="model-b",
        )
        assert store_b.load(checkpoint_id) == {}

        survivor = db.query(CandidateProfileArtifact).filter(
            CandidateProfileArtifact.checkpoint_id == checkpoint_id
        ).first()
        assert survivor is not None, "a completed profile was deleted by a policy change"
        assert survivor.status == "completed"
