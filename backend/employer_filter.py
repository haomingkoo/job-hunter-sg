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
)

RECRUITER_SSIC_KEYWORDS = (
    "employment agency",
    "employment agencies",
    "executive search",
    "human resource",
    "recruitment",
    "staffing",
)


def normalize_employer_name(name: str) -> str:
    text = (name or "").lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def is_recruitment_employer(company: str, ssic_description: str = "") -> bool:
    company_name = normalize_employer_name(company)
    ssic = normalize_employer_name(ssic_description)
    if not company_name:
        return False
    if any(keyword in company_name for keyword in RECRUITER_COMPANY_KEYWORDS):
        return True
    return any(keyword in ssic for keyword in RECRUITER_SSIC_KEYWORDS)


def direct_employer_condition(company_column, ssic_description_column=None):
    company_lower = func.lower(company_column)
    recruiter_conditions = [
        company_lower.like(f"%{keyword}%")
        for keyword in RECRUITER_COMPANY_KEYWORDS
    ]
    if ssic_description_column is not None:
        ssic_lower = func.lower(ssic_description_column)
        recruiter_conditions.extend(
            ssic_lower.like(f"%{keyword}%")
            for keyword in RECRUITER_SSIC_KEYWORDS
        )
    return ~or_(*recruiter_conditions)
