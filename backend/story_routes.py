"""HTTP routes for the candidate-owned interview story bank."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from account_lifecycle import locked_account_storage
from auth import get_current_user
from database import get_db
from models import User
from security import FixedWindowRateLimiter
from story_bank import (
    archive_story,
    create_story,
    get_owned_active_story,
    list_stories,
    record_usage,
    suggest_stories,
    update_story,
)


router = APIRouter(prefix="/api/stories", tags=["stories"])
_STORY_USAGE_RATE_LIMITER = FixedWindowRateLimiter()


@router.get("")
def list_story_bank(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict]:
    return list_stories(db, user.id)


@router.post("", status_code=201)
def create_story_route(body: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    with locked_account_storage(user.id, db):
        story = create_story(db, user.id, body)
        db.commit()
        db.refresh(story)
    return {"id": story.id, "message": "Story created"}


@router.put("/{story_id}")
def update_story_route(
    story_id: int,
    body: dict,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    with locked_account_storage(user.id, db):
        story = update_story(db, user.id, story_id, body)
        db.commit()
    return {"id": story.id, "message": "Story updated"}


@router.delete("/{story_id}")
def delete_story_route(
    story_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    with locked_account_storage(user.id, db):
        archive_story(db, user.id, story_id)
        db.commit()
    return {"message": "Story deleted"}


@router.get("/suggest/{job_id}")
def suggest_stories_route(
    job_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return suggest_stories(db, user.id, job_id)


@router.post("/{story_id}/use")
def record_story_usage(
    story_id: int,
    body: dict,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    with locked_account_storage(user.id, db):
        # Validate ownership before charging the caller's quota. Otherwise repeated
        # requests for a missing or foreign ID eventually change from 404 to 429.
        get_owned_active_story(db, user.id, story_id)
        if not _STORY_USAGE_RATE_LIMITER.allow(f"story-use:{user.id}", limit=60, window_seconds=60):
            raise HTTPException(status_code=429, detail="Too many story usage requests")
        record_usage(db, user.id, story_id, body)
        db.commit()
    return {"message": "Usage recorded"}
