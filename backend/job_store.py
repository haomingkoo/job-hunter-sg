"""Database lookup helpers for scraped job upserts."""

from __future__ import annotations

from sqlalchemy.orm import Session

from models import ScrapedJob


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

    return None
