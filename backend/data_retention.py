"""Inactive-account retention: warn, then purge resumes, AI artifacts and usage logs."""

from __future__ import annotations

import html
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

import config as app_config
from account_lifecycle import (
    INACTIVE_PURGE_MODELS,
    SUBMITTED_RESUME_METADATA_KEYS,
    account_lifecycle_lock,
    delete_inactive_account_content,
    has_active_recruitment_runs,
    locked_account_storage,
    purge_recruitment_checkpoints,
)
from email_service import email_configured, send_email
from models import (
    CandidateProfileArtifact,
    InterviewStory,
    JobAlertPreference,
    RecruitmentThread,
    ResumeVersion,
    TailoredResume,
    TrackedJob,
    UsageLog,
    User,
    UserMemory,
)


log = logging.getLogger("jobhunter.retention")

RETENTION_WARNING_ACTION = "retention_warning_sent"
_ACTIVITY_MODELS = (ResumeVersion, UserMemory, TrackedJob, RecruitmentThread, InterviewStory, TailoredResume)


class RetentionAction(str, Enum):
    WARN = "warn"
    PURGE = "purge"


@dataclass(frozen=True)
class RetentionPolicy:
    retention_days: int = app_config.INACTIVE_ACCOUNT_RETENTION_DAYS
    warning_days: int = app_config.INACTIVE_ACCOUNT_WARNING_DAYS


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def last_activity_at(db: Session, user: User) -> datetime:
    """Latest sign-in, logged action, or edit to user-owned content."""
    moments = [_utc(user.created_at), _utc(user.last_login)]
    moments.append(_utc(
        db.query(func.max(UsageLog.created_at))
        .filter(UsageLog.user_id == user.id, UsageLog.action != RETENTION_WARNING_ACTION)
        .scalar()
    ))
    for model in _ACTIVITY_MODELS:
        moments.append(_utc(db.query(func.max(model.updated_at)).filter(model.user_id == user.id).scalar()))
    known = [moment for moment in moments if moment is not None]
    return max(known) if known else datetime.min.replace(tzinfo=timezone.utc)


def has_purgeable_data(db: Session, user_id: int) -> bool:
    for model in INACTIVE_PURGE_MODELS:
        query = db.query(model.id).filter(model.user_id == user_id)
        if model is UsageLog:
            query = query.filter(UsageLog.action != RETENTION_WARNING_ACTION)
        if query.first() is not None:
            return True
    for model in (RecruitmentThread, CandidateProfileArtifact):
        if db.query(model.id).filter(model.user_id == user_id).first() is not None:
            return True
    for (metadata,) in db.query(TrackedJob.role_metadata).filter(TrackedJob.user_id == user_id):
        if isinstance(metadata, dict) and any(metadata.get(key) for key in SUBMITTED_RESUME_METADATA_KEYS):
            return True
    return False


def _alerts_enabled(db: Session, user_id: int) -> bool:
    return (
        db.query(JobAlertPreference.id)
        .filter(JobAlertPreference.user_id == user_id, JobAlertPreference.enabled == 1)
        .first()
        is not None
    )


def _warned_at(db: Session, user_id: int, since: datetime) -> datetime | None:
    warned = _utc(
        db.query(func.max(UsageLog.created_at))
        .filter(UsageLog.user_id == user_id, UsageLog.action == RETENTION_WARNING_ACTION)
        .scalar()
    )
    return warned if warned and warned >= since else None


def decide(db: Session, user: User, now: datetime, policy: RetentionPolicy) -> RetentionAction | None:
    """Return what retention should do for one account, or None to leave it alone."""
    if user.tier == "admin" or _alerts_enabled(db, user.id):
        return None
    last_active = last_activity_at(db, user)
    purge_cutoff = now - timedelta(days=policy.retention_days)
    warn_cutoff = purge_cutoff + timedelta(days=policy.warning_days)
    if last_active > warn_cutoff or not has_purgeable_data(db, user.id):
        return None
    warned_at = _warned_at(db, user.id, since=last_active)
    if warned_at is None:
        return RetentionAction.WARN
    if last_active <= purge_cutoff and warned_at <= now - timedelta(days=policy.warning_days):
        return RetentionAction.PURGE
    return None


def plan_retention(db: Session, now: datetime, policy: RetentionPolicy) -> list[tuple[int, RetentionAction]]:
    warn_cutoff = now - timedelta(days=policy.retention_days - policy.warning_days)
    naive_cutoff = warn_cutoff.replace(tzinfo=None)
    users = (
        db.query(User)
        .filter(
            User.created_at <= naive_cutoff,
            or_(User.last_login.is_(None), User.last_login <= naive_cutoff),
        )
        .order_by(User.id)
        .all()
    )
    plan = []
    for user in users:
        action = decide(db, user, now, policy)
        if action is not None:
            plan.append((user.id, action))
    return plan


def render_warning_email(user: User, policy: RetentionPolicy) -> tuple[str, str, str]:
    app_base_url = os.environ.get("APP_BASE_URL", "https://job.kooexperience.com").rstrip("/")
    contact = app_config.PRIVACY_CONTACT_EMAIL
    subject = f"Your Job Hunter SG resume data will be deleted in {policy.warning_days} days"
    lines = [
        f"Hi {user.name},",
        "",
        f"You have not used Job Hunter SG for a while. In {policy.warning_days} days we will delete the "
        "resumes, AI results and usage history stored in your account. Your account itself stays.",
        "",
        f"To keep your data, sign in at {app_base_url}. To keep a copy first, use Account > Privacy > Export my data.",
        "",
        f"Job Hunter SG is operated by {app_config.OPERATOR_NAME}. Questions: {contact}",
    ]
    text_body = "\n".join(lines)
    html_body = (
        '<div style="font-family:Inter,Arial,sans-serif;color:#243447;max-width:600px;">'
        f"<p>Hi {html.escape(user.name)},</p>"
        f"<p>You have not used Job Hunter SG for a while. In {policy.warning_days} days we will delete the "
        "resumes, AI results and usage history stored in your account. Your account itself stays.</p>"
        f'<p>To keep your data, <a href="{html.escape(app_base_url)}">sign in</a>. To keep a copy first, '
        "use Account &gt; Privacy &gt; Export my data.</p>"
        f'<p style="color:#6b7280;font-size:12px;">Job Hunter SG is operated by '
        f"{html.escape(app_config.OPERATOR_NAME)}. Questions: {html.escape(contact)}</p>"
        "</div>"
    )
    return subject, text_body, html_body


def _apply(db: Session, user_id: int, now: datetime, policy: RetentionPolicy, stats: dict) -> None:
    with account_lifecycle_lock(user_id), locked_account_storage(user_id, db):
        user = db.get(User, user_id)
        if user is None or has_active_recruitment_runs(user_id, db):
            db.rollback()
            return
        action = decide(db, user, now, policy)
        if action is RetentionAction.WARN:
            subject, text_body, html_body = render_warning_email(user, policy)
            send_email(user.email, subject, text_body, html_body)
            db.add(UsageLog(user_id=user_id, action=RETENTION_WARNING_ACTION, detail="", created_at=now))
            db.commit()
            stats["warned"] += 1
        elif action is RetentionAction.PURGE:
            tokens = delete_inactive_account_content(user_id, db)
            purge_recruitment_checkpoints(tokens, db)
            db.commit()
            stats["purged"] += 1
        else:
            db.rollback()


def purge_anonymous_usage_logs(db: Session, now: datetime, days: int) -> int:
    cutoff = (now - timedelta(days=days)).replace(tzinfo=None)
    return (
        db.query(UsageLog)
        .filter(UsageLog.user_id.is_(None), UsageLog.created_at < cutoff)
        .delete(synchronize_session=False)
    )


def run_retention(db: Session, *, now: datetime | None = None, dry_run: bool = False) -> dict:
    """Warn and purge inactive accounts, then drop old anonymous usage logs."""
    now = now or datetime.now(timezone.utc)
    policy = RetentionPolicy()
    # Nobody loses data without the warning email, so no SMTP means no account purges.
    email_ready = email_configured()
    plan = plan_retention(db, now, policy) if email_ready else []
    stats: dict = {
        "email_configured": email_ready,
        "planned_warnings": sum(action is RetentionAction.WARN for _, action in plan),
        "planned_purges": sum(action is RetentionAction.PURGE for _, action in plan),
        "warned": 0,
        "purged": 0,
        "anonymous_logs_deleted": 0,
        "errors": 0,
    }
    if dry_run:
        db.rollback()
        return stats
    for user_id, _action in plan:
        try:
            _apply(db, user_id, now, policy, stats)
        except Exception as exc:
            db.rollback()
            stats["errors"] += 1
            log.warning("Retention failed for user_id=%s: %s", user_id, type(exc).__name__)
    stats["anonymous_logs_deleted"] = purge_anonymous_usage_logs(
        db, now, app_config.ANONYMOUS_USAGE_LOG_RETENTION_DAYS
    )
    db.commit()
    return stats
