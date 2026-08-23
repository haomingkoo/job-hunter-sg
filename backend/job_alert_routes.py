"""HTTP boundary and persistence helpers for candidate job alerts."""

from __future__ import annotations

import html
import os
from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from account_lifecycle import account_lifecycle_lock, locked_account_storage
from auth import get_current_user
from database import get_db
from job_alerts import verify_unsubscribe_token
from job_alert_preferences import (
    disable_preference,
    dismiss_job,
    get_or_create_preference,
    update_preference,
)
from models import JobAlertPreference, User
from schemas import JobAlertPreferenceOut, JobAlertPreferenceUpdate


router = APIRouter(prefix="/api/job-alerts", tags=["job-alerts"])


@router.get("/preferences", response_model=JobAlertPreferenceOut)
def get_job_alert_preference(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JobAlertPreference:
    with locked_account_storage(user.id, db):
        preference = get_or_create_preference(db, user.id)
        db.commit()
    db.refresh(preference)
    return preference


@router.put("/preferences", response_model=JobAlertPreferenceOut)
def update_job_alert_preference(
    body: JobAlertPreferenceUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JobAlertPreference:
    with locked_account_storage(user.id, db):
        preference = update_preference(db, user.id, body)
        db.commit()
    db.refresh(preference)
    return preference


@router.post("/jobs/{job_id}/dismiss")
def dismiss_job_alert(
    job_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    with locked_account_storage(user.id, db):
        dismiss_job(db, user.id, job_id)
        db.commit()
    return {"ok": True}


@router.get("/unsubscribe")
@router.post("/unsubscribe")
def unsubscribe_job_alerts(
    request: Request,
    token: str = Query(..., min_length=20, max_length=200),
    db: Session = Depends(get_db),
) -> Response:
    try:
        user_id = verify_unsubscribe_token(token, db)
    except RuntimeError:
        user_id = None
    if not user_id:
        return Response(
            content=(
                "<!DOCTYPE html><html><body style=\"font-family:system-ui,sans-serif;"
                "max-width:640px;margin:48px auto;line-height:1.6;\">"
                "<h1>Invalid unsubscribe link</h1>"
                "<p>This alert link is invalid or expired. Sign in and turn off Job Match Alerts from Account.</p>"
                "</body></html>"
            ),
            media_type="text/html",
            status_code=400,
        )

    if request.method == "GET":
        escaped_token = html.escape(token, quote=True)
        return Response(
            content=(
                "<!DOCTYPE html><html><body style=\"font-family:system-ui,sans-serif;"
                "max-width:640px;margin:48px auto;line-height:1.6;color:#243447;\">"
                "<h1>Unsubscribe from job alerts?</h1>"
                "<p>Confirm below to stop receiving Job Hunter SG match alert emails.</p>"
                f"<form method=\"post\" action=\"/api/job-alerts/unsubscribe?token={escaped_token}\">"
                "<button type=\"submit\">Unsubscribe</button>"
                "</form></body></html>"
            ),
            media_type="text/html",
        )

    with account_lifecycle_lock(user_id):
        try:
            current_user_id = verify_unsubscribe_token(token, db)
        except RuntimeError:
            current_user_id = None
        if current_user_id != user_id:
            return Response(
                content="Invalid or expired unsubscribe link.",
                media_type="text/plain",
                status_code=400,
            )
        with locked_account_storage(user_id, db):
            disable_preference(db, user_id)
            db.commit()

    app_base_url = os.environ.get("APP_BASE_URL", "https://job.kooexperience.com").rstrip("/")
    return Response(
        content=(
            "<!DOCTYPE html><html><body style=\"font-family:system-ui,sans-serif;"
            "max-width:640px;margin:48px auto;line-height:1.6;color:#243447;\">"
            "<h1>Job alerts unsubscribed</h1>"
            "<p>You will no longer receive Job Hunter SG match alert emails. "
            "You can turn alerts back on from the Account page anytime.</p>"
            f"<p><a href=\"{app_base_url}\">Return to Job Hunter SG</a></p>"
            "</body></html>"
        ),
        media_type="text/html",
    )
