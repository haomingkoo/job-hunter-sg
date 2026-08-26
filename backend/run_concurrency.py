"""One in-process admission gate for model-backed user runs."""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

import config


active_runs: dict[str, int] = {}
_lock = threading.Lock()


def reserve_owner_run(owner_key: str) -> bool:
    """Reserve capacity without waiting, or return False when either cap is full."""
    with _lock:
        owner_count = active_runs.get(owner_key, 0)
        if (
            owner_count >= config.AGENT_MAX_CONCURRENT_RUNS_PER_USER
            or sum(active_runs.values()) >= config.AGENT_MAX_ACTIVE_RUNS
        ):
            return False
        active_runs[owner_key] = owner_count + 1
        return True


def release_owner_run(owner_key: str) -> None:
    with _lock:
        owner_count = active_runs.get(owner_key, 0)
        if owner_count <= 1:
            active_runs.pop(owner_key, None)
        else:
            active_runs[owner_key] = owner_count - 1


def owner_has_active_run(owner_key: str) -> bool:
    with _lock:
        return active_runs.get(owner_key, 0) > 0


def _owner_admission_statement(owner_id: int):
    from models import User

    return select(User.id).where(User.id == owner_id).with_for_update()


def database_owner_run_available(db: Session, owner_id: int) -> bool:
    """Serialize per-user admission until the caller commits its running row.

    PostgreSQL turns ``FOR UPDATE`` into a cross-worker lock on the existing
    user row. SQLite ignores the clause, where the process-local gate above is
    still the concurrency mechanism used by the application and tests.

    The caller must create or claim its ``RecruitmentRun`` and commit before
    releasing this transaction; otherwise another worker could observe the
    owner as idle after the row lock is released.
    """

    # Import lazily: models imports configuration used by application startup,
    # while this module is also imported by that startup path.
    from models import RecruitmentRun

    db.execute(_owner_admission_statement(owner_id)).scalar_one()
    now = datetime.now(timezone.utc)
    legacy_cutoff = now - timedelta(seconds=config.RECRUITMENT_RUN_LEASE_SECONDS)
    live_lease = or_(
        RecruitmentRun.lease_expires_at > now,
        and_(
            RecruitmentRun.lease_expires_at.is_(None),
            RecruitmentRun.created_at > legacy_cutoff,
        ),
    )
    active_for_owner = (
        db.query(RecruitmentRun.id)
        .filter(
            RecruitmentRun.user_id == owner_id,
            RecruitmentRun.status == "running",
            live_lease,
        )
        .count()
    )
    return active_for_owner < config.AGENT_MAX_CONCURRENT_RUNS_PER_USER
