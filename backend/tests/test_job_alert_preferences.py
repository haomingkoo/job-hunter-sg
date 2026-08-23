from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from database import Base
from job_alert_preferences import (
    disable_preference,
    dismiss_job,
    get_or_create_preference,
    record_delivery_action,
    update_preference,
)
from models import JobAlertDelivery, JobAlertPreference, ScrapedJob, User, UserMemory
from schemas import JobAlertPreferenceUpdate


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'job-alerts.db'}")
    Base.metadata.create_all(bind=engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _user(db: Session) -> User:
    user = User(email="alerts@example.test", password_hash="unused", name="Alert User")
    db.add(user)
    db.flush()
    return user


def _job(db: Session) -> ScrapedJob:
    job = ScrapedJob(
        title="Platform Engineer",
        company="Example Employer",
        url="https://example.test/jobs/platform-engineer",
        source="Careers@Gov",
        dedup_key="careersgov:platform-engineer",
    )
    db.add(job)
    db.flush()
    return job


def test_preference_creation_is_idempotent(db):
    user = _user(db)

    first = get_or_create_preference(db, user.id)
    second = get_or_create_preference(db, user.id)

    assert first.id == second.id
    assert db.query(JobAlertPreference).filter_by(user_id=user.id).count() == 1


def test_enabling_requires_resume_and_records_consent(db):
    user = _user(db)
    changed_at = datetime(2026, 8, 23, tzinfo=timezone.utc)

    with pytest.raises(HTTPException) as caught:
        update_preference(
            db,
            user.id,
            JobAlertPreferenceUpdate(enabled=True),
            now=changed_at,
        )
    assert caught.value.status_code == 400

    db.add(UserMemory(user_id=user.id, resume_text="Experienced engineer " * 5))
    preference = update_preference(
        db,
        user.id,
        JobAlertPreferenceUpdate(enabled=True, keywords="<b>platform</b>"),
        now=changed_at,
    )

    assert preference.enabled is True
    assert preference.keywords == "platform"
    assert preference.consented_at == changed_at
    assert preference.last_run_at == changed_at
    assert preference.match_cursor_at == changed_at

    disabled_at = datetime(2026, 8, 24, tzinfo=timezone.utc)
    disable_preference(db, user.id, now=disabled_at)
    assert preference.enabled is False
    assert preference.unsubscribed_at == disabled_at


def test_delivery_action_updates_one_user_job_identity(db):
    user = _user(db)
    job = _job(db)

    record_delivery_action(db, user.id, job.id, "tracked")
    db.flush()
    record_delivery_action(db, user.id, job.id, "dismissed")
    db.flush()

    deliveries = db.query(JobAlertDelivery).filter_by(user_id=user.id).all()
    assert len(deliveries) == 1
    assert deliveries[0].action == "dismissed"
    assert deliveries[0].dismissed_at is not None


def test_dismiss_rejects_an_unknown_job_without_creating_a_preference(db):
    user = _user(db)

    with pytest.raises(HTTPException) as caught:
        dismiss_job(db, user.id, 999_999)

    assert caught.value.status_code == 404
    assert db.query(JobAlertPreference).filter_by(user_id=user.id).count() == 0
