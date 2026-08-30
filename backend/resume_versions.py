"""Owned resume-version validation and persistence operations."""

from __future__ import annotations

import hashlib
import json

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from models import ResumeVersion, ScrapedJob
from resume_document import SCHEMA_VERSION, create_resume_document
from sanitizer import sanitize_user_input


MAX_ACTIVE_RESUME_VERSIONS = 50
MAX_SAVED_RESUME_CHARS = 30_000
MAX_RESUME_STRUCTURED_BYTES = 200_000


def _structure_for_storage(resume_text: str, supplied: object = None) -> dict:
    if supplied is None:
        return create_resume_document(resume_text)
    if not isinstance(supplied, dict):
        raise HTTPException(status_code=422, detail="Structured resume must be an object")
    if supplied.get("schema_version") != SCHEMA_VERSION:
        return create_resume_document(resume_text)
    if supplied.get("raw_text") != resume_text:
        raise HTTPException(status_code=409, detail="Structured resume does not match resume text")
    return supplied


def _validated_resume_text(value: object) -> str:
    if not isinstance(value, str):
        raise HTTPException(status_code=422, detail="Resume text must be a string")
    resume_text = value.strip()
    if len(resume_text) < 50:
        raise HTTPException(status_code=400, detail="Resume text too short")
    if len(resume_text) > MAX_SAVED_RESUME_CHARS:
        raise HTTPException(status_code=413, detail="Resume text is too large")
    return resume_text


def _validated_structure(resume_text: str, supplied: object = None) -> dict:
    structured = _structure_for_storage(resume_text, supplied)
    if len(json.dumps(structured, separators=(",", ":"))) > MAX_RESUME_STRUCTURED_BYTES:
        raise HTTPException(status_code=413, detail="Structured resume is too large")
    return structured


def _validated_label(value: object) -> str:
    if not isinstance(value, str):
        raise HTTPException(status_code=422, detail="Label must be a string")
    label = sanitize_user_input(value).strip()[:200]
    if not label:
        raise HTTPException(status_code=400, detail="Label is required")
    return label


def _validated_score(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
        raise HTTPException(status_code=422, detail="Score must be an integer from 0 to 100")
    return value


def get_owned_version(db: Session, user_id: int, version_id: int) -> ResumeVersion:
    version = (
        db.query(ResumeVersion)
        .filter(
            ResumeVersion.id == version_id,
            ResumeVersion.user_id == user_id,
            ResumeVersion.is_active == True,
        )
        .first()
    )
    if version is None:
        raise HTTPException(status_code=404, detail="Version not found")
    return version


def version_summary(version: ResumeVersion) -> dict:
    return {
        "id": version.id,
        "label": version.label,
        "source": version.source,
        "job_id": version.job_id,
        "job_title": version.job_title,
        "job_company": version.job_company,
        "score": version.score,
        "word_count": version.word_count if version.word_count is not None else len(version.resume_text.split()),
        "content_sha256": hashlib.sha256(version.resume_text.encode()).hexdigest(),
        "is_master": version.is_master,
        "created_at": version.created_at.isoformat() if version.created_at else "",
        "updated_at": version.updated_at.isoformat() if version.updated_at else "",
    }


def version_detail(version: ResumeVersion) -> dict:
    return {
        **version_summary(version),
        "resume_text": version.resume_text,
        "resume_structured": version.resume_structured,
    }


def list_versions(db: Session, user_id: int) -> list[dict]:
    versions = (
        db.query(ResumeVersion)
        .filter(ResumeVersion.user_id == user_id, ResumeVersion.is_active == True)
        .order_by(ResumeVersion.updated_at.desc())
        .all()
    )
    return [version_summary(version) for version in versions]


def create_version(db: Session, user_id: int, body: dict) -> ResumeVersion:
    label = _validated_label(body.get("label"))
    resume_text = _validated_resume_text(body.get("resume_text"))
    resume_structured = _validated_structure(resume_text, body.get("resume_structured"))
    score = _validated_score(body.get("score"))
    is_master = body.get("is_master") is True
    source = sanitize_user_input(str(body.get("source") or "manual")).strip()[:50] or "manual"

    job_id = body.get("job_id")
    if job_id is not None and (isinstance(job_id, bool) or not isinstance(job_id, int) or job_id <= 0):
        raise HTTPException(status_code=422, detail="Job ID must be a positive integer")

    active_count = (
        db.query(func.count(ResumeVersion.id))
        .filter(ResumeVersion.user_id == user_id, ResumeVersion.is_active == True)
        .scalar()
        or 0
    )
    if active_count >= MAX_ACTIVE_RESUME_VERSIONS:
        raise HTTPException(status_code=409, detail="Resume version limit reached")

    job_title = ""
    job_company = ""
    if job_id is not None:
        job = db.query(ScrapedJob).filter(ScrapedJob.id == job_id).first()
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        job_title = job.title or ""
        job_company = job.company or ""

    if is_master:
        db.query(ResumeVersion).filter(
            ResumeVersion.user_id == user_id,
            ResumeVersion.is_master == True,
        ).update({"is_master": False})

    version = ResumeVersion(
        user_id=user_id,
        label=label,
        source=source,
        resume_text=resume_text,
        resume_structured=resume_structured,
        job_id=job_id,
        job_title=job_title,
        job_company=job_company,
        score=score,
        word_count=len(resume_text.split()),
        is_master=is_master,
    )
    db.add(version)
    db.flush()
    return version


def update_version(db: Session, user_id: int, version_id: int, body: dict) -> ResumeVersion:
    version = get_owned_version(db, user_id, version_id)
    immutable_fields = {"resume_text", "resume_structured", "source", "job_id", "job_title", "job_company"}
    if immutable_fields.intersection(body):
        raise HTTPException(
            status_code=409,
            detail="Resume version content is immutable; save changed content as a new version",
        )
    if "label" in body:
        version.label = _validated_label(body["label"])
    if "score" in body:
        version.score = _validated_score(body["score"])
    if body.get("is_master") is True:
        db.query(ResumeVersion).filter(
            ResumeVersion.user_id == user_id,
            ResumeVersion.is_master == True,
        ).update({"is_master": False})
        version.is_master = True
    return version


def archive_version(db: Session, user_id: int, version_id: int) -> ResumeVersion:
    version = get_owned_version(db, user_id, version_id)
    version.is_active = False
    return version
