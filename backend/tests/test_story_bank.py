from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from database import Base
from models import InterviewStory, ScrapedJob, StoryUsage, User
from story_bank import (
    archive_story,
    create_story,
    get_owned_active_story,
    list_stories,
    record_usage,
    suggest_stories,
    update_story,
)


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'story-bank.db'}")
    Base.metadata.create_all(bind=engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _user(db: Session, email: str = "story-owner@example.test") -> User:
    user = User(email=email, password_hash="unused", name="Story Owner")
    db.add(user)
    db.flush()
    return user


def _job(db: Session) -> ScrapedJob:
    job = ScrapedJob(
        title="Platform Lead",
        company="Example Employer",
        description="Own an ambiguous greenfield mission and influence cross-functional stakeholders.",
        url="https://example.test/jobs/platform-lead",
        source="Employer site",
        dedup_key="employer:platform-lead",
    )
    db.add(job)
    db.flush()
    return job


def test_create_sanitizes_and_normalizes_story(db):
    user = _user(db)

    story = create_story(
        db,
        user.id,
        {
            "title": "<b>Service recovery</b>",
            "project_name": "Platform",
            "situation": "<script>bad()</script>Production incident",
            "tags": ["ambiguity", "ambiguity", "unknown", 4],
            "seniority": "executive",
        },
    )

    assert story.title == "Service recovery"
    assert "script" not in story.situation
    assert story.tags == ["ambiguity"]
    assert story.seniority == "mid"
    assert list_stories(db, user.id)[0]["title"] == "Service recovery"


@pytest.mark.parametrize(
    ("body", "status_code"),
    [
        ({"title": 7}, 422),
        ({"title": "<b></b>"}, 400),
        ({"title": "Valid", "situation": ["not", "text"]}, 422),
    ],
)
def test_create_rejects_malformed_story_fields(db, body, status_code):
    user = _user(db)

    with pytest.raises(HTTPException) as caught:
        create_story(db, user.id, body)

    assert caught.value.status_code == status_code


def test_update_and_archive_are_owner_scoped(db):
    owner = _user(db)
    other = _user(db, "other-story-owner@example.test")
    story = create_story(db, owner.id, {"title": "Original"})

    updated = update_story(
        db,
        owner.id,
        story.id,
        {"title": "Updated", "tags": ["communication"], "seniority": "senior"},
    )

    assert updated.title == "Updated"
    assert updated.tags == ["communication"]
    assert updated.seniority == "senior"
    with pytest.raises(HTTPException) as caught:
        update_story(db, owner.id, story.id, {"title": "<b></b>"})
    assert caught.value.status_code == 400
    with pytest.raises(HTTPException) as caught:
        get_owned_active_story(db, other.id, story.id)
    assert caught.value.status_code == 404

    archive_story(db, owner.id, story.id)
    db.flush()
    assert db.get(InterviewStory, story.id) is not None
    assert list_stories(db, owner.id) == []
    with pytest.raises(HTTPException) as caught:
        get_owned_active_story(db, owner.id, story.id)
    assert caught.value.status_code == 404


def test_suggestions_rank_tag_overlap_for_the_requested_job(db):
    user = _user(db)
    job = _job(db)
    create_story(db, user.id, {"title": "Led through uncertainty", "tags": ["ambiguity", "communication"]})
    create_story(db, user.id, {"title": "Unrelated lesson", "tags": ["growth"]})

    result = suggest_stories(db, user.id, job.id)

    assert {"ambiguity", "communication"}.issubset(result["detected_tags"])
    assert result["suggestions"][0]["title"] == "Led through uncertainty"
    assert result["suggestions"][0]["match_count"] == 2
    assert result["other_stories"][0]["title"] == "Unrelated lesson"


def test_record_usage_validates_job_and_preserves_owner_boundary(db):
    owner = _user(db)
    other = _user(db, "story-usage-other@example.test")
    story = create_story(db, owner.id, {"title": "Incident response"})
    job = _job(db)

    with pytest.raises(HTTPException) as caught:
        record_usage(db, owner.id, story.id, {"job_id": "not-an-id"})
    assert caught.value.status_code == 422
    with pytest.raises(HTTPException) as caught:
        record_usage(db, owner.id, story.id, {"job_id": 999_999})
    assert caught.value.status_code == 404
    with pytest.raises(HTTPException) as caught:
        record_usage(db, other.id, story.id, {"job_id": job.id})
    assert caught.value.status_code == 404

    usage = record_usage(
        db,
        owner.id,
        story.id,
        {"job_id": job.id, "question_asked": "Tell me about ambiguity", "notes": "Use the recovery example"},
    )

    assert usage.story_id == story.id
    assert usage.job_id == job.id
    assert db.query(StoryUsage).filter(StoryUsage.user_id == owner.id).count() == 1


def test_story_routes_preserve_http_contract_and_generator_route(db):
    import main
    from auth import get_current_user
    from database import get_db

    user = _user(db, "story-http@example.test")

    def override_db():
        yield db

    main.app.dependency_overrides[get_current_user] = lambda: user
    main.app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(main.app) as client:
            created = client.post(
                "/api/stories",
                json={"title": "HTTP story", "tags": ["communication"]},
            )
            assert created.status_code == 201
            story_id = created.json()["id"]

            listed = client.get("/api/stories")
            assert listed.status_code == 200
            assert listed.headers["cache-control"] == "no-store"
            assert listed.json()[0]["title"] == "HTTP story"

            updated = client.put(f"/api/stories/{story_id}", json={"title": "Updated over HTTP"})
            assert updated.status_code == 200
            assert updated.json() == {"id": story_id, "message": "Story updated"}

            # The static AI endpoint must not be swallowed by /{story_id} routes.
            generated = client.post("/api/stories/generate", json={})
            assert generated.status_code == 400
            assert generated.json()["detail"].startswith("Resume text too short")

            deleted = client.delete(f"/api/stories/{story_id}")
            assert deleted.status_code == 200
            assert deleted.json() == {"message": "Story deleted"}
    finally:
        main.app.dependency_overrides.pop(get_current_user, None)
        main.app.dependency_overrides.pop(get_db, None)
