"""Employer classification helpers for job search filters."""

from __future__ import annotations

import re

from sqlalchemy import func, or_


RECRUITER_COMPANY_KEYWORDS = (
    "recruit",
    "recruitment",
    "staffing",
    "employment agency",
    "personnel",
    "career services",
    "people profilers",
    "supreme hr",
    "hrnet",
    "persol",
    "randstad",
    "adecco",
    "pasona",
    "manpower staffing",
    "michael page",
    "wecruit",
    "anradus",
    "talent trader",
    "talent search",
    "talentsis",
    "business edge personnel",
    "scientec",
    "gmp technologies",
    "flintex",
    "ambition group",
    "search personnel",
    "avaron",
    "envirodynamics",
    "royal org",
    "job express",
    "good job creations",
    "staffking",
    "hkm hr",
    "hr management",
    "hr advisory",
    "rn care",
    "skilmatch recruiment",
    "talent spot",
    "j&l apex",
    "j and l apex",
    "adaba",
    "apba tg human resource",
    "first konnection",
)

RECRUITER_COMPANY_ALIASES = (
    "allied search",
    "sinweb manpower",
    "search avenue",
    "oaktree consulting",
    "direct search asia",
    "aisearch",
    "starsearch",
    "placement professionals",
    "bgc group",
    "ethos search",
    "employment pte",
    "employment services",
    "manpower service",
    "manpower services",
    "manpower consultant",
    "manpower consultancy",
)

RECRUITER_SSIC_KEYWORDS = (
    "employment agency",
    "employment agencies",
    "executive search",
    "human resource",
    "recruitment",
    "staffing",
)

RECRUITER_DESCRIPTION_MARKERS = (
    "ea licence",
    "ea license",
    "ea no",
    "ea personnel",
    "eapersonnel",
    "ea registration",
    "ea reg no",
    "employment agency licence",
    "employment agency license",
)

RECRUITER_DESCRIPTION_SQL_PATTERN = (
    r"(^|[^a-z])(?:"
    r"ea\s*[/|:]?\s*(?:licen[cs]e|no|personnel|registration|reg(?:istration)?\s*no)"
    r"|eapersonnel"
    r"|employment\s+agency\s*\(?\s*licen[cs]e"
    r")\b"
)

# Singapore employment-agency licence numbers are often printed without an
# explicit "EA Licence" label, for example ``15C7752``.
EA_LICENCE_NUMBER_PATTERN = r"(^|[^a-z0-9])\d{2}[cs]\d{4}([^a-z0-9]|$)"
_EA_LICENCE_NUMBER_RE = re.compile(EA_LICENCE_NUMBER_PATTERN, re.IGNORECASE)


def normalize_employer_name(name: str) -> str:
    text = (name or "").lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _contains_phrase(text: str, phrase: str) -> bool:
    return f" {phrase} " in f" {text} "


def is_recruitment_employer(
    company: str,
    ssic_description: str = "",
    description: str = "",
) -> bool:
    company_name = normalize_employer_name(company)
    ssic = normalize_employer_name(ssic_description)
    job_description = normalize_employer_name(description)
    if not company_name:
        return False
    if any(keyword in company_name for keyword in RECRUITER_COMPANY_KEYWORDS):
        return True
    if any(_contains_phrase(company_name, alias) for alias in RECRUITER_COMPANY_ALIASES):
        return True
    if any(keyword in ssic for keyword in RECRUITER_SSIC_KEYWORDS):
        return True
    return any(
        _contains_phrase(job_description, marker)
        for marker in RECRUITER_DESCRIPTION_MARKERS
    ) or bool(_EA_LICENCE_NUMBER_RE.search(job_description))


def _sql_phrase_condition(lowered_column, phrase: str):
    return or_(
        lowered_column == phrase,
        lowered_column.like(f"{phrase} %"),
        lowered_column.like(f"% {phrase}"),
        lowered_column.like(f"% {phrase} %"),
    )


def direct_employer_condition(
    company_column,
    ssic_description_column=None,
    description_column=None,
):
    company_lower = func.lower(company_column)
    recruiter_conditions = [company_lower.like(f"%{keyword}%") for keyword in RECRUITER_COMPANY_KEYWORDS]
    recruiter_conditions.extend(_sql_phrase_condition(company_lower, alias) for alias in RECRUITER_COMPANY_ALIASES)
    if ssic_description_column is not None:
        ssic_lower = func.lower(func.coalesce(ssic_description_column, ""))
        recruiter_conditions.extend(ssic_lower.like(f"%{keyword}%") for keyword in RECRUITER_SSIC_KEYWORDS)
    if description_column is not None:
        description_lower = func.lower(func.coalesce(description_column, ""))
        recruiter_conditions.append(
            description_lower.regexp_match(RECRUITER_DESCRIPTION_SQL_PATTERN)
        )
        recruiter_conditions.append(
            description_lower.regexp_match(EA_LICENCE_NUMBER_PATTERN)
        )
    return ~or_(*recruiter_conditions)
