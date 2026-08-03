from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from models import CandidateProfileArtifact, RecruitmentActivityEvent, RecruitmentThread, ResumeVersion, User
from recruitment_team.candidate_profile import (
    CandidateEvidenceProfile,
    CandidateProfileRun,
    ScriptedCandidateProfilerFactory,
)
from recruitment_team.study import _run_dispatched_study, study_resume_version
from recruitment_team.telemetry import RecordedTelemetry
from recruitment_team.activity_publisher import IgnoreActivityPublisher, RecordedActivityPublisher
from recruitment_team.conversation_model import ScriptedConversationModel
from recruitment_team.discovery import ScriptedDiscovery
from recruitment_team.interface import StartThread
from recruitment_team.recruitment_team import RecruitmentTeam


def _sessions():
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


def _owner_resume_thread(sessions):
    with sessions() as db:
        owner = User(email="study@example.com", password_hash="test-only", name="Candidate")
        db.add(owner)
        db.flush()
        resume = ResumeVersion(
            user_id=owner.id,
            label="Master",
            resume_text="EXPERIENCE\n- Built a validated workflow.",
        )
        db.add(resume)
        db.flush()
        thread = RecruitmentThread(
            id="study-thread",
            user_id=owner.id,
            resume_version_id=resume.id,
            case_facts={"resume_version_id": resume.id},
        )
        db.add(thread)
        db.commit()
        return owner.id, resume.id, thread.id


def _run():
    return CandidateProfileRun(
        profile=CandidateEvidenceProfile(
            profile_version="candidate-evidence-profile-v3",
            resume_document_id="document",
            resume_revision="revision",
            fields=(),
            cited_resume_evidence=(),
        ),
        model_name="study-model",
        attempt_count=1,
        scope_count=1,
        model_call_count=1,
        checkpoint_id="a" * 64,
    )


def test_study_is_cached_per_resume_version_without_a_second_profiler_run():
    sessions = _sessions()
    owner_id, resume_id, _ = _owner_resume_thread(sessions)
    factory = ScriptedCandidateProfilerFactory([_run()], model_name="study-model")

    with sessions() as db:
        first = study_resume_version(
            db,
            owner_id=owner_id,
            resume_version_id=resume_id,
            profiler_factory=factory,
            telemetry=RecordedTelemetry(),
        )
        second = study_resume_version(
            db,
            owner_id=owner_id,
            resume_version_id=resume_id,
            profiler_factory=factory,
            telemetry=RecordedTelemetry(),
        )

        assert second.id == first.id
        assert db.query(CandidateProfileArtifact).count() == 1


def test_dispatched_study_is_visible_and_links_the_completed_artifact():
    sessions = _sessions()
    owner_id, resume_id, thread_id = _owner_resume_thread(sessions)
    factory = ScriptedCandidateProfilerFactory([_run()], model_name="study-model")
    publisher = RecordedActivityPublisher()

    with sessions() as db:
        _run_dispatched_study(
            db,
            owner_id=owner_id,
            resume_version_id=resume_id,
            thread_id=thread_id,
            profiler_factory=factory,
            telemetry=RecordedTelemetry(),
            activity_publisher=publisher,
        )

        thread = db.query(RecruitmentThread).filter_by(id=thread_id).one()
        events = db.query(RecruitmentActivityEvent).order_by(RecruitmentActivityEvent.sequence).all()
        assert [event.detail.get("transition") for event in events] == [
            None,
            "start",
            "checkpoint",
            "completion",
            None,
        ]
        assert [event.status for event in events] == [
            "running",
            "running",
            "running",
            "running",
            "completed",
        ]
        assert "studying" in events[0].summary
        assert thread.case_facts["candidate_profile_status"] == "completed"
        assert thread.case_facts["candidate_profile_artifact_id"]
        assert [event.status for event in publisher.events] == [event.status for event in events]


def test_second_thread_resolves_the_resume_scoped_study_without_rerunning_it():
    sessions = _sessions()
    owner_id, resume_id, _ = _owner_resume_thread(sessions)
    factory = ScriptedCandidateProfilerFactory([_run()], model_name="study-model")

    with sessions() as db:
        artifact = study_resume_version(
            db,
            owner_id=owner_id,
            resume_version_id=resume_id,
            profiler_factory=factory,
            telemetry=RecordedTelemetry(),
        )
        second = RecruitmentThread(
            id="second-thread",
            user_id=owner_id,
            resume_version_id=resume_id,
            case_facts={"resume_version_id": resume_id},
        )
        db.add(second)
        db.commit()

        team = RecruitmentTeam(
            db,
            None,
            None,
            None,
            RecordedTelemetry(),
            IgnoreActivityPublisher(),
        )
        snapshot = team.candidate_profile(owner_id, second.id)

        assert snapshot is not None
        assert snapshot.artifact_id == artifact.id


def test_a_profile_from_the_previous_resume_schema_is_not_reused():
    sessions = _sessions()
    owner_id, resume_id, thread_id = _owner_resume_thread(sessions)
    factory = ScriptedCandidateProfilerFactory([_run()], model_name="study-model")

    with sessions() as db:
        artifact = study_resume_version(
            db,
            owner_id=owner_id,
            resume_version_id=resume_id,
            profiler_factory=factory,
            telemetry=RecordedTelemetry(),
        )
        policy = dict(artifact.execution_policy)
        policy.pop("resume_document_schema_version")
        artifact.execution_policy = policy
        db.commit()

        team = RecruitmentTeam(
            db,
            None,
            None,
            None,
            RecordedTelemetry(),
            IgnoreActivityPublisher(),
        )

        assert team.candidate_profile(owner_id, thread_id) is None


def test_start_thread_dispatches_the_resume_study_after_the_thread_is_durable():
    sessions = _sessions()
    owner_id, resume_id, _ = _owner_resume_thread(sessions)
    dispatched = []

    with sessions() as db:
        team = RecruitmentTeam(
            db,
            ScriptedConversationModel(["Ready."]),
            ScriptedDiscovery([]),
            None,
            RecordedTelemetry(),
            IgnoreActivityPublisher(),
            study_dispatcher=lambda owner, resume, thread: dispatched.append((owner, resume, thread)),
        )
        receipt = team.execute(
            owner_id,
            StartThread(resume_version_id=resume_id, message="Find roles for me."),
            "start-with-study",
        )

        assert dispatched == [(owner_id, resume_id, receipt.thread_id)]
        assert db.query(RecruitmentThread).filter_by(id=receipt.thread_id).one()


def test_streaming_team_routes_background_study_events_to_the_active_publisher():
    from recruitment_team.http_routes import _streaming_team_factory

    sessions = _sessions()
    owner_id, resume_id, _ = _owner_resume_thread(sessions)
    publisher = RecordedActivityPublisher()
    dispatched = []

    with sessions() as db:
        create_team = _streaming_team_factory(
            db,
            ScriptedConversationModel(["Ready."]),
            ScriptedDiscovery([]),
            None,
            RecordedTelemetry(),
            study_dispatcher=lambda owner, resume, thread, activity: dispatched.append(
                (owner, resume, thread, activity)
            ),
        )
        receipt = create_team(publisher).execute(
            owner_id,
            StartThread(resume_version_id=resume_id, message="Find roles for me."),
            "stream-visible-study",
        )

    assert dispatched == [(owner_id, resume_id, receipt.thread_id, publisher)]
