"""Database lease and hard-kill recovery for recruitment runs."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, update
from sqlalchemy.orm import Session

import config
from models import RecruitmentActivityEvent, RecruitmentRun, RecruitmentThread

from .recovery import classify_failure


CANDIDATE_PROFILE_COMMAND_TYPES = frozenset({
    "build_candidate_profile",
    "study_resume_version",
})


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def lease_deadline(now: datetime) -> datetime:
    return now + timedelta(seconds=config.RECRUITMENT_RUN_LEASE_SECONDS)


def claim_failed_run(db: Session, run_id: str, owner: str, now: datetime) -> bool:
    claimed = db.execute(
        update(RecruitmentRun)
        .where(RecruitmentRun.id == run_id, RecruitmentRun.status == "failed")
        .values(
            status="running",
            lease_owner=owner,
            lease_expires_at=lease_deadline(now),
            error_type=None,
            result=None,
            completed_at=None,
        )
        .execution_options(synchronize_session=False)
        .returning(RecruitmentRun.id)
    ).scalar_one_or_none()
    return claimed is not None


def renew_run_lease(db: Session, run_id: str, owner: str, now: datetime) -> bool:
    renewed = db.execute(
        update(RecruitmentRun)
        .where(
            RecruitmentRun.id == run_id,
            RecruitmentRun.status == "running",
            RecruitmentRun.lease_owner == owner,
            RecruitmentRun.lease_expires_at > now,
        )
        .values(lease_expires_at=lease_deadline(now))
        .execution_options(synchronize_session=False)
        .returning(RecruitmentRun.id)
    ).scalar_one_or_none()
    return renewed is not None


def _interrupted_ledger(ledger: dict | None, run_id: str) -> dict:
    decision = classify_failure("process_interrupted", attempts_remaining=True)
    updated = deepcopy(ledger) if ledger else {"logical_run_id": run_id, "stages": {}}
    interruptions = [dict(item) for item in updated.get("interruptions") or []]
    interruptions.append({
        "attempt_id": f"process_interrupted:{len(interruptions) + 1}",
        "status": "interrupted",
        "decision": asdict(decision),
    })
    updated["interruptions"] = interruptions
    updated["last_decision"] = asdict(decision)
    return updated


def reconcile_expired_runs(
    db: Session,
    *,
    now: datetime | None = None,
    thread_id: str | None = None,
) -> int:
    """Atomically stop expired running runs; safe for concurrent callers."""

    timestamp = now or _utcnow()
    # Runs written before leases were introduced can have a null lease forever.
    # A current runtime always assigns a lease before its first commit, so a
    # null-lease row older than one full lease window is an interrupted legacy
    # run rather than live work.
    legacy_cutoff = timestamp - timedelta(seconds=config.RECRUITMENT_RUN_LEASE_SECONDS)
    interrupted_condition = or_(
        and_(
            RecruitmentRun.lease_expires_at.is_not(None),
            RecruitmentRun.lease_expires_at <= timestamp,
        ),
        and_(
            RecruitmentRun.lease_expires_at.is_(None),
            RecruitmentRun.created_at <= legacy_cutoff,
        ),
    )
    candidates = db.query(RecruitmentRun.id).filter(
        RecruitmentRun.status == "running",
        interrupted_condition,
    )
    if thread_id is not None:
        candidates = candidates.filter(RecruitmentRun.thread_id == thread_id)

    reconciled = 0
    for (run_id,) in candidates.order_by(RecruitmentRun.id).all():
        row = db.execute(
            update(RecruitmentRun)
            .where(
                RecruitmentRun.id == run_id,
                RecruitmentRun.status == "running",
                interrupted_condition,
            )
            .values(
                status="failed",
                error_type="process_interrupted",
                completed_at=timestamp,
                lease_owner=None,
                lease_expires_at=None,
            )
            .execution_options(synchronize_session=False)
            .returning(
                RecruitmentRun.id,
                RecruitmentRun.thread_id,
                RecruitmentRun.command_type,
                RecruitmentRun.trace_key,
                RecruitmentRun.attempt_ledger,
            )
        ).one_or_none()
        if row is None:
            continue

        detail = {
            "command_type": row.command_type,
            "error_type": "process_interrupted",
            "failure_type": "transient",
            "failure_code": "process_interrupted",
            "retryable": True,
            "recovery_action": "retry_incomplete_stage",
        }
        team_member = (
            "candidate_profiler"
            if row.command_type in CANDIDATE_PROFILE_COMMAND_TYPES
            else "coordinator"
        )
        if row.command_type in CANDIDATE_PROFILE_COMMAND_TYPES:
            thread = db.get(RecruitmentThread, row.thread_id)
            facts = dict(thread.case_facts or {})
            facts["candidate_profile_status"] = "failed"
            thread.case_facts = facts
        db.execute(
            update(RecruitmentRun)
            .where(RecruitmentRun.id == row.id)
            .values(attempt_ledger=_interrupted_ledger(row.attempt_ledger, row.id))
            .execution_options(synchronize_session=False)
        )
        next_value = db.execute(
            update(RecruitmentThread)
            .where(RecruitmentThread.id == row.thread_id)
            .values(next_event_sequence=RecruitmentThread.next_event_sequence + 1)
            .returning(RecruitmentThread.next_event_sequence)
        ).scalar_one()
        db.add(RecruitmentActivityEvent(
            thread_id=row.thread_id,
            run_id=row.id,
            sequence=int(next_value) - 1,
            event_type="run",
            status="failed",
            team_member=team_member,
            attempt=1,
            trace_key=row.trace_key,
            summary=f"The {team_member.replace('_', ' ')} stopped because its worker was interrupted.",
            detail=detail,
            parent_id=row.id,
            attributes=detail,
            created_at=timestamp,
        ))
        reconciled += 1

    if reconciled:
        db.commit()
        db.expire_all()
    return reconciled
