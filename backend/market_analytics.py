"""Public job-market analytics routes and their cache-backed read model."""

from __future__ import annotations

import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Callable

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import or_
from sqlalchemy.orm import Session, load_only

import config as app_config
from database import get_db
from employer_filter import (
    employer_relationship_eligibility_condition,
    get_employer_relationship_readiness,
)
from job_precompute import salary_bounds_from_text as _salary_bounds_from_text
from job_visibility import (
    job_corpus_marker as _job_corpus_marker,
    sector_filter_condition as _sector_filter_condition,
    sector_label as _analytics_sector_label,
    source_label as _analytics_source_label,
)
from models import ScrapedJob
from security import (
    FixedWindowRateLimiter,
    contains_like_pattern as _contains_like_pattern,
    get_client_ip as _get_client_ip,
    split_multi_value_filter as _split_multi_value_filter,
)

router = APIRouter()

_ANALYTICS_CACHE_TTL = app_config.ANALYTICS_CACHE_TTL_SECONDS
_ANALYTICS_QUERY_CACHE_TTL = app_config.ANALYTICS_QUERY_CACHE_TTL_SECONDS
_ANALYTICS_QUERY_CACHE_MAX = app_config.ANALYTICS_QUERY_CACHE_MAX
_ANALYTICS_MAX_ROWS = app_config.ANALYTICS_MAX_ROWS
_ANALYTICS_YIELD_PER = app_config.ANALYTICS_YIELD_PER
_ANALYTICS_SALARY_BUCKET_MIN_ROLES = 5
_ANALYTICS_OVERINDEX_MIN_TOTAL = 20
_ANALYTICS_OVERINDEX_MIN_BASELINE_COUNT = 10
_ANALYTICS_OVERINDEX_MIN_SHARE = 0.015
_ANALYTICS_OVERINDEX_LIFT_THRESHOLD = 1.35
_ANALYTICS_OVERINDEX_LIMIT = 10
_ANALYTICS_MARKET_WINDOW_DAYS = 30
_ANALYTICS_MARKET_MIN_TOTAL = 50
_ANALYTICS_MARKET_MIN_COUNT = 5
_ANALYTICS_MARKET_RECENT_MIN_SHARE = 0.01
_ANALYTICS_MARKET_OLDER_MIN_SHARE = 0.005
_ANALYTICS_MARKET_LIFT_THRESHOLD = 1.35
_ANALYTICS_MARKET_COOLING_MIN_RECENT_COUNT = 2
_ANALYTICS_MARKET_MOVER_LIMIT = 8
_ANALYTICS_LABEL_MOVER_MIN_COUNT = 3
_ANALYTICS_LABEL_MOVER_MIN_SHARE = 0.002

_analytics_cache: dict | None = None
_analytics_cache_ts: float = 0
_analytics_query_cache: dict[tuple, tuple[float, dict]] = {}
_ANALYTICS_CACHE_LOCK = threading.Lock()
_ANALYTICS_COMPUTE_SLOTS = threading.BoundedSemaphore(2)
_analytics_cache_generation = 0
_PUBLIC_RATE_LIMITER = FixedWindowRateLimiter()


def invalidate() -> None:
    """Invalidate every market-analytics cache after the job corpus changes."""
    global _analytics_cache, _analytics_cache_ts, _analytics_cache_generation
    with _ANALYTICS_CACHE_LOCK:
        _analytics_cache = None
        _analytics_cache_ts = 0
        _analytics_query_cache.clear()
        _analytics_cache_generation += 1


def _store_analytics_query_cache(cache_key: tuple, cache_ts: float, result: dict, generation: int) -> None:
    with _ANALYTICS_CACHE_LOCK:
        if generation != _analytics_cache_generation:
            return
        expired_keys = [
            key
            for key, (stored_ts, _) in _analytics_query_cache.items()
            if cache_ts - stored_ts >= _ANALYTICS_QUERY_CACHE_TTL
        ]
        for key in expired_keys:
            _analytics_query_cache.pop(key, None)
        if len(_analytics_query_cache) >= _ANALYTICS_QUERY_CACHE_MAX:
            oldest_key = min(_analytics_query_cache, key=lambda key: _analytics_query_cache[key][0])
            _analytics_query_cache.pop(oldest_key, None)
        _analytics_query_cache[cache_key] = (cache_ts, result)


def _admit_analytics_request():
    if not _ANALYTICS_COMPUTE_SLOTS.acquire(blocking=False):
        raise HTTPException(
            status_code=503,
            detail="Analytics is busy. Try again shortly.",
            headers={"Retry-After": "2"},
        )
    try:
        yield
    finally:
        _ANALYTICS_COMPUTE_SLOTS.release()


_ANALYTICS_SKILL_ALIASES = {
    "excel": "microsoft excel",
    "ms excel": "microsoft excel",
    "microsoft excel": "microsoft excel",
    "word": "microsoft word",
    "ms word": "microsoft word",
    "microsoft word": "microsoft word",
    "powerpoint": "microsoft powerpoint",
    "ms powerpoint": "microsoft powerpoint",
    "microsoft powerpoint": "microsoft powerpoint",
    "aws": "aws",
    "amazon web services": "aws",
    "gcp": "gcp",
    "google cloud": "gcp",
    "google cloud platform": "gcp",
    "azure": "microsoft azure",
    "microsoft azure": "microsoft azure",
    "power bi": "power bi",
    "microsoft power bi": "power bi",
    "javascript": "javascript",
    "java script": "javascript",
    "typescript": "typescript",
    "node": "node.js",
    "nodejs": "node.js",
    "node.js": "node.js",
    "reactjs": "react",
    "react.js": "react",
    "react": "react",
    "ui ux": "ui/ux",
    "ui/ux": "ui/ux",
}

_ANALYTICS_SKILL_DISPLAY = {
    "aws": "AWS",
    "gcp": "GCP",
    "sql": "SQL",
    "ai": "AI",
    "api": "API",
    "apis": "APIs",
    "ui/ux": "UI/UX",
    "power bi": "Power BI",
    "node.js": "Node.js",
    "javascript": "JavaScript",
    "typescript": "TypeScript",
    "microsoft azure": "Microsoft Azure",
    "microsoft excel": "Microsoft Excel",
    "microsoft word": "Microsoft Word",
    "microsoft powerpoint": "Microsoft PowerPoint",
}

_ANALYTICS_GENERIC_SKILLS = {
    "customer service",
    "communication skills",
    "leadership",
    "problem solving",
    "teamwork",
    "interpersonal skills",
    "customer satisfaction",
    "customer experience",
    "administrative support",
    "administrative work",
    "data entry",
    "driving license",
    "microsoft office",
    "microsoft word",
    "microsoft powerpoint",
    "time management",
    "attention to detail",
    "written communication",
    "verbal communication",
    "cross-functional teams",
    "continuous improvement",
    "communication",
    "critical thinking",
    "decision making",
    "emotional intelligence",
    "learning & putting skills",
    "improving & innovating",
    "passion for sport",
    "centre of excellence",
}

_ANALYTICS_EXCLUDED_SKILLS = {
    "express",
    "government technology",
    "insolvency & public trustee",
    "ministry of home affairs",
}

_ANALYTICS_EXCLUDED_SKILL_PATTERNS = (
    re.compile(r"\bministry of\b", re.IGNORECASE),
    re.compile(r"\bpublic trustee\b", re.IGNORECASE),
    re.compile(r"\bgovernment technology\b", re.IGNORECASE),
    re.compile(r"\bcentre of excellence\b", re.IGNORECASE),
    re.compile(r"\bpassion for\b", re.IGNORECASE),
    re.compile(r"\blearning\s*&\s*putting skills\b", re.IGNORECASE),
    re.compile(r"\bimproving\s*&\s*innovating\b", re.IGNORECASE),
)

_ANALYTICS_GENERIC_COMPANY_NAMES = {
    "singapore public service",
}

_CAREERSGOV_AGENCY_ALIASES = {
    "AGC": "Attorney-General's Chambers",
    "AIC": "Agency for Integrated Care",
    "A*STAR": "Agency for Science, Technology and Research",
    "ASTAR": "Agency for Science, Technology and Research",
    "BCA": "Building and Construction Authority",
    "CAA": "Civil Aviation Authority of Singapore",
    "CDA": "Communicable Diseases Agency",
    "CPF": "Central Provident Fund Board",
    "ECDA": "Early Childhood Development Agency",
    "EDB": "Economic Development Board",
    "ESG": "Enterprise Singapore",
    "GOVTECH": "Government Technology Agency",
    "HDB": "Housing & Development Board",
    "HSA": "Health Sciences Authority",
    "HTX": "Home Team Science and Technology Agency",
    "IMD": "Infocomm Media Development Authority",
    "IMDA": "Infocomm Media Development Authority",
    "LTA": "Land Transport Authority",
    "MAS": "Monetary Authority of Singapore",
    "MCCY": "Ministry of Culture, Community and Youth",
    "MDDI": "Ministry of Digital Development and Information",
    "MFA": "Ministry of Foreign Affairs",
    "MHA": "Ministry of Home Affairs",
    "MINDEF": "Ministry of Defence",
    "MINLAW": "Ministry of Law",
    "MND": "Ministry of National Development",
    "MOE": "Ministry of Education",
    "MOF": "Ministry of Finance",
    "MOH": "Ministry of Health",
    "MOM": "Ministry of Manpower",
    "MOT": "Ministry of Transport",
    "MPA": "Maritime and Port Authority of Singapore",
    "MSF": "Ministry of Social and Family Development",
    "MTI": "Ministry of Trade and Industry",
    "NAC": "National Arts Council",
    "NEA": "National Environment Agency",
    "NLB": "National Library Board",
    "NPARKS": "National Parks Board",
    "PA": "People's Association",
    "PAS": "People's Association",
    "PUB": "PUB, Singapore's National Water Agency",
    "SCB": "Science Centre Board",
    "SLA": "Singapore Land Authority",
    "SSG": "SkillsFuture Singapore",
    "URA": "Urban Redevelopment Authority",
}

_CAREERSGOV_AGENCY_LABEL_TO_CODES: dict[str, list[str]] = {}

for _agency_code, _agency_label in _CAREERSGOV_AGENCY_ALIASES.items():
    _CAREERSGOV_AGENCY_LABEL_TO_CODES.setdefault(_agency_label.lower(), []).append(_agency_code)

_CAREERSGOV_BRACKET_CODE_RE = re.compile(r"^\[([A-Z][A-Z0-9*]{1,8})(?:[-\]/\s]|$)")

_CAREERSGOV_MINISTRY_RE = re.compile(r"\b(Ministry of [A-Za-z][A-Za-z &]+)")

_CAREERSGOV_MINISTRY_PHRASE_ALIASES = {
    "ministry of social and family": "Ministry of Social and Family Development",
}

_ANALYTICS_AGENCY_SUBSETS = {
    "public_sector": {
        "label": "Public sector",
        "terms": ["Careers@Gov", "Singapore Public Service"],
    },
    "ministries": {
        "label": "Ministries",
        "terms": [
            "Ministry of",
            "MCCY",
            "MDDI",
            "MFA",
            "MHA",
            "MINDEF",
            "MINLAW",
            "MND",
            "MOE",
            "MOF",
            "MOH",
            "MOM",
            "MOT",
            "MSF",
            "MTI",
            *[label for label in _CAREERSGOV_AGENCY_ALIASES.values() if label.startswith("Ministry of ")],
        ],
    },
    "stat_boards": {
        "label": "Stat boards",
        "terms": [
            "AIC",
            "AGC",
            "A*STAR",
            "ASTAR",
            "BCA",
            "CAA",
            "CDA",
            "CPF",
            "ECDA",
            "EDB",
            "ESG",
            "GOVTECH",
            "HDB",
            "HSA",
            "HTX",
            "IMD",
            "IMDA",
            "LTA",
            "MAS",
            "MPA",
            "NAC",
            "NEA",
            "NLB",
            "NPARKS",
            "PA",
            "PAS",
            "PUB",
            "SCB",
            "SLA",
            "SSG",
            "URA",
            *[label for label in _CAREERSGOV_AGENCY_ALIASES.values() if not label.startswith("Ministry of ")],
        ],
    },
    "digital_gov": {
        "label": "Digital Gov",
        "terms": [
            "GOVTECH",
            "Government Technology Agency",
            "IMD",
            "IMDA",
            "Infocomm Media Development Authority",
            "MDDI",
            "Ministry of Digital Development and Information",
            "HTX",
            "Home Team Science and Technology Agency",
        ],
    },
    "defence_home": {
        "label": "Defence / Home Team",
        "terms": [
            "MINDEF",
            "Ministry of Defence",
            "MHA",
            "Ministry of Home Affairs",
            "HTX",
            "Home Team Science and Technology Agency",
        ],
    },
    "transport": {
        "label": "Transport",
        "terms": [
            "MOT",
            "Ministry of Transport",
            "LTA",
            "Land Transport Authority",
            "MPA",
            "Maritime and Port Authority of Singapore",
            "CAA",
            "Civil Aviation Authority of Singapore",
        ],
    },
    "education_research": {
        "label": "Education / Research",
        "terms": [
            "MOE",
            "Ministry of Education",
            "A*STAR",
            "ASTAR",
            "Agency for Science, Technology and Research",
            "ECDA",
            "Early Childhood Development Agency",
            "SSG",
            "SkillsFuture Singapore",
            "SCB",
            "Science Centre Board",
            "NLB",
            "National Library Board",
        ],
    },
    "healthcare": {
        "label": "Healthcare",
        "terms": [
            "MOH",
            "Ministry of Health",
            "HSA",
            "Health Sciences Authority",
            "CDA",
            "Communicable Diseases Agency",
            "AIC",
            "Agency for Integrated Care",
        ],
    },
}


def _normalize_title(raw_title: str) -> str:
    """Normalize a job title for grouping (strip seniority prefixes, title case)."""
    import re

    t = raw_title.strip()
    t = re.sub(
        r"^(Senior|Junior|Jr\.?|Sr\.?|Lead|Principal|Staff|Chief|Head of|"
        r"Associate|Assistant|Intern\b)[,\s]+",
        "",
        t,
        flags=re.IGNORECASE,
    ).strip()
    t = re.sub(r"\s+", " ", t)
    # Title case normalization (fix "PROJECT ENGINEER" -> "Project Engineer")
    _SMALL_WORDS = {"a", "an", "and", "as", "at", "by", "for", "from", "in", "of", "on", "or", "the", "to", "with"}
    if t == t.upper() or t == t.lower():
        words = t.split()
        t = " ".join(w.lower() if w.lower() in _SMALL_WORDS and i > 0 else w.capitalize() for i, w in enumerate(words))
    return t


def _analytics_skill_key(raw: str) -> str:
    key = re.sub(r"\s+", " ", (raw or "").strip().lower())
    key = key.strip(" -•.,;:")
    key = _ANALYTICS_SKILL_ALIASES.get(key, key)
    if key in _ANALYTICS_EXCLUDED_SKILLS or any(pattern.search(key) for pattern in _ANALYTICS_EXCLUDED_SKILL_PATTERNS):
        return ""
    return key


def _analytics_skill_display(key: str) -> str:
    if key in _ANALYTICS_SKILL_DISPLAY:
        return _ANALYTICS_SKILL_DISPLAY[key]
    return key.title()


def _is_generic_analytics_skill(key: str) -> bool:
    return key in _ANALYTICS_GENERIC_SKILLS


def _display_ministry_name(raw: str) -> str:
    cleaned = re.sub(r"\s+", " ", raw.replace("&", "and")).strip(" ,.-")
    return _CAREERSGOV_MINISTRY_PHRASE_ALIASES.get(cleaned.lower(), cleaned)


def _careersgov_hiring_org(job: ScrapedJob) -> str:
    title = (getattr(job, "title", "") or "").strip()
    agency = (getattr(job, "agency", "") or "").strip()
    haystacks = [agency, title]

    for text in haystacks:
        if not text:
            continue
        bracket = _CAREERSGOV_BRACKET_CODE_RE.search(text)
        if bracket:
            code = bracket.group(1).upper()
            if code in _CAREERSGOV_AGENCY_ALIASES:
                return _CAREERSGOV_AGENCY_ALIASES[code]

    for text in haystacks:
        if not text:
            continue
        for token in re.findall(r"\b[A-Z][A-Z0-9*]{1,8}\b", text.upper()):
            if token in _CAREERSGOV_AGENCY_ALIASES:
                return _CAREERSGOV_AGENCY_ALIASES[token]

    ministry = _CAREERSGOV_MINISTRY_RE.search(title)
    if ministry:
        return _display_ministry_name(ministry.group(1))

    if agency and agency.lower() not in {"singapore", "not available", "n/a"}:
        return agency
    return ""


def _analytics_company_label(job: ScrapedJob) -> str:
    company = (getattr(job, "company", "") or "").strip()
    agency = (getattr(job, "agency", "") or "").strip()
    if company.lower() in _ANALYTICS_GENERIC_COMPANY_NAMES:
        return _careersgov_hiring_org(job)
    if agency and not company:
        return _careersgov_hiring_org(job) or agency
    return company or agency


def _analytics_company_filter_condition(raw_company: str):
    cleaned = (raw_company or "").strip()
    terms = [cleaned]
    terms.extend(_CAREERSGOV_AGENCY_LABEL_TO_CODES.get(cleaned.lower(), []))
    terms = [term for term in _split_multi_value_filter(",".join(terms)) if term]
    if not terms:
        return ScrapedJob.company.ilike("%%")
    return or_(
        *(
            or_(
                ScrapedJob.company.ilike(_contains_like_pattern(term), escape="\\"),
                ScrapedJob.agency.ilike(_contains_like_pattern(term), escape="\\"),
                ScrapedJob.title.ilike(_contains_like_pattern(term), escape="\\"),
            )
            for term in terms
        )
    )


def _normalise_agency_subset_id(value: str | None) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    return key if key in _ANALYTICS_AGENCY_SUBSETS else ""


def _analytics_agency_subset_options() -> list[dict]:
    return [{"id": subset_id, "label": meta["label"]} for subset_id, meta in _ANALYTICS_AGENCY_SUBSETS.items()]


def _is_agency_code_term(term: str) -> bool:
    return bool(re.fullmatch(r"[A-Z][A-Z0-9*]{1,8}", term or ""))


def _agency_term_condition(term: str):
    if _is_agency_code_term(term):
        return or_(
            ScrapedJob.agency.ilike(f"{term}%"),
            ScrapedJob.agency.ilike(f"% {term}%"),
            ScrapedJob.title.ilike(f"%[{term}%"),
            ScrapedJob.title.ilike(f"% {term} %"),
        )
    return or_(
        ScrapedJob.company.ilike(f"%{term}%"),
        ScrapedJob.agency.ilike(f"%{term}%"),
        ScrapedJob.title.ilike(f"%{term}%"),
        ScrapedJob.source.ilike(f"%{term}%"),
    )


def _analytics_agency_subset_condition(subset_id: str):
    subset_key = _normalise_agency_subset_id(subset_id)
    if not subset_key:
        return ScrapedJob.company.ilike("%%")

    terms = []
    seen = set()
    for raw in _ANALYTICS_AGENCY_SUBSETS[subset_key]["terms"]:
        term = str(raw or "").strip()
        key = term.lower()
        if term and key not in seen:
            seen.add(key)
            terms.append(term)

    conditions = []
    if subset_key == "public_sector":
        conditions.append(ScrapedJob.source.ilike("%Careers@Gov%"))
    for term in terms:
        conditions.append(_agency_term_condition(term))
    return or_(*conditions) if conditions else ScrapedJob.company.ilike("%%")


def _apply_market_filters(
    query,
    *,
    source: str | None,
    company: str | None,
    title: str | None,
    sector: str | None,
    agency_subset: str,
    direct_employers_only: bool,
):
    """Apply the filters shared by the analytics snapshot and trend views."""
    if source:
        query = query.filter(ScrapedJob.source == source)
    if company:
        query = query.filter(_analytics_company_filter_condition(company))
    if title:
        query = query.filter(ScrapedJob.title.ilike(_contains_like_pattern(title), escape="\\"))
    if sector:
        query = query.filter(_sector_filter_condition(sector))
    if agency_subset:
        query = query.filter(_analytics_agency_subset_condition(agency_subset))
    if direct_employers_only:
        query = query.filter(
            employer_relationship_eligibility_condition(
                ScrapedJob.employer_relationship,
                ScrapedJob.employer_relationship_evidence,
                ScrapedJob.company,
            )
        )
    return query


def _agency_term_matches(text: str, term: str) -> bool:
    cleaned = str(term or "").strip()
    if not cleaned:
        return False
    if _is_agency_code_term(cleaned):
        return bool(re.search(rf"(^|[^A-Z0-9*]){re.escape(cleaned)}([^A-Z0-9*]|$)", text.upper()))
    return cleaned.lower() in text.lower()


def _analytics_job_matches_agency_subset(job: ScrapedJob, subset_id: str) -> bool:
    subset_key = _normalise_agency_subset_id(subset_id)
    if not subset_key:
        return False
    haystack = " ".join(
        str(value or "")
        for value in (
            getattr(job, "source", ""),
            getattr(job, "company", ""),
            getattr(job, "agency", ""),
            getattr(job, "title", ""),
            _analytics_company_label(job),
        )
    )
    return any(
        _agency_term_matches(haystack, str(term or "")) for term in _ANALYTICS_AGENCY_SUBSETS[subset_key]["terms"]
    )


def _analytics_seniority_label(job: ScrapedJob) -> str:
    text = f"{job.seniority or ''} {job.title or ''}".lower()
    if "intern" in text:
        return "Intern"
    if any(term in text for term in {"assistant director", "associate director", "deputy director"}):
        return "Manager / Lead"
    if any(term in text for term in {"vice president", "vp", "director", "head of", "chief"}):
        return "Leadership"
    if any(term in text for term in {"manager", "lead", "principal", "staff"}):
        return "Manager / Lead"
    if "senior" in text:
        return "Senior IC"
    if any(term in text for term in {"entry", "fresh", "junior", "assistant", "associate"}):
        return "Entry / Junior"
    return "Mid / Unspecified"


def _parse_posted_sort(value: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _trend_bucket_start(posted_at: datetime, bucket: str) -> datetime:
    if bucket == "month":
        return posted_at.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    start = posted_at - timedelta(days=posted_at.weekday())
    return start.replace(hour=0, minute=0, second=0, microsecond=0)


def _trend_bucket_label(start: datetime, bucket: str) -> str:
    if bucket == "month":
        return start.strftime("%b %Y")
    year, week, _weekday = start.isocalendar()
    return f"{year} W{week:02d}"


def _trend_bucket_series(cutoff: datetime, now: datetime, bucket: str) -> list[datetime]:
    current = _trend_bucket_start(cutoff, bucket)
    end = _trend_bucket_start(now, bucket)
    starts = []
    while current <= end:
        starts.append(current)
        if bucket == "month":
            year = current.year + (1 if current.month == 12 else 0)
            month = 1 if current.month == 12 else current.month + 1
            current = current.replace(year=year, month=month)
        else:
            current += timedelta(days=7)
    return starts


def _percentile(sorted_values: list[int], percentile: float) -> int:
    if not sorted_values:
        return 0
    index = min(len(sorted_values) - 1, max(0, round((len(sorted_values) - 1) * percentile)))
    return int(sorted_values[index])


def _salary_bucket(
    items: dict[str, list[int]],
    label_key: str,
    midpoint_items: dict[str, list[int]] | None = None,
    ceiling_items: dict[str, list[int]] | None = None,
) -> list[dict]:
    rows = []
    for label, values in items.items():
        if len(values) < _ANALYTICS_SALARY_BUCKET_MIN_ROLES:
            continue
        sorted_values = sorted(values)
        midpoint_values = sorted((midpoint_items or {}).get(label, []))
        ceiling_values = sorted((ceiling_items or {}).get(label, []))
        row = {
            label_key: label,
            "count": len(sorted_values),
            "median_floor": _percentile(sorted_values, 0.5),
            "p75_floor": _percentile(sorted_values, 0.75),
        }
        if midpoint_values:
            row["median_midpoint"] = _percentile(midpoint_values, 0.5)
        if ceiling_values:
            row["median_ceiling"] = _percentile(ceiling_values, 0.5)
        rows.append(row)
    return sorted(rows, key=lambda item: (-item["count"], -item["median_floor"]))[:8]


def _increment_analytics_skill(bucket: dict[str, dict], key: str) -> None:
    if key not in bucket:
        bucket[key] = {"display": _analytics_skill_display(key), "count": 0}
    bucket[key]["count"] += 1


def _increment_label_count(bucket: dict[str, dict], key: str, display: str) -> None:
    if not key:
        return
    if key not in bucket:
        bucket[key] = {"display": display, "count": 0}
    bucket[key]["count"] += 1


def _build_overindexed_skills(
    current_counts: dict[str, dict],
    current_total: int,
    baseline_counts: dict[str, int] | None,
    baseline_total: int,
) -> list[dict]:
    if not baseline_counts or current_total < _ANALYTICS_OVERINDEX_MIN_TOTAL or baseline_total <= 0:
        return []
    minimum_count = max(
        _ANALYTICS_MARKET_MIN_COUNT,
        round(current_total * _ANALYTICS_OVERINDEX_MIN_SHARE),
    )
    rows = []
    for key, item in current_counts.items():
        count = int(item["count"])
        baseline_count = int(baseline_counts.get(key, 0))
        if (
            count < minimum_count
            or baseline_count < _ANALYTICS_OVERINDEX_MIN_BASELINE_COUNT
            or _is_generic_analytics_skill(key)
        ):
            continue
        current_rate = count / current_total
        baseline_rate = baseline_count / baseline_total
        if baseline_rate <= 0:
            continue
        lift = current_rate / baseline_rate
        if lift < _ANALYTICS_OVERINDEX_LIFT_THRESHOLD:
            continue
        rows.append(
            {
                "skill": item["display"],
                "count": count,
                "lift": round(lift, 1),
                "rate_percent": round(current_rate * 100, 1),
                "market_rate_percent": round(baseline_rate * 100, 1),
            }
        )
    return sorted(rows, key=lambda item: (-item["lift"], -item["count"]))[:_ANALYTICS_OVERINDEX_LIMIT]


def _build_label_movers(
    recent_counts: dict[str, dict],
    recent_total: int,
    older_counts: dict[str, dict],
    older_total: int,
    label_key: str,
    *,
    min_count: int = _ANALYTICS_LABEL_MOVER_MIN_COUNT,
    recent_min_share: float = _ANALYTICS_LABEL_MOVER_MIN_SHARE,
    older_min_share: float = _ANALYTICS_LABEL_MOVER_MIN_SHARE,
    skip: Callable[[str], bool] | None = None,
    display_fallback: Callable[[str], str] = str.title,
    sparse_note: str = "Needs enough dated postings to compare recent hiring against older hiring.",
) -> dict:
    if recent_total < _ANALYTICS_MARKET_MIN_TOTAL or older_total < _ANALYTICS_MARKET_MIN_TOTAL:
        return {
            "window_days": _ANALYTICS_MARKET_WINDOW_DAYS,
            "recent_total": recent_total,
            "older_total": older_total,
            "rising": [],
            "cooling": [],
            "note": sparse_note,
        }

    minimum_recent = max(min_count, round(recent_total * recent_min_share))
    minimum_older = max(min_count, round(older_total * older_min_share))
    rising = []
    cooling = []

    for key in set(recent_counts) | set(older_counts):
        if skip is not None and skip(key):
            continue
        recent_count = int(recent_counts.get(key, {}).get("count", 0))
        older_count = int(older_counts.get(key, {}).get("count", 0))
        recent_rate = recent_count / recent_total if recent_total else 0
        older_rate = older_count / older_total if older_total else 0
        display = (
            recent_counts.get(key, {}).get("display")
            or older_counts.get(key, {}).get("display")
            or display_fallback(key)
        )

        if recent_count >= minimum_recent and older_count >= minimum_older and older_rate > 0:
            lift = recent_rate / older_rate
            if lift >= _ANALYTICS_MARKET_LIFT_THRESHOLD:
                rising.append(
                    {
                        label_key: display,
                        "recent_count": recent_count,
                        "older_count": older_count,
                        "lift": round(lift, 1),
                        "recent_rate_percent": round(recent_rate * 100, 1),
                        "older_rate_percent": round(older_rate * 100, 1),
                    }
                )

        if (
            older_count >= minimum_older
            and recent_count >= _ANALYTICS_MARKET_COOLING_MIN_RECENT_COUNT
            and recent_rate > 0
        ):
            drop = older_rate / recent_rate
            if drop >= _ANALYTICS_MARKET_LIFT_THRESHOLD:
                cooling.append(
                    {
                        label_key: display,
                        "recent_count": recent_count,
                        "older_count": older_count,
                        "drop": round(drop, 1),
                        "recent_rate_percent": round(recent_rate * 100, 1),
                        "older_rate_percent": round(older_rate * 100, 1),
                    }
                )

    return {
        "window_days": _ANALYTICS_MARKET_WINDOW_DAYS,
        "recent_total": recent_total,
        "older_total": older_total,
        "rising": sorted(rising, key=lambda item: (-item["lift"], -item["recent_count"]))[
            :_ANALYTICS_MARKET_MOVER_LIMIT
        ],
        "cooling": sorted(cooling, key=lambda item: (-item["drop"], -item["older_count"]))[
            :_ANALYTICS_MARKET_MOVER_LIMIT
        ],
        "note": f"Compares dated postings from the last {_ANALYTICS_MARKET_WINDOW_DAYS} days against older dated postings in the current corpus.",
    }


def _build_market_movers(
    recent_counts: dict[str, dict],
    recent_total: int,
    older_counts: dict[str, dict],
    older_total: int,
) -> dict:
    return _build_label_movers(
        recent_counts,
        recent_total,
        older_counts,
        older_total,
        "skill",
        min_count=_ANALYTICS_MARKET_MIN_COUNT,
        recent_min_share=_ANALYTICS_MARKET_RECENT_MIN_SHARE,
        older_min_share=_ANALYTICS_MARKET_OLDER_MIN_SHARE,
        skip=_is_generic_analytics_skill,
        display_fallback=_analytics_skill_display,
        sparse_note="Needs enough dated postings to compare recent demand against older demand.",
    )


@router.get("/api/analytics/skills")
def analytics_skills(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    source: str | None = Query(None, max_length=50),
    q: str | None = Query(None, max_length=100),
    sector: str | None = Query(None, max_length=100),
    company: str | None = Query(None, max_length=200),
    title: str | None = Query(None, max_length=200),
    agency_subset: str | None = Query(None, max_length=50),
    direct_employers_only: bool = Query(False),
    db: Session = Depends(get_db),
    _admission: None = Depends(_admit_analytics_request),
) -> dict:
    """Aggregate ATS skill demand, top titles, and sectors from scraped jobs."""
    global _analytics_cache, _analytics_cache_ts

    if not _PUBLIC_RATE_LIMITER.allow(
        f"analytics-skills:{_get_client_ip(request)}",
        limit=30,
        window_seconds=60,
    ):
        raise HTTPException(status_code=429, detail="Too many analytics requests")
    if direct_employers_only and not get_employer_relationship_readiness(db)["ready"]:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "employer_index_unavailable",
                "message": "The employer classification index is rebuilding. Please retry shortly.",
            },
        )

    agency_subset_key = _normalise_agency_subset_id(agency_subset)
    has_filter = source or sector or company or title or agency_subset_key or direct_employers_only
    now = time.time()
    corpus_marker = _job_corpus_marker(db)
    query_cache_key = (
        corpus_marker,
        limit,
        source or "",
        q or "",
        sector or "",
        company or "",
        title or "",
        agency_subset_key,
        int(direct_employers_only),
    )
    with _ANALYTICS_CACHE_LOCK:
        cache_generation = _analytics_cache_generation
        cached_query = _analytics_query_cache.get(query_cache_key)
        if cached_query and now - cached_query[0] < _ANALYTICS_QUERY_CACHE_TTL:
            return cached_query[1]

        cached = (
            _analytics_cache
            if not has_filter
            and _analytics_cache is not None
            and _analytics_cache.get("_corpus_marker") == corpus_marker
            and now - _analytics_cache_ts < _ANALYTICS_CACHE_TTL
            else None
        )

    if cached is not None:
        all_skills = cached["_all_skills"]
        if q:
            q_lower = q.lower()
            all_skills = [s for s in all_skills if q_lower in s["skill"].lower()]
        result = {
            "top_skills": all_skills[:limit],
            "total_jobs_with_terms": cached["total_jobs_with_terms"],
            "skill_signal_count": cached.get("skill_signal_count", len(cached.get("_all_skills", []))),
            "company_count": cached.get("company_count", len(cached.get("top_companies", []))),
            "title_count": cached.get("title_count", len(cached.get("top_titles", []))),
            "sector_count": cached.get("sector_count", len(cached.get("sectors", []))),
            "sources": cached["sources"],
            "top_titles": cached["top_titles"],
            "sectors": cached["sectors"],
            "top_companies": cached.get("top_companies", []),
            "hard_skills": cached.get("hard_skills", []),
            "overindexed_skills": cached.get("overindexed_skills", []),
            "market_movers": cached.get("market_movers", {}),
            "company_movers": cached.get("company_movers", {}),
            "salary_insights": cached.get("salary_insights", {}),
            "freshness": cached.get("freshness", {}),
            "sampled_jobs": cached.get("sampled_jobs", cached["total_jobs_with_terms"]),
            "sampled_job_limit": cached.get("sampled_job_limit", _ANALYTICS_MAX_ROWS),
            "partial": cached.get("partial", False),
            "seniority_mix": cached.get("seniority_mix", []),
            "ssic_coverage": cached.get("ssic_coverage", {}),
            "sector_source_mix": cached.get("sector_source_mix", []),
            "agency_subsets": cached.get("agency_subsets", _analytics_agency_subset_options()),
            "agency_subset": agency_subset_key,
            "direct_employers_only": direct_employers_only,
        }
        _store_analytics_query_cache(query_cache_key, now, result, cache_generation)
        return result

    baseline_counts: dict[str, int] | None = None
    baseline_total = 0
    with _ANALYTICS_CACHE_LOCK:
        if _analytics_cache is not None and now - _analytics_cache_ts < _ANALYTICS_CACHE_TTL:
            baseline_counts = _analytics_cache.get("_skill_counts")
            baseline_total = int(_analytics_cache.get("total_jobs_with_terms", 0) or 0)
    baseline_ready = bool(baseline_counts and baseline_total > 0)

    db_query = (
        db.query(ScrapedJob)
        .options(
            load_only(
                ScrapedJob.id,
                ScrapedJob.job_terms_preview,
                ScrapedJob.source,
                ScrapedJob.title,
                ScrapedJob.company,
                ScrapedJob.agency,
                ScrapedJob.salary,
                ScrapedJob.sector,
                ScrapedJob.company_ssic_source,
                ScrapedJob.company_ssic_description,
                ScrapedJob.skills_flat,
                ScrapedJob.salary_floor,
                ScrapedJob.posted_at_sort,
                ScrapedJob.seniority,
            )
        )
        .filter(
            ScrapedJob.hidden == 0,
            ScrapedJob.job_terms_preview.isnot(None),
        )
    )
    db_query = _apply_market_filters(
        db_query,
        source=source,
        company=company,
        title=title,
        sector=sector,
        agency_subset=agency_subset_key,
        direct_employers_only=direct_employers_only,
    )

    skill_counts: dict[str, dict] = {}
    source_counts: dict[str, int] = {}
    title_counts: dict[str, int] = {}
    sector_counts: dict[str, int] = {}
    company_counts: dict[str, int] = {}
    seniority_counts: dict[str, int] = {}
    sector_source_counts: dict[str, int] = {}
    agency_subset_counts: dict[str, int] = {subset_id: 0 for subset_id in _ANALYTICS_AGENCY_SUBSETS}
    salary_floors: list[int] = []
    salary_midpoints: list[int] = []
    salary_ceilings: list[int] = []
    salary_by_sector: dict[str, list[int]] = {}
    salary_mid_by_sector: dict[str, list[int]] = {}
    salary_ceiling_by_sector: dict[str, list[int]] = {}
    salary_by_title: dict[str, list[int]] = {}
    salary_mid_by_title: dict[str, list[int]] = {}
    salary_ceiling_by_title: dict[str, list[int]] = {}
    recent_skill_counts: dict[str, dict] = {}
    older_skill_counts: dict[str, dict] = {}
    recent_company_counts: dict[str, dict] = {}
    older_company_counts: dict[str, dict] = {}
    recent_total = 0
    older_total = 0
    fresh_counts = {"last_7": 0, "last_14": 0, "last_30": 0}
    posted_count = 0
    total_jobs = 0
    scanned_rows = 0
    utc_now = datetime.now(timezone.utc)

    scan_query = db_query.order_by(ScrapedJob.posted_at_sort.desc().nullslast(), ScrapedJob.id.desc()).limit(
        _ANALYTICS_MAX_ROWS
    )
    for job in scan_query.yield_per(_ANALYTICS_YIELD_PER):
        scanned_rows += 1
        preview = job.job_terms_preview
        if not isinstance(preview, list) or not preview:
            continue

        raw_title = (job.title or "").strip()
        job_sector = _analytics_sector_label(job.sector)
        sector_source = (job.company_ssic_source or "").strip().lower() or "unavailable"
        if sector_source not in {"acra", "inferred", "unavailable"}:
            sector_source = "unavailable"
        norm_title = _normalize_title(raw_title) if raw_title else ""

        total_jobs += 1
        sector_source_counts[sector_source] = sector_source_counts.get(sector_source, 0) + 1
        for subset_id in agency_subset_counts:
            if _analytics_job_matches_agency_subset(job, subset_id):
                agency_subset_counts[subset_id] += 1

        src = _analytics_source_label(job.source)
        source_counts[src] = source_counts.get(src, 0) + 1

        # Company/agency aggregation. Careers@Gov rows often use the generic
        # "Singapore Public Service" company; agency is the useful hiring org.
        comp = _analytics_company_label(job)
        comp_key = comp.lower() if comp else ""
        if comp_key:
            _increment_label_count(company_counts, comp_key, comp)

        term_keys: set[str] = set()
        for term in preview:
            key = _analytics_skill_key(str(term))
            if not key:
                continue
            _increment_analytics_skill(skill_counts, key)
            term_keys.add(key)

        if norm_title:
            title_key = norm_title.lower()
            if title_key:
                if title_key not in title_counts:
                    title_counts[title_key] = {"display": norm_title, "count": 0}
                title_counts[title_key]["count"] += 1

        sector_counts[job_sector] = sector_counts.get(job_sector, 0) + 1

        seniority_label = _analytics_seniority_label(job)
        seniority_counts[seniority_label] = seniority_counts.get(seniority_label, 0) + 1

        parsed_floor, parsed_ceiling, parsed_midpoint = _salary_bounds_from_text(job.salary or "")
        salary_floor = int(job.salary_floor or parsed_floor or 0)
        if 0 < salary_floor < 1000000:
            salary_floors.append(salary_floor)
            salary_by_sector.setdefault(job_sector, []).append(salary_floor)
            if norm_title:
                salary_by_title.setdefault(norm_title, []).append(salary_floor)
        if 0 < parsed_midpoint < 1000000:
            salary_midpoints.append(parsed_midpoint)
            salary_mid_by_sector.setdefault(job_sector, []).append(parsed_midpoint)
            if norm_title:
                salary_mid_by_title.setdefault(norm_title, []).append(parsed_midpoint)
        if 0 < parsed_ceiling < 1000000:
            salary_ceilings.append(parsed_ceiling)
            salary_ceiling_by_sector.setdefault(job_sector, []).append(parsed_ceiling)
            if norm_title:
                salary_ceiling_by_title.setdefault(norm_title, []).append(parsed_ceiling)

        posted_at = _parse_posted_sort(job.posted_at_sort or "")
        if posted_at:
            posted_count += 1
            age_days = (utc_now - posted_at).days
            if 0 <= age_days <= 7:
                fresh_counts["last_7"] += 1
            if 0 <= age_days <= 14:
                fresh_counts["last_14"] += 1
            if 0 <= age_days <= 30:
                fresh_counts["last_30"] += 1
                recent_total += 1
                _increment_label_count(recent_company_counts, comp_key, comp)
                for key in term_keys:
                    _increment_analytics_skill(recent_skill_counts, key)
            elif age_days > 30:
                older_total += 1
                _increment_label_count(older_company_counts, comp_key, comp)
                for key in term_keys:
                    _increment_analytics_skill(older_skill_counts, key)

    sorted_skills = sorted(skill_counts.values(), key=lambda x: -x["count"])

    all_skills = [{"skill": item["display"], "count": item["count"]} for item in sorted_skills]
    skill_count_numbers = {key: int(item["count"]) for key, item in skill_counts.items()}

    hard_skills = [
        {"skill": item["display"], "count": item["count"]}
        for key, item in sorted(skill_counts.items(), key=lambda x: -x[1]["count"])
        if not _is_generic_analytics_skill(key)
    ][:20]

    overindexed_skills = _build_overindexed_skills(
        current_counts=skill_counts,
        current_total=total_jobs,
        baseline_counts=baseline_counts,
        baseline_total=baseline_total,
    )
    market_movers = _build_market_movers(
        recent_counts=recent_skill_counts,
        recent_total=recent_total,
        older_counts=older_skill_counts,
        older_total=older_total,
    )
    company_movers = _build_label_movers(
        recent_counts=recent_company_counts,
        recent_total=recent_total,
        older_counts=older_company_counts,
        older_total=older_total,
        label_key="company",
    )

    sources_list = [
        {"source": s, "label": _analytics_source_label(s), "count": c}
        for s, c in sorted(source_counts.items(), key=lambda x: -x[1])
    ]

    top_titles = sorted(
        [{"title": v["display"], "count": v["count"]} for v in title_counts.values()],
        key=lambda x: -x["count"],
    )[:20]

    sectors = sorted(
        [{"sector": s, "count": c} for s, c in sector_counts.items()],
        key=lambda x: -x["count"],
    )

    top_companies = sorted(
        [{"company": v["display"], "count": v["count"]} for v in company_counts.values()],
        key=lambda x: -x["count"],
    )[:30]

    sorted_salary_floors = sorted(salary_floors)
    sorted_salary_midpoints = sorted(salary_midpoints)
    sorted_salary_ceilings = sorted(salary_ceilings)
    salary_insights = {
        "coverage_count": len(sorted_salary_floors),
        "coverage_percent": round((len(sorted_salary_floors) / total_jobs) * 100, 1) if total_jobs else 0,
        "median_floor": _percentile(sorted_salary_floors, 0.5),
        "median_midpoint": _percentile(sorted_salary_midpoints, 0.5),
        "median_ceiling": _percentile(sorted_salary_ceilings, 0.5),
        "p75_floor": _percentile(sorted_salary_floors, 0.75),
        "by_sector": _salary_bucket(
            salary_by_sector,
            "sector",
            salary_mid_by_sector,
            salary_ceiling_by_sector,
        ),
        "by_title": _salary_bucket(
            salary_by_title,
            "title",
            salary_mid_by_title,
            salary_ceiling_by_title,
        ),
    }
    freshness = {
        **fresh_counts,
        "coverage_count": posted_count,
        "last_30_percent": round((fresh_counts["last_30"] / posted_count) * 100, 1) if posted_count else 0,
    }
    partial = scanned_rows >= _ANALYTICS_MAX_ROWS
    seniority_order = {
        "Intern": 0,
        "Entry / Junior": 1,
        "Mid / Unspecified": 2,
        "Senior IC": 3,
        "Manager / Lead": 4,
        "Leadership": 5,
    }
    seniority_mix = [
        {
            "label": label,
            "count": count,
            "percent": round((count / total_jobs) * 100, 1) if total_jobs else 0,
        }
        for label, count in sorted(
            seniority_counts.items(),
            key=lambda item: (-item[1], seniority_order.get(item[0], 99)),
        )
    ]
    sector_source_labels = {
        "acra": "Official ACRA SSIC",
        "inferred": "Inferred fallback",
        "unavailable": "Unavailable",
    }
    sector_source_mix = [
        {
            "source": key,
            "label": sector_source_labels[key],
            "count": sector_source_counts.get(key, 0),
            "percent": round((sector_source_counts.get(key, 0) / total_jobs) * 100, 1) if total_jobs else 0,
        }
        for key in ("acra", "inferred", "unavailable")
        if sector_source_counts.get(key, 0)
    ]
    ssic_coverage = {
        "official_count": sector_source_counts.get("acra", 0),
        "official_percent": round((sector_source_counts.get("acra", 0) / total_jobs) * 100, 1) if total_jobs else 0,
        "inferred_count": sector_source_counts.get("inferred", 0),
        "unavailable_count": sector_source_counts.get("unavailable", 0),
    }
    agency_subsets = [
        {
            **option,
            "count": agency_subset_counts.get(option["id"], 0),
        }
        for option in _analytics_agency_subset_options()
    ]

    filtered_skills = all_skills
    if q:
        q_lower = q.lower()
        filtered_skills = [s for s in all_skills if q_lower in s["skill"].lower()]

    result = {
        "top_skills": filtered_skills[:limit],
        "total_jobs_with_terms": total_jobs,
        "skill_signal_count": len(all_skills),
        "company_count": len(company_counts),
        "title_count": len(title_counts),
        "sector_count": len(sector_counts),
        "sources": sources_list,
        "top_titles": top_titles,
        "sectors": sectors,
        "top_companies": top_companies,
        "hard_skills": hard_skills,
        "overindexed_skills": overindexed_skills,
        "market_movers": market_movers,
        "company_movers": company_movers,
        "salary_insights": salary_insights,
        "freshness": freshness,
        "sampled_jobs": scanned_rows,
        "sampled_job_limit": _ANALYTICS_MAX_ROWS,
        "partial": partial,
        "seniority_mix": seniority_mix,
        "ssic_coverage": ssic_coverage,
        "sector_source_mix": sector_source_mix,
        "agency_subsets": agency_subsets,
        "agency_subset": agency_subset_key,
        "direct_employers_only": direct_employers_only,
    }
    cache_payload = None
    if not has_filter:
        cache_payload = dict(result)
        cache_payload.pop("top_skills")
        cache_payload.update(
            {
                "_corpus_marker": corpus_marker,
                "_all_skills": all_skills,
                "_skill_counts": skill_count_numbers,
            }
        )
    if cache_payload is not None:
        with _ANALYTICS_CACHE_LOCK:
            if cache_generation == _analytics_cache_generation:
                _analytics_cache = cache_payload
                _analytics_cache_ts = now
    if not has_filter or baseline_ready:
        _store_analytics_query_cache(query_cache_key, now, result, cache_generation)
    return result


@router.get("/api/analytics/trends")
def analytics_trends(
    request: Request,
    source: str | None = Query(None, max_length=50),
    sector: str | None = Query(None, max_length=100),
    company: str | None = Query(None, max_length=200),
    title: str | None = Query(None, max_length=200),
    agency_subset: str | None = Query(None, max_length=50),
    direct_employers_only: bool = Query(False),
    bucket: str = Query("week", pattern="^(week|month)$"),
    weeks: int = Query(26, ge=4, le=104),
    db: Session = Depends(get_db),
    _admission: None = Depends(_admit_analytics_request),
) -> dict:
    """Return posting-count trend buckets plus recent role and ATS-term mix."""
    if not _PUBLIC_RATE_LIMITER.allow(
        f"analytics-trends:{_get_client_ip(request)}",
        limit=30,
        window_seconds=60,
    ):
        raise HTTPException(status_code=429, detail="Too many analytics requests")
    if direct_employers_only and not get_employer_relationship_readiness(db)["ready"]:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "employer_index_unavailable",
                "message": "The employer classification index is rebuilding. Please retry shortly.",
            },
        )
    now_dt = datetime.now(timezone.utc)
    now = time.time()
    cutoff = now_dt - timedelta(weeks=weeks)
    agency_subset_key = _normalise_agency_subset_id(agency_subset)
    cache_key = (
        "trends",
        _job_corpus_marker(db),
        source or "",
        sector or "",
        company or "",
        title or "",
        agency_subset_key,
        int(direct_employers_only),
        bucket,
        weeks,
    )
    with _ANALYTICS_CACHE_LOCK:
        cache_generation = _analytics_cache_generation
        cached_query = _analytics_query_cache.get(cache_key)
        if cached_query and now - cached_query[0] < _ANALYTICS_QUERY_CACHE_TTL:
            return cached_query[1]

    db_query = (
        db.query(ScrapedJob)
        .options(
            load_only(
                ScrapedJob.id,
                ScrapedJob.title,
                ScrapedJob.source,
                ScrapedJob.company,
                ScrapedJob.agency,
                ScrapedJob.sector,
                ScrapedJob.company_ssic_description,
                ScrapedJob.job_terms_preview,
                ScrapedJob.posted_at_sort,
            )
        )
        .filter(
            ScrapedJob.hidden == 0,
            ScrapedJob.posted_at_sort.isnot(None),
            ScrapedJob.posted_at_sort != "",
            ScrapedJob.posted_at_sort >= cutoff.isoformat(),
        )
    )
    db_query = _apply_market_filters(
        db_query,
        source=source,
        company=company,
        title=title,
        sector=sector,
        agency_subset=agency_subset_key,
        direct_employers_only=direct_employers_only,
    )

    bucket_starts = _trend_bucket_series(cutoff, now_dt, bucket)
    bucket_counts = {start.date().isoformat(): 0 for start in bucket_starts}
    recent_title_counts: dict[str, dict] = {}
    recent_skill_counts: dict[str, dict] = {}
    recent_cutoff = now_dt - timedelta(days=30)
    total = 0
    recent_total = 0

    for job in (
        db_query.order_by(ScrapedJob.posted_at_sort.desc().nullslast(), ScrapedJob.id.desc())
        .limit(_ANALYTICS_MAX_ROWS)
        .yield_per(_ANALYTICS_YIELD_PER)
    ):
        posted_at = _parse_posted_sort(job.posted_at_sort or "")
        if not posted_at or posted_at < cutoff:
            continue
        total += 1
        bucket_key = _trend_bucket_start(posted_at, bucket).date().isoformat()
        bucket_counts[bucket_key] = bucket_counts.get(bucket_key, 0) + 1

        if posted_at >= recent_cutoff:
            recent_total += 1
            norm_title = _normalize_title(job.title or "")
            if norm_title:
                _increment_label_count(recent_title_counts, norm_title.lower(), norm_title)
            preview = job.job_terms_preview
            if isinstance(preview, list):
                for term in preview:
                    key = _analytics_skill_key(str(term))
                    if key and not _is_generic_analytics_skill(key):
                        _increment_analytics_skill(recent_skill_counts, key)

    series = [
        {
            "start": start.date().isoformat(),
            "label": _trend_bucket_label(start, bucket),
            "count": bucket_counts.get(start.date().isoformat(), 0),
        }
        for start in bucket_starts
    ]
    peak = max(series, key=lambda item: item["count"], default=None)
    result = {
        "bucket": bucket,
        "window_weeks": weeks,
        "total_postings": total,
        "recent_30_postings": recent_total,
        "peak": peak,
        "series": series,
        "recent_top_titles": sorted(
            [{"title": item["display"], "count": item["count"]} for item in recent_title_counts.values()],
            key=lambda item: -item["count"],
        )[:8],
        "recent_ats_terms": sorted(
            [{"skill": item["display"], "count": item["count"]} for item in recent_skill_counts.values()],
            key=lambda item: -item["count"],
        )[:8],
    }
    _store_analytics_query_cache(cache_key, now, result, cache_generation)
    return result


__all__ = ["invalidate", "router"]
