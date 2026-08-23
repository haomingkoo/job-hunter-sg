"""Shared visibility rules for public job listings."""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, or_

from models import ScrapedJob


DEFAULT_PUBLIC_JOB_MAX_AGE_DAYS = int(os.environ.get("PUBLIC_JOB_MAX_AGE_DAYS", "60"))
KNOWN_RETIREMENT_REASONS = ("source_retired", "age_retired")
UNCLASSIFIED_SECTOR = "Unclassified"


def job_corpus_marker(db) -> str:
    """Stable marker for the currently public job corpus."""
    corpus_query = db.query(
        func.count(ScrapedJob.id),
        func.max(ScrapedJob.id),
        func.max(ScrapedJob.scraped_at),
    )
    count, max_id, max_scraped_at = apply_public_job_visibility(corpus_query).one()
    return f"{int(count or 0)}:{int(max_id or 0)}:{max_scraped_at or ''}"


def sector_filter_condition(selected_sector: str):
    selected = selected_sector.strip()
    if selected == UNCLASSIFIED_SECTOR:
        return or_(ScrapedJob.sector.is_(None), ScrapedJob.sector == "")
    return ScrapedJob.sector == selected


_SSIC_SECTION_LETTER_PREFIX_RE = re.compile(r"^[A-U]\s+(?=[A-Z])")


def sector_label(sector: str | None) -> str:
    cleaned = (sector or "").strip()
    if not cleaned:
        return UNCLASSIFIED_SECTOR
    return _SSIC_SECTION_LETTER_PREFIX_RE.sub("", cleaned) or UNCLASSIFIED_SECTOR


def source_label(source: str | None) -> str:
    return (source or "").strip() or "Unknown"


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


def apply_expired_job_visibility(query):
    """Return only jobs with evidence that they are no longer active."""
    today = datetime.now(timezone.utc).date().isoformat()
    return query.filter(
        or_(
            and_(
                ScrapedJob.hidden == 1,
                ScrapedJob.retirement_reason.in_(KNOWN_RETIREMENT_REASONS),
            ),
            and_(
                ScrapedJob.hidden == 0,
                ScrapedJob.closing_date.isnot(None),
                ScrapedJob.closing_date != "",
                ScrapedJob.closing_date < today,
            ),
        )
    )


# MyCareersFuture and Careers@Gov seniority labels, grouped so a candidate can be
# kept away from tiers below their own. 42% of the live corpus sits in the junior
# tier, which is why an experienced candidate otherwise gets shown traineeships.
JUNIOR_SENIORITY_LABELS = frozenset({
    "fresh/entry level", "entry level", "junior executive", "non-executive",
    "intern", "internship", "traineeship", "student",
})
# Titles carry it even when the seniority column does not.
_JUNIOR_TITLE = re.compile(
    r"\b(intern|internship|trainee|traineeship|apprentice|fresh\s*grad\w*|entry[-\s]?level)\b",
    re.IGNORECASE,
)


# Employers self-report seniority and often get it wrong: the corpus holds
# "Non-executive" roles paying $18,000. Junior tiers sit at a $3,600-3,800 p90
# and Executive at $5,000, so pay at or above this contradicts a junior label
# outright, and the pay is the more honest signal.
JUNIOR_LABEL_SALARY_CEILING = 5000


def is_junior_posting(
    seniority: str | None,
    title: str | None,
    salary_floor: int | float | None = None,
) -> bool:
    """True when a posting is genuinely pitched below an experienced hire.

    Salary overrules the label. Dropping a $12,500 project manager because its
    employer ticked "Non-executive" costs the candidate more than showing it.
    """
    looks_junior = (
        (seniority or "").strip().lower() in JUNIOR_SENIORITY_LABELS
        or bool(_JUNIOR_TITLE.search(title or ""))
    )
    if not looks_junior:
        return False
    if salary_floor and salary_floor >= JUNIOR_LABEL_SALARY_CEILING:
        return False
    return True
