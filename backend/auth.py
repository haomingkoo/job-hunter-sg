"""
JWT authentication, password hashing, and rate-limit checks.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from models import UsageLog, User

SECRET_KEY = os.environ.get("JWT_SECRET", "")
ALGORITHM = "HS256"
TOKEN_EXPIRY_DAYS = 7

# Crash in production if JWT_SECRET is not set
_db_url = os.environ.get("DATABASE_URL", "")
if "postgresql" in _db_url and not SECRET_KEY:
    raise RuntimeError(
        "JWT_SECRET must be set in production! "
        'Generate one: python -c "import secrets; print(secrets.token_hex(32))"'
    )
if not SECRET_KEY:
    import warnings
    warnings.warn(
        "JWT_SECRET not set — using insecure default for local dev only. "
        "Set JWT_SECRET env var before deploying.",
        stacklevel=1,
    )
    SECRET_KEY = "insecure-local-dev-only"

# Configurable via env vars — tune from Railway dashboard, no redeploy needed
_FREE_AI = int(os.environ.get("FREE_AI_PER_DAY", "999999"))
_PRO_AI = int(os.environ.get("PRO_AI_PER_DAY", "50"))
_PRO_DOMAINS = [
    d.strip().lower()
    for d in os.environ.get("PRO_EMAIL_DOMAINS", "aisg.sg").split(",")
    if d.strip()
]

TIER_LIMITS: dict[str, dict] = {
    # Anonymous / no login — unlimited search, limited AI
    "free": {
        "searches_per_day": 999999,
        "ai_per_day": _FREE_AI,
        "max_tracked_jobs": 0,
        "can_export": False,
        "can_save": False,
    },
    # AISG batch mates — everything unlimited + persistence
    "pro": {
        "searches_per_day": 999999,
        "ai_per_day": _PRO_AI,
        "max_tracked_jobs": 999999,
        "can_export": True,
        "can_save": True,
    },
    # Admin
    "admin": {
        "searches_per_day": 999999,
        "ai_per_day": 999999,
        "max_tracked_jobs": 999999,
        "can_export": True,
        "can_save": True,
    },
}


# ── Password helpers ─────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def validate_password(password: str) -> None:
    """Raise HTTPException 422 if password is too weak."""
    if len(password) < 8:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Password must be at least 8 characters",
        )


# ── JWT helpers ──────────────────────────────────────────────────────────────

def create_token(user_id: int) -> str:
    payload = {
        "sub": str(user_id),
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


def _get_or_create_cf_user(email: str, db) -> User:
    """
    Auto-create a user from Cloudflare Access email.
    No password needed — Cloudflare handles auth via OTP.
    """
    user = db.query(User).filter(User.email == email).first()
    if user:
        user.last_login = datetime.now(timezone.utc)
        db.commit()
        return user

    # Auto-create new user
    domain = email.split("@")[-1].lower()
    tier = "pro" if domain in _PRO_DOMAINS else "free"
    name = email.split("@")[0].replace(".", " ").replace("_", " ").title()

    user = User(
        email=email,
        password_hash="cloudflare-access",  # No password — CF handles auth
        name=name,
        tier=tier,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_current_user(
    authorization: Optional[str] = Header(None),
    cf_access_email: Optional[str] = Header(None, alias="Cf-Access-Authenticated-User-Email"),
    db: Session = Depends(get_db),
) -> User:
    """
    Get authenticated user. Supports two modes:
    1. Cloudflare Access (production): reads Cf-Access-Authenticated-User-Email header
    2. JWT Bearer token (local dev / API access)
    """
    # Mode 1: Cloudflare Access header (production only)
    # SECURITY: Only trust this header when behind Cloudflare (production).
    # In dev (SQLite), ignore it to prevent header spoofing.
    _is_prod = "postgresql" in os.environ.get("DATABASE_URL", "")
    if cf_access_email and _is_prod:
        return _get_or_create_cf_user(cf_access_email, db)

    # Mode 2: JWT Bearer token (local dev / API)
    token = _extract_token(authorization)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
        )
    payload = decode_token(token)
    user_id = int(payload["sub"])
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    return user


def get_optional_user(
    authorization: Optional[str] = Header(None),
    cf_access_email: Optional[str] = Header(None, alias="Cf-Access-Authenticated-User-Email"),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """Return user if authenticated (via CF Access or JWT), else None."""
    # Mode 1: Cloudflare Access (production only)
    _is_prod = "postgresql" in os.environ.get("DATABASE_URL", "")
    if cf_access_email and _is_prod:
        return _get_or_create_cf_user(cf_access_email, db)

    # Mode 2: JWT
    token = _extract_token(authorization)
    if not token:
        return None
    try:
        payload = decode_token(token)
    except HTTPException:
        return None
    user_id = int(payload["sub"])
    return db.query(User).filter(User.id == user_id).first()


# ── Rate-limit check ────────────────────────────────────────────────────────

def check_rate_limit(user: Optional[User], action: str, db: Session) -> None:
    """
    Raise 429 if the user (or anonymous) has exceeded tier limits for today.
    Anonymous users are treated as 'free' tier.

    Actions: "search" (unlimited for all), "ai" (limited for free users)
    """
    tier = user.tier if user else "free"
    limits = TIER_LIMITS.get(tier, TIER_LIMITS["free"])

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
            detail=f"Rate limit exceeded: {max_allowed} {action}(es) per day for {tier} tier",
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
