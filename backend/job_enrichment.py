"""
Shared job enrichment utilities.

Single source of truth for skill normalization, term preview computation,
and power-skill filtering. Used by main.py, backfill_enrichment.py, and
seed_jobs.py to ensure consistent ATS term extraction everywhere.
"""

from __future__ import annotations

import re

from ats_terms import build_job_ats_terms
from jd_preparser import preparse_job_description as preparse_jd


# ── Skill normalization ──────────────────────────────────────────────────────

def normalize_skill_strings(raw_skills) -> list[str]:
    """Recursively flatten and normalize skill values from JSON (str/list/dict)."""
    collected: list[str] = []

    def visit(value) -> None:
        if isinstance(value, str):
            for part in re.split(r"[;,|/]", value):
                cleaned = part.strip()
                if cleaned:
                    collected.append(cleaned)
        elif isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            for key, item in value.items():
                visit(key)
                visit(item)

    visit(raw_skills)

    deduped: list[str] = []
    seen: set[str] = set()
    for skill in collected:
        cleaned = re.sub(r"\s+", " ", skill).strip(" -\u2022\t")
        lower = cleaned.lower()
        if not cleaned or len(cleaned) < 2 or len(cleaned) > 60:
            continue
        if lower in seen:
            continue
        seen.add(lower)
        deduped.append(cleaned)
    return deduped


# ── Term label extraction ────────────────────────────────────────────────────

def job_term_labels(terms: list[dict], limit: int = 8) -> list[str]:
    """Extract deduplicated skill labels from ATS term dicts."""
    labels: list[str] = []
    seen: set[str] = set()
    for term in terms or []:
        label = re.sub(r"\s+", " ", str(term.get("skill", "")).strip())
        lower = label.lower()
        if not label or lower in seen:
            continue
        seen.add(lower)
        labels.append(label)
        if len(labels) >= limit:
            break
    return labels


# ── Compute and cache term preview ───────────────────────────────────────────

def compute_term_preview(
    *,
    description: str,
    skills: list | dict | None,
    parsed_jd: dict | None,
    title: str = "",
    db_session=None,
    limit: int = 8,
    filter_noise: bool = True,
) -> list[str]:
    """Compute ATS term preview labels from job data. Pure computation, no DB writes."""
    db_skills = normalize_skill_strings(skills)
    pjd = parsed_jd if isinstance(parsed_jd, dict) else None

    terms = build_job_ats_terms(
        jd_text=description or "",
        job_skills=db_skills,
        parsed_jd=pjd,
        job_title=title,
        limit=24,
        db_session=db_session,
    )

    if filter_noise:
        terms = [t for t in terms if not _is_noise_term(t.get("skill", ""))]

    return job_term_labels(terms, limit=limit)


def parse_and_preview_job(job, db_session=None) -> None:
    """Parse JD and compute preview for a job row. Mutates job in place."""
    if not (job.description or "").strip():
        return

    if not job.parsed_jd:
        db_skills = normalize_skill_strings(job.skills)
        job.parsed_jd = preparse_jd(
            job.description or "",
            skills=db_skills,
            db_session=db_session,
            job_title=job.title or "",
        )

    if not job.job_terms_preview:
        job.job_terms_preview = compute_term_preview(
            description=job.description or "",
            skills=job.skills,
            parsed_jd=job.parsed_jd,
            title=job.title or "",
            db_session=db_session,
        )


# ── Noise filtering ─────────────────────────────────────────────────────────

_NOISE_SINGLE_WORDS = {
    "experience", "skills", "ability", "knowledge", "team",
    "communication", "management", "work", "support", "business",
    "development", "service", "good", "strong", "working",
    "years", "year", "relevant", "related", "preferred",
    "required", "minimum", "including", "ensure", "based",
    "well", "role", "within", "across", "using", "new",
    "high", "key", "also", "must", "time", "level",
}


def _is_noise_term(skill: str) -> bool:
    """Check if a skill term is too generic for ATS display."""
    lower = re.sub(r"\s+", " ", (skill or "").strip().lower())
    if not lower:
        return True
    if lower in _NOISE_SINGLE_WORDS:
        return True
    if len(lower.split()) == 1 and lower in _NOISE_SINGLE_WORDS:
        return True
    return False
