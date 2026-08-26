"""Employer classification helpers for job search filters."""

from __future__ import annotations

from dataclasses import dataclass
import re

from sqlalchemy import and_, func, or_


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
    "searchasia",
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
    "one search consulting",
)

RECRUITER_COMPANY_ALIASES = (
    "allied search",
    "sinweb manpower",
    "search avenue",
    "oaktree consulting",
    "direct search asia",
    "asia search",
    "kerry consulting",
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

# Singapore employment-agency licence numbers are often printed without an
# explicit "EA Licence" label, for example ``15C7752``.
EA_LICENCE_NUMBER_PATTERN = r"(^|[^a-z0-9])\d{2}[cs]\d{4}([^a-z0-9]|$)"
_EA_LICENCE_NUMBER_RE = re.compile(EA_LICENCE_NUMBER_PATTERN, re.IGNORECASE)

# Some agencies omit their licence from the posting and describe an unnamed
# client in the third person. This is evidence that the named poster is not the
# employing company; ordinary references to a direct employer's customers do
# not match these forms.
ANONYMOUS_CLIENT_DESCRIPTION_PATTERN = (
    r"(^|[^a-z])(?:"
    r"(?:our\s+client|the\s+hiring\s+company)\s+(?:is|are|seeks?|requires?)"
    r"|(?:we\s+are\s+)?hiring\s+on\s+behalf\s+of"
    r"|an?\s+(?:well[-\s]+)?established\b[^.!?\n]*\bis\s+(?:looking|seeking)"
    r")([^a-z]|$)"
)
_ANONYMOUS_CLIENT_DESCRIPTION_RE = re.compile(
    ANONYMOUS_CLIENT_DESCRIPTION_PATTERN,
    re.IGNORECASE,
)

EMPLOYER_RELATIONSHIP_DIRECT = "direct"
EMPLOYER_RELATIONSHIP_INTERMEDIARY = "intermediary"
EMPLOYER_RELATIONSHIP_UNKNOWN = "unknown"
EMPLOYER_RELATIONSHIP_CLASSIFIER_VERSION = "employer-relationship-v1"
EMPLOYER_RELATIONSHIP_PRECOMPUTE_MARKER = (
    f"employer_relationship:{EMPLOYER_RELATIONSHIP_CLASSIFIER_VERSION}"
)
EMPLOYER_RELATIONSHIPS = frozenset(
    {
        EMPLOYER_RELATIONSHIP_DIRECT,
        EMPLOYER_RELATIONSHIP_INTERMEDIARY,
        EMPLOYER_RELATIONSHIP_UNKNOWN,
    }
)
EMPLOYER_RELATIONSHIP_EVIDENCE = {
    EMPLOYER_RELATIONSHIP_DIRECT: frozenset({"careers_gov_official"}),
    EMPLOYER_RELATIONSHIP_INTERMEDIARY: frozenset(
        {
            "mcf_posted_company_ssic_78",
            "mcf_posted_company_ssic_description",
            "acra_recruitment_ssic",
            "company_recruitment_taxonomy",
            "description_ea_licence",
            "description_anonymous_client",
        }
    ),
    EMPLOYER_RELATIONSHIP_UNKNOWN: frozenset(
        {
            "mcf_no_relationship_signal",
            "legacy_no_relationship_signal",
            "missing_company",
        }
    ),
}


@dataclass(frozen=True)
class EmployerRelationshipAssessment:
    relationship: str
    evidence: str


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
    return any(_contains_phrase(job_description, marker) for marker in RECRUITER_DESCRIPTION_MARKERS) or bool(
        _EA_LICENCE_NUMBER_RE.search(job_description) or _ANONYMOUS_CLIENT_DESCRIPTION_RE.search(description or "")
    )


def classify_employer_relationship(
    *,
    source: str,
    company: str,
    agency: str = "",
    ssic_code: str = "",
    ssic_description: str = "",
    ssic_source: str = "",
    description: str = "",
) -> EmployerRelationshipAssessment:
    """Classify only source-backed relationships; absence of agency evidence is unknown."""
    company_name = normalize_employer_name(company)
    if not company_name:
        return EmployerRelationshipAssessment(EMPLOYER_RELATIONSHIP_UNKNOWN, "missing_company")

    ssic_digits = re.sub(r"\D", "", ssic_code or "")
    ssic_origin = (ssic_source or "").strip().casefold()
    if ssic_digits.startswith("78"):
        evidence = "mcf_posted_company_ssic_78" if ssic_origin == "mcf_posted_company" else "acra_recruitment_ssic"
        return EmployerRelationshipAssessment(EMPLOYER_RELATIONSHIP_INTERMEDIARY, evidence)

    normalized_ssic = normalize_employer_name(ssic_description)
    if any(keyword in normalized_ssic for keyword in RECRUITER_SSIC_KEYWORDS):
        return EmployerRelationshipAssessment(
            EMPLOYER_RELATIONSHIP_INTERMEDIARY,
            (
                "mcf_posted_company_ssic_description"
                if ssic_origin == "mcf_posted_company"
                else "acra_recruitment_ssic"
            ),
        )

    if any(keyword in company_name for keyword in RECRUITER_COMPANY_KEYWORDS) or any(
        _contains_phrase(company_name, alias) for alias in RECRUITER_COMPANY_ALIASES
    ):
        return EmployerRelationshipAssessment(
            EMPLOYER_RELATIONSHIP_INTERMEDIARY,
            "company_recruitment_taxonomy",
        )

    normalized_description = normalize_employer_name(description)
    if any(
        _contains_phrase(normalized_description, marker) for marker in RECRUITER_DESCRIPTION_MARKERS
    ) or _EA_LICENCE_NUMBER_RE.search(description or ""):
        return EmployerRelationshipAssessment(
            EMPLOYER_RELATIONSHIP_INTERMEDIARY,
            "description_ea_licence",
        )
    if _ANONYMOUS_CLIENT_DESCRIPTION_RE.search(description or ""):
        return EmployerRelationshipAssessment(
            EMPLOYER_RELATIONSHIP_INTERMEDIARY,
            "description_anonymous_client",
        )

    if (source or "").strip().casefold() == "careers@gov" and (agency or "").strip():
        return EmployerRelationshipAssessment(
            EMPLOYER_RELATIONSHIP_DIRECT,
            "careers_gov_official",
        )
    evidence = (
        "mcf_no_relationship_signal"
        if (source or "").strip().casefold() == "mycareersfuture"
        else "legacy_no_relationship_signal"
    )
    return EmployerRelationshipAssessment(EMPLOYER_RELATIONSHIP_UNKNOWN, evidence)


def employer_relationship_eligibility_condition(
    relationship_column,
    evidence_column,
    company_column,
):
    """Keep verified direct and unknown employers; exclude known intermediaries and NULL."""
    return and_(
        func.trim(func.coalesce(company_column, "")) != "",
        employer_relationship_valid_condition(relationship_column, evidence_column),
        relationship_column.in_(
            (
                EMPLOYER_RELATIONSHIP_DIRECT,
                EMPLOYER_RELATIONSHIP_UNKNOWN,
            )
        ),
    )


def employer_relationship_valid_condition(relationship_column, evidence_column):
    """SQL invariant binding each relationship state to allowed positive evidence."""
    return or_(
        *(
            and_(
                relationship_column == relationship,
                evidence_column.in_(tuple(sorted(evidence_codes))),
            )
            for relationship, evidence_codes in EMPLOYER_RELATIONSHIP_EVIDENCE.items()
        )
    )


def employer_relationship_unclassified_condition(relationship_column, evidence_column):
    valid = employer_relationship_valid_condition(relationship_column, evidence_column)
    return or_(
        relationship_column.is_(None),
        evidence_column.is_(None),
        evidence_column == "",
        ~valid,
    )


def get_employer_relationship_readiness(db) -> dict[str, int | bool | str]:
    """Return the version-bound completeness state shared by every consumer."""
    from job_visibility import apply_public_job_visibility
    from models import ScrapedJob, UsageLog

    public_jobs = apply_public_job_visibility(db.query(func.count(ScrapedJob.id))).scalar() or 0
    valid_jobs = (
        apply_public_job_visibility(db.query(func.count(ScrapedJob.id)))
        .filter(
            employer_relationship_valid_condition(
                ScrapedJob.employer_relationship,
                ScrapedJob.employer_relationship_evidence,
            )
        )
        .scalar()
        or 0
    )
    current_marker = (
        db.query(UsageLog.id)
        .filter(
            UsageLog.user_id.is_(None),
            UsageLog.action == "job_precompute",
            UsageLog.detail == EMPLOYER_RELATIONSHIP_PRECOMPUTE_MARKER,
        )
        .first()
        is not None
    )
    return {
        "ready": public_jobs > 0 and valid_jobs == public_jobs and current_marker,
        "public_jobs": int(public_jobs),
        "valid_jobs": int(valid_jobs),
        "classifier_version": EMPLOYER_RELATIONSHIP_CLASSIFIER_VERSION,
        "current_marker": current_marker,
    }


def employer_relationship_rank(relationship: str | None) -> int:
    """Secondary deterministic preference for positively verified first-party sources."""
    if relationship == EMPLOYER_RELATIONSHIP_DIRECT:
        return 2
    if relationship == EMPLOYER_RELATIONSHIP_UNKNOWN:
        return 1
    return 0


def company_name_matches(company: str, requested_company: str) -> bool:
    """Match a requested employer on whole normalized words, not substrings."""
    company_name = normalize_employer_name(company)
    requested_name = normalize_employer_name(requested_company)
    return bool(requested_name) and _contains_phrase(company_name, requested_name)
