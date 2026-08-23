"""Transactional preference and delivery mutations for candidate job alerts."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from models import JobAlertDelivery, JobAlertPreference, ScrapedJob, UserMemory
from sanitizer import sanitize_user_input
from schemas import JobAlertPreferenceUpdate


def get_or_create_preference(db: Session, user_id: int) -> JobAlertPreference:
    preference = (
        db.query(JobAlertPreference)
        .filter(JobAlertPreference.user_id == user_id)
        .first()
    )
    if preference is not None:
        return preference
    preference = JobAlertPreference(user_id=user_id)
    db.add(preference)
    db.flush()
    return preference


def record_delivery_action(
    db: Session,
    user_id: int,
    scraped_job_id: int | None,
    action: str,
) -> None:
    if not scraped_job_id:
        return
    preference = get_or_create_preference(db, user_id)
    delivery = (
        db.query(JobAlertDelivery)
        .filter(
            JobAlertDelivery.user_id == user_id,
            JobAlertDelivery.scraped_job_id == scraped_job_id,
        )
        .first()
    )
    now = datetime.now(timezone.utc)
    if delivery is None:
        delivery = JobAlertDelivery(
            user_id=user_id,
            preference_id=preference.id,
            scraped_job_id=scraped_job_id,
            action=action,
            sent_at=now,
        )
        db.add(delivery)
    delivery.preference_id = preference.id
    delivery.action = action
    if action != "sent":
        delivery.dismissed_at = now


def update_preference(
    db: Session,
    user_id: int,
    body: JobAlertPreferenceUpdate,
    *,
    now: datetime | None = None,
) -> JobAlertPreference:
    preference = get_or_create_preference(db, user_id)
    updates = body.model_dump(exclude_unset=True)
    enabling = updates.get("enabled") is True and not bool(preference.enabled)
    disabling = updates.get("enabled") is False and bool(preference.enabled)

    if updates.get("enabled") is True:
        memory = db.query(UserMemory).filter(UserMemory.user_id == user_id).first()
        resume_text = (memory.resume_text or "").strip() if memory else ""
        if len(resume_text) < 50:
            raise HTTPException(
                status_code=400,
                detail="Upload or score a resume first before enabling matched job alerts.",
            )

    for key, value in updates.items():
        if key == "keywords" and isinstance(value, str):
            value = sanitize_user_input(value)[:300]
        setattr(preference, key, value)

    changed_at = now or datetime.now(timezone.utc)
    if enabling:
        preference.last_run_at = changed_at
        preference.match_cursor_at = changed_at
        preference.consented_at = changed_at
        preference.unsubscribed_at = None
    if disabling:
        preference.unsubscribed_at = changed_at
    preference.updated_at = changed_at
    return preference


def dismiss_job(db: Session, user_id: int, job_id: int) -> None:
    if db.query(ScrapedJob.id).filter(ScrapedJob.id == job_id).first() is None:
        raise HTTPException(status_code=404, detail="Job not found")
    record_delivery_action(db, user_id, job_id, "dismissed")


def disable_preference(
    db: Session,
    user_id: int,
    *,
    now: datetime | None = None,
) -> JobAlertPreference:
    preference = get_or_create_preference(db, user_id)
    changed_at = now or datetime.now(timezone.utc)
    preference.enabled = False
    preference.unsubscribed_at = changed_at
    preference.updated_at = changed_at
    return preference
