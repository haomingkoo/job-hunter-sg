"""Owned STAR+R story persistence, matching, and usage policy."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from models import InterviewStory, ScrapedJob, StoryUsage
from sanitizer import sanitize_user_input


STORY_TAGS = (
    "motivation",
    "proactiveness",
    "ambiguity",
    "perseverance",
    "conflict_resolution",
    "empathy",
    "growth",
    "communication",
)
MAX_ACTIVE_STORIES = 100
MAX_STORY_USAGES = 1_000
_SENIORITY_LEVELS = ("junior", "mid", "senior", "staff")
_TAG_KEYWORDS = {
    "motivation": ("passion", "driven", "motivated", "mission", "purpose", "impact"),
    "proactiveness": ("initiative", "proactive", "self-starter", "ownership", "autonomous"),
    "ambiguity": ("ambiguous", "unstructured", "fast-paced", "startup", "greenfield", "undefined"),
    "perseverance": ("resilient", "challenge", "obstacle", "pressure", "deadline", "persist"),
    "conflict_resolution": ("conflict", "stakeholder", "negotiate", "disagree", "alignment", "cross-functional"),
    "empathy": ("empathy", "user-centric", "customer", "inclusive", "diversity", "mentor"),
    "growth": ("learn", "grow", "feedback", "continuous improvement", "adapt", "mentor"),
    "communication": ("communicate", "present", "write", "collaborate", "cross-functional", "influence"),
}


def _clean_text(value: object, *, field: str, max_length: int = 1_000) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise HTTPException(status_code=422, detail=f"{field} must be a string")
    return sanitize_user_input(value, max_length=max_length)


def _clean_tags(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(tag for tag in value if isinstance(tag, str) and tag in STORY_TAGS))


def _clean_seniority(value: object) -> str:
    return str(value) if value in _SENIORITY_LEVELS else "mid"


def _story_detail(story: InterviewStory) -> dict:
    return {
        "id": story.id,
        "title": story.title,
        "project_name": story.project_name,
        "situation": story.situation,
        "task": story.task,
        "action": story.action,
        "result": story.result,
        "reflection": story.reflection,
        "tags": story.tags or [],
        "seniority": story.seniority,
        "created_at": story.created_at.isoformat() if story.created_at else "",
        "updated_at": story.updated_at.isoformat() if story.updated_at else "",
    }


def list_stories(db: Session, user_id: int) -> list[dict]:
    stories = (
        db.query(InterviewStory)
        .filter(InterviewStory.user_id == user_id, InterviewStory.is_active == 1)
        .order_by(InterviewStory.updated_at.desc())
        .all()
    )
    return [_story_detail(story) for story in stories]


def get_owned_active_story(db: Session, user_id: int, story_id: int) -> InterviewStory:
    story = (
        db.query(InterviewStory)
        .filter(
            InterviewStory.id == story_id,
            InterviewStory.user_id == user_id,
            InterviewStory.is_active == 1,
        )
        .first()
    )
    if story is None:
        raise HTTPException(status_code=404, detail="Story not found")
    return story


def create_story(db: Session, user_id: int, body: dict) -> InterviewStory:
    active_count = (
        db.query(func.count(InterviewStory.id))
        .filter(InterviewStory.user_id == user_id, InterviewStory.is_active == 1)
        .scalar()
        or 0
    )
    if active_count >= MAX_ACTIVE_STORIES:
        raise HTTPException(status_code=409, detail="Story limit reached")

    title = _clean_text(body.get("title"), field="Title", max_length=300).strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title is required")
    story = InterviewStory(
        user_id=user_id,
        title=title,
        project_name=_clean_text(body.get("project_name"), field="Project name", max_length=300),
        situation=_clean_text(body.get("situation"), field="Situation"),
        task=_clean_text(body.get("task"), field="Task"),
        action=_clean_text(body.get("action"), field="Action"),
        result=_clean_text(body.get("result"), field="Result"),
        reflection=_clean_text(body.get("reflection"), field="Reflection"),
        tags=_clean_tags(body.get("tags")),
        seniority=_clean_seniority(body.get("seniority", "mid")),
    )
    db.add(story)
    db.flush()
    return story


def update_story(db: Session, user_id: int, story_id: int, body: dict) -> InterviewStory:
    story = get_owned_active_story(db, user_id, story_id)
    limits = {"title": 300, "project_name": 300}
    for field in ("title", "project_name", "situation", "task", "action", "result", "reflection"):
        if field in body:
            value = _clean_text(body[field], field=field.replace("_", " ").title(), max_length=limits.get(field, 1_000))
            if field == "title" and not value.strip():
                raise HTTPException(status_code=400, detail="Title is required")
            setattr(story, field, value)
    if "tags" in body and isinstance(body["tags"], list):
        story.tags = _clean_tags(body["tags"])
    if "seniority" in body and body["seniority"] in _SENIORITY_LEVELS:
        story.seniority = str(body["seniority"])
    return story


def archive_story(db: Session, user_id: int, story_id: int) -> InterviewStory:
    story = get_owned_active_story(db, user_id, story_id)
    story.is_active = 0
    return story


def _suggestion(story: InterviewStory, matching_tags: set[str]) -> dict:
    return {
        "story_id": story.id,
        "title": story.title,
        "project_name": story.project_name,
        "situation": story.situation or "",
        "task": story.task or "",
        "action": story.action or "",
        "result": story.result or "",
        "reflection": story.reflection or "",
        "tags": story.tags or [],
        "matching_tags": sorted(matching_tags),
        "match_count": len(matching_tags),
    }


def suggest_stories(db: Session, user_id: int, job_id: int) -> dict:
    job = db.query(ScrapedJob).filter(ScrapedJob.id == job_id).first()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    stories = (
        db.query(InterviewStory)
        .filter(InterviewStory.user_id == user_id, InterviewStory.is_active == 1)
        .all()
    )
    if not stories:
        return {"suggestions": [], "detected_tags": [], "message": "No stories yet. Create some first!"}

    job_text = (job.description or "").lower()
    detected_tags = [
        tag for tag, keywords in _TAG_KEYWORDS.items() if any(keyword in job_text for keyword in keywords)
    ]
    detected = set(detected_tags)
    suggestions = []
    other_stories = []
    for story in stories:
        overlap = set(story.tags or ()) & detected
        target = suggestions if overlap else other_stories
        target.append(_suggestion(story, overlap))
    suggestions.sort(key=lambda item: item["match_count"], reverse=True)
    return {
        "suggestions": suggestions,
        "other_stories": other_stories,
        "detected_tags": detected_tags,
        "job_title": job.title,
    }


def record_usage(db: Session, user_id: int, story_id: int, body: dict) -> StoryUsage:
    get_owned_active_story(db, user_id, story_id)
    usage_count = (
        db.query(func.count(StoryUsage.id))
        .filter(StoryUsage.user_id == user_id)
        .scalar()
        or 0
    )
    if usage_count >= MAX_STORY_USAGES:
        raise HTTPException(status_code=409, detail="Story usage limit reached")

    job_id = body.get("job_id")
    if job_id is not None:
        if isinstance(job_id, bool) or not isinstance(job_id, int) or job_id <= 0:
            raise HTTPException(status_code=422, detail="Job ID must be a positive integer")
        if db.query(ScrapedJob.id).filter(ScrapedJob.id == job_id).first() is None:
            raise HTTPException(status_code=404, detail="Job not found")
    usage = StoryUsage(
        story_id=story_id,
        job_id=job_id,
        user_id=user_id,
        question_asked=_clean_text(body.get("question_asked"), field="Question", max_length=1_000),
        notes=_clean_text(body.get("notes"), field="Notes", max_length=5_000),
    )
    db.add(usage)
    db.flush()
    return usage
