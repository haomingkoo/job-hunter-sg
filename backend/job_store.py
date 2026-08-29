"""Database lookup helpers for scraped job upserts."""

from __future__ import annotations

import hashlib
import re

from sqlalchemy import exists
from sqlalchemy.orm import Session

from models import (
    JobAlertDelivery,
    ResumeVersion,
    ScrapedJob,
    StoryUsage,
    TailoredResume,
    TrackedJob,
)

# Fields that make a listing the same listing to a reader. Deliberately excludes
# posted_date, closing_date and every posting identifier, because those are exactly
# what change when an employer reposts unchanged content.
_CONTENT_FIELDS = (
    "company",
    "title",
    "location",
    "salary",
    "employment_type",
    "description",
)


def compute_content_hash(job_data: dict) -> str:
    """Hash a listing's visible content.

    Must be computed from already-sanitized values, or the same listing hashes
    differently depending on how much HTML its source happened to include.
    """
    description = re.sub(r"\s+", " ", str(job_data.get("description") or "")).strip()
    if not description:
        # Without a description there is not enough signal to call two rows the same.
        return ""
    parts = [
        re.sub(r"\s+", " ", str(job_data.get(field) or "")).strip().casefold()
        for field in _CONTENT_FIELDS[:-1]
    ]
    parts.append(description.casefold())
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


def backfill_content_hashes(
    db: Session,
    limit: int = 5000,
    *,
    public_only: bool = False,
) -> int:
    """Stamp content_hash on rows written before the column existed.

    Without this the content fallback never fires on the existing corpus, because
    a stored row with an empty hash can never match an incoming one. Returns the
    number stamped; call until it returns 0. Batched rather than threaded so it
    stays a plain request with no background-progress machinery.
    """
    query = db.query(ScrapedJob).filter(ScrapedJob.content_hash == "")
    if public_only:
        query = query.filter(ScrapedJob.hidden == 0)
    rows = query.order_by(ScrapedJob.id).limit(limit).all()
    stamped = 0
    for row in rows:
        content_hash = compute_content_hash(
            {
                "company": row.company,
                "title": row.title,
                "location": row.location,
                "salary": row.salary,
                "employment_type": row.employment_type,
                "description": row.description,
            }
        )
        # A row with no description hashes to "", so it stays selected by the filter
        # above forever. Park it on a sentinel so the batch loop can terminate.
        row.content_hash = content_hash or "-"
        stamped += 1
    db.commit()
    return stamped


def prune_unreferenced_legacy_hidden_jobs(db: Session, limit: int) -> int:
    """Delete invisible legacy duplicates while preserving user-linked jobs."""
    candidate_ids = [
        row.id
        for row in (
            db.query(ScrapedJob.id)
            .filter(
                ScrapedJob.hidden == 1,
                ScrapedJob.retirement_reason == "",
                ~exists().where(TrackedJob.scraped_job_id == ScrapedJob.id),
                ~exists().where(TailoredResume.job_id == ScrapedJob.id),
                ~exists().where(ResumeVersion.job_id == ScrapedJob.id),
                ~exists().where(StoryUsage.job_id == ScrapedJob.id),
                ~exists().where(JobAlertDelivery.scraped_job_id == ScrapedJob.id),
            )
            .order_by(ScrapedJob.id)
            .limit(limit)
        )
    ]
    if not candidate_ids:
        return 0
    deleted = (
        db.query(ScrapedJob)
        .filter(ScrapedJob.id.in_(candidate_ids))
        .delete(synchronize_session=False)
    )
    db.commit()
    return deleted


def find_existing_scraped_job(db: Session, job_data: dict) -> ScrapedJob | None:
    """Find an existing listing across old and new dedup key strategies."""
    dedup_key = (job_data.get("dedup_key") or "").strip()
    if dedup_key:
        existing = db.query(ScrapedJob).filter(ScrapedJob.dedup_key == dedup_key).first()
        if existing:
            return existing

    source = (job_data.get("source") or "").strip()
    source_posting_id = (job_data.get("source_posting_id") or "").strip()
    if source and source_posting_id:
        existing = (
            db.query(ScrapedJob)
            .filter(
                ScrapedJob.source == source,
                ScrapedJob.source_posting_id == source_posting_id,
            )
            .first()
        )
        if existing:
            return existing

    url = (job_data.get("url") or "").strip()
    if source and url:
        existing = (
            db.query(ScrapedJob)
            .filter(ScrapedJob.source == source, ScrapedJob.url == url)
            .first()
        )
        if existing:
            return existing

    # Every strategy above identifies a posting, and a repost carries a fresh
    # dedup_key, source_posting_id and url, so unchanged content reposted later
    # reads as a brand new job. Fall back to the content itself, within one source
    # so two boards advertising the same role still both appear.
    content_hash = (job_data.get("content_hash") or "").strip()
    if source and content_hash:
        existing = (
            db.query(ScrapedJob)
            .filter(
                ScrapedJob.source == source,
                ScrapedJob.content_hash == content_hash,
            )
            .first()
        )
        if existing:
            return existing

    return None
