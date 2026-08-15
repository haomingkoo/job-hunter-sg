from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from models import RecruitmentRun, RecruitmentThread, ResumeVersion, RoleProfileArtifact, User
from recruitment_team.role_evidence_assessor import RoleEvidenceCheckpoint
from recruitment_team.role_profile_store import (
    RoleProfileCheckpointMismatch,
    SQLAlchemyRoleProfileStore,
    role_profile_identity,
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


def _run(factory, email: str, run_id: str):
    with factory() as db:
        user = User(email=email, password_hash="test-only", name="Candidate")  # pragma: allowlist secret
        db.add(user)
        db.flush()
        resume = ResumeVersion(user_id=user.id, label="Master", resume_text="private resume text")
        db.add(resume)
        db.flush()
        thread = RecruitmentThread(id=f"thread-{run_id}", user_id=user.id, resume_version_id=resume.id)
        db.add(thread)
        db.flush()
        db.add(
            RecruitmentRun(
                id=run_id,
                user_id=user.id,
                thread_id=thread.id,
                idempotency_key=run_id,
                command_type="select_target_job",
                status="running",
                trace_key=f"trace-{run_id}",
            )
        )
        db.commit()
        return user.id, resume.id, thread.id


def _store(db, owner_id, resume_id, thread_id, run_id, identity):
    return SQLAlchemyRoleProfileStore(
        db,
        owner_id=owner_id,
        thread_id=thread_id,
        run_id=run_id,
        resume_version_id=resume_id,
        target_job_id=101,
        identity=identity,
    )


def test_role_profile_store_keeps_only_validated_definition_and_rejected_draft_private():
    factory = _session_factory()
    owner_id, resume_id, thread_id = _run(factory, "owner@example.com", "run-1")
    identity = {"fingerprint": "a" * 64, "candidate_profile_sha256": "b" * 64}
    definition = {"profile": {"criteria": [{"criterion_id": "c1"}]}, "attempt_count": 1}
    checkpoint = RoleEvidenceCheckpoint(
        validation_code="literal_quote:unsupported:c1",
        rejected_submission={"judgments": [{"criterion_id": "c1", "draft": True}]},
        validation_codes=("literal_quote:unsupported:c1",),
        attempt_count=1,
        full_attempt_count=1,
        corrected_criterion_ids=(),
        previous_scope="full",
    )

    with factory() as db:
        store = _store(db, owner_id, resume_id, thread_id, "run-1", identity)
        store.start()
        store.save_definition(definition)
        store.save_assessment(checkpoint)

        row = db.query(RoleProfileArtifact).one()
        assert row.status == "assessment_rejected"
        assert row.result is None
        assert store.completed() is None
        assert store.definition() == definition
        assert store.assessment() == checkpoint
        assert row.error["partial_artifact_id"] == row.id
        assert "private resume text" not in str(row.error)

        result = {"profile": {"criteria": []}, "model_name": "model-a", "attempt_count": 2}
        store.complete(result)
        assert store.completed() == result
        assert row.status == "completed"
        assert row.assessment_checkpoint is None
        assert row.error is None


def test_role_profile_store_rejects_changed_fingerprint_and_is_owner_isolated():
    factory = _session_factory()
    owner_id, resume_id, thread_id = _run(factory, "owner@example.com", "run-owner")
    other_id, other_resume_id, other_thread_id = _run(factory, "other@example.com", "run-other")
    identity = {"fingerprint": "a" * 64}

    with factory() as db:
        owner = _store(db, owner_id, resume_id, thread_id, "run-owner", identity)
        owner.start()
        owner.save_definition({"profile": {}, "attempt_count": 1})

        with pytest.raises(RoleProfileCheckpointMismatch):
            _store(
                db,
                owner_id,
                resume_id,
                thread_id,
                "run-owner",
                {"fingerprint": "c" * 64},
            )

        other = _store(db, other_id, other_resume_id, other_thread_id, "run-other", identity)
        assert other.definition() is None


def test_deleting_thread_cascades_role_profile_checkpoint():
    factory = _session_factory()
    owner_id, resume_id, thread_id = _run(factory, "owner@example.com", "run-delete")

    with factory() as db:
        store = _store(
            db,
            owner_id,
            resume_id,
            thread_id,
            "run-delete",
            {"fingerprint": "d" * 64},
        )
        store.start()
        db.delete(db.get(RecruitmentThread, thread_id))
        db.commit()

        assert db.query(RoleProfileArtifact).count() == 0


@dataclass(frozen=True)
class _Source:
    snapshot_sha256: str
    url: str = "https://example.test/job"


@dataclass(frozen=True)
class _Target:
    job_id: int
    title: str
    source: _Source


@dataclass(frozen=True)
class _Candidate:
    statement: str


class _Profiler:
    def __init__(self, configuration):
        self.configuration = configuration

    def checkpoint_identity(self):
        return self.configuration


def test_role_profile_fingerprint_changes_for_every_required_identity_dimension():
    configuration = {
        "prompts": {"definition": {"content": "prompt-a"}},
        "schemas": {"definition": {"properties": {"criteria": {"type": "array"}}}},
        "models": {"definition": {"model": "model-a"}},
        "sources": [{"source_id": "occupation-a", "content": "source-a"}],
    }
    candidate = _Candidate("candidate-a")
    target = _Target(1, "Target A", _Source("a" * 64))
    comparable = _Target(2, "Comparable A", _Source("b" * 64))

    def fingerprint(*, current_candidate=candidate, current_target=target, current_comparable=comparable, config=None):
        return role_profile_identity(
            candidate_profile=current_candidate,
            target=current_target,
            comparable_jobs=(current_comparable,),
            profiler=_Profiler(config or configuration),
        )["fingerprint"]

    baseline = fingerprint()
    prompt = deepcopy(configuration)
    prompt["prompts"]["definition"]["content"] = "prompt-b"
    schema = deepcopy(configuration)
    schema["schemas"]["definition"]["properties"]["criteria"]["type"] = "object"
    model = deepcopy(configuration)
    model["models"]["definition"]["model"] = "model-b"
    source = deepcopy(configuration)
    source["sources"][0]["content"] = "source-b"

    assert fingerprint(
        current_target=replace(target, source=replace(target.source, snapshot_sha256="c" * 64))
    ) != baseline
    assert fingerprint(current_comparable=replace(comparable, title="Comparable B")) != baseline
    assert fingerprint(current_candidate=replace(candidate, statement="candidate-b")) != baseline
    assert fingerprint(config=prompt) != baseline
    assert fingerprint(config=schema) != baseline
    assert fingerprint(config=model) != baseline
    assert fingerprint(config=source) != baseline


def test_production_checkpoint_identity_contains_real_prompt_and_tool_contracts():
    from recruitment_team.assessed_role_success import EvidenceAssessedRoleSuccessProfiler
    from recruitment_team.prompts import ROLE_SUCCESS_SYSTEM_PROMPT
    from recruitment_team.prompts.role_evidence_assessor import ROLE_EVIDENCE_ASSESSOR_SYSTEM_PROMPT
    from recruitment_team.role_evidence_assessor import ScriptedRoleEvidenceAssessor
    from recruitment_team.role_success import ScriptedRoleDefinitionGenerator

    identity = EvidenceAssessedRoleSuccessProfiler(
        ScriptedRoleDefinitionGenerator([]),
        ScriptedRoleEvidenceAssessor([]),
    ).checkpoint_identity()

    assert identity["prompts"]["definition"]["content"] == ROLE_SUCCESS_SYSTEM_PROMPT
    assert identity["prompts"]["assessment"]["content"] == ROLE_EVIDENCE_ASSESSOR_SYSTEM_PROMPT
    assert "properties" in identity["schemas"]["definition"]
    assert "properties" in identity["schemas"]["evidence"]["assessment"]
    assert "properties" in identity["schemas"]["evidence"]["correction"]
