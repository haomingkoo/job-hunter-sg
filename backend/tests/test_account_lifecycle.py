from __future__ import annotations

import hashlib
import secrets
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
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
def client():
    with main._PUBLIC_RATE_LIMITER._lock:
        main._PUBLIC_RATE_LIMITER._hits.clear()
    yield TestClient(main.app)
    with main._PUBLIC_RATE_LIMITER._lock:
        main._PUBLIC_RATE_LIMITER._hits.clear()


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


def _verify(client: TestClient, verification_token: str, password: str) -> str:
    response = client.post(
        "/api/auth/verify-email",
        json={
            "token": verification_token,
            "password": password,
            "name": "Account Test",
            "accepted_terms": True,
        },
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

    bearer = _verify(client, verification_token, password)
    replay = client.post(
        "/api/auth/verify-email",
        json={
            "token": verification_token,
            "password": password,
            "name": "Account Test",
            "accepted_terms": True,
        },
    )
    assert replay.status_code == 400
    assert client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {bearer}"}
    ).status_code == 200


def test_expired_and_unknown_verification_links_are_rejected(
    client: TestClient,
    verification_mail: list[str],
) -> None:
    email, password, verification_token = _signup(client, verification_mail)
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
        "/api/auth/verify-email",
        json={
            "token": verification_token,
            "password": password,
            "name": "Account Test",
            "accepted_terms": True,
        },
    ).status_code == 400
    assert client.post(
        "/api/auth/verify-email",
        json={
            "token": secrets.token_urlsafe(40),
            "password": password,
            "name": "Account Test",
            "accepted_terms": True,
        },
    ).status_code == 400


def test_resend_does_not_revoke_an_already_delivered_verification_link(
    client: TestClient,
    verification_mail: list[str],
) -> None:
    email, password, first_token = _signup(client, verification_mail)
    with SessionLocal() as db:
        token_row = (
            db.query(EmailVerificationToken)
            .join(User, User.id == EmailVerificationToken.user_id)
            .filter(User.email == email)
            .one()
        )
        token_row.created_at = datetime.now(timezone.utc) - timedelta(minutes=6)
        db.commit()

    resent = client.post("/api/auth/resend-verification", json={"email": email})
    assert resent.status_code == 200
    assert len(verification_mail) == 2
    second_token = verification_mail[-1]
    assert second_token != first_token

    bearer = _verify(client, first_token, password)
    assert bearer
    assert client.post(
        "/api/auth/verify-email",
        json={
            "token": second_token,
            "password": password,
            "name": "Account Test",
            "accepted_terms": True,
        },
    ).status_code == 400


def test_invalid_bcrypt_length_does_not_consume_verification_link(
    client: TestClient,
    verification_mail: list[str],
) -> None:
    _email, password, verification_token = _signup(client, verification_mail)
    invalid = client.post(
        "/api/auth/verify-email",
        json={
            "token": verification_token,
            "password": "a" * 73,
            "name": "Account Test",
            "accepted_terms": True,
        },
    )
    assert invalid.status_code == 422
    assert _verify(client, verification_token, password)


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
    assert len(verification_mail) == 1
    assert client.post(
        "/api/auth/verify-email",
        json={
            "token": first_token,
            "password": password,
            "name": "Account Test",
            "accepted_terms": True,
        },
    ).status_code == 200

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


def test_mailbox_owner_can_claim_a_pre_registered_email_without_signup_races(
    client: TestClient,
    verification_mail: list[str],
) -> None:
    email, attacker_password, attacker_token = _signup(client, verification_mail)
    victim_password = "VictimOwnedPassword456!"  # pragma: allowlist secret
    replacement = client.post(
        "/api/auth/signup",
        json={
            "email": email,
            "password": victim_password,
            "name": "Actual Email Owner",
            "accepted_terms": True,
        },
    )

    assert replacement.status_code == 200
    assert len(verification_mail) == 1

    attacker_retry = client.post(
        "/api/auth/signup",
        json={
            "email": email,
            "password": attacker_password,
            "name": "Attacker Retry",
            "accepted_terms": True,
        },
    )
    assert attacker_retry.status_code == 200
    assert len(verification_mail) == 1
    assert client.post(
        "/api/auth/verify-email",
        json={
            "token": attacker_token,
            "password": victim_password,
            "name": "Actual Email Owner",
            "accepted_terms": True,
        },
    ).status_code == 200
    assert client.post(
        "/api/auth/login", json={"email": email, "password": attacker_password}
    ).status_code == 401
    victim_login = client.post(
        "/api/auth/login", json={"email": email, "password": victim_password}
    )
    assert victim_login.status_code == 200
    assert victim_login.json()["user"]["name"] == "Actual Email Owner"


def test_correct_password_is_not_blocked_by_attackers_failed_attempts(
    client: TestClient,
    verification_mail: list[str],
) -> None:
    email, password, verification_token = _signup(client, verification_mail)
    _verify(client, verification_token, password)
    email_hash = hashlib.sha256(email.encode()).hexdigest()[:16]
    with SessionLocal() as db:
        db.add_all(
            UsageLog(user_id=None, action="login_failed", detail=email_hash)
            for _ in range(5)
        )
        db.commit()

    valid = client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )
    invalid = client.post(
        "/api/auth/login",
        json={
            "email": email,
            "password": "WrongPassword123!",  # pragma: allowlist secret
        },
    )

    assert valid.status_code == 200
    assert invalid.status_code == 429


def test_password_change_and_reset_revoke_existing_tokens(
    client: TestClient,
    verification_mail: list[str],
    monkeypatch,
) -> None:
    email, password, verification_token = _signup(client, verification_mail)
    original_token = _verify(client, verification_token, password)
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


def test_password_reset_requests_share_a_per_account_cooldown(
    client: TestClient,
    verification_mail: list[str],
    monkeypatch,
) -> None:
    email, password, verification_token = _signup(client, verification_mail)
    _verify(client, verification_token, password)
    reset_tokens: list[str] = []
    monkeypatch.setattr(
        main,
        "_send_password_reset_email",
        lambda _user, token: reset_tokens.append(token),
    )

    for _ in range(2):
        assert client.post(
            "/api/auth/forgot-password",
            json={"email": email},
        ).status_code == 200
    assert len(reset_tokens) == 1

    with SessionLocal() as db:
        token = (
            db.query(PasswordResetToken)
            .join(User, User.id == PasswordResetToken.user_id)
            .filter(User.email == email)
            .one()
        )
        token.created_at = datetime.now(timezone.utc) - timedelta(minutes=6)
        db.commit()

    assert client.post(
        "/api/auth/forgot-password",
        json={"email": email},
    ).status_code == 200
    assert len(reset_tokens) == 2

    reset_password = "ResetPassword123!"  # pragma: allowlist secret
    assert client.post(
        "/api/auth/reset-password",
        json={"token": reset_tokens[0], "password": reset_password},
    ).status_code == 200
    assert client.post(
        "/api/auth/reset-password",
        json={"token": reset_tokens[1], "password": reset_password},
    ).status_code == 400


def test_concurrent_password_changes_are_serialized(
    client: TestClient,
    monkeypatch,
) -> None:
    from auth import hash_password, verify_password
    from schemas import ChangePasswordRequest

    email = f"credential_race_{secrets.token_hex(6)}@aisg.sg"
    current_password = "StartingPassword123!"  # pragma: allowlist secret
    first_password = "FirstPassword123!"  # pragma: allowlist secret
    second_password = "SecondPassword123!"  # pragma: allowlist secret
    with SessionLocal() as db:
        user = User(
            email=email,
            password_hash=hash_password(current_password),
            name="Credential Race",
            email_verified_at=datetime.now(timezone.utc),
        )
        db.add(user)
        db.commit()
        user_id = user.id
        initial_token_version = user.token_version

    first_db = SessionLocal()
    second_db = SessionLocal()
    first_user = first_db.get(User, user_id)
    second_user = second_db.get(User, user_id)
    first_hash_started = threading.Event()
    release_first = threading.Event()
    second_started = threading.Event()
    real_hash_password = main.hash_password

    def gated_hash_password(password: str) -> str:
        if password == first_password:
            first_hash_started.set()
            assert release_first.wait(5)
        return real_hash_password(password)

    monkeypatch.setattr(main, "hash_password", gated_hash_password)

    def run_first_change() -> dict:
        return main.change_password(
            ChangePasswordRequest(
                current_password=current_password,
                new_password=first_password,
            ),
            first_user,
            first_db,
        )

    def run_second_change() -> dict:
        second_started.set()
        return main.change_password(
            ChangePasswordRequest(
                current_password=current_password,
                new_password=second_password,
            ),
            second_user,
            second_db,
        )

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first_future = pool.submit(run_first_change)
            assert first_hash_started.wait(5)
            second_future = pool.submit(run_second_change)
            assert second_started.wait(5)
            release_first.set()
            first_change = first_future.result(timeout=10)
            with pytest.raises(HTTPException) as exc_info:
                second_future.result(timeout=10)
            assert exc_info.value.status_code == 401

        with SessionLocal() as db:
            final_user = db.get(User, user_id)
            assert final_user.token_version == initial_token_version + 1
            assert verify_password(first_password, final_user.password_hash)
        assert client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {first_change['token']}"},
        ).status_code == 200
    finally:
        release_first.set()
        first_db.rollback()
        second_db.rollback()
        first_db.close()
        second_db.close()
        with SessionLocal() as db:
            db.query(User).filter(User.id == user_id).delete()
            db.commit()


def test_reset_password_increments_a_fresh_token_version(
    client: TestClient,
    monkeypatch,
) -> None:
    from auth import hash_password, verify_password
    from schemas import ChangePasswordRequest, ResetPasswordRequest

    email = f"reset_version_{secrets.token_hex(6)}@aisg.sg"
    current_password = "StartingPassword123!"  # pragma: allowlist secret
    changed_password = "ChangedPassword123!"  # pragma: allowlist secret
    reset_password = "ResetPassword123!"  # pragma: allowlist secret
    reset_token = secrets.token_urlsafe(40)
    with SessionLocal() as db:
        user = User(
            email=email,
            password_hash=hash_password(current_password),
            name="Reset Version",
            email_verified_at=datetime.now(timezone.utc),
        )
        db.add(user)
        db.commit()
        user_id = user.id
        initial_token_version = user.token_version

    change_db = SessionLocal()
    reset_db = SessionLocal()
    change_user = change_db.get(User, user_id)
    reset_db.get(User, user_id)  # Simulate a request that read the old version.
    monkeypatch.setattr(main._PUBLIC_RATE_LIMITER, "allow", lambda *_args, **_kwargs: True)

    try:
        changed = main.change_password(
            ChangePasswordRequest(
                current_password=current_password,
                new_password=changed_password,
            ),
            change_user,
            change_db,
        )
        with SessionLocal() as db:
            db.add(
                PasswordResetToken(
                    user_id=user_id,
                    token_hash=main._password_reset_hash(reset_token),
                    expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                )
            )
            db.commit()

        main.reset_password(
            SimpleNamespace(client=SimpleNamespace(host="127.0.0.1")),
            ResetPasswordRequest(token=reset_token, password=reset_password),
            reset_db,
        )

        with SessionLocal() as db:
            final_user = db.get(User, user_id)
            assert final_user.token_version == initial_token_version + 2
            assert verify_password(reset_password, final_user.password_hash)
        assert client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {changed['token']}"},
        ).status_code == 401
    finally:
        change_db.rollback()
        reset_db.rollback()
        change_db.close()
        reset_db.close()
        with SessionLocal() as db:
            db.query(UsageLog).filter(UsageLog.user_id == user_id).delete()
            db.query(PasswordResetToken).filter(
                PasswordResetToken.user_id == user_id
            ).delete()
            db.query(User).filter(User.id == user_id).delete()
            db.commit()


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


def test_cloudflare_registration_records_consent_for_a_legacy_sentinel_account(
    client: TestClient,
) -> None:
    email = f"cf_legacy_{secrets.token_hex(6)}@aisg.sg"
    with SessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=CLOUDFLARE_PASSWORD_SENTINEL,
                name="Legacy Cloudflare User",
                email_verified_at=None,
                terms_accepted_at=None,
                privacy_accepted_at=None,
            )
        )
        db.commit()

    main.app.dependency_overrides[main.get_cloudflare_email] = lambda: email
    try:
        response = client.post(
            "/api/auth/cloudflare/register",
            json={"name": "Legacy Cloudflare User", "accepted_terms": True},
        )
    finally:
        main.app.dependency_overrides.pop(main.get_cloudflare_email, None)

    assert response.status_code == 200
    with SessionLocal() as db:
        user = db.query(User).filter(User.email == email).one()
        assert user.email_verified_at is not None
        assert user.terms_accepted_at is not None
        assert user.privacy_accepted_at is not None
        db.delete(user)
        db.commit()


def test_contact_form_delivers_the_authenticated_users_message(
    monkeypatch,
) -> None:
    from schemas import ContactRequest

    email = f"contact-{secrets.token_hex(6)}@example.com"
    delivered = {}
    monkeypatch.setenv("CONTACT_EMAIL", "support@example.com")
    monkeypatch.setattr(main, "email_configured", lambda: True)
    monkeypatch.setattr(main._PUBLIC_RATE_LIMITER, "allow", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        main,
        "send_email",
        lambda to, subject, text, html: delivered.update(
            to=to,
            subject=subject,
            text=text,
            html=html,
        ),
    )

    with SessionLocal() as db:
        user = User(
            name="Account User",
            email=email,
            password_hash="not-used",  # pragma: allowlist secret
            email_verified_at=datetime.now(timezone.utc),
        )
        db.add(user)
        db.commit()
        response = main.contact(
            SimpleNamespace(client=SimpleNamespace(host="127.0.0.1")),
            ContactRequest(
                name=user.name,
                email=user.email,
                message="Please help with my saved resume.",
            ),
            user,
            db,
        )
        db.query(UsageLog).filter(UsageLog.user_id == user.id).delete()
        db.delete(user)
        db.commit()

    assert response == {"message": "Message sent."}
    assert delivered["to"] == "support@example.com"
    assert "Please help with my saved resume." in delivered["text"]
    assert email in delivered["text"]


def test_contact_form_is_not_public(client: TestClient) -> None:
    response = client.post(
        "/api/contact",
        json={
            "name": "Anonymous",
            "email": "anonymous@example.com",
            "message": "This should not be accepted anonymously.",
        },
    )

    assert response.status_code == 401


def test_logout_revokes_the_presented_password_session(
    client: TestClient,
    verification_mail: list[str],
) -> None:
    _email, password, verification_token = _signup(client, verification_mail)
    bearer = _verify(client, verification_token, password)
    headers = {"Authorization": f"Bearer {bearer}"}

    response = client.post("/api/auth/logout", headers=headers)

    assert response.status_code == 200
    assert client.get("/api/auth/me", headers=headers).status_code == 401


def test_deletion_rejects_wrong_password_and_active_sessions_then_rolls_back(
    client: TestClient,
    verification_mail: list[str],
    monkeypatch,
) -> None:
    email, password, verification_token = _signup(client, verification_mail)
    bearer = _verify(client, verification_token, password)
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

    from tailoring_pipeline import PipelineState, _active_pipelines

    active_pipeline = PipelineState("active-deletion-check", owner_key=owner_key)
    _active_pipelines[active_pipeline.session_id] = active_pipeline
    try:
        active_tailoring = client.request(
            "DELETE",
            "/api/account",
            headers=headers,
            json={"confirm_email": email, "current_password": password},
        )
    finally:
        _active_pipelines.pop(active_pipeline.session_id, None)
    assert active_tailoring.status_code == 409

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


def test_agent_admission_and_account_deletion_share_a_lifecycle_barrier(
    monkeypatch,
) -> None:
    from auth import hash_password
    from resume_agent.session import release_owner_run
    from schemas import DeleteAccountRequest

    email = f"lifecycle-race-{secrets.token_hex(6)}@aisg.sg"
    password = "LifecyclePassword123!"  # pragma: allowlist secret
    with SessionLocal() as db:
        user = User(
            email=email,
            password_hash=hash_password(password),
            name="Lifecycle Race",
            email_verified_at=datetime.now(timezone.utc),
        )
        db.add(user)
        db.commit()
        user_id = user.id

    agent_db = SessionLocal()
    deletion_db = SessionLocal()
    agent_user = agent_db.get(User, user_id)
    deletion_user = deletion_db.get(User, user_id)
    credit_started = threading.Event()
    release_credit = threading.Event()
    deletion_started = threading.Event()
    owner_key = f"user:{user_id}"

    def blocked_credit(*_args, **_kwargs) -> None:
        credit_started.set()
        assert release_credit.wait(5)

    def run_deletion():
        deletion_started.set()
        return main.delete_account(
            DeleteAccountRequest(
                confirm_email=email,
                current_password=password,
            ),
            deletion_user,
            deletion_db,
        )

    monkeypatch.setattr(main, "_consume_ai_credit", blocked_credit)
    monkeypatch.setattr(main._PUBLIC_RATE_LIMITER, "allow", lambda *_args, **_kwargs: True)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            admitted = pool.submit(main.resume_agent_chat, {}, agent_user, agent_db)
            assert credit_started.wait(5)
            deleting = pool.submit(run_deletion)
            assert deletion_started.wait(5)
            with pytest.raises(TimeoutError):
                deleting.result(timeout=0.2)
            release_credit.set()
            assert admitted.result(timeout=5).media_type == "text/event-stream"
            with pytest.raises(HTTPException) as exc_info:
                deleting.result(timeout=5)
            assert exc_info.value.status_code == 409
    finally:
        release_credit.set()
        release_owner_run(owner_key)
        agent_db.rollback()
        deletion_db.rollback()
        agent_db.close()
        deletion_db.close()
        with SessionLocal() as db:
            db.query(User).filter(User.id == user_id).delete()
            db.commit()


def test_password_change_revokes_a_delete_request_waiting_on_old_credentials(
    monkeypatch,
) -> None:
    import tailoring_pipeline as _tailoring_pipeline  # noqa: F401
    from resume_agent import session as _agent_session  # noqa: F401
    from schemas import DeleteAccountRequest

    user_id = 9_700_001
    email = "delete-credential-race@example.com"
    old_password = "StartingPassword123!"  # pragma: allowlist secret
    dependency_user = SimpleNamespace(id=user_id, token_version=0)
    locked_user = SimpleNamespace(
        id=user_id,
        token_version=0,
        email=email,
        password_hash="old-hash",  # pragma: allowlist secret
    )
    credential_lock = threading.Lock()
    change_started = threading.Event()
    release_change = threading.Event()
    deletion_started = threading.Event()

    class FakeDb:
        rolled_back = False

        def rollback(self):
            self.rolled_back = True

    @contextmanager
    def locked_credential_user(_user_id, _db):
        with credential_lock:
            yield locked_user

    def run_change():
        with credential_lock:
            change_started.set()
            assert release_change.wait(5)
            locked_user.token_version += 1
            locked_user.password_hash = "new-hash"  # pragma: allowlist secret

    def run_deletion():
        deletion_started.set()
        return main.delete_account(
            DeleteAccountRequest(
                confirm_email=email,
                current_password=old_password,
            ),
            dependency_user,
            FakeDb(),
        )

    monkeypatch.setattr(main, "_locked_credential_user", locked_credential_user)
    monkeypatch.setattr(main._PUBLIC_RATE_LIMITER, "allow", lambda *_args, **_kwargs: True)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            changing = pool.submit(run_change)
            assert change_started.wait(5)
            deleting = pool.submit(run_deletion)
            assert deletion_started.wait(5)
            with pytest.raises(TimeoutError):
                deleting.result(timeout=0.2)
            release_change.set()
            changed = changing.result(timeout=5)
            with pytest.raises(HTTPException) as exc_info:
                deleting.result(timeout=5)
            assert exc_info.value.status_code == 401
            assert changed is None
    finally:
        release_change.set()


def test_completed_deletion_rejects_an_agent_request_already_waiting_for_admission(
    monkeypatch,
) -> None:
    from auth import hash_password
    from schemas import DeleteAccountRequest

    email = f"deletion-first-{secrets.token_hex(6)}@aisg.sg"
    password = "DeletionFirstPassword123!"  # pragma: allowlist secret
    with SessionLocal() as db:
        user = User(
            email=email,
            password_hash=hash_password(password),
            name="Deletion First",
            email_verified_at=datetime.now(timezone.utc),
        )
        db.add(user)
        db.commit()
        user_id = user.id

    deletion_db = SessionLocal()
    agent_db = SessionLocal()
    deletion_user = deletion_db.get(User, user_id)
    deletion_started = threading.Event()
    release_deletion = threading.Event()
    agent_started = threading.Event()
    real_delete = main._delete_owned_account_rows

    def blocked_delete(user, db) -> None:
        deletion_started.set()
        assert release_deletion.wait(5)
        real_delete(user, db)

    def run_agent():
        agent_started.set()
        return main.resume_agent_chat({}, SimpleNamespace(id=user_id), agent_db)

    monkeypatch.setattr(main, "_delete_owned_account_rows", blocked_delete)
    monkeypatch.setattr(main._PUBLIC_RATE_LIMITER, "allow", lambda *_args, **_kwargs: True)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            deleting = pool.submit(
                main.delete_account,
                DeleteAccountRequest(
                    confirm_email=email,
                    current_password=password,
                ),
                deletion_user,
                deletion_db,
            )
            assert deletion_started.wait(5)
            agent = pool.submit(run_agent)
            assert agent_started.wait(5)
            with pytest.raises(TimeoutError):
                agent.result(timeout=0.2)
            release_deletion.set()
            assert deleting.result(timeout=5) == {"message": "Account deleted."}
            with pytest.raises(HTTPException) as exc_info:
                agent.result(timeout=5)
            assert exc_info.value.status_code == 401
    finally:
        release_deletion.set()
        deletion_db.rollback()
        agent_db.rollback()
        deletion_db.close()
        agent_db.close()
        with SessionLocal() as db:
            db.query(User).filter(User.id == user_id).delete()
            db.commit()


def test_lifecycle_barrier_does_not_block_another_account(monkeypatch) -> None:
    from auth import hash_password
    from resume_agent.session import release_owner_run
    from schemas import DeleteAccountRequest

    password = "LifecyclePassword123!"  # pragma: allowlist secret
    with SessionLocal() as db:
        agent_user = User(
            email=f"agent-{secrets.token_hex(6)}@aisg.sg",
            password_hash=hash_password(password),
            name="Agent Account",
            email_verified_at=datetime.now(timezone.utc),
        )
        deleting_user = User(
            email=f"deleting-{secrets.token_hex(6)}@aisg.sg",
            password_hash=hash_password(password),
            name="Deleting Account",
            email_verified_at=datetime.now(timezone.utc),
        )
        db.add_all([agent_user, deleting_user])
        db.commit()
        agent_user_id = agent_user.id
        deleting_user_id = deleting_user.id
        deleting_email = deleting_user.email

    agent_db = SessionLocal()
    deletion_db = SessionLocal()
    agent_user = agent_db.get(User, agent_user_id)
    deleting_user = deletion_db.get(User, deleting_user_id)
    credit_started = threading.Event()
    release_credit = threading.Event()
    owner_key = f"user:{agent_user_id}"

    def blocked_credit(*_args, **_kwargs) -> None:
        credit_started.set()
        assert release_credit.wait(5)

    monkeypatch.setattr(main, "_consume_ai_credit", blocked_credit)
    monkeypatch.setattr(main._PUBLIC_RATE_LIMITER, "allow", lambda *_args, **_kwargs: True)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            admitted = pool.submit(main.resume_agent_chat, {}, agent_user, agent_db)
            assert credit_started.wait(5)
            deleting = pool.submit(
                main.delete_account,
                DeleteAccountRequest(
                    confirm_email=deleting_email,
                    current_password=password,
                ),
                deleting_user,
                deletion_db,
            )
            assert deleting.result(timeout=2) == {"message": "Account deleted."}
            release_credit.set()
            assert admitted.result(timeout=5).media_type == "text/event-stream"
    finally:
        release_credit.set()
        release_owner_run(owner_key)
        agent_db.rollback()
        deletion_db.rollback()
        agent_db.close()
        deletion_db.close()
        with SessionLocal() as db:
            db.query(User).filter(User.id.in_([agent_user_id, deleting_user_id])).delete(
                synchronize_session=False
            )
            db.commit()


def test_concurrent_tailoring_result_fetch_saves_one_resume_version() -> None:
    from auth import hash_password
    from tailoring_pipeline import PipelineState, _active_pipelines, _pipelines_lock

    session_id = f"tailor-{secrets.token_hex(8)}"
    with SessionLocal() as db:
        user = User(
            email=f"tailor-{secrets.token_hex(6)}@aisg.sg",
            password_hash=hash_password("TailorPassword123!"),  # pragma: allowlist secret
            name="Tailor Race",
            email_verified_at=datetime.now(timezone.utc),
        )
        db.add(user)
        db.commit()
        user_id = user.id

    state = PipelineState(session_id, owner_key=f"user:{user_id}")
    state.set_result(
        {
            "tailored_text": "Built secure services with measurable results. " * 4,
            "score": {"after": 90},
        }
    )
    with _pipelines_lock:
        _active_pipelines[session_id] = state

    first_db = SessionLocal()
    second_db = SessionLocal()
    first_user = first_db.get(User, user_id)
    second_user = second_db.get(User, user_id)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [
                future.result(timeout=5)
                for future in (
                    pool.submit(
                        main.get_tailoring_result,
                        session_id,
                        first_user,
                        first_db,
                    ),
                    pool.submit(
                        main.get_tailoring_result,
                        session_id,
                        second_user,
                        second_db,
                    ),
                )
            ]

        assert results[0]["version_id"] == results[1]["version_id"]
        with SessionLocal() as db:
            assert (
                db.query(ResumeVersion)
                .filter(
                    ResumeVersion.user_id == user_id,
                    ResumeVersion.source == "tailored",
                )
                .count()
                == 1
            )
    finally:
        with _pipelines_lock:
            _active_pipelines.pop(session_id, None)
        first_db.rollback()
        second_db.rollback()
        first_db.close()
        second_db.close()
        with SessionLocal() as db:
            db.query(ResumeVersion).filter(ResumeVersion.user_id == user_id).delete()
            db.query(User).filter(User.id == user_id).delete()
            db.commit()


def test_account_deletion_removes_every_owned_row_but_retains_jobs(
    client: TestClient,
    verification_mail: list[str],
) -> None:
    email, password, verification_token = _signup(client, verification_mail)
    bearer = _verify(client, verification_token, password)
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
