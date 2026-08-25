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
SINGAPORE_JOB_LOCATIONS = frozenset({
    "singapore",
    "central",
    "islandwide",
    "west",
    "north",
    "east",
    "north-east",
})
# Some source rows claim a Singapore region while the title states the actual
# overseas work site. These are the unambiguous overseas place names currently
# observed in that title pattern; ordinary mentions of overseas customers or
# travel in descriptions are deliberately ignored.
_OVERSEAS_TITLE_LOCATION = re.compile(
    r"\b(?:based|located|stationed)\s+in\s+(?:"
    r"indonesia|hong\s+kong|bangkok|kuala\s+lumpur|kl|malaysia|batam|jb|"
    r"china|shanghai|vietnam|thailand|india|south\s+korea|korea|philippines|"
    r"taiwan|cyprus|saudi\s+arabia|united\s+arab\s+emirates|uae|myanmar"
    r")\b",
    re.IGNORECASE,
)


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


def apply_public_job_visibility(
    query,
    include_old: bool = False,
    *,
    now: datetime | None = None,
):
    query = query.filter(ScrapedJob.hidden == 0)
    if include_old:
        return query
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    today = reference.date().isoformat()
    return query.filter(
        ScrapedJob.posted_at_sort.isnot(None),
        ScrapedJob.posted_at_sort != "",
        ScrapedJob.posted_at_sort >= public_job_cutoff_iso(now=reference),
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


def is_singapore_job_location(location: str | None, title: str | None = None) -> bool:
    """Return whether structured and explicit title evidence point to Singapore."""
    return (
        (location or "").strip().casefold() in SINGAPORE_JOB_LOCATIONS
        and not _OVERSEAS_TITLE_LOCATION.search(title or "")
    )


def singapore_job_prefilter_condition(location_column):
    """Portable SQL prefilter; Python verifies title evidence after loading."""
    return func.lower(func.trim(func.coalesce(location_column, ""))).in_(
        SINGAPORE_JOB_LOCATIONS
    )


def job_title_matches(title: str | None, phrase: str | None) -> bool:
    """Match a caller-supplied title phrase on normalized whole words."""
    wanted = " ".join(re.findall(r"[a-z0-9]+", (phrase or "").casefold()))
    actual = " ".join(re.findall(r"[a-z0-9]+", (title or "").casefold()))
    return bool(wanted) and f" {wanted} " in f" {actual} "


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
EXPERIENCED_TITLE_PATTERN = (
    r"(^|[^a-z])(?:assistant\s+manager|manager|senior|staff|lead|principal|"
    r"director|head|vice\s+president)([^a-z]|$)"
)
_EXPERIENCED_TITLE = re.compile(EXPERIENCED_TITLE_PATTERN, re.IGNORECASE)


def is_junior_posting(
    seniority: str | None,
    title: str | None,
    salary_floor: int | float | None = None,
) -> bool:
    """Return explicit source or title evidence that a posting is junior.

    ``salary_floor`` remains accepted because callers share one job-classifier
    signature, but salary must not silently reverse an explicit eligibility
    constraint.
    """
    del salary_floor
    level = (seniority or "").strip().lower()
    if level in JUNIOR_SENIORITY_LABELS or _JUNIOR_TITLE.search(title or ""):
        return True
    return level == "executive" and not _EXPERIENCED_TITLE.search(title or "")


def experienced_hire_prefilter_condition(seniority_column, title_column):
    """Portable SQL prefilter; Python verifies title evidence after loading."""
    seniority = func.lower(func.coalesce(seniority_column, ""))
    experienced_title = func.lower(func.coalesce(title_column, "")).regexp_match(
        EXPERIENCED_TITLE_PATTERN
    )
    return and_(
        ~seniority.in_(JUNIOR_SENIORITY_LABELS),
        or_(seniority != "executive", experienced_title),
    )
