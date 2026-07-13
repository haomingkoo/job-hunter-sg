"""
JWT authentication, password hashing, and rate-limit checks.
"""

from __future__ import annotations

import os
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

SECRET_KEY = os.environ.get("JWT_SECRET", "")
ALGORITHM = "HS256"
TOKEN_EXPIRY_DAYS = 7
CLOUDFLARE_PASSWORD_SENTINEL = "cloudflare-access"  # pragma: allowlist secret

# JWT_SECRET is required in ALL environments. No silent fallbacks.
_db_url = os.environ.get("DATABASE_URL", "")
_is_production = _db_url.lower().startswith(("postgres://", "postgresql://", "postgresql+"))
if not SECRET_KEY:
    if _is_production:
        raise RuntimeError(
            "JWT_SECRET must be set in production! "
            'Generate one: python -c "import secrets; print(secrets.token_hex(32))"'
        )
    # Local dev: generate a random key per process. Auth still works,
    # but tokens don't survive restarts. This is intentional.
    import secrets as _secrets
    import logging as _logging
    SECRET_KEY = _secrets.token_hex(32)
    _logging.getLogger("jobhunter.auth").warning(
        "JWT_SECRET not set. Generated ephemeral key for this process. "
        "Tokens will not survive restarts. Set JWT_SECRET in .env for persistence."
    )

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
        "max_tracked_jobs": 999999,
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


def validate_password(password: str) -> None:
    """Raise HTTPException 422 if password is too weak."""
    if len(password) < 8:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Password must be at least 8 characters",
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
    cached = _CF_JWKS_CACHE.get(team_domain)
    cache_valid = bool(cached and cached[0] > time.monotonic())
    keys = cached[1] if cache_valid else _fetch_cloudflare_jwks(team_domain)

    jwk = next((key for key in keys if key.get("kid") == kid), None)
    now = time.monotonic()
    if (
        jwk is None
        and cache_valid
        and now >= _CF_JWKS_NEXT_MISS_REFRESH.get(team_domain, 0)
    ):
        # Refresh once on an unknown kid so Cloudflare key rotation takes effect
        # before the short cache expires, with a cooldown against forced refetches.
        _CF_JWKS_NEXT_MISS_REFRESH[team_domain] = (
            now + _CF_JWKS_REFRESH_COOLDOWN_SECONDS
        )
        keys = _fetch_cloudflare_jwks(team_domain)
        jwk = next((key for key in keys if key.get("kid") == kid), None)
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
    except (jwt.PyJWTError, requests.RequestException, TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Cloudflare Access authentication",
        )


def _get_cf_user(email: str, db) -> User:
    """Return an explicitly registered Cloudflare account."""
    user = db.query(User).filter(User.email == email).first()
    if not user or user.password_hash != CLOUDFLARE_PASSWORD_SENTINEL:
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


def _get_jwt_user(token: str, db: Session) -> User:
    payload = decode_token(token)
    try:
        user_id = int(payload["sub"])
        token_version = int(payload["ver"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )
    user = db.query(User).filter(User.id == user_id).first()
    if not user or user.token_version != token_version:
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
    """
    Get authenticated user. Supports two modes:
    1. Cloudflare Access: validates its signed assertion
    2. JWT Bearer token (local dev / API access)
    """
    # A partial or invalid Cloudflare identity must not fall through to app JWT auth.
    if cf_access_email is not None or cf_access_assertion is not None:
        email = _validate_cloudflare_assertion(cf_access_assertion, cf_access_email)
        return _get_cf_user(email, db)

    if AUTH_MODE == "cloudflare":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Cloudflare Access authentication required",
        )

    # Mode 2: JWT Bearer token (local password-auth development)
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
    """Return user if authenticated (via CF Access or JWT), else None."""
    if cf_access_email is not None or cf_access_assertion is not None:
        email = _validate_cloudflare_assertion(cf_access_assertion, cf_access_email)
        try:
            return _get_cf_user(email, db)
        except HTTPException as exc:
            if exc.detail == "Account registration required":
                return None
            raise

    if AUTH_MODE == "cloudflare":
        return None

    # Mode 2: JWT
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
