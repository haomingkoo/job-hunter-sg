"""Agent-drafted resume edits must be reviewable, and accepting must be reversible.

Before this surface existed, ProposedResumeEdit had one INSERT and no readers:
edits were drafted, stored, and shown to nobody, so the pending status could
never be resolved. These tests pin the read path and the accept semantics.
"""

from __future__ import annotations

import hashlib
import uuid

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from models import ProposedResumeEdit, RecruitmentRun, ResumeVersion, User


RESUME_TEXT = (
    "Built a self-service Kubernetes platform used by 120 engineers.\n"
    "Ran vLLM inference clusters on AMD MI300X.\n"
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


def _team(db):
    from recruitment_team import RecruitmentTeam, ScriptedConversationModel
    from recruitment_team.candidate_profile import ScriptedCandidateProfilerFactory
    from recruitment_team.discovery import ScriptedDiscovery
    from recruitment_team.role_success import ScriptedRoleSuccessProfiler
    from recruitment_team.telemetry import RecordedTelemetry
    from recruitment_team.activity_publisher import RecordedActivityPublisher

    from backend.tests.test_recruitment_team_module import _candidate_profile_run

    return RecruitmentTeam(
        db,
        ScriptedConversationModel(["Understood."]),
        ScriptedDiscovery([]),
        ScriptedRoleSuccessProfiler([]),
        RecordedTelemetry(),
        RecordedActivityPublisher(),
        candidate_profiler_factory_provider=(
            lambda: ScriptedCandidateProfilerFactory([_candidate_profile_run()])
        ),
    )


def _thread_with_edits(db, edits):
    """Seed an owner, resume and thread, then attach `edits` as pending drafts."""
    from recruitment_team.interface import StartThread

    user = User(email="c@example.com", password_hash="test-only", name="C")  # pragma: allowlist secret
    db.add(user)
    db.flush()
    resume = ResumeVersion(
        user_id=user.id,
        label="Master",
        resume_text=RESUME_TEXT,
        is_master=True,
    )
    db.add(resume)
    db.commit()

    started = _team(db).execute(
        user.id,
        StartThread(resume_version_id=resume.id, message="Find me platform roles."),
        idempotency_key=f"start-{uuid.uuid4()}",
    )
    run_id = db.query(RecruitmentRun).filter(RecruitmentRun.thread_id == started.thread_id).first().id

    from resume_document import create_resume_document

    revision = create_resume_document(RESUME_TEXT)["revision"]
    for original, rewrite in edits:
        db.add(
            ProposedResumeEdit(
                id=str(uuid.uuid4()),
                user_id=user.id,
                thread_id=started.thread_id,
                run_id=run_id,
                resume_version_id=resume.id,
                block_id=f"block-{uuid.uuid4().hex[:8]}",
                original=original,
                rewrite=rewrite,
                document_revision=revision,
                status="pending",
            )
        )
    db.commit()
    return user.id, resume.id, started.thread_id


def test_pending_edits_are_listed_with_their_applicability():
    sessions = _session_factory()
    with sessions() as db:
        owner_id, _, thread_id = _thread_with_edits(
            db,
            [
                ("Ran vLLM inference clusters on AMD MI300X.", "Operated vLLM inference clusters on AMD MI300X GPUs."),
                ("A line that is not in the resume.", "Anything."),
            ],
        )

        listed = _team(db).proposed_edits(owner_id, thread_id)

        assert len(listed) == 2
        assert [edit["applicable"] for edit in listed] == [True, False]


def test_accepting_writes_a_new_version_and_leaves_the_source_untouched():
    sessions = _session_factory()
    with sessions() as db:
        owner_id, resume_id, thread_id = _thread_with_edits(
            db,
            [("Ran vLLM inference clusters on AMD MI300X.", "Operated vLLM inference clusters on AMD MI300X GPUs.")],
        )

        result = _team(db).accept_proposed_edits(owner_id, thread_id)

        created = db.query(ResumeVersion).filter(ResumeVersion.id == result["resume_version_id"]).one()
        source = db.query(ResumeVersion).filter(ResumeVersion.id == resume_id).one()

        from models import RecruitmentThread

        thread = db.query(RecruitmentThread).filter(RecruitmentThread.id == thread_id).one()

        assert "Operated vLLM inference clusters on AMD MI300X GPUs." in created.resume_text
        assert created.id != resume_id
        assert source.resume_text == RESUME_TEXT, "accepting overwrote the candidate's master resume"
        assert thread.resume_version_id == created.id
        assert thread.case_facts["resume_version_id"] == created.id
        assert thread.case_facts["resume_sha256"] != hashlib.sha256(source.resume_text.encode()).hexdigest()
        assert thread.case_facts["candidate_profile_status"] == "not_started"
        assert thread.case_facts["target_assessment_status"] == "not_started"


def test_stale_edits_are_reported_rather_than_silently_dropped():
    """Accept-all must never claim success for an edit it could not apply."""
    sessions = _session_factory()
    with sessions() as db:
        owner_id, _, thread_id = _thread_with_edits(
            db,
            [
                ("Ran vLLM inference clusters on AMD MI300X.", "Operated vLLM inference clusters."),
                ("Text the resume no longer contains.", "Never applied."),
            ],
        )

        result = _team(db).accept_proposed_edits(owner_id, thread_id)

        assert len(result["accepted_edit_ids"]) == 1
        assert len(result["stale_edit_ids"]) == 1


def test_accepting_when_every_edit_is_stale_is_rejected():
    from recruitment_team.errors import InvalidCommand

    sessions = _session_factory()
    with sessions() as db:
        owner_id, _, thread_id = _thread_with_edits(db, [("Not present at all.", "Anything.")])

        with pytest.raises(InvalidCommand):
            _team(db).accept_proposed_edits(owner_id, thread_id)


def test_an_edit_from_the_previous_document_schema_is_stale_even_if_text_matches():
    from recruitment_team.errors import InvalidCommand

    sessions = _session_factory()
    with sessions() as db:
        owner_id, _, thread_id = _thread_with_edits(
            db,
            [("Ran vLLM inference clusters on AMD MI300X.", "Operated vLLM inference clusters.")],
        )
        edit = db.query(ProposedResumeEdit).filter_by(thread_id=thread_id).one()
        edit.document_revision = "r_schema_v1"
        db.commit()

        assert _team(db).proposed_edits(owner_id, thread_id)[0]["applicable"] is False
        with pytest.raises(InvalidCommand):
            _team(db).accept_proposed_edits(owner_id, thread_id)


def test_rejected_edits_leave_the_pending_list():
    sessions = _session_factory()
    with sessions() as db:
        owner_id, _, thread_id = _thread_with_edits(
            db,
            [("Ran vLLM inference clusters on AMD MI300X.", "Operated vLLM inference clusters.")],
        )
        team = _team(db)
        pending = team.proposed_edits(owner_id, thread_id)

        team.reject_proposed_edits(owner_id, thread_id, [pending[0]["id"]])

        assert team.proposed_edits(owner_id, thread_id) == []


def test_another_user_cannot_read_or_accept_someone_elses_edits():
    from recruitment_team.errors import ThreadNotFound

    sessions = _session_factory()
    with sessions() as db:
        _, _, thread_id = _thread_with_edits(
            db,
            [("Ran vLLM inference clusters on AMD MI300X.", "Operated vLLM inference clusters.")],
        )
        intruder = User(email="x@example.com", password_hash="test-only", name="X")  # pragma: allowlist secret
        db.add(intruder)
        db.commit()

        with pytest.raises(ThreadNotFound):
            _team(db).proposed_edits(intruder.id, thread_id)
        with pytest.raises(ThreadNotFound):
            _team(db).accept_proposed_edits(intruder.id, thread_id)
