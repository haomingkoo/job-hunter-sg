"""HTTP routes for the owned resume-version library."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from account_lifecycle import locked_account_storage
from auth import get_current_user
from database import get_db
from models import User
from resume_versions import (
    archive_version,
    create_version,
    get_owned_version,
    list_versions,
    update_version,
    version_detail,
)


router = APIRouter(prefix="/api/resume/versions", tags=["resume-versions"])


@router.get("")
def list_resume_versions(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    return list_versions(db, user.id)


@router.post("")
def save_resume_version(
    body: dict,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    with locked_account_storage(user.id, db):
        version = create_version(db, user.id, body)
        db.commit()
        db.refresh(version)
    return {"id": version.id, "label": version.label, "created_at": version.created_at.isoformat()}


@router.get("/{version_id}")
def get_resume_version(
    version_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return version_detail(get_owned_version(db, user.id, version_id))


@router.put("/{version_id}")
def update_resume_version(
    version_id: int,
    body: dict,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    with locked_account_storage(user.id, db):
        version = update_version(db, user.id, version_id, body)
        db.commit()
    return {"id": version.id, "label": version.label, "updated": True}


@router.delete("/{version_id}")
def delete_resume_version(
    version_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    with locked_account_storage(user.id, db):
        version = archive_version(db, user.id, version_id)
        db.commit()
    return {"id": version.id, "deleted": True}
