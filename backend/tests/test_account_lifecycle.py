from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import main
from auth import CLOUDFLARE_PASSWORD_SENTINEL
from database import SessionLocal
from models import (
    EmailVerificationToken,
    InterviewStory,
    JobAlertDelivery,
    JobAlertPreference,
    PasswordResetToken,
    PowerMatchSnapshot,
    ResumeVersion,
    ScrapedJob,
    StoryUsage,
    TailoredResume,
    TrackedJob,
    UsageLog,
    User,
    UserMemory,
)


@pytest.fixture
def client() -> TestClient:
    return TestClient(main.app)


@pytest.fixture
def verification_mail(monkeypatch) -> list[str]:
    tokens: list[str] = []
    monkeypatch.setattr(main, "email_configured", lambda: True)
    monkeypatch.setattr(
        main,
        "_send_verification_email",
        lambda _user, token: tokens.append(token),
    )
    return tokens


def _signup(client: TestClient, tokens: list[str]) -> tuple[str, str, str]:
    email = f"account_{secrets.token_hex(6)}@aisg.sg"
    password = "StartingPassword123!"  # pragma: allowlist secret
    response = client.post(
        "/api/auth/signup",
        json={
            "email": email,
            "password": password,
            "name": "Account Test",
            "accepted_terms": True,
        },
    )
    assert response.status_code == 200
    assert "token" not in response.json()
    return email, password, tokens[-1]


def _verify(client: TestClient, verification_token: str) -> str:
    response = client.post(
        "/api/auth/verify-email",
        json={"token": verification_token},
    )
    assert response.status_code == 200
    return response.json()["token"]


def test_signup_requires_single_use_email_verification(
    client: TestClient,
    verification_mail: list[str],
) -> None:
    email, password, verification_token = _signup(client, verification_mail)

    before_verification = client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert before_verification.status_code == 403

    with SessionLocal() as db:
        stored = (
            db.query(EmailVerificationToken)
            .join(User, User.id == EmailVerificationToken.user_id)
            .filter(User.email == email)
            .one()
        )
        assert stored.token_hash != verification_token
        assert stored.token_hash == main._auth_token_hash(verification_token)

    bearer = _verify(client, verification_token)
    replay = client.post(
        "/api/auth/verify-email", json={"token": verification_token}
    )
    assert replay.status_code == 400
    assert client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {bearer}"}
    ).status_code == 200


def test_expired_and_unknown_verification_links_are_rejected(
    client: TestClient,
    verification_mail: list[str],
) -> None:
    email, _password, verification_token = _signup(client, verification_mail)
    with SessionLocal() as db:
        verification = (
            db.query(EmailVerificationToken)
            .join(User, User.id == EmailVerificationToken.user_id)
            .filter(User.email == email)
            .one()
        )
        verification.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()

    assert client.post(
        "/api/auth/verify-email", json={"token": verification_token}
    ).status_code == 400
    assert client.post(
        "/api/auth/verify-email", json={"token": secrets.token_urlsafe(40)}
    ).status_code == 400


def test_duplicate_signup_is_generic_and_cloudflare_hash_never_reaches_bcrypt(
    client: TestClient,
    verification_mail: list[str],
) -> None:
    email, password, first_token = _signup(client, verification_mail)
    duplicate = client.post(
        "/api/auth/signup",
        json={
            "email": email,
            "password": password,
            "name": "Account Test",
            "accepted_terms": True,
        },
    )
    assert duplicate.status_code == 200
    assert duplicate.json() == main._VERIFICATION_MESSAGE
    assert verification_mail[-1] != first_token
    assert client.post(
        "/api/auth/verify-email", json={"token": first_token}
    ).status_code == 400

    cloudflare_email = f"cf_{secrets.token_hex(6)}@aisg.sg"
    with SessionLocal() as db:
        db.add(
            User(
                email=cloudflare_email,
                password_hash=CLOUDFLARE_PASSWORD_SENTINEL,
                name="CF User",
                email_verified_at=datetime.now(timezone.utc),
            )
        )
        db.commit()
    response = client.post(
        "/api/auth/login",
        json={
            "email": cloudflare_email,
            "password": "Anything123!",  # pragma: allowlist secret
        },
    )
    assert response.status_code == 401


def test_password_change_and_reset_revoke_existing_tokens(
    client: TestClient,
    verification_mail: list[str],
    monkeypatch,
) -> None:
    email, password, verification_token = _signup(client, verification_mail)
    original_token = _verify(client, verification_token)
    changed_password = "ChangedPassword123!"  # pragma: allowlist secret
    change = client.post(
        "/api/auth/change-password",
        headers={"Authorization": f"Bearer {original_token}"},
        json={"current_password": password, "new_password": changed_password},
    )
    assert change.status_code == 200
    changed_token = change.json()["token"]
    assert client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {original_token}"}
    ).status_code == 401
    assert client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {changed_token}"}
    ).status_code == 200

    reset_tokens: list[str] = []
    monkeypatch.setattr(
        main,
        "_send_password_reset_email",
        lambda _user, token: reset_tokens.append(token),
    )
    assert client.post(
        "/api/auth/forgot-password", json={"email": email}
    ).status_code == 200
    reset_password = "ResetPassword123!"  # pragma: allowlist secret
    assert client.post(
        "/api/auth/reset-password",
        json={"token": reset_tokens[-1], "password": reset_password},
    ).status_code == 200
    assert client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {changed_token}"}
    ).status_code == 401
    assert client.post(
        "/api/auth/login", json={"email": email, "password": reset_password}
    ).status_code == 200


def test_cloudflare_registration_is_explicit(client: TestClient) -> None:
    email = f"cf_register_{secrets.token_hex(6)}@aisg.sg"
    main.app.dependency_overrides[main.get_cloudflare_email] = lambda: email
    try:
        response = client.post(
            "/api/auth/cloudflare/register",
            json={"name": "Cloudflare User", "accepted_terms": True},
        )
    finally:
        main.app.dependency_overrides.pop(main.get_cloudflare_email, None)
    assert response.status_code == 200
    with SessionLocal() as db:
        user = db.query(User).filter(User.email == email).one()
        assert user.password_hash == CLOUDFLARE_PASSWORD_SENTINEL
        assert user.email_verified_at is not None
        db.delete(user)
        db.commit()


def test_deletion_rejects_wrong_password_and_active_sessions_then_rolls_back(
    client: TestClient,
    verification_mail: list[str],
    monkeypatch,
) -> None:
    email, password, verification_token = _signup(client, verification_mail)
    bearer = _verify(client, verification_token)
    headers = {"Authorization": f"Bearer {bearer}"}
    with SessionLocal() as db:
        user = db.query(User).filter(User.email == email).one()
        user_id = user.id
        db.add(UserMemory(user_id=user_id, resume_text="must survive rollback"))
        db.commit()

    wrong_password = client.request(
        "DELETE",
        "/api/account",
        headers=headers,
        json={
            "confirm_email": email,
            "current_password": "WrongPassword123!",  # pragma: allowlist secret
        },
    )
    assert wrong_password.status_code == 400

    from resume_agent import session as agent_session

    owner_key = f"user:{user_id}"
    agent_session._active_runs[owner_key] = 1
    try:
        active = client.request(
            "DELETE",
            "/api/account",
            headers=headers,
            json={"confirm_email": email, "current_password": password},
        )
    finally:
        agent_session._active_runs.pop(owner_key, None)
    assert active.status_code == 409

    original_delete = main._delete_owned_account_rows

    def fail_after_deletes(user: User, db) -> None:
        original_delete(user, db)
        raise RuntimeError("forced rollback")

    monkeypatch.setattr(main, "_delete_owned_account_rows", fail_after_deletes)
    rollback_client = TestClient(main.app, raise_server_exceptions=False)
    failed = rollback_client.request(
        "DELETE",
        "/api/account",
        headers=headers,
        json={"confirm_email": email, "current_password": password},
    )
    assert failed.status_code == 500
    with SessionLocal() as db:
        assert db.get(User, user_id) is not None
        assert db.query(UserMemory).filter(UserMemory.user_id == user_id).count() == 1


def test_account_deletion_removes_every_owned_row_but_retains_jobs(
    client: TestClient,
    verification_mail: list[str],
) -> None:
    email, password, verification_token = _signup(client, verification_mail)
    bearer = _verify(client, verification_token)
    now = datetime.now(timezone.utc)

    with SessionLocal() as db:
        user = db.query(User).filter(User.email == email).one()
        user_id = user.id
        other_user = User(
            email=f"other_{secrets.token_hex(6)}@aisg.sg",
            password_hash=user.password_hash,
            name="Other Account",
            email_verified_at=now,
        )
        job = ScrapedJob(title="Role", company="Employer", dedup_key=secrets.token_hex(16))
        resume = ResumeVersion(user_id=user_id, label="Master")
        story = InterviewStory(user_id=user_id, title="Story")
        preference = JobAlertPreference(user_id=user_id)
        db.add_all([other_user, job, resume, story, preference])
        db.flush()
        other_user_id = other_user.id
        job_id = job.id
        db.add_all(
            [
                StoryUsage(story_id=story.id, user_id=user_id),
                JobAlertDelivery(
                    user_id=user_id,
                    preference_id=preference.id,
                    scraped_job_id=job.id,
                ),
                TrackedJob(
                    user_id=user_id,
                    company="Employer",
                    role="Role",
                    resume_version_id=resume.id,
                ),
                PasswordResetToken(
                    user_id=user_id,
                    token_hash=hashlib.sha256(secrets.token_bytes(20)).hexdigest(),
                    expires_at=now + timedelta(hours=1),
                ),
                PowerMatchSnapshot(
                    user_id=user_id,
                    resume_hash="resume",
                    corpus_marker="corpus",
                    result={},
                ),
                TailoredResume(
                    user_id=user_id,
                    job_id=job.id,
                    session_id=secrets.token_hex(16),
                ),
                UserMemory(user_id=user_id, resume_text="private resume"),
                UserMemory(user_id=other_user_id, resume_text="other account data"),
                UsageLog(user_id=user_id, action="ai", detail="private"),
                UsageLog(
                    user_id=None,
                    action="login_failed",
                    detail=hashlib.sha256(email.encode()).hexdigest()[:16],
                ),
            ]
        )
        db.commit()

    main._power_match_cache[user_id] = {"private": True}
    from resume_agent import session as agent_session
    from tailoring_pipeline import PipelineState, _active_pipelines

    agent_session._sessions["completed-agent"] = {
        "_owner_key": f"user:{user_id}",
        "_updated_at": 0,
    }
    pipeline = PipelineState("completed-pipeline", owner_key=f"user:{user_id}")
    pipeline.set_result({})
    _active_pipelines[pipeline.session_id] = pipeline

    mismatch = client.request(
        "DELETE",
        "/api/account",
        headers={"Authorization": f"Bearer {bearer}"},
        json={"confirm_email": email.upper(), "current_password": password},
    )
    assert mismatch.status_code == 400
    deleted = client.request(
        "DELETE",
        "/api/account",
        headers={"Authorization": f"Bearer {bearer}"},
        json={"confirm_email": email, "current_password": password},
    )
    assert deleted.status_code == 200
    assert client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {bearer}"}
    ).status_code == 401

    with SessionLocal() as db:
        assert db.get(User, user_id) is None
        for model in (
            StoryUsage,
            JobAlertDelivery,
            TrackedJob,
            PasswordResetToken,
            EmailVerificationToken,
            PowerMatchSnapshot,
            TailoredResume,
            ResumeVersion,
            InterviewStory,
            JobAlertPreference,
            UserMemory,
        ):
            assert db.query(model).filter(model.user_id == user_id).count() == 0
        assert db.query(UsageLog).filter(UsageLog.user_id == user_id).count() == 0
        assert db.get(ScrapedJob, job_id) is not None
        assert db.get(User, other_user_id) is not None
        assert db.query(UserMemory).filter(UserMemory.user_id == other_user_id).count() == 1
    assert user_id not in main._power_match_cache
    assert "completed-agent" not in agent_session._sessions
    assert "completed-pipeline" not in _active_pipelines
