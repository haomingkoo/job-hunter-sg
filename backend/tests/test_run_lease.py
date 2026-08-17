from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier, Lock, Thread

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import sessionmaker

from database import Base
from models import (
    RecruitmentActivityEvent,
    RecruitmentMessage,
    RecruitmentRun,
    RecruitmentThread,
    ResumeVersion,
    User,
)
from recruitment_team.run_lease import reconcile_expired_runs, renew_run_lease


def _sessions(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'leases.db'}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )

    @event.listens_for(engine, "connect")
    def _foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _running_run(sessions, *, expires_at: datetime) -> tuple[int, str, str]:
    with sessions() as db:
        user = User(email="lease@example.com", password_hash="test-only", name="Candidate")
        db.add(user)
        db.flush()
        resume = ResumeVersion(
            user_id=user.id,
            label="Resume",
            resume_text="Built reliable systems.",
            is_master=True,
        )
        db.add(resume)
        db.flush()
        thread = RecruitmentThread(
            id="thread-lease",
            user_id=user.id,
            resume_version_id=resume.id,
            case_facts={"partial_marker": "preserve-me"},
            next_event_sequence=2,
        )
        run = RecruitmentRun(
            id="run-lease",
            user_id=user.id,
            thread_id=thread.id,
            idempotency_key="lease-key",
            command_type="send_message",
            status="running",
            trace_key="a" * 64,
            attempt_ledger={"logical_run_id": "run-lease", "stages": {}},
            lease_owner="worker-a",
            lease_expires_at=expires_at,
        )
        db.add(thread)
        db.flush()
        db.add(run)
        db.flush()
        db.add_all([
            RecruitmentMessage(
                thread_id=thread.id,
                run_id=run.id,
                role="user",
                content="Continue my search.",
            ),
            RecruitmentActivityEvent(
                thread_id=thread.id,
                run_id=run.id,
                sequence=1,
                event_type="run",
                status="running",
                team_member="coordinator",
                trace_key=run.trace_key,
                summary="Working.",
            ),
        ])
        db.commit()
        return user.id, thread.id, run.id


def test_two_reconcilers_create_one_retryable_interruption(tmp_path):
    now = datetime.now(timezone.utc)
    sessions = _sessions(tmp_path)
    owner_id, thread_id, run_id = _running_run(
        sessions,
        expires_at=now - timedelta(seconds=1),
    )
    barrier = Barrier(2)
    result_lock = Lock()
    results: list[int] = []

    def reconcile():
        with sessions() as db:
            barrier.wait()
            count = reconcile_expired_runs(db, now=now)
            with result_lock:
                results.append(count)

    workers = [Thread(target=reconcile) for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(5)

    assert all(not worker.is_alive() for worker in workers)
    assert sorted(results) == [0, 1]
    with sessions() as db:
        run = db.get(RecruitmentRun, run_id)
        events = db.query(RecruitmentActivityEvent).filter_by(run_id=run_id).all()
        messages = db.query(RecruitmentMessage).filter_by(run_id=run_id).all()
        thread = db.get(RecruitmentThread, thread_id)

        assert run.status == "failed"
        assert run.error_type == "process_interrupted"
        assert run.lease_owner is None and run.lease_expires_at is None
        assert run.attempt_ledger["last_decision"] == {
            "failure_type": "transient",
            "failure_code": "process_interrupted",
            "retryable": True,
            "recovery_action": "retry_incomplete_stage",
            "retry_after_seconds": None,
        }
        assert len(run.attempt_ledger["interruptions"]) == 1
        assert [event.status for event in events] == ["running", "failed"]
        assert events[-1].detail["recovery_action"] == "retry_incomplete_stage"
        assert [message.role for message in messages] == ["user"]
        assert thread.user_id == owner_id
        assert thread.case_facts["partial_marker"] == "preserve-me"


def test_reconciliation_ignores_live_and_terminal_runs_and_checks_owner(tmp_path):
    now = datetime.now(timezone.utc)
    sessions = _sessions(tmp_path)
    _, _, run_id = _running_run(sessions, expires_at=now + timedelta(minutes=5))

    with sessions() as db:
        assert reconcile_expired_runs(db, now=now) == 0
        assert renew_run_lease(db, run_id, "worker-b", now) is False
        assert renew_run_lease(db, run_id, "worker-a", now) is True
        db.commit()

        run = db.get(RecruitmentRun, run_id)
        assert run.status == "running"
        run.status = "completed"
        run.lease_expires_at = now - timedelta(seconds=1)
        db.commit()
        assert reconcile_expired_runs(db, now=now) == 0
        assert db.get(RecruitmentRun, run_id).status == "completed"

        run.status = "failed"
        run.error_type = "existing_failure"
        db.commit()
        assert reconcile_expired_runs(db, now=now) == 0
        assert db.get(RecruitmentRun, run_id).error_type == "existing_failure"


def test_hidden_conversation_model_attempts_renew_between_sequential_calls(tmp_path, monkeypatch):
    import config
    import recruitment_team.recruitment_team as module
    from recruitment_team import RecruitmentTeam
    from recruitment_team.activity_publisher import IgnoreActivityPublisher
    from recruitment_team.telemetry import RecordedTelemetry

    started = datetime(2026, 8, 16, tzinfo=timezone.utc)
    sessions = _sessions(tmp_path)
    owner_id, thread_id, run_id = _running_run(
        sessions,
        expires_at=started + timedelta(seconds=10),
    )
    times = iter((started + timedelta(seconds=9), started + timedelta(seconds=18)))
    monkeypatch.setattr(config, "RECRUITMENT_RUN_LEASE_SECONDS", 10)
    monkeypatch.setattr(module, "_utcnow", lambda: next(times))

    with sessions() as db:
        team = RecruitmentTeam(
            db, None, None, None, RecordedTelemetry(), IgnoreActivityPublisher()
        )
        run = db.get(RecruitmentRun, run_id)
        publish = team._conversation_activity(db.get(RecruitmentThread, thread_id), run)
        publish({"kind": "model_attempt"})
        publish({"kind": "model_attempt"})
        db.expire_all()

        assert db.get(RecruitmentRun, run_id).lease_expires_at == (
            started + timedelta(seconds=28)
        ).replace(tzinfo=None)
        assert db.get(RecruitmentRun, run_id).user_id == owner_id


def test_configured_lease_exceeds_one_full_model_retry_envelope():
    import config

    maximum_invoke = (
        config.RECRUITMENT_MODEL_HTTP_TIMEOUT_SECONDS
        * (config.RECRUITMENT_MODEL_TRANSPORT_RETRIES + 1)
    )
    assert config.RECRUITMENT_RUN_LEASE_SECONDS > maximum_invoke

    env = os.environ.copy()
    env.update({
        "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
        "RECRUITMENT_MODEL_HTTP_TIMEOUT_SECONDS": "10",
        "RECRUITMENT_MODEL_TRANSPORT_RETRIES": "2",
        "RECRUITMENT_RUN_LEASE_SECONDS": "30",
    })
    rejected = subprocess.run(
        [sys.executable, "-c", "import config"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert rejected.returncode != 0
    assert "must exceed the configured model timeout and retries (30s)" in rejected.stderr


def test_two_startups_reconcile_one_hard_kill_once(tmp_path):
    from main import _reconcile_interrupted_recruitment_runs

    sessions = _sessions(tmp_path)
    _, _, run_id = _running_run(
        sessions,
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )

    assert _reconcile_interrupted_recruitment_runs(sessions) == 1
    assert _reconcile_interrupted_recruitment_runs(sessions) == 0
    with sessions() as db:
        run = db.get(RecruitmentRun, run_id)
        assert run.status == "failed"
        assert run.error_type == "process_interrupted"
        assert db.query(RecruitmentActivityEvent).filter_by(run_id=run_id, status="failed").count() == 1


def test_reattached_expired_run_returns_the_persisted_interruption(tmp_path):
    from recruitment_team import RecruitmentTeam
    from recruitment_team.activity_publisher import IgnoreActivityPublisher
    from recruitment_team.telemetry import RecordedTelemetry

    sessions = _sessions(tmp_path)
    owner_id, _, run_id = _running_run(
        sessions,
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    with sessions() as db:
        team = RecruitmentTeam(
            db,
            None,
            None,
            None,
            RecordedTelemetry(),
            IgnoreActivityPublisher(),
        )
        events, terminal = team.run_replay(owner_id, run_id, after_sequence=1)

    assert [event.status for event in events] == ["failed"]
    assert terminal is not None and terminal[0] == "error"
    assert terminal[1]["failure_code"] == "process_interrupted"
    assert terminal[1]["retryable"] is True


def test_lightweight_migration_adds_lease_columns_to_a_legacy_database(tmp_path, monkeypatch):
    import database

    legacy_engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    Base.metadata.create_all(legacy_engine)
    with legacy_engine.begin() as connection:
        connection.execute(text("DROP TABLE recruitment_runs"))
        connection.execute(text(
            "CREATE TABLE recruitment_runs ("
            "id VARCHAR(36) PRIMARY KEY, user_id INTEGER NOT NULL, thread_id VARCHAR(36) NOT NULL, "
            "idempotency_key VARCHAR(200) NOT NULL, command_type VARCHAR(50) NOT NULL, "
            "status VARCHAR(30) NOT NULL, trace_key VARCHAR(64) NOT NULL, "
            "attempt_ledger JSON NOT NULL DEFAULT '{}', result JSON, error_type VARCHAR(100), "
            "created_at TIMESTAMP NOT NULL, completed_at TIMESTAMP)"
        ))

    monkeypatch.setattr(database, "engine", legacy_engine)
    monkeypatch.setattr(database, "DATABASE_URL", f"sqlite:///{tmp_path / 'legacy.db'}")
    database._apply_lightweight_migrations()

    columns = {column["name"] for column in inspect(legacy_engine).get_columns("recruitment_runs")}
    assert {"lease_owner", "lease_expires_at"} <= columns
