from __future__ import annotations

from datetime import datetime, timedelta, timezone

import config
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from models import (
    CandidateProfileArtifact,
    RecruitmentActivityEvent,
    RecruitmentRun,
    RecruitmentThread,
    ResumeVersion,
    User,
)
from recruitment_team.candidate_profile import (
    CandidateEvidenceProfile,
    CandidateProfileRun,
    ScriptedCandidateProfilerFactory,
)
from recruitment_team.study import (
    dispatch_resume_study,
    _run_dispatched_study,
    _study_idempotency_key,
    study_resume_version,
)
from recruitment_team.telemetry import RecordedTelemetry
from recruitment_team.activity_publisher import IgnoreActivityPublisher, RecordedActivityPublisher
from recruitment_team.conversation_model import ScriptedConversationModel
from recruitment_team.discovery import ScriptedDiscovery
from recruitment_team.interface import StartThread
from recruitment_team.prompts import CANDIDATE_PROFILE_REVIEW_VERSION
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
        evaluation={
            "evaluation_version": CANDIDATE_PROFILE_REVIEW_VERSION,
            "profile_version": "candidate-evidence-profile-v3",
            "field_evaluations": [],
            "strengths": ["The profile contains no unsupported fields."],
            "weaknesses": [],
            "score": 100,
            "score_reason": "The empty fixture passed its independent review.",
            "result": "pass",
        },
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
        assert first.evaluation["result"] == "pass"
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


def test_stale_completed_dispatch_receipt_does_not_block_current_profile():
    sessions = _sessions()
    owner_id, resume_id, thread_id = _owner_resume_thread(sessions)
    factory = ScriptedCandidateProfilerFactory([_run()], model_name="study-model")

    with sessions() as db:
        db.add(
            RecruitmentRun(
                id="legacy-study-run",
                user_id=owner_id,
                thread_id=thread_id,
                idempotency_key=f"study:{resume_id}:{factory.model_name}",
                command_type="study_resume_version",
                status="completed",
                trace_key="legacy-study-trace",
            )
        )
        db.commit()

        _run_dispatched_study(
            db,
            owner_id=owner_id,
            resume_version_id=resume_id,
            thread_id=thread_id,
            profiler_factory=factory,
            telemetry=RecordedTelemetry(),
        )

        thread = db.query(RecruitmentThread).filter_by(id=thread_id).one()
        runs = db.query(RecruitmentRun).order_by(RecruitmentRun.id).all()
        assert len(runs) == 2
        assert thread.case_facts["candidate_profile_status"] == "completed"
        assert thread.case_facts["candidate_profile_artifact_id"]


def test_current_profile_is_linked_to_each_new_conversation_without_rerunning():
    sessions = _sessions()
    owner_id, resume_id, thread_id = _owner_resume_thread(sessions)
    first_factory = ScriptedCandidateProfilerFactory([_run()], model_name="study-model")

    with sessions() as db:
        artifact = study_resume_version(
            db,
            owner_id=owner_id,
            resume_version_id=resume_id,
            profiler_factory=first_factory,
            telemetry=RecordedTelemetry(),
        )
        second_factory = ScriptedCandidateProfilerFactory([], model_name="study-model")

        _run_dispatched_study(
            db,
            owner_id=owner_id,
            resume_version_id=resume_id,
            thread_id=thread_id,
            profiler_factory=second_factory,
            telemetry=RecordedTelemetry(),
        )

        thread = db.query(RecruitmentThread).filter_by(id=thread_id).one()
        assert thread.case_facts["candidate_profile_status"] == "completed"
        assert thread.case_facts["candidate_profile_artifact_id"] == artifact.id
        assert db.query(RecruitmentRun).count() == 0


def test_second_thread_reuses_the_profile_after_an_operational_budget_change():
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
        policy = dict(artifact.execution_policy)
        policy["model_timeout_seconds"] = int(policy["model_timeout_seconds"]) + 1
        artifact.execution_policy = policy
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


def test_study_provider_startup_failure_is_durable_and_user_visible():
    sessions = _sessions()
    owner_id, resume_id, thread_id = _owner_resume_thread(sessions)
    publisher = RecordedActivityPublisher()

    def unavailable_provider():
        raise RuntimeError("private configuration detail")

    worker = dispatch_resume_study(
        sessions,
        owner_id=owner_id,
        resume_version_id=resume_id,
        thread_id=thread_id,
        profiler_factory_provider=unavailable_provider,
        telemetry=RecordedTelemetry(),
        activity_publisher=publisher,
    )
    worker.join(timeout=2)

    assert not worker.is_alive()
    with sessions() as db:
        run = db.query(RecruitmentRun).filter_by(thread_id=thread_id).one()
        thread = db.query(RecruitmentThread).filter_by(id=thread_id).one()
        event = db.query(RecruitmentActivityEvent).filter_by(run_id=run.id).one()
        assert run.status == "failed"
        assert run.error_type == "RuntimeError"
        assert thread.case_facts["candidate_profile_status"] == "failed"
        assert event.status == "failed"
        assert event.detail["failure_code"] == "provider_startup_failed"
        assert "private configuration detail" not in str(event.detail)
    assert [event.status for event in publisher.events] == ["failed"]


def test_expired_running_study_is_reconciled_and_retried():
    sessions = _sessions()
    owner_id, resume_id, thread_id = _owner_resume_thread(sessions)
    factory = ScriptedCandidateProfilerFactory([_run()], model_name="study-model")
    stale_run_id = "stale-study-run"

    with sessions() as db:
        db.add(RecruitmentRun(
            id=stale_run_id,
            user_id=owner_id,
            thread_id=thread_id,
            idempotency_key=_study_idempotency_key(resume_id, factory.model_name),
            command_type="study_resume_version",
            status="running",
            trace_key="stale-study-trace",
            created_at=datetime.now(timezone.utc)
            - timedelta(seconds=config.RECRUITMENT_RUN_LEASE_SECONDS + 1),
        ))
        db.commit()

        _run_dispatched_study(
            db,
            owner_id=owner_id,
            resume_version_id=resume_id,
            thread_id=thread_id,
            profiler_factory=factory,
            telemetry=RecordedTelemetry(),
        )

        run = db.get(RecruitmentRun, stale_run_id)
        thread = db.get(RecruitmentThread, thread_id)
        assert run.status == "completed"
        assert run.error_type is None
        assert thread.case_facts["candidate_profile_status"] == "completed"


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
