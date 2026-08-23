"""Transactional account-owned data cleanup and external checkpoint privacy gate."""

from __future__ import annotations

import hashlib
import threading
import weakref
from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy import and_, or_, text
from sqlalchemy.orm import Session

from models import (
    CandidateProfileArtifact,
    EmailVerificationToken,
    InterviewStory,
    JobAlertDelivery,
    JobAlertPreference,
    PasswordResetToken,
    PowerMatchSnapshot,
    ProposedResumeEdit,
    RecruitmentActivityEvent,
    RecruitmentMessage,
    RecruitmentRun,
    RecruitmentThread,
    RecruitmentThreadDeletionRequest,
    ResumeVersion,
    RoleProfileArtifact,
    StoryUsage,
    TailoredResume,
    TargetAssessmentArtifact,
    TrackedJob,
    UsageLog,
    User,
    UserMemory,
)


_ACCOUNT_LIFECYCLE_LOCKS: weakref.WeakValueDictionary[int, threading.Lock] = (
    weakref.WeakValueDictionary()
)
_ACCOUNT_LIFECYCLE_LOCKS_GUARD = threading.Lock()
_ACCOUNT_STORAGE_LOCK = threading.Lock()


def account_lifecycle_lock(user_id: int) -> threading.Lock:
    """Serialize account deletion against user-owned background work locally."""
    with _ACCOUNT_LIFECYCLE_LOCKS_GUARD:
        lock = _ACCOUNT_LIFECYCLE_LOCKS.get(user_id)
        if lock is None:
            lock = threading.Lock()
            _ACCOUNT_LIFECYCLE_LOCKS[user_id] = lock
        return lock


@contextmanager
def locked_account_storage(user_id: int, db: Session):
    """Serialize account-owned writes locally and across PostgreSQL replicas."""
    with _ACCOUNT_STORAGE_LOCK:
        if db.get_bind().dialect.name == "postgresql":
            db.execute(
                text("SELECT pg_advisory_xact_lock(:key)"),
                {"key": 0x4A490000 + user_id},
            )
        yield


def owned_recruitment_checkpoint_tokens(user_id: int, db: Session) -> tuple[str, ...]:
    tokens: set[str] = set()
    for (case_facts,) in db.query(RecruitmentThread.case_facts).filter(
        RecruitmentThread.user_id == user_id
    ):
        facts = case_facts if isinstance(case_facts, dict) else {}
        for key in (
            "coordinator_pause_token",
            "coordinator_cleanup_token",
            "target_assessment_pause_token",
            "target_assessment_cleanup_token",
        ):
            token = str(facts.get(key) or "").strip()
            if token:
                tokens.add(token)
    return tuple(sorted(tokens))


def purge_recruitment_checkpoints(
    checkpoint_tokens: tuple[str, ...],
    db: Session | None = None,
) -> None:
    """Delete agent state, transactionally when it shares PostgreSQL."""
    if db is not None and db.get_bind().dialect.name == "postgresql":
        for token in checkpoint_tokens:
            parameters = {"thread_id": token}
            db.execute(
                text("DELETE FROM checkpoints WHERE thread_id = :thread_id"),
                parameters,
            )
            db.execute(
                text("DELETE FROM checkpoint_blobs WHERE thread_id = :thread_id"),
                parameters,
            )
            db.execute(
                text("DELETE FROM checkpoint_writes WHERE thread_id = :thread_id"),
                parameters,
            )
        return

    from recruitment_team.open_agent.runner import delete_checkpoint

    for token in checkpoint_tokens:
        delete_checkpoint(token)


def has_active_recruitment_runs(user_id: int, db: Session) -> bool:
    now = datetime.now(timezone.utc)
    return (
        db.query(RecruitmentRun.id)
        .filter(
            RecruitmentRun.user_id == user_id,
            RecruitmentRun.status == "running",
            RecruitmentRun.lease_expires_at.is_not(None),
            RecruitmentRun.lease_expires_at > now,
        )
        .first()
        is not None
    )


def delete_owned_account_rows(user: User, db: Session) -> tuple[str, ...]:
    """Stage every account-owned SQL row for deletion in foreign-key order."""
    user_id = user.id
    email_hash = hashlib.sha256(user.email.lower().encode()).hexdigest()[:16]
    checkpoint_tokens = owned_recruitment_checkpoint_tokens(user_id, db)

    db.query(ProposedResumeEdit).filter(ProposedResumeEdit.user_id == user_id).delete(
        synchronize_session=False
    )
    db.query(TargetAssessmentArtifact).filter(
        TargetAssessmentArtifact.user_id == user_id
    ).delete(synchronize_session=False)
    db.query(RoleProfileArtifact).filter(RoleProfileArtifact.user_id == user_id).delete(
        synchronize_session=False
    )
    thread_ids = db.query(RecruitmentThread.id).filter(RecruitmentThread.user_id == user_id)
    db.query(RecruitmentActivityEvent).filter(
        RecruitmentActivityEvent.thread_id.in_(thread_ids)
    ).delete(synchronize_session=False)
    db.query(RecruitmentMessage).filter(RecruitmentMessage.thread_id.in_(thread_ids)).delete(
        synchronize_session=False
    )
    db.query(RecruitmentRun).filter(RecruitmentRun.user_id == user_id).delete(
        synchronize_session=False
    )
    db.query(RecruitmentThread).filter(RecruitmentThread.user_id == user_id).delete(
        synchronize_session=False
    )
    db.query(RecruitmentThreadDeletionRequest).filter(
        RecruitmentThreadDeletionRequest.user_id == user_id
    ).delete(synchronize_session=False)
    db.query(CandidateProfileArtifact).filter(
        CandidateProfileArtifact.user_id == user_id
    ).delete(synchronize_session=False)

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
        db.query(model).filter(model.user_id == user_id).delete(synchronize_session=False)
    db.query(UsageLog).filter(
        or_(
            UsageLog.user_id == user_id,
            and_(
                UsageLog.user_id.is_(None),
                UsageLog.action.in_((
                    "login_failed",
                    "password_reset_request",
                    "email_verification_request",
                )),
                UsageLog.detail == email_hash,
            ),
        )
    ).delete(synchronize_session=False)
    db.delete(user)
    return checkpoint_tokens
