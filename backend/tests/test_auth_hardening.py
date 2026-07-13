from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

import auth


_RAILWAY_ENV_VARS = (
    "RAILWAY_ENVIRONMENT",
    "RAILWAY_ENVIRONMENT_NAME",
    "RAILWAY_PROJECT_ID",
    "RAILWAY_SERVICE_ID",
)


def _clear_railway_env(monkeypatch) -> None:
    for name in _RAILWAY_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize(
    ("app_env", "expected"),
    [
        ("production", True),
        ("staging", True),
        ("development", False),
        ("test", False),
    ],
)
def test_app_env_explicitly_controls_production_detection(
    monkeypatch,
    app_env: str,
    expected: bool,
) -> None:
    _clear_railway_env(monkeypatch)
    monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.setenv("DATABASE_URL", "postgresql://local/test")

    assert auth.is_production_environment() is expected


def test_legacy_postgres_and_railway_deploys_still_fail_closed(monkeypatch) -> None:
    _clear_railway_env(monkeypatch)
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://legacy/production")
    assert auth.is_production_environment() is True

    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///local.db")
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
    assert auth.is_production_environment() is True


def test_missing_account_still_runs_one_dummy_bcrypt_check(monkeypatch) -> None:
    checks: list[tuple[str, str]] = []

    def fake_verify(plain: str, hashed: str) -> bool:
        checks.append((plain, hashed))
        return True

    monkeypatch.setattr(auth, "verify_password", fake_verify)

    assert auth.verify_password_or_dummy("candidate", None) is False
    assert checks == [("candidate", auth._DUMMY_PASSWORD_HASH)]

    checks.clear()
    assert auth.verify_password_or_dummy("candidate", auth.CLOUDFLARE_PASSWORD_SENTINEL) is False
    assert checks == [("candidate", auth._DUMMY_PASSWORD_HASH)]

    checks.clear()
    assert auth.verify_password_or_dummy("candidate", "bcrypt-hash") is True
    assert checks == [("candidate", "bcrypt-hash")]


def test_cloudflare_unsafe_requests_require_an_allowed_origin(monkeypatch) -> None:
    monkeypatch.setattr(auth, "AUTH_MODE", "cloudflare")
    monkeypatch.setenv(
        "ALLOWED_ORIGINS",
        "https://job.example.com,http://localhost:5173/",
    )

    auth.validate_cloudflare_unsafe_origin("POST", "https://job.example.com")
    auth.validate_cloudflare_unsafe_origin("DELETE", "HTTP://LOCALHOST:5173")
    auth.validate_cloudflare_unsafe_origin("GET", None)

    for origin in (None, "null", "https://attacker.example"):
        with pytest.raises(HTTPException) as exc_info:
            auth.validate_cloudflare_unsafe_origin("POST", origin)
        assert exc_info.value.status_code == 403


def test_cloudflare_origin_check_rejects_wildcard_and_ignores_password_mode(
    monkeypatch,
) -> None:
    monkeypatch.setattr(auth, "AUTH_MODE", "cloudflare")
    monkeypatch.setenv("ALLOWED_ORIGINS", "*")
    with pytest.raises(HTTPException):
        auth.validate_cloudflare_unsafe_origin("POST", "https://attacker.example")

    monkeypatch.setattr(auth, "AUTH_MODE", "password")
    auth.validate_cloudflare_unsafe_origin("POST", None)


def test_production_jwt_secret_rejects_short_and_placeholder_values() -> None:
    assert not auth._jwt_secret_is_strong("x")
    assert not auth._jwt_secret_is_strong(
        "change-me-to-a-random-secret-in-production"
    )
    assert auth._jwt_secret_is_strong(
        "a7f3d8c2e9b14f60a5c7d1e3f8b2c4d6"  # pragma: allowlist secret
    )


def test_new_passwords_reject_bcrypt_truncation_and_unicode_overflow() -> None:
    auth.validate_password("a" * 72)

    for password in ("a" * 73, "界" * 25):
        with pytest.raises(HTTPException) as exc_info:
            auth.validate_password(password)
        assert exc_info.value.status_code == 422
        assert "72 UTF-8 bytes" in exc_info.value.detail


def test_new_account_nonce_rejects_a_stale_same_id_token() -> None:
    from database import SessionLocal
    from models import User

    with SessionLocal() as db:
        user = User(
            email=f"nonce-{auth.time.time_ns()}@example.com",
            password_hash=auth.hash_password("StartingPassword123!"),
            name="Nonce Test",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        user_id = user.id
        assert user.token_version > 0
        stale_token = auth.create_token(user_id, 0)

        with pytest.raises(HTTPException) as exc_info:
            auth._get_jwt_user(stale_token, db)
        assert exc_info.value.status_code == 401

        db.delete(user)
        db.commit()


def test_legacy_token_without_version_only_matches_legacy_account(monkeypatch) -> None:
    legacy_user = type(
        "LegacyUser",
        (),
        {"token_version": 0, "email_verified_at": datetime.now(timezone.utc)},
    )()

    class Query:
        def filter(self, _condition):
            return self

        def first(self):
            return legacy_user

    class DB:
        def query(self, _model):
            return Query()

    monkeypatch.setattr(auth, "decode_token", lambda _token: {"sub": "42"})
    assert auth._get_jwt_user("legacy-token", DB()) is legacy_user

    legacy_user.token_version = 1
    with pytest.raises(HTTPException) as exc_info:
        auth._get_jwt_user("legacy-token", DB())
    assert exc_info.value.status_code == 401


def test_unverified_password_account_cannot_use_an_existing_jwt(monkeypatch) -> None:
    user = type("LegacyUser", (), {"token_version": 0, "email_verified_at": None})()

    class Query:
        def filter(self, _condition):
            return self

        def first(self):
            return user

    class DB:
        def query(self, _model):
            return Query()

    monkeypatch.setattr(auth, "decode_token", lambda _token: {"sub": "42", "ver": 0})

    with pytest.raises(HTTPException) as exc_info:
        auth._get_jwt_user("legacy-token", DB())

    assert exc_info.value.status_code == 401
