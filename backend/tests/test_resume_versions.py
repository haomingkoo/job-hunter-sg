from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from database import Base
from models import ResumeVersion, ScrapedJob, User
from resume_document import is_resume_document
from resume_versions import (
    archive_version,
    create_version,
    get_owned_version,
    list_versions,
    update_version,
    version_detail,
)


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'resume-versions.db'}")
    Base.metadata.create_all(bind=engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _user(db: Session, email: str = "resume-owner@example.test") -> User:
    user = User(email=email, password_hash="unused", name="Resume Owner")
    db.add(user)
    db.flush()
    return user


def _body(**updates) -> dict:
    body = {
        "label": "Master resume",
        "resume_text": "Built reliable Python services and agent workflows for public-sector teams.",
        "is_master": True,
        "score": 84,
    }
    body.update(updates)
    return body


def test_create_snapshots_job_and_builds_canonical_document(db):
    user = _user(db)
    job = ScrapedJob(
        title="Platform Engineer",
        company="Example Employer",
        url="https://example.test/jobs/platform",
        source="Careers@Gov",
        dedup_key="careersgov:platform",
    )
    db.add(job)
    db.flush()

    version = create_version(db, user.id, _body(job_id=job.id))
    detail = version_detail(version)

    assert detail["job_title"] == "Platform Engineer"
    assert detail["job_company"] == "Example Employer"
    assert detail["word_count"] == len(detail["resume_text"].split())
    assert is_resume_document(detail["resume_structured"])
    summaries = list_versions(db, user.id)
    assert len(summaries) == 1
    assert "resume_text" not in summaries[0]


@pytest.mark.parametrize(
    ("updates", "status_code"),
    [
        ({"label": 7}, 422),
        ({"label": "<b></b>"}, 400),
        ({"resume_text": ["not", "text"]}, 422),
        ({"resume_text": "too short"}, 400),
        ({"score": True}, 422),
        ({"score": 101}, 422),
        ({"job_id": "17"}, 422),
        ({"job_id": 999_999}, 404),
    ],
)
def test_create_rejects_malformed_scalar_fields(db, updates, status_code):
    user = _user(db)

    with pytest.raises(HTTPException) as caught:
        create_version(db, user.id, _body(**updates))

    assert caught.value.status_code == status_code


def test_update_is_owner_scoped_and_keeps_one_master(db):
    owner = _user(db)
    other = _user(db, "other-owner@example.test")
    first = create_version(db, owner.id, _body(label="First"))
    second = create_version(db, owner.id, _body(label="Second", is_master=False))

    updated = update_version(
        db,
        owner.id,
        second.id,
        {
            "label": "Updated second",
            "resume_text": "Led dependable platform delivery and improved service reliability across teams.",
            "is_master": True,
            "score": 91,
        },
    )

    db.flush()
    db.refresh(first)
    assert updated.is_master is True
    assert first.is_master is False
    assert updated.word_count == len(updated.resume_text.split())
    assert updated.score == 91
    with pytest.raises(HTTPException) as caught:
        get_owned_version(db, other.id, updated.id)
    assert caught.value.status_code == 404


def test_archive_is_soft_and_removes_version_from_owned_library(db):
    user = _user(db)
    version = create_version(db, user.id, _body())

    archive_version(db, user.id, version.id)
    db.flush()

    assert db.get(ResumeVersion, version.id) is not None
    assert list_versions(db, user.id) == []
    with pytest.raises(HTTPException) as caught:
        get_owned_version(db, user.id, version.id)
    assert caught.value.status_code == 404
