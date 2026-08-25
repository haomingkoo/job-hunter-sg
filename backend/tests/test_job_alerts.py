import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import job_alerts
from database import Base
from job_alerts import AlertMatch, find_alert_matches
from models import JobAlertDelivery, JobAlertPreference, ScrapedJob, User, UserMemory


def test_local_job_alert_run_lease_rejects_overlap_and_releases():
    engine = create_engine("sqlite://")
    with Session(engine) as first_db, Session(engine) as second_db:
        with job_alerts._job_alert_run_lease(first_db) as first_acquired:
            with job_alerts._job_alert_run_lease(second_db) as second_acquired:
                assert first_acquired is True
                assert second_acquired is False
        with job_alerts._job_alert_run_lease(second_db) as acquired_after_release:
            assert acquired_after_release is True


def test_postgres_job_alert_run_lease_uses_session_advisory_lock():
    statements = []
    connection_closed = []

    class Dialect:
        name = "postgresql"

    class Bind:
        dialect = Dialect()

        def connect(self):
            return Connection()

    class Result:
        def scalar(self):
            return True

    class Connection:
        def execute(self, statement, parameters):
            statements.append((str(statement), parameters))
            return Result()

        def close(self):
            connection_closed.append(True)

    class Database:
        def get_bind(self):
            return Bind()

    with job_alerts._job_alert_run_lease(Database()) as acquired:
        assert acquired is True

    assert statements == [
        (
            "SELECT pg_try_advisory_lock(:key)",
            {"key": job_alerts._JOB_ALERT_RUN_LOCK_KEY},
        ),
        (
            "SELECT pg_advisory_unlock(:key)",
            {"key": job_alerts._JOB_ALERT_RUN_LOCK_KEY},
        ),
    ]
    assert connection_closed == [True]


def test_job_alert_run_skips_before_querying_when_another_runner_holds_the_lease(
    monkeypatch,
):
    class Database:
        def query(self, _model):
            raise AssertionError("an overlapping runner must not query alert recipients")

        def close(self):
            pass

    @contextmanager
    def unavailable_lease(_db):
        yield False

    monkeypatch.setattr(job_alerts, "email_configured", lambda: True)
    monkeypatch.setattr(job_alerts, "email_provider", lambda: "test")
    monkeypatch.setattr(job_alerts, "smtp_configured", lambda: False)
    monkeypatch.setattr(job_alerts, "SessionLocal", Database)
    monkeypatch.setattr(job_alerts, "_job_alert_run_lease", unavailable_lease)

    result = job_alerts.run_job_alerts()

    assert result["skipped_overlap"] is True
    assert result["emails_sent"] == 0


def test_job_alert_commit_failure_does_not_report_a_durable_send(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'alert-commit-failure.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as seed:
        user = User(email="alert@example.test", password_hash="unused", name="Alert User")
        seed.add(user)
        seed.flush()
        job = ScrapedJob(
            title="Platform Engineer",
            company="Example Employer",
            dedup_key="alert-commit-failure",
            direct_employer=1,
        )
        seed.add(job)
        seed.flush()
        seed.add_all([
            UserMemory(user_id=user.id, resume_text="Experienced platform engineer " * 4),
            JobAlertPreference(
                user_id=user.id,
                enabled=True,
                last_run_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
            ),
        ])
        seed.commit()
        user_id = user.id
        job_id = job.id

    class CommitFailSession(Session):
        def commit(self):
            self.flush()
            raise RuntimeError("commit unavailable")

    accepted = []
    monkeypatch.setattr(job_alerts, "SessionLocal", lambda: CommitFailSession(bind=engine))
    monkeypatch.setattr(job_alerts, "email_configured", lambda: True)
    monkeypatch.setattr(job_alerts, "email_provider", lambda: "test")
    monkeypatch.setattr(job_alerts, "smtp_configured", lambda: True)
    monkeypatch.setattr(
        job_alerts,
        "render_alert_email",
        lambda *_args: ("subject", "text", "html", "https://example.test/unsubscribe"),
    )
    monkeypatch.setattr(job_alerts, "send_email", lambda *args, **kwargs: accepted.append(args[0]))
    monkeypatch.setattr(
        job_alerts,
        "find_alert_matches",
        lambda *_args, **_kwargs: [
            AlertMatch(
                job=SimpleNamespace(id=job_id),
                score=90,
                matched_skills=[],
                missing_skills=[],
                why="Regression fixture",
            )
        ],
    )

    result = job_alerts.run_job_alerts()

    assert accepted == ["alert@example.test"]
    assert result["emails_sent"] == 0
    assert result["jobs_sent"] == 0
    assert result["smtp_accepted"] == 1
    assert result["durably_recorded"] == 0
    assert result["persistence_after_acceptance"] == 1
    assert result["errors"] == [{
        "user_id": user_id,
        "error": "AlertPersistenceAfterAcceptanceError",
        "stage": "persistence_after_acceptance",
    }]
    with Session(engine) as check:
        assert check.query(JobAlertDelivery).count() == 0
    engine.dispose()


def test_direct_employer_alert_does_not_advance_while_index_is_incomplete(
    monkeypatch,
    tmp_path,
):
    engine = create_engine(f"sqlite:///{tmp_path / 'alert-index-rebuild.db'}")
    Base.metadata.create_all(engine)
    now = datetime(2026, 8, 25, tzinfo=timezone.utc)
    previous_cursor = now - timedelta(days=2)
    with Session(engine, expire_on_commit=False) as db:
        user = User(email="rebuild@example.test", password_hash="unused", name="Rebuild")
        db.add(user)
        db.flush()
        db.add_all([
            UserMemory(user_id=user.id, resume_text="Experienced quality manager " * 4),
            JobAlertPreference(
                user_id=user.id,
                enabled=True,
                direct_employers_only=True,
                last_run_at=previous_cursor,
                match_cursor_at=previous_cursor,
            ),
            ScrapedJob(
                title="Quality Manager",
                company="Direct Employer",
                dedup_key="unclassified-alert-job",
                scraped_at=now.isoformat(),
                direct_employer=-1,
            ),
        ])
        db.commit()
        user_id = user.id

    monkeypatch.setattr(job_alerts, "_utcnow", lambda: now)
    monkeypatch.setattr(job_alerts, "SessionLocal", lambda: Session(engine))
    result = job_alerts.run_job_alerts(dry_run=True)

    assert result["skipped_employer_index_unavailable"] == 1
    with Session(engine) as check:
        preference = check.query(JobAlertPreference).filter_by(user_id=user_id).one()
        assert job_alerts._as_utc(preference.last_run_at) == previous_cursor
        assert job_alerts._as_utc(preference.match_cursor_at) == previous_cursor
    engine.dispose()


def test_find_alert_matches_ranks_all_bounded_candidates_before_limiting(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    now = datetime(2026, 7, 13, tzinfo=timezone.utc)

    with Session(engine) as db:
        high_match = ScrapedJob(
            title="High match",
            company="Direct Employer",
            dedup_key="high-match",
            scraped_at=now.isoformat(),
        )
        low_match = ScrapedJob(
            title="Low match",
            company="Another Direct Employer",
            dedup_key="low-match",
            scraped_at=now.isoformat(),
        )
        db.add_all([high_match, low_match])
        db.commit()

        scores = {high_match.id: 99, low_match.id: 75}
        monkeypatch.setattr(job_alerts, "extract_resume_alert_skills", lambda _resume: [])
        monkeypatch.setattr(
            job_alerts,
            "score_job_for_alert",
            lambda _resume, _skills, job: AlertMatch(
                job=job,
                score=scores[job.id],
                matched_skills=[],
                missing_skills=[],
                why="Regression fixture",
            ),
        )
        preference = SimpleNamespace(
            user_id=1,
            last_run_at=now - timedelta(hours=1),
            keywords="",
            direct_employers_only=False,
            min_score=75,
            max_jobs=1,
        )

        matches = find_alert_matches(db, preference, "resume", now=now)

    assert [(match.job.title, match.score) for match in matches] == [("High match", 99)]


def test_alert_overflow_drains_on_schedule_without_losing_matches(
    monkeypatch,
    tmp_path,
):
    engine = create_engine(f"sqlite:///{tmp_path / 'alert-backlog.db'}")
    Base.metadata.create_all(engine)
    now = datetime(2026, 8, 23, tzinfo=timezone.utc)
    previous_cursor = now - timedelta(days=8)
    accepted = []

    with Session(engine, expire_on_commit=False) as db:
        user = User(email="backlog@example.test", password_hash="unused", name="Backlog User")
        db.add(user)
        db.flush()
        preference = JobAlertPreference(
            user_id=user.id,
            enabled=True,
            direct_employers_only=False,
            min_score=75,
            max_jobs=1,
            frequency="weekly",
            last_run_at=previous_cursor,
            match_cursor_at=previous_cursor,
        )
        jobs = [
            ScrapedJob(
                title=f"Platform Engineer {index}",
                company="Direct Employer",
                dedup_key=f"backlog-{index}",
                scraped_at=now.isoformat(),
            )
            for index in (1, 2)
        ]
        db.add_all([
            preference,
            UserMemory(user_id=user.id, resume_text="Experienced platform engineer " * 4),
            *jobs,
        ])
        db.commit()

        monkeypatch.setattr(job_alerts, "extract_resume_alert_skills", lambda _resume: [])
        monkeypatch.setattr(
            job_alerts,
            "score_job_for_alert",
            lambda _resume, _skills, job: AlertMatch(
                job=job,
                score=90,
                matched_skills=[],
                missing_skills=[],
                why="Regression fixture",
            ),
        )
        monkeypatch.setattr(
            job_alerts,
            "render_alert_email",
            lambda *_args: ("subject", "text", "html", "https://example.test/unsubscribe"),
        )
        monkeypatch.setattr(
            job_alerts,
            "send_email",
            lambda *args, **_kwargs: accepted.append(args[0]),
        )

        user_id = user.id

    clock = [now]
    monkeypatch.setattr(job_alerts, "_utcnow", lambda: clock[0])
    monkeypatch.setattr(job_alerts, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(job_alerts, "email_configured", lambda: True)
    monkeypatch.setattr(job_alerts, "email_provider", lambda: "test")
    monkeypatch.setattr(job_alerts, "smtp_configured", lambda: True)

    first = job_alerts.run_job_alerts()
    with Session(engine) as check:
        preference = check.query(JobAlertPreference).filter_by(user_id=user_id).one()
        assert job_alerts._as_utc(preference.last_run_at) == now
        assert job_alerts._as_utc(preference.match_cursor_at) == previous_cursor

    clock[0] = now + timedelta(days=1)
    too_soon = job_alerts.run_job_alerts()

    clock[0] = now + timedelta(days=7)
    second = job_alerts.run_job_alerts()
    with Session(engine) as check:
        preference = check.query(JobAlertPreference).filter_by(user_id=user_id).one()
        assert job_alerts._as_utc(preference.last_run_at) == clock[0]
        assert job_alerts._as_utc(preference.match_cursor_at) == clock[0]
        assert check.query(JobAlertDelivery).count() == 2

    assert first["jobs_sent"] == 1
    assert first["users_with_backlog"] == 1
    assert too_soon["skipped_not_due"] == 1
    assert too_soon["emails_sent"] == 0
    assert second["jobs_sent"] == 1
    assert accepted == ["backlog@example.test", "backlog@example.test"]

    engine.dispose()


def test_dry_run_reports_candidates_without_mutating_delivery_state(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'alert-dry-run.db'}")
    Base.metadata.create_all(engine)
    now = datetime(2026, 8, 23, tzinfo=timezone.utc)
    with Session(engine) as db:
        user = User(email="dry@example.test", password_hash="unused", name="Dry Run")
        db.add(user)
        db.flush()
        db.add_all([
            UserMemory(user_id=user.id, resume_text="Experienced platform engineer " * 4),
            JobAlertPreference(user_id=user.id, enabled=True, last_run_at=now - timedelta(days=2)),
        ])
        db.commit()
        user_id = user.id

    monkeypatch.setattr(job_alerts, "_utcnow", lambda: now)
    monkeypatch.setattr(job_alerts, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(job_alerts, "find_alert_matches", lambda *_args, **_kwargs: [
        AlertMatch(
            job=SimpleNamespace(id=123),
            score=90,
            matched_skills=[],
            missing_skills=[],
            why="Regression fixture",
        )
    ])

    result = job_alerts.run_job_alerts(dry_run=True)

    assert result["emails_would_send"] == 1
    assert result["jobs_would_send"] == 1
    assert result["emails_sent"] == 0
    with Session(engine) as check:
        preference = check.query(JobAlertPreference).filter_by(user_id=user_id).one()
        assert job_alerts._as_utc(preference.last_run_at) == now - timedelta(days=2)
        assert check.query(JobAlertDelivery).count() == 0
    engine.dispose()


@pytest.mark.parametrize("limit", [0, -1])
def test_run_job_alerts_rejects_non_positive_user_limit(limit):
    with pytest.raises(ValueError, match="positive integer"):
        job_alerts.run_job_alerts(limit_users=limit)


@pytest.mark.parametrize("value", ["0", "-1"])
def test_job_alert_cli_rejects_non_positive_user_limit(value):
    from send_job_alerts import _positive_int

    with pytest.raises(argparse.ArgumentTypeError, match="positive integer"):
        _positive_int(value)
