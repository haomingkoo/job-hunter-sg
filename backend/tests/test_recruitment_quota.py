from __future__ import annotations


def test_recruitment_model_run_consumes_one_credit_per_idempotency_key():
    from backend.tests.test_recruitment_team_module import (
        _discovery,
        _candidate_profile_run,
        _owner_with_resume,
        _role_profiler,
        _session_factory,
    )
    from recruitment_team.activity_publisher import IgnoreActivityPublisher
    from recruitment_team.candidate_profile import ScriptedCandidateProfilerFactory
    from recruitment_team.conversation_model import ScriptedConversationModel
    from recruitment_team.interface import StartThread
    from recruitment_team.recruitment_team import RecruitmentTeam
    from recruitment_team.telemetry import RecordedTelemetry

    sessions = _session_factory()
    owner_id, resume_id = _owner_with_resume(sessions)
    consumed: list[tuple[int, str, str]] = []

    with sessions() as db:
        team = RecruitmentTeam(
            db,
            ScriptedConversationModel(["Ready."]),
            _discovery(),
            _role_profiler(),
            RecordedTelemetry(),
            IgnoreActivityPublisher(),
            ai_credit_consumer=lambda *receipt: consumed.append(receipt),
            candidate_profiler_factory_provider=lambda: ScriptedCandidateProfilerFactory(
                [_candidate_profile_run()]
            ),
        )
        command = StartThread(resume_version_id=resume_id, message="Find roles for me.")

        first = team.execute(owner_id, command, "quota-operation")
        duplicate = team.execute(owner_id, command, "quota-operation")

    assert duplicate == first
    assert consumed == [(owner_id, "StartThread", "quota-operation")]


def test_shared_quota_receipt_is_idempotent_without_storing_the_operation_key():
    from ai_quota import consume_ai_credit
    from auth import hash_password
    from backend.tests.test_recruitment_team_module import _session_factory
    from models import UsageLog, User

    sessions = _session_factory()
    with sessions() as db:
        user = User(
            email="quota-receipt@example.test",
            password_hash=hash_password("TestPassword123!"),
            name="Quota Receipt",
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        assert consume_ai_credit(
            user,
            db,
            "recruitment_team:StartThread",
            operation_key="private-idempotency-key",
        ) is True
        assert consume_ai_credit(
            user,
            db,
            "recruitment_team:StartThread",
            operation_key="private-idempotency-key",
        ) is False

        [receipt] = db.query(UsageLog).filter_by(user_id=user.id, action="ai").all()
        assert receipt.detail.startswith("recruitment_team:StartThread:")
        assert "private-idempotency-key" not in receipt.detail
