"""Privacy controls: upload consent, data export, retention purge, token redaction, tracing guard."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import config
import data_retention
import main
from auth import create_token
from data_retention import RETENTION_WARNING_ACTION, RetentionAction, RetentionPolicy, decide, run_retention
from database import SessionLocal
from models import JobAlertPreference, ResumeVersion, TrackedJob, UsageLog, User, UserMemory

NOW = datetime(2027, 6, 1, tzinfo=timezone.utc)
POLICY = RetentionPolicy(retention_days=365, warning_days=30)


@pytest.fixture
def client():
    with main._PUBLIC_RATE_LIMITER._lock:
        main._PUBLIC_RATE_LIMITER._hits.clear()
    yield TestClient(main.app)
    with main._PUBLIC_RATE_LIMITER._lock:
        main._PUBLIC_RATE_LIMITER._hits.clear()


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


def _user(db, *, last_seen: datetime | None = None, tier: str = "user") -> User:
    moment = last_seen or datetime.now(timezone.utc)
    user = User(
        name="Privacy Tester",
        email=f"privacy-{secrets.token_hex(6)}@example.com",
        password_hash="not-used",  # pragma: allowlist secret
        tier=tier,
        created_at=moment,
        last_login=moment,
        email_verified_at=moment,
        terms_accepted_at=moment,
        privacy_accepted_at=moment,
    )
    db.add(user)
    db.commit()
    return user


def _resume(db, user: User, at: datetime) -> None:
    db.add(ResumeVersion(
        user_id=user.id,
        label="Main",
        resume_text="Jane Doe resume text",
        created_at=at,
        updated_at=at,
    ))
    db.add(UserMemory(user_id=user.id, resume_text="Jane Doe resume text", created_at=at, updated_at=at))
    db.add(UsageLog(user_id=user.id, action="resume_upload", detail="{}", created_at=at))
    db.commit()


def _auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_token(user.id, user.token_version)}"}


# Upload consent

def _stub_parser(monkeypatch) -> None:
    async def parsed_upload(_file):
        return SimpleNamespace(parsed_resume={
            "text": "Jane Doe resume", "file_type": "pdf", "word_count": 3, "line_count": 1, "parse_quality": {},
        })

    monkeypatch.setattr(main, "parse_uploaded_resume", parsed_upload)


def test_anonymous_upload_without_consent_is_rejected(client, monkeypatch):
    _stub_parser(monkeypatch)

    response = client.post("/api/resume/upload", files={"file": ("cv.pdf", b"x", "application/pdf")})

    assert response.status_code == 400
    assert "agree" in response.json()["detail"]


def test_anonymous_upload_with_consent_is_parsed(client, monkeypatch):
    _stub_parser(monkeypatch)

    response = client.post(
        "/api/resume/upload",
        files={"file": ("cv.pdf", b"x", "application/pdf")},
        data={"consent": "true"},
    )

    assert response.status_code == 200
    assert response.json()["text"] == "Jane Doe resume"


# Data export

def test_export_requires_authentication(client):
    response = client.get("/api/account/export")

    assert response.status_code == 401


def test_export_returns_only_the_callers_rows_without_credentials(client, db):
    owner = _user(db)
    other = _user(db)
    _resume(db, owner, datetime.now(timezone.utc))
    _resume(db, other, datetime.now(timezone.utc))

    response = client.get("/api/account/export", headers=_auth(owner))

    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    data = response.json()["data"]
    assert [row["email"] for row in data["users"]] == [owner.email]
    assert {row["user_id"] for row in data["resume_versions"]} == {owner.id}
    assert data["user_memories"][0]["resume_text"] == "Jane Doe resume text"
    assert {"password_hash", "api_key", "token_version"}.isdisjoint(data["users"][0])
    assert "password_reset_tokens" not in data


# Retention selection (fake clock)

def test_recently_active_account_is_left_alone(db):
    user = _user(db, last_seen=NOW - timedelta(days=30))
    _resume(db, user, NOW - timedelta(days=30))

    assert decide(db, user, NOW, POLICY) is None


def test_account_inactive_for_eleven_months_gets_a_warning_first(db):
    user = _user(db, last_seen=NOW - timedelta(days=340))
    _resume(db, user, NOW - timedelta(days=340))

    assert decide(db, user, NOW, POLICY) is RetentionAction.WARN


def test_inactive_account_is_purged_only_after_the_warning_period(db):
    old = NOW - timedelta(days=400)
    user = _user(db, last_seen=old)
    _resume(db, user, old)
    db.add(UsageLog(user_id=user.id, action=RETENTION_WARNING_ACTION, created_at=NOW - timedelta(days=10)))
    db.commit()

    assert decide(db, user, NOW, POLICY) is None
    assert decide(db, user, NOW + timedelta(days=21), POLICY) is RetentionAction.PURGE


def test_accounts_with_alerts_on_admins_or_no_data_are_skipped(db):
    old = NOW - timedelta(days=500)
    with_alerts = _user(db, last_seen=old)
    _resume(db, with_alerts, old)
    db.add(JobAlertPreference(user_id=with_alerts.id, enabled=1))
    admin = _user(db, last_seen=old, tier="admin")
    _resume(db, admin, old)
    empty = _user(db, last_seen=old)
    db.commit()

    assert [decide(db, user, NOW, POLICY) for user in (with_alerts, admin, empty)] == [None, None, None]


def test_recent_activity_resets_the_clock_after_a_warning(db):
    old = NOW - timedelta(days=400)
    user = _user(db, last_seen=old)
    _resume(db, user, old)
    db.add(UsageLog(user_id=user.id, action=RETENTION_WARNING_ACTION, created_at=NOW - timedelta(days=40)))
    db.add(UsageLog(user_id=user.id, action="resume_score", created_at=NOW - timedelta(days=5)))
    db.commit()

    assert decide(db, user, NOW, POLICY) is None


def test_plan_retention_selects_stale_accounts_and_skips_fresh_ones(db):
    stale = _user(db, last_seen=NOW - timedelta(days=350))
    _resume(db, stale, NOW - timedelta(days=350))
    fresh = _user(db, last_seen=NOW - timedelta(days=3))
    _resume(db, fresh, NOW - timedelta(days=3))

    plan = dict(data_retention.plan_retention(db, NOW, POLICY))

    assert plan.get(stale.id) is RetentionAction.WARN
    assert fresh.id not in plan


def test_run_retention_purges_content_but_keeps_account_and_tracker(db, monkeypatch):
    old = NOW - timedelta(days=400)
    user = _user(db, last_seen=old)
    _resume(db, user, old)
    db.add(TrackedJob(
        user_id=user.id, role="Analyst", company="Acme", status="applied",
        role_metadata={"submitted_resume": {"text": "secret"}, "notes": "keep"},
        created_at=old, updated_at=old,
    ))
    db.add(UsageLog(user_id=user.id, action=RETENTION_WARNING_ACTION, created_at=NOW - timedelta(days=31)))
    db.commit()
    monkeypatch.setattr(data_retention, "email_configured", lambda: True)
    monkeypatch.setattr(data_retention, "plan_retention", lambda session, now, policy: [(user.id, RetentionAction.PURGE)])
    monkeypatch.setattr(data_retention, "RetentionPolicy", lambda: POLICY)

    stats = run_retention(db, now=NOW)

    assert stats["purged"] == 1
    db.expire_all()
    assert db.get(User, user.id) is not None
    assert db.query(ResumeVersion).filter_by(user_id=user.id).count() == 0
    assert db.query(UserMemory).filter_by(user_id=user.id).count() == 0
    assert db.query(UsageLog).filter_by(user_id=user.id).count() == 0
    assert db.query(TrackedJob).filter_by(user_id=user.id).one().role_metadata == {"notes": "keep"}


def test_run_retention_sends_warning_email_and_records_it(db, monkeypatch):
    old = NOW - timedelta(days=340)
    user = _user(db, last_seen=old)
    _resume(db, user, old)
    sent = []
    monkeypatch.setattr(data_retention, "email_configured", lambda: True)
    monkeypatch.setattr(data_retention, "send_email", lambda to, subject, text, html: sent.append((to, text)))
    monkeypatch.setattr(data_retention, "plan_retention", lambda session, now, policy: [(user.id, RetentionAction.WARN)])
    monkeypatch.setattr(data_retention, "RetentionPolicy", lambda: POLICY)

    stats = run_retention(db, now=NOW)

    assert stats["warned"] == 1
    assert sent[0][0] == user.email
    assert config.PRIVACY_CONTACT_EMAIL in sent[0][1]
    assert db.query(UsageLog).filter_by(user_id=user.id, action=RETENTION_WARNING_ACTION).count() == 1


def test_run_retention_purges_no_accounts_without_email(db, monkeypatch):
    monkeypatch.setattr(data_retention, "email_configured", lambda: False)

    stats = run_retention(db, now=NOW, dry_run=True)

    assert stats["email_configured"] is False
    assert stats["planned_purges"] == 0


# Token redaction

def test_client_error_reports_redact_email_link_tokens():
    url = "https://job.kooexperience.com/?reset_token=abc123&tab=x#verify_token=def456"

    cleaned = main._redact_auth_tokens(url)

    assert "abc123" not in cleaned and "def456" not in cleaned
    assert "reset_token=[redacted]" in cleaned and "tab=x" in cleaned


# Tracing guard

def test_llm_tracing_is_forced_off_without_opt_in(monkeypatch):
    monkeypatch.delenv(config.LLM_TRACING_OPT_IN_ENV, raising=False)
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")

    config.enforce_llm_tracing_opt_in()

    assert main.os.environ["LANGCHAIN_TRACING_V2"] == "false"
    assert main.os.environ["LANGSMITH_TRACING"] == "false"


def test_llm_tracing_is_left_alone_with_explicit_opt_in(monkeypatch):
    monkeypatch.setenv(config.LLM_TRACING_OPT_IN_ENV, "1")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")

    config.enforce_llm_tracing_opt_in()

    assert main.os.environ["LANGCHAIN_TRACING_V2"] == "true"
