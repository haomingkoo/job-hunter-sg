from __future__ import annotations

import pytest

from models import CandidateProfileArtifact, RecruitmentActivityEvent, RecruitmentRun, RecruitmentThread, ResumeVersion
from recruitment_team.activity_publisher import IgnoreActivityPublisher, RecordedActivityPublisher
from recruitment_team.candidate_profile import (
    CandidateProfileValidationError,
    ScriptedCandidateProfilerFactory,
)
from recruitment_team.conversation_model import ModelReply, ScriptedConversationModel
from recruitment_team.discovery import JobSearchResult, ScriptedDiscovery
from recruitment_team.errors import CandidateProfilingUnavailable, InvalidCommand, ServiceUnavailable
from recruitment_team.interface import SearchJobs, SendMessage, StartThread
from recruitment_team.recruitment_team import RecruitmentTeam
from recruitment_team.recovery import classify_failure
from recruitment_team.telemetry import RecordedTelemetry
from run_concurrency import owner_has_active_run

from backend.tests.test_recruitment_team_module import (
    _candidate_profile_run,
    _job_snapshot,
    _owner_with_resume,
    _session_factory,
)


def _team(db, model, discovery, publisher, factory):
    return RecruitmentTeam(
        db,
        model,
        discovery,
        None,
        RecordedTelemetry(),
        publisher,
        candidate_profiler_factory_provider=lambda: factory,
    )


def test_start_thread_profiles_after_durable_admission_then_starts_coordinator():
    sessions = _session_factory()
    owner_id, resume_id = _owner_with_resume(sessions)
    publisher = RecordedActivityPublisher()
    factory = ScriptedCandidateProfilerFactory([_candidate_profile_run()])
    provider_states = []

    with sessions() as db:
        def provide_factory():
            run = db.query(RecruitmentRun).filter_by(command_type="start_thread").one()
            provider_states.append((run.status, owner_has_active_run(f"user:{owner_id}")))
            return factory

        team = RecruitmentTeam(
            db,
            ScriptedConversationModel(["Ready."]),
            ScriptedDiscovery([]),
            None,
            RecordedTelemetry(),
            publisher,
            candidate_profiler_factory_provider=provide_factory,
        )
        receipt = team.execute(
            owner_id,
            StartThread(resume_version_id=resume_id, message="Find roles."),
            "profile-first-start",
        )
        stages = [
            (event.event_type, event.status, event.team_member)
            for event in db.query(RecruitmentActivityEvent)
            .filter_by(run_id=receipt.run_id)
            .order_by(RecruitmentActivityEvent.sequence)
        ]

    assert provider_states == [("running", True)]
    assert stages.index(("candidate_profile", "completed", "candidate_profiler")) < stages.index(
        ("conversation", "running", "coordinator")
    ) < stages.index(("run", "completed", "coordinator"))


def test_first_search_uses_profile_and_later_turn_reuses_current_artifact():
    sessions = _session_factory()
    owner_id, resume_id = _owner_with_resume(sessions)
    job = _job_snapshot()
    result = JobSearchResult(
        query="fixture",
        jobs=(job,),
        candidate_count=1,
        visible_candidate_count=1,
        truncated=False,
        valid_empty=False,
    )
    discovery = ScriptedDiscovery([result, result])
    factory = ScriptedCandidateProfilerFactory([_candidate_profile_run()])

    class SearchingCoordinator:
        def __init__(self):
            self.calls = 0

        def respond(self, _messages, _resume_text, _preferences, context):
            self.calls += 1
            if self.calls == 1:
                batch = context.recommender.search(
                    context.candidate_profile,
                    context.discovery,
                    "AI solution architect",
                )
                assert batch.receipt.candidate_profile_used is True
            return ModelReply(content="Ready.", model_name="test-coordinator")

    with sessions() as db:
        team = _team(db, SearchingCoordinator(), discovery, IgnoreActivityPublisher(), factory)
        started = team.execute(
            owner_id,
            StartThread(resume_version_id=resume_id, message="Find roles."),
            "profile-search",
        )
        team.execute(
            owner_id,
            SendMessage(thread_id=started.thread_id, message="Continue."),
            "profile-reuse",
        )
        assert db.query(CandidateProfileArtifact).count() == 1


def test_rebinding_a_thread_to_a_new_resume_fails_closed():
    sessions = _session_factory()
    owner_id, resume_id = _owner_with_resume(sessions)
    factory = ScriptedCandidateProfilerFactory([
        _candidate_profile_run(),
        _candidate_profile_run(),
    ])

    with sessions() as db:
        team = _team(
            db,
            ScriptedConversationModel(["Ready.", "Updated."]),
            ScriptedDiscovery([]),
            IgnoreActivityPublisher(),
            factory,
        )
        started = team.execute(
            owner_id,
            StartThread(resume_version_id=resume_id, message="Find roles."),
            "original-profile",
        )
        revised = ResumeVersion(
            user_id=owner_id,
            label="Accepted edit",
            resume_text="Built and deployed a production agent platform.",
        )
        db.add(revised)
        db.flush()
        thread = db.get(RecruitmentThread, started.thread_id)
        thread.resume_version_id = revised.id
        facts = dict(thread.case_facts)
        facts["resume_version_id"] = revised.id
        thread.case_facts = facts
        db.commit()

        with pytest.raises(InvalidCommand, match="resume_binding_mismatch"):
            team.execute(
                owner_id,
                SendMessage(thread_id=started.thread_id, message="Use the accepted edit."),
                "revised-profile",
            )

        artifacts = db.query(CandidateProfileArtifact).all()
        assert [artifact.resume_version_id for artifact in artifacts] == [resume_id]


def test_direct_search_on_hashless_legacy_thread_fails_closed():
    sessions = _session_factory()
    owner_id, resume_id = _owner_with_resume(sessions)
    job = _job_snapshot()
    result = JobSearchResult(
        query="fixture",
        jobs=(job,),
        candidate_count=1,
        visible_candidate_count=1,
        truncated=False,
        valid_empty=False,
    )
    factory = ScriptedCandidateProfilerFactory([_candidate_profile_run()])

    with sessions() as db:
        thread = RecruitmentThread(
            id="legacy-profileless-search",
            user_id=owner_id,
            resume_version_id=resume_id,
            case_facts={"resume_version_id": resume_id},
        )
        db.add(thread)
        db.commit()
        team = _team(
            db,
            ScriptedConversationModel([]),
            ScriptedDiscovery([result]),
            IgnoreActivityPublisher(),
            factory,
        )

        with pytest.raises(InvalidCommand, match="resume_binding_mismatch"):
            team.execute(
                owner_id,
                SearchJobs(thread_id=thread.id, query="AI solution architect"),
                "legacy-direct-search",
            )
        assert "latest_ranking_receipt" not in thread.case_facts


def test_coordinator_retry_reuses_completed_profile_without_profiler_work():
    sessions = _session_factory()
    owner_id, resume_id = _owner_with_resume(sessions)
    factory = ScriptedCandidateProfilerFactory([_candidate_profile_run()])
    provider_calls = []

    class FailOnceCoordinator:
        def __init__(self):
            self.calls = 0

        def respond(self, _messages, _resume_text, _preferences, context):
            self.calls += 1
            assert context.candidate_profile is not None
            if self.calls == 1:
                raise ServiceUnavailable(
                    "coordinator transport failed",
                    decision=classify_failure("transport_timeout", attempts_remaining=True),
                )
            return ModelReply(content="Recovered.", model_name="test-coordinator")

    model = FailOnceCoordinator()
    with sessions() as db:
        team = RecruitmentTeam(
            db,
            model,
            ScriptedDiscovery([]),
            None,
            RecordedTelemetry(),
            IgnoreActivityPublisher(),
            candidate_profiler_factory_provider=lambda: provider_calls.append(True) or factory,
        )
        with pytest.raises(ServiceUnavailable):
            team.execute(
                owner_id,
                StartThread(resume_version_id=resume_id, message="Find roles."),
                "coordinator-retry",
            )
        failed = db.query(RecruitmentRun).filter_by(idempotency_key="coordinator-retry").one()

        receipt = team.retry_conversation_run(owner_id, failed.thread_id, failed.id)

        assert receipt.status == "completed"
        assert provider_calls == [True]
        assert db.query(CandidateProfileArtifact).count() == 1


def test_profiler_semantic_failure_is_attributed_and_never_calls_coordinator():
    sessions = _session_factory()
    owner_id, resume_id = _owner_with_resume(sessions)
    publisher = RecordedActivityPublisher()
    factory = ScriptedCandidateProfilerFactory([
        CandidateProfileValidationError(
            "profile:unsupported_claim",
            {"fields": []},
            attempt_count=1,
            model_name="study-model",
            validation_codes=("profile:unsupported_claim",),
            checkpoint_id="d" * 64,
        )
    ])
    model = ScriptedConversationModel(["must not run"])

    with sessions() as db:
        team = _team(db, model, ScriptedDiscovery([]), publisher, factory)
        with pytest.raises(CandidateProfilingUnavailable):
            team.execute(
                owner_id,
                StartThread(resume_version_id=resume_id, message="Find roles."),
                "profile-semantic-failure",
            )
        run = db.query(RecruitmentRun).filter_by(
            idempotency_key="profile-semantic-failure"
        ).one()
        failed_event = [event for event in publisher.events if event.status == "failed"][-1]

    assert model.call_count == 0
    assert run.attempt_ledger["last_attempted_stage"] == "candidate_profile"
    assert "semantic" in run.attempt_ledger["stages"]["candidate_profile"]
    assert failed_event.team_member == "candidate_profiler"
    assert failed_event.detail["attempted_stage"] == "candidate_profile"
