"""Shared visibility rules for public job listings."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_

from models import ScrapedJob


DEFAULT_PUBLIC_JOB_MAX_AGE_DAYS = int(os.environ.get("PUBLIC_JOB_MAX_AGE_DAYS", "60"))


def public_job_cutoff_iso(max_age_days: int | None = None, now: datetime | None = None) -> str:
    days = DEFAULT_PUBLIC_JOB_MAX_AGE_DAYS if max_age_days is None else int(max_age_days)
    ref = now or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    return (ref - timedelta(days=days)).isoformat()


def apply_public_job_visibility(query, include_old: bool = False):
    query = query.filter(ScrapedJob.hidden == 0)
    if include_old:
        return query
    today = datetime.now(timezone.utc).date().isoformat()
    return query.filter(
        ScrapedJob.posted_at_sort.isnot(None),
        ScrapedJob.posted_at_sort != "",
        ScrapedJob.posted_at_sort >= public_job_cutoff_iso(),
        or_(
            ScrapedJob.closing_date.is_(None),
            ScrapedJob.closing_date == "",
            ScrapedJob.closing_date >= today,
        ),
    )
