"""
Job description pre-parser -- runs at scrape time for fast downstream matching.

Pure local computation (regex + string matching), no LLM calls.
Target: ~50ms per job description.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone

from resume_scorer import COMPETENCY_KEYWORDS
from skill_extractor import extract_skill_phrases

log = logging.getLogger("jobhunter.jd_preparser")

# ── Constants ───────────────────────────────────────────────────────────────

SINGLE_WORD_TECH: set[str] = {
    "python", "java", "javascript", "typescript", "go", "golang",
    "rust", "c++", "c#", "ruby", "php", "swift", "kotlin", "scala",
    "r", "sql", "nosql", "mongodb", "postgresql", "mysql", "redis",
    "elasticsearch", "docker", "kubernetes", "terraform", "ansible",
    "jenkins", "react", "angular", "vue", "svelte", "nextjs",
    "django", "flask", "fastapi", "spring", "express", "node",
    "nodejs", "aws", "azure", "gcp", "linux", "git", "jira",
    "confluence", "tableau", "powerbi", "excel", "figma", "sketch",
    "pytorch", "tensorflow", "keras", "scikit-learn", "pandas",
    "numpy", "spark", "hadoop", "airflow", "kafka", "rabbitmq",
    "graphql", "rest", "grpc", "websocket", "html", "css", "sass",
    "tailwind",
}

# Markers that split required vs preferred skills
_PREFERRED_MARKERS: list[str] = [
    "preferred",
    "nice to have",
    "bonus",
    "good to have",
    "desirable",
    "advantageous",
]

# Regex for experience years extraction
_EXPERIENCE_RE = re.compile(
    r"(?:"
    r"(?:at\s+least|minimum|min\.?)\s+(\d+)\s*\+?\s*years?"
    r"|(\d+)\s*\+\s*years?"
    r"|(\d+)\s*[-–]\s*(\d+)\s*years?"
    r"|(\d+)\s+years?\s+(?:of\s+)?(?:experience|exp)"
    r")",
    re.IGNORECASE,
)

# Education level keywords ordered by highest to lowest
_EDUCATION_LEVELS: list[tuple[str, list[str]]] = [
    ("phd", ["phd", "ph.d", "doctorate", "doctoral"]),
    ("master", ["master's", "masters", "master", "msc", "m.sc",
                "mba", "m.b.a"]),
    ("bachelor", ["bachelor's", "bachelors", "bachelor", "bsc",
                  "b.sc", "b.a.", "b.eng", "undergraduate"]),
    ("diploma", ["diploma", "polytechnic", "poly"]),
    ("degree", ["degree"]),
]

# Bullet-point line pattern
_BULLET_LINE_RE = re.compile(
    r"^\s*(?:[-*\u2022\u2023\u25E6\u2043\u2219]|\d{1,2}[.)]\s)",
    re.MULTILINE,
)

# Word boundary helper for single-word tech matching
# Precompile patterns for tech terms that contain special regex chars
_TECH_PATTERNS: dict[str, re.Pattern[str]] = {}
for _term in SINGLE_WORD_TECH:
    _escaped = re.escape(_term)
    _TECH_PATTERNS[_term] = re.compile(
        rf"\b{_escaped}\b", re.IGNORECASE
    )


# ── Helpers ─────────────────────────────────────────────────────────────────

def _find_preferred_split(text: str) -> int:
    """Find the character index where 'preferred' section begins.

    Returns -1 if no preferred marker found.
    """
    text_lower = text.lower()
    earliest = -1
    for marker in _PREFERRED_MARKERS:
        idx = text_lower.find(marker)
        if idx != -1 and (earliest == -1 or idx < earliest):
            earliest = idx
    return earliest


def _extract_experience_years(text: str) -> str:
    """Extract experience years requirement from JD text.

    Returns strings like "5+", "3-5", "3", or "" if not found.
    """
    match = _EXPERIENCE_RE.search(text)
    if not match:
        return ""

    # Group 1: "at least/minimum N years"
    if match.group(1):
        return f"{match.group(1)}+"
    # Group 2: "N+ years"
    if match.group(2):
        return f"{match.group(2)}+"
    # Groups 3-4: "N-M years"
    if match.group(3) and match.group(4):
        return f"{match.group(3)}-{match.group(4)}"
    # Group 5: "N years of experience"
    if match.group(5):
        return match.group(5)

    return ""


def _extract_education_level(text: str) -> str:
    """Extract the highest education level mentioned in the JD."""
    text_lower = text.lower()
    for level, keywords in _EDUCATION_LEVELS:
        for kw in keywords:
            pattern = re.compile(
                rf"\b{re.escape(kw)}\b", re.IGNORECASE
            )
            if pattern.search(text_lower):
                return level
    return ""


def _extract_single_word_tech(text: str) -> list[str]:
    """Find single-word tech terms in the JD text."""
    found: list[str] = []
    for term, pattern in _TECH_PATTERNS.items():
        if pattern.search(text):
            found.append(term)
    found.sort()
    return found


def _extract_bullet_lines(text: str, limit: int = 8) -> list[str]:
    """Extract responsibility phrases from bullet-point lines.

    Returns the first `limit` bullet lines found in the JD.
    """
    lines = text.split("\n")
    bullets: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if not _BULLET_LINE_RE.match(line):
            continue

        # Strip the bullet prefix
        cleaned = re.sub(
            r"^\s*(?:[-*\u2022\u2023\u25E6\u2043\u2219]"
            r"|\d{1,2}[.)]\s)\s*",
            "",
            line,
        ).strip()

        if cleaned and len(cleaned) >= 15:
            bullets.append(cleaned)
            if len(bullets) >= limit:
                break

    return bullets


def _extract_competency_signals(
    text: str,
) -> dict[str, list[str]]:
    """Match COMPETENCY_KEYWORDS against JD text.

    Returns a dict mapping competency names to lists of matched
    keywords found in the text.
    """
    text_lower = text.lower()
    signals: dict[str, list[str]] = {}

    for competency, keywords in COMPETENCY_KEYWORDS.items():
        matched = [kw for kw in keywords if kw in text_lower]
        if matched:
            signals[competency] = matched

    return signals


# ── Main function ───────────────────────────────────────────────────────────

def preparse_job_description(
    description: str,
    skills: list[str] | None = None,
) -> dict:
    """Pre-parse a job description into structured fields.

    Pure regex/string matching, no LLM calls. Runs in ~50ms.

    Args:
        description: Raw job description text.
        skills: Optional list of skill tags from the job listing.

    Returns:
        Dict with required_skills, preferred_skills,
        single_word_skills, competency_signals, experience_years,
        education_level, key_responsibilities, and parsed_at.
    """
    if not description or not description.strip():
        return {
            "required_skills": [],
            "preferred_skills": [],
            "single_word_skills": [],
            "competency_signals": {},
            "experience_years": "",
            "education_level": "",
            "key_responsibilities": [],
            "parsed_at": datetime.now(timezone.utc).isoformat(),
        }

    # Split JD into required vs preferred sections
    split_idx = _find_preferred_split(description)

    if split_idx != -1:
        required_text = description[:split_idx]
        preferred_text = description[split_idx:]
    else:
        required_text = description
        preferred_text = ""

    # Extract multi-word skill phrases per section
    all_skills = extract_skill_phrases(description, skills)
    required_lower = required_text.lower()
    preferred_lower = preferred_text.lower()

    required_skills: list[str] = []
    preferred_skills: list[str] = []

    for skill in all_skills:
        skill_lower = skill.lower()
        parts = skill_lower.split()
        pattern = (
            r"\b"
            + r"[\s\-]+".join(re.escape(p) for p in parts)
            + r"\b"
        )

        in_preferred = (
            bool(re.search(pattern, preferred_lower))
            if preferred_text
            else False
        )
        in_required = bool(re.search(pattern, required_lower))

        if in_preferred and not in_required:
            preferred_skills.append(skill)
        else:
            required_skills.append(skill)

    # Single-word tech terms
    single_word = _extract_single_word_tech(description)

    # Competency signals
    competency_signals = _extract_competency_signals(description)

    # Experience years
    experience_years = _extract_experience_years(description)

    # Education level
    education_level = _extract_education_level(description)

    # Key responsibilities (bullet points)
    key_responsibilities = _extract_bullet_lines(description)

    return {
        "required_skills": required_skills,
        "preferred_skills": preferred_skills,
        "single_word_skills": single_word,
        "competency_signals": competency_signals,
        "experience_years": experience_years,
        "education_level": education_level,
        "key_responsibilities": key_responsibilities,
        "parsed_at": datetime.now(timezone.utc).isoformat(),
    }


# ── DB integration ──────────────────────────────────────────────────────────

def preparse_and_store(job_id: int, db) -> dict | None:
    """Load a ScrapedJob by ID, pre-parse its JD, store result.

    Stores the parsed data in the parsed_jd JSON column.
    Returns the parsed dict, or None if the job was not found.
    """
    from models import ScrapedJob

    job = (
        db.query(ScrapedJob)
        .filter(ScrapedJob.id == job_id)
        .first()
    )
    if not job:
        log.warning(f"Job ID {job_id} not found for pre-parsing")
        return None

    if not job.description:
        log.debug(f"Job ID {job_id} has no description, skipping")
        return None

    skills_list = (
        job.skills
        if isinstance(job.skills, list)
        else []
    )

    parsed = preparse_job_description(
        job.description, skills_list
    )

    # Store as JSON in the parsed_jd column via raw SQL
    # (column may or may not exist on the ORM model yet)
    try:
        from sqlalchemy import text

        db.execute(
            text(
                "UPDATE scraped_jobs "
                "SET parsed_jd = :data WHERE id = :jid"
            ),
            {"data": json.dumps(parsed), "jid": job_id},
        )
        db.commit()
        log.debug(f"Stored parsed_jd for job ID {job_id}")
    except Exception as exc:
        db.rollback()
        log.error(
            f"Failed to store parsed_jd for job ID {job_id}: "
            f"{exc}"
        )

    return parsed


def backfill_all(db, batch_size: int = 100) -> dict:
    """Backfill parsed_jd for all jobs where it is NULL.

    Processes in batches to avoid long-running transactions.

    Returns:
        Dict with stats: total, parsed, skipped, errors,
        elapsed_ms.
    """
    from sqlalchemy import text

    from models import ScrapedJob

    start = time.time()
    total = 0
    parsed_count = 0
    skipped = 0
    errors = 0

    # Ensure parsed_jd column exists (SQLite-safe)
    try:
        db.execute(
            text(
                "ALTER TABLE scraped_jobs "
                "ADD COLUMN parsed_jd TEXT"
            )
        )
        db.commit()
        log.info("Added parsed_jd column to scraped_jobs")
    except Exception:
        db.rollback()
        # Column already exists, that's fine

    offset = 0
    while True:
        jobs = (
            db.query(
                ScrapedJob.id,
                ScrapedJob.description,
                ScrapedJob.skills,
            )
            .filter(
                ScrapedJob.description != "",
                ScrapedJob.description.isnot(None),
            )
            .order_by(ScrapedJob.id)
            .offset(offset)
            .limit(batch_size)
            .all()
        )

        if not jobs:
            break

        for job_id, description, skills_raw in jobs:
            total += 1

            # Check if already parsed via raw SQL
            row = db.execute(
                text(
                    "SELECT parsed_jd FROM scraped_jobs "
                    "WHERE id = :jid"
                ),
                {"jid": job_id},
            ).fetchone()

            if row and row[0]:
                skipped += 1
                continue

            if not description or not description.strip():
                skipped += 1
                continue

            try:
                skills_list = (
                    skills_raw
                    if isinstance(skills_raw, list)
                    else []
                )
                parsed = preparse_job_description(
                    description, skills_list
                )
                db.execute(
                    text(
                        "UPDATE scraped_jobs "
                        "SET parsed_jd = :data WHERE id = :jid"
                    ),
                    {"data": json.dumps(parsed), "jid": job_id},
                )
                parsed_count += 1
            except Exception as exc:
                errors += 1
                log.error(
                    f"Failed to parse job ID {job_id}: {exc}"
                )

        db.commit()
        offset += batch_size

        log.info(
            f"Backfill progress: {total} processed, "
            f"{parsed_count} parsed, {skipped} skipped"
        )

    elapsed_ms = round((time.time() - start) * 1000)

    stats = {
        "total": total,
        "parsed": parsed_count,
        "skipped": skipped,
        "errors": errors,
        "elapsed_ms": elapsed_ms,
    }

    log.info(
        f"Backfill complete: {parsed_count}/{total} parsed "
        f"({skipped} skipped, {errors} errors) in {elapsed_ms}ms"
    )

    return stats
