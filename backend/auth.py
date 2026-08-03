"""
JWT authentication, password hashing, and rate-limit checks.
"""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlsplit

import bcrypt
import jwt
import requests
from fastapi import Depends, Header, HTTPException, status
from jwt.algorithms import RSAAlgorithm
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from models import UsageLog, User

ALGORITHM = "HS256"
TOKEN_EXPIRY_DAYS = 7
CLOUDFLARE_PASSWORD_SENTINEL = "cloudflare-access"  # pragma: allowlist secret
_DUMMY_PASSWORD_HASH = "$2b$12$8eFh8m9T8OQqR9bf97Lz5ubKa6eBIqH0uC4TWmMMK6cTG7Vq5nS3K"


class CloudflareJwksUnavailable(Exception):
    """Cloudflare signing keys could not be refreshed without blocking."""

# JWT_SECRET is required in ALL environments. No silent fallbacks.
def _jwt_secret_is_strong(secret: str) -> bool:
    normalized = secret.strip().lower()
    weak_markers = ("change-me", "changeme", "replace-me", "example", "password")
    return len(secret.encode("utf-8")) >= 32 and not any(
        marker in normalized for marker in weak_markers
    )


def is_production_environment() -> bool:
    """Use APP_ENV explicitly, while keeping older Railway deploys fail-closed."""
    if any(
        os.environ.get(name, "").strip()
        for name in (
            "RAILWAY_ENVIRONMENT",
            "RAILWAY_ENVIRONMENT_NAME",
            "RAILWAY_PROJECT_ID",
            "RAILWAY_SERVICE_ID",
        )
    ):
        return True
    app_env = os.environ.get("APP_ENV", "").strip().lower()
    if app_env:
        return app_env not in {"dev", "development", "local", "test"}
    db_url = os.environ.get("DATABASE_URL", "").lower()
    return db_url.startswith(("postgres://", "postgresql://", "postgresql+"))


def _load_jwt_secret() -> str:
    secret = os.environ.get("JWT_SECRET", "")
    if is_production_environment() and not _jwt_secret_is_strong(secret):
        raise RuntimeError(
            "JWT_SECRET must be a non-placeholder value of at least 32 bytes in production. "
            'Generate one: python -c "import secrets; print(secrets.token_hex(32))"'
        )
    if secret:
        return secret

    # Local dev: generate a random key per process. Auth still works,
    # but tokens don't survive restarts. This is intentional.
    import logging as _logging
    import secrets as _secrets

    generated = _secrets.token_hex(32)
    _logging.getLogger("jobhunter.auth").warning(
        "JWT_SECRET not set. Generated ephemeral key for this process. "
        "Tokens will not survive restarts. Set JWT_SECRET in .env for persistence."
    )
    return generated


SECRET_KEY = _load_jwt_secret()

AUTH_MODE = os.environ.get(
    "AUTH_MODE",
    "password",
).strip().lower()
if AUTH_MODE not in {"cloudflare", "password"}:
    raise RuntimeError("AUTH_MODE must be either 'cloudflare' or 'password'")


def password_auth_enabled() -> bool:
    return AUTH_MODE == "password"

# Configurable via env vars — tune from Railway dashboard, no redeploy needed.
_ANONYMOUS_AI = int(os.environ.get("ANONYMOUS_AI_PER_DAY", "3"))
_ACCOUNT_AI = int(os.environ.get("ACCOUNT_AI_PER_DAY", "500"))

ACCESS_LIMITS: dict[str, dict] = {
    "anonymous": {
        "searches_per_day": 999999,
        "ai_per_day": _ANONYMOUS_AI,
        "max_tracked_jobs": 0,
        "can_export": False,
        "can_save": False,
    },
    "user": {
        "searches_per_day": 999999,
        "ai_per_day": _ACCOUNT_AI,
        "max_tracked_jobs": 500,
        "can_export": True,
        "can_save": True,
    },
}


def get_account_limits(user: User | None) -> dict:
    if user is None:
        return ACCESS_LIMITS["anonymous"]
    return ACCESS_LIMITS["user"]


# ── Password helpers ─────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def verify_password_or_dummy(plain: str, hashed: str | None) -> bool:
    """Run one bcrypt check even when no usable account hash exists."""
    usable_hash = bool(hashed and hashed != CLOUDFLARE_PASSWORD_SENTINEL)
    candidate = hashed if usable_hash else _DUMMY_PASSWORD_HASH
    try:
        matches = verify_password(plain, candidate)
    except (TypeError, ValueError):
        usable_hash = False
        matches = verify_password(plain, _DUMMY_PASSWORD_HASH)
    return usable_hash and matches


def validate_password(password: str) -> None:
    """Raise HTTPException 422 if password is too weak."""
    if len(password) < 8:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Password must be at least 8 characters",
        )
    if len(password.encode("utf-8")) > 72:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Password must be at most 72 UTF-8 bytes",
        )


# ── JWT helpers ──────────────────────────────────────────────────────────────

def create_token(user_id: int, token_version: int = 0) -> str:
    payload = {
        "sub": str(user_id),
        "ver": token_version,
        "exp": datetime.now(timezone.utc) + timedelta(days=TOKEN_EXPIRY_DAYS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )


# ── FastAPI dependencies ─────────────────────────────────────────────────────

def _extract_token(authorization: Optional[str]) -> Optional[str]:
    """Pull the bare JWT out of an Authorization header."""
    if not authorization:
        return None
    parts = authorization.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None


_CF_JWKS_CACHE_TTL_SECONDS = 300
_CF_JWKS_REFRESH_COOLDOWN_SECONDS = 30
_CF_JWKS_CACHE: dict[str, tuple[float, list[dict]]] = {}
_CF_JWKS_NEXT_MISS_REFRESH: dict[str, float] = {}
_CF_JWKS_REFRESH_LOCK = threading.Lock()


def _cloudflare_config() -> tuple[str, str]:
    team_domain = os.environ.get("CF_ACCESS_TEAM_DOMAIN", "").strip().rstrip("/")
    audience = os.environ.get("CF_ACCESS_AUD", "").strip()
    if team_domain and "://" not in team_domain:
        team_domain = f"https://{team_domain}"

    parsed = urlsplit(team_domain)
    if (
        not audience
        or parsed.scheme != "https"
        or not parsed.hostname
        or not parsed.hostname.endswith(".cloudflareaccess.com")
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Cloudflare Access is not configured correctly")
    return team_domain, audience


def _fetch_cloudflare_jwks(team_domain: str) -> list[dict]:
    response = requests.get(
        f"{team_domain}/cdn-cgi/access/certs",
        timeout=5,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Cloudflare JWKS response was invalid")
    raw_keys = payload.get("keys")
    if not isinstance(raw_keys, list):
        raise ValueError("Cloudflare JWKS response did not contain keys")
    keys = [key for key in raw_keys if isinstance(key, dict)]
    if not keys:
        raise ValueError("Cloudflare JWKS response did not contain keys")
    _CF_JWKS_CACHE[team_domain] = (
        time.monotonic() + _CF_JWKS_CACHE_TTL_SECONDS,
        keys,
    )
    return keys


def _cloudflare_signing_key(team_domain: str, kid: str):
    now = time.monotonic()
    cached = _CF_JWKS_CACHE.get(team_domain)
    if cached and cached[0] > now:
        jwk = next((key for key in cached[1] if key.get("kid") == kid), None)
        if jwk is not None:
            return _parse_cloudflare_signing_key(jwk)
        if now < _CF_JWKS_NEXT_MISS_REFRESH.get(team_domain, 0):
            raise ValueError("No matching Cloudflare signing key")

    # Only one request may perform the network refresh. Other requests fail
    # closed instead of tying up every sync worker behind a five-second fetch.
    if not _CF_JWKS_REFRESH_LOCK.acquire(blocking=False):
        raise CloudflareJwksUnavailable("Cloudflare signing keys are refreshing")
    try:
        cached = _CF_JWKS_CACHE.get(team_domain)
        now = time.monotonic()
        cache_valid = bool(cached and cached[0] > now)
        if cache_valid:
            jwk = next((key for key in cached[1] if key.get("kid") == kid), None)
            if jwk is not None:
                return _parse_cloudflare_signing_key(jwk)
        if now < _CF_JWKS_NEXT_MISS_REFRESH.get(team_domain, 0):
            if cache_valid:
                raise ValueError("No matching Cloudflare signing key")
            raise CloudflareJwksUnavailable("Cloudflare signing keys are unavailable")

        # Set the cooldown before the network call so failures cannot trigger a
        # new five-second fetch on every subsequent request.
        _CF_JWKS_NEXT_MISS_REFRESH[team_domain] = (
            now + _CF_JWKS_REFRESH_COOLDOWN_SECONDS
        )
        try:
            keys = _fetch_cloudflare_jwks(team_domain)
        except (requests.RequestException, TypeError, ValueError) as exc:
            raise CloudflareJwksUnavailable(
                "Cloudflare signing keys are unavailable"
            ) from exc
        jwk = next((key for key in keys if key.get("kid") == kid), None)
        if not cache_valid and jwk is not None:
            # A successful normal refresh should not delay an immediate
            # rotation lookup. The cooldown is only retained for unknown-kid
            # refreshes and failed network calls.
            _CF_JWKS_NEXT_MISS_REFRESH.pop(team_domain, None)
    finally:
        _CF_JWKS_REFRESH_LOCK.release()
    return _parse_cloudflare_signing_key(jwk)


def _parse_cloudflare_signing_key(jwk: dict | None):
    if (
        jwk is None
        or jwk.get("kty") != "RSA"
        or jwk.get("alg") not in (None, "RS256")
    ):
        raise ValueError("No matching Cloudflare signing key")
    return RSAAlgorithm.from_jwk(jwk)


def _validate_cloudflare_assertion(
    assertion: Optional[str], header_email: Optional[str]
) -> str:
    try:
        if not assertion:
            raise ValueError("Missing Cloudflare Access assertion")
        team_domain, audience = _cloudflare_config()
        kid = jwt.get_unverified_header(assertion).get("kid")
        if not isinstance(kid, str) or not kid:
            raise ValueError("Missing Cloudflare signing key ID")
        payload = jwt.decode(
            assertion,
            _cloudflare_signing_key(team_domain, kid),
            algorithms=["RS256"],
            audience=audience,
            issuer=team_domain,
        )
        email = payload.get("email")
        if not isinstance(email, str) or "@" not in email:
            raise ValueError("Missing email claim")
        email = email.strip().lower()
        if header_email is not None and header_email.strip().lower() != email:
            raise ValueError("Cloudflare email header does not match assertion")
        return email
    except CloudflareJwksUnavailable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cloudflare Access authentication is temporarily unavailable",
            headers={"Retry-After": "2"},
        )
    except (jwt.PyJWTError, requests.RequestException, TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Cloudflare Access authentication",
        )


def _get_cf_user(email: str, db) -> User:
    """Return an explicitly registered Cloudflare account."""
    user = db.query(User).filter(User.email == email).first()
    if (
        not user
        or user.password_hash != CLOUDFLARE_PASSWORD_SENTINEL
        or user.terms_accepted_at is None
        or user.privacy_accepted_at is None
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account registration required",
        )
    now = datetime.now(timezone.utc)
    user.email_verified_at = user.email_verified_at or now
    user.last_login = now
    db.commit()
    return user


def get_cloudflare_email(
    cf_access_email: Optional[str] = Header(None, alias="Cf-Access-Authenticated-User-Email"),
    cf_access_assertion: Optional[str] = Header(None, alias="Cf-Access-Jwt-Assertion"),
) -> str:
    """Validate Cloudflare Access and return the signed email claim."""
    if AUTH_MODE != "cloudflare":
        raise HTTPException(status_code=404, detail="Cloudflare authentication is disabled")
    return _validate_cloudflare_assertion(cf_access_assertion, cf_access_email)


def auth_config() -> dict[str, str]:
    config = {"mode": AUTH_MODE}
    if AUTH_MODE == "cloudflare":
        login_url = os.environ.get("CF_ACCESS_LOGIN_URL", "").strip()
        logout_url = os.environ.get("CF_ACCESS_LOGOUT_URL", "").strip()
        if login_url:
            config["cloudflare_login_url"] = login_url
        if logout_url:
            config["cloudflare_logout_url"] = logout_url
    return config


def validate_cloudflare_unsafe_origin(method: str, origin: str | None) -> None:
    """Reject cross-site state changes authenticated by Cloudflare cookies."""
    if AUTH_MODE != "cloudflare" or method.upper() in {"GET", "HEAD", "OPTIONS"}:
        return
    allowed_origins = {
        value.strip().lower().rstrip("/")
        for value in os.environ.get(
            "ALLOWED_ORIGINS",
            "http://localhost:5173,http://localhost:3000",
        ).split(",")
        if value.strip() and value.strip() != "*"
    }
    normalized_origin = (origin or "").strip().lower().rstrip("/")
    if not normalized_origin or normalized_origin not in allowed_origins:
        raise HTTPException(status_code=403, detail="Cross-site request blocked")


def _get_jwt_user(token: str, db: Session) -> User:
    payload = decode_token(token)
    try:
        user_id = int(payload["sub"])
        # Tokens issued before account-wide revocation existed had no version.
        # They remain valid only for legacy rows at version 0 and expire within
        # the normal seven-day JWT lifetime.
        token_version = int(payload.get("ver", 0))
    except (KeyError, TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )
    user = db.query(User).filter(User.id == user_id).first()
    if (
        not user
        or user.token_version != token_version
        or user.email_verified_at is None
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )
    return user


def get_current_user(
    authorization: Optional[str] = Header(None),
    cf_access_email: Optional[str] = Header(None, alias="Cf-Access-Authenticated-User-Email"),
    cf_access_assertion: Optional[str] = Header(None, alias="Cf-Access-Jwt-Assertion"),
    db: Session = Depends(get_db),
) -> User:
    """Return the user for the configured authentication mode, or raise 401."""
    if AUTH_MODE == "cloudflare":
        # A partial or invalid Cloudflare identity must not fall through.
        if cf_access_email is not None or cf_access_assertion is not None:
            email = _validate_cloudflare_assertion(cf_access_assertion, cf_access_email)
            return _get_cf_user(email, db)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Cloudflare Access authentication required",
        )

    # Cloudflare may still add its headers when password auth sits behind
    # Access. In password mode, only the app's bearer token is authoritative.
    token = _extract_token(authorization)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
        )
    return _get_jwt_user(token, db)


def get_optional_user(
    authorization: Optional[str] = Header(None),
    cf_access_email: Optional[str] = Header(None, alias="Cf-Access-Authenticated-User-Email"),
    cf_access_assertion: Optional[str] = Header(None, alias="Cf-Access-Jwt-Assertion"),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """Return the user for the configured authentication mode, else None."""
    if AUTH_MODE == "cloudflare":
        if cf_access_email is not None or cf_access_assertion is not None:
            email = _validate_cloudflare_assertion(cf_access_assertion, cf_access_email)
            try:
                return _get_cf_user(email, db)
            except HTTPException as exc:
                if exc.detail == "Account registration required":
                    return None
                raise
        return None

    token = _extract_token(authorization)
    if not token:
        return None
    try:
        return _get_jwt_user(token, db)
    except HTTPException:
        return None


# ── Rate-limit check ────────────────────────────────────────────────────────

def check_rate_limit(user: Optional[User], action: str, db: Session) -> None:
    """
    Raise 429 if the user (or anonymous visitor) has exceeded the daily limit.

    Actions: "search" (unlimited), "ai" (limited per account)
    """
    limits = get_account_limits(user)

    if action == "search":
        limit_key = "searches_per_day"
    elif action == "ai":
        limit_key = "ai_per_day"
    else:
        return

    max_allowed = limits[limit_key]
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    query = db.query(func.count(UsageLog.id)).filter(
        UsageLog.action == action,
        UsageLog.created_at >= today_start,
    )
    if user:
        query = query.filter(UsageLog.user_id == user.id)
    else:
        query = query.filter(UsageLog.user_id.is_(None))

    count = query.scalar() or 0

    if count >= max_allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"You've used all {max_allowed} AI requests for today. "
                f"Your limit resets at midnight UTC. "
                f"For more access, contact haomingkoo@gmail.com."
            ),
        )


def check_login_rate_limit(email: str, db: Session) -> None:
    """Raise 429 if too many failed login attempts for this email."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=15)
    failed = (
        db.query(func.count(UsageLog.id))
        .filter(
            UsageLog.action == "login_failed",
            UsageLog.detail == email,
            UsageLog.created_at >= cutoff,
        )
        .scalar()
        or 0
    )
    if failed >= 5:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Try again in 15 minutes.",
        )
