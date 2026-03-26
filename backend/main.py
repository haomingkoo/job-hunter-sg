"""
FastAPI backend for Job Hunter SG.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import os
import random
import time
import concurrent.futures
import re
import secrets
import threading
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

from pathlib import Path

from fastapi import Cookie, Depends, FastAPI, File, Header, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import String, cast, func, or_, text
from sqlalchemy.orm import Session, load_only

from auth import (
    TIER_LIMITS,
    _PRO_DOMAINS,
    check_login_rate_limit,
    check_rate_limit,
    create_token,
    get_current_user,
    get_optional_user,
    hash_password,
    validate_password,
    verify_password,
)
from database import get_db, init_db
from models import ScrapedJob, TrackedJob, UsageLog, User, UserMemory
from sanitizer import sanitize_job, sanitize_resume_text, sanitize_user_input
from schemas import (
    AuthResponse,
    ContactRequest,
    IntegrateKeywordsRequest,
    JobOut,
    LoginRequest,
    RegenerateSummaryRequest,
    ResumeScoreRequest,
    RewriteBulletRequest,
    SearchResponse,
    SignupRequest,
    TierInfo,
    TrackedJobCreate,
    TrackedJobOut,
    TrackedJobUpdate,
    UserOut,
)
from ai_service import SEALION_MODEL, _call_sealion, coach_resume, get_ai_health, get_ai_status, integrate_keywords, rewrite_bullet
from ats_terms import build_job_ats_terms, match_resume_against_job_terms, merge_job_terms_with_match
from resume_parser import parse_resume
from resume_scorer import ResumeScorer
from resume_templates import generate_docx, inspect_resume_export, list_templates
from skill_extractor import extract_skill_phrases
from scraper import CareersGovScraper, JobAggregator, SSGSkillsFrameworkAPI, _clean_html
from tailoring_pipeline import get_pipeline_state, run_pipeline
from jd_preparser import preparse_job_description as preparse_jd
from jd_summary import summarize_job_description

log = logging.getLogger("jobhunter")

# Disable OpenAPI docs in production to reduce attack surface
_is_production = "postgresql" in os.environ.get("DATABASE_URL", "")

_CAREERSGOV_PATH_RE = re.compile(r"/en-US/PublicServiceCareers(/job/.+)$")
_JD_ENRICHMENT_IN_FLIGHT: set[int] = set()
_JD_ENRICHMENT_LOCK = threading.Lock()
_JD_ENRICHMENT_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=3)
_FAILED_RETRY_SECONDS = 300  # retry failed/unavailable summaries after 5 min

# ── Cached filter metadata (avoid 3 GROUP BY queries per page 1 load) ────────
_filter_meta_cache: dict = {}
_filter_meta_ts: float = 0.0
_FILTER_META_TTL = 300  # 5 minutes

# ── Cached analytics/skills response (avoid 70K row scan per request) ─────────
_analytics_cache: dict | None = None
_analytics_cache_ts: float = 0
_ANALYTICS_CACHE_TTL = 86400  # 24 hours - refreshed daily, invalidated on new scrape

# ── Per-user power-match cache (avoid recomputing every request) ──────────────
_power_match_cache: dict[int, dict] = {}
_POWER_MATCH_CACHE_TTL = 600  # 10 minutes


from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Startup and shutdown lifecycle for the app."""
    # ── Startup ──
    init_db()
    from database import SessionLocal

    # Auto-cleanup jobs older than 30 days
    try:
        db = SessionLocal()
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        stale = db.query(ScrapedJob).filter(
            ScrapedJob.scraped_at < cutoff.isoformat()
        ).count()
        if stale > 0:
            db.query(ScrapedJob).filter(
                ScrapedJob.scraped_at < cutoff.isoformat()
            ).delete()
            db.commit()
            log.info(f"Cleaned up {stale} stale jobs (older than 30 days)")
        db.close()
    except Exception as e:
        log.warning(f"Stale job cleanup failed: {e}")

    # Backfill sortable posted timestamps for existing rows.
    db_sort = SessionLocal()
    try:
        jobs_missing_sort = (
            db_sort.query(ScrapedJob)
            .filter(or_(ScrapedJob.posted_at_sort.is_(None), ScrapedJob.posted_at_sort == ""))
            .all()
        )
        if jobs_missing_sort:
            for job in jobs_missing_sort:
                job.posted_at_sort = _posted_sort_iso(job.posted_date, job.scraped_at)
            db_sort.commit()
            log.info("Backfilled posted_at_sort for %s jobs", len(jobs_missing_sort))
    except Exception as e:
        log.warning(f"posted_at_sort backfill failed: {e}")
    finally:
        db_sort.close()

    # Auto-create admin account if configured
    try:
        db2 = SessionLocal()
        admin_email = os.environ.get("ADMIN_EMAIL", "")
        admin_pw = os.environ.get("ADMIN_PASSWORD", "")
        if admin_email and admin_pw and not db2.query(User).filter(User.email == admin_email).first():
            admin = User(
                email=admin_email,
                password_hash=hash_password(admin_pw),
                name="Admin",
                tier="admin",
            )
            db2.add(admin)
            db2.commit()
            log.info("Admin account created")
        db2.close()
    except Exception as e:
        log.warning(f"Admin account creation failed: {e}")

    # Start idle summary filler in background
    _idle_filler_stop = threading.Event()

    def _idle_summary_filler() -> None:
        """Generate JD summaries when LLM is idle. Yields to user requests."""
        from database import SessionLocal as _SL
        from ai_service import _limiter, get_ai_health
        from jd_summary import summarize_job_description

        log.info("[IDLE-FILL] Background summary filler started")
        while not _idle_filler_stop.is_set():
            try:
                # Only run if AI is healthy and no queue pressure
                if not get_ai_health()["is_healthy"]:
                    _idle_filler_stop.wait(60)
                    continue
                if _limiter.queue_position > 0 or _limiter.wait_seconds > 2:
                    # Users are active - back off
                    _idle_filler_stop.wait(10)
                    continue

                db = _SL()
                try:
                    job = (
                        db.query(ScrapedJob)
                        .filter(
                            ScrapedJob.description != "",
                            ScrapedJob.parsed_jd.isnot(None),
                            (ScrapedJob.jd_summary.is_(None)) | (ScrapedJob.jd_summary == ""),
                        )
                        .filter(
                            (ScrapedJob.jd_summary_status.is_(None))
                            | (ScrapedJob.jd_summary_status == "")
                            | (ScrapedJob.jd_summary_status == "failed")
                        )
                        .order_by(ScrapedJob.id.desc())
                        .first()
                    )
                    if not job:
                        # All done - check again in 5 min
                        _idle_filler_stop.wait(300)
                        continue

                    # Double-check idle before making the API call
                    if _limiter.queue_position > 0:
                        _idle_filler_stop.wait(5)
                        continue

                    parsed = job.parsed_jd if isinstance(job.parsed_jd, dict) else {}
                    job.jd_summary_status = "generating"
                    db.commit()

                    summary, model_used = summarize_job_description(
                        job_title=job.title or "",
                        description=job.description or "",
                        parsed_jd=parsed,
                    )

                    now_iso = datetime.now(timezone.utc).isoformat()
                    if summary:
                        job.jd_summary = summary
                        job.jd_summary_generated_at = now_iso
                        job.jd_summary_status = model_used
                    else:
                        job.jd_summary_generated_at = now_iso
                        job.jd_summary_status = "unavailable"
                    db.commit()

                except Exception as exc:
                    log.warning(f"[IDLE-FILL] Summary failed: {exc}")
                    try:
                        db.rollback()
                    except Exception:
                        pass
                finally:
                    db.close()

                # Small pause between jobs to stay responsive
                _idle_filler_stop.wait(2)

            except Exception as exc:
                log.warning(f"[IDLE-FILL] Loop error: {exc}")
                _idle_filler_stop.wait(30)

    _filler_thread = threading.Thread(target=_idle_summary_filler, daemon=True)
    _filler_thread.start()

    yield  # App is running

    _idle_filler_stop.set()

    # ── Shutdown ──
    log.info("Shutting down Job Hunter SG API")
    _JD_ENRICHMENT_POOL.shutdown(wait=False, cancel_futures=True)


app = FastAPI(
    title="Job Hunter SG API",
    version="2.0.0",
    lifespan=lifespan,
    docs_url=None if _is_production else "/docs",
    redoc_url=None if _is_production else "/redoc",
    openapi_url=None if _is_production else "/openapi.json",
)

# ── CORS ─────────────────────────────────────────────────────────────────────

allowed_origins = [
    o.strip() for o in os.environ.get(
        "ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3000"
    ).split(",") if o.strip()
]
# SECURITY: Block wildcard CORS in production
if _is_production and "*" in allowed_origins:
    raise RuntimeError(
        "ALLOWED_ORIGINS must not be '*' in production. "
        "Set it to your frontend URL (e.g. https://jobhuntersg.com)."
    )
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# ── Singletons ───────────────────────────────────────────────────────────────

aggregator = JobAggregator()
ssg_api = SSGSkillsFrameworkAPI()
_scorer = ResumeScorer()

POWER_SKILL_TERMS = {
    "python", "sql", "excel", "tableau", "power bi", "aws", "azure", "gcp",
    "docker", "kubernetes", "terraform", "linux", "react", "typescript",
    "javascript", "java", "node.js", "node", "golang", "rust", "git",
    "ci/cd", "agile", "scrum", "project management", "stakeholder management",
    "roadmap", "analytics", "data analysis", "machine learning", "ai",
    "communication", "leadership", "change management", "quality", "spc",
    "six sigma", "manufacturing", "semulator3d", "jira", "salesforce",
    "figma", "product management", "program management", "root cause analysis",
    "semiconductor", "process integration", "process control", "yield engineering",
    "yield optimization", "yield ramp", "lithography", "metrology",
    "wafer fabrication", "fab operations", "product engineering operations",
    "front end operations", "quality systems", "eqms", "feol", "beol",
    "doe", "design of experiments", "virtual doe", "equipment engineering",
    "wet process development", "defect metrology", "hbm3e", "lpddr5x",
}

POWER_ALLOWED_SINGLE_SKILLS = {
    "python", "sql", "excel", "tableau", "aws", "azure", "gcp", "docker",
    "kubernetes", "terraform", "linux", "react", "typescript", "javascript",
    "java", "node", "golang", "rust", "git", "agile", "scrum", "analytics",
    "ai", "leadership", "quality", "spc", "jira", "manufacturing",
    "semiconductor", "lithography", "metrology", "yield", "automation",
    "reliability", "validation", "integration", "eqms", "feol", "beol",
    "doe", "semulator3d", "hbm3e", "lpddr5x",
}

POWER_NOISE_SKILLS = {
    "professional experience", "professional summary", "core skills",
    "core competencies", "technical skills", "additional information",
    "certification", "certifications", "education", "languages",
    "personal", "professional learning communities", "exit interviews",
    "loan processing", "medical study", "subject matter expert",
    "certifications & technical upskilling",
}

POWER_GENERIC_SINGLE_SKILLS = {
    "experience", "professional", "organization", "performance", "development",
    "transformation", "documentation", "collaboration", "validation",
    "automation", "leadership", "engineering", "integration",
}

POWER_DISPLAY_SINGLE_SKILLS = {
    "python", "sql", "excel", "tableau", "aws", "azure", "gcp", "docker",
    "kubernetes", "react", "typescript", "javascript", "java", "agile",
    "analytics", "ai", "spc", "jira", "semiconductor", "lithography",
    "metrology", "eqms", "doe", "semulator3d", "hbm3e", "lpddr5x",
    "feol", "beol",
}

POWER_DISPLAY_EXCLUDE = POWER_NOISE_SKILLS | {
    "professional experience", "professional summary", "technical skills",
    "core skills", "core competencies", "additional information",
    "standardized documentation", "documentation", "organization",
    "performance", "development", "transformation", "integration",
    "automation", "leadership", "reliability", "engineering", "validation",
    "collaboration", "certifications", "professional",
}

SEMICONDUCTOR_DOMAIN_TERMS = {
    "semiconductor", "process integration", "process control",
    "yield engineering", "yield optimization", "yield ramp", "lithography",
    "metrology", "wafer fabrication", "fab operations", "product engineering operations",
    "front end operations", "quality systems", "eqms", "spc", "root cause analysis",
    "design of experiments", "virtual doe", "equipment engineering",
    "wet process development", "defect metrology", "feol", "beol",
    "semulator3d", "hbm3e", "lpddr5x",
}

SEMICONDUCTOR_HARD_TERMS = {
    "semiconductor", "semiconductor manufacturing", "process integration",
    "process control", "yield engineering", "yield optimization", "yield ramp",
    "lithography", "metrology", "wafer fabrication", "fab operations",
    "product engineering operations", "front end operations", "quality systems",
    "eqms", "root cause analysis", "design of experiments", "virtual doe",
    "equipment engineering", "wet process development", "defect metrology",
    "feol", "beol", "semulator3d", "hbm3e", "lpddr5x",
}

POWER_ROLE_STOPWORDS = {
    "the", "and", "for", "with", "from", "lead", "senior", "junior", "staff",
    "principal", "manager", "engineer", "executive", "associate", "specialist",
    "analyst", "intern", "contract", "full", "time", "part", "level",
}

POWER_BRIDGE_LIBRARY = [
    {
        "title": "Cloud & DevOps bridge",
        "keywords": {"aws", "azure", "gcp", "docker", "kubernetes", "terraform", "linux", "ci/cd"},
        "suggestion": "Bridge this with cloud foundations, one deployment lab, and one shipped project artifact before you prioritise similar roles.",
    },
    {
        "title": "Data & analytics bridge",
        "keywords": {"sql", "python", "tableau", "power bi", "excel", "analytics", "data analysis", "etl"},
        "suggestion": "Bridge this with an analytics short course, a dashboard or SQL portfolio sample, and one quantified resume bullet.",
    },
    {
        "title": "Software engineering bridge",
        "keywords": {"react", "typescript", "javascript", "java", "node", "node.js", "golang", "rust", "git"},
        "suggestion": "Bridge this with a hands-on build, repository evidence, and one project bullet that shows delivery, testing, and ownership.",
    },
    {
        "title": "Product & delivery bridge",
        "keywords": {"product management", "program management", "project management", "roadmap", "stakeholder management", "agile", "scrum", "jira"},
        "suggestion": "Bridge this with delivery case studies, roadmap artifacts, and examples that show prioritisation, cross-functional work, and measurable outcomes.",
    },
    {
        "title": "Operations & quality bridge",
        "keywords": {"quality", "spc", "six sigma", "manufacturing", "root cause analysis", "change management"},
        "suggestion": "Bridge this with process-improvement coursework, one before/after case study, and quantified quality or efficiency wins.",
    },
]



# Startup logic moved to lifespan() context manager above.


def _normalize_skill_strings(raw_skills) -> list[str]:
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
        cleaned = re.sub(r"\s+", " ", skill).strip(" -•\t")
        lower = cleaned.lower()
        if not cleaned or len(cleaned) < 2 or len(cleaned) > 60:
            continue
        if lower in seen:
            continue
        seen.add(lower)
        deduped.append(cleaned)
    return deduped


def _is_power_skill_noise(skill: str) -> bool:
    lower = re.sub(r"\s+", " ", (skill or "").strip().lower())
    if not lower:
        return True
    if lower in POWER_NOISE_SKILLS:
        return True
    if lower in POWER_GENERIC_SINGLE_SKILLS and lower not in POWER_ALLOWED_SINGLE_SKILLS:
        return True
    if len(lower.split()) == 1 and lower not in POWER_ALLOWED_SINGLE_SKILLS:
        return True
    return False


def _clean_power_skills(skills: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for skill in skills:
        normalized = re.sub(r"\s+", " ", (skill or "").strip())
        lower = normalized.lower()
        if not normalized or lower in seen or _is_power_skill_noise(normalized):
            continue
        seen.add(lower)
        cleaned.append(normalized)
    return cleaned


def _is_power_surface_noise(skill: str) -> bool:
    lower = re.sub(r"\s+", " ", (skill or "").strip().lower())
    if not lower:
        return True
    if lower in POWER_DISPLAY_EXCLUDE:
        return True
    if re.fullmatch(r"(professional|work|core|technical|additional|selected)\s+(experience|summary|skills?|competencies|information|projects?)", lower):
        return True
    if len(lower.split()) == 1 and lower not in POWER_DISPLAY_SINGLE_SKILLS:
        return True
    return False


def _surface_power_skills(skills: list[str], limit: int = 24) -> list[str]:
    surfaced: list[str] = []
    seen: set[str] = set()
    ranked = sorted(
        skills,
        key=lambda skill: (
            0 if skill.lower() in SEMICONDUCTOR_HARD_TERMS else 1,
            0 if len(skill.split()) >= 2 else 1,
            -len(skill.split()),
            skill.lower(),
        ),
    )
    for skill in ranked:
        normalized = re.sub(r"\s+", " ", (skill or "").strip())
        lower = normalized.lower()
        if not normalized or lower in seen or _is_power_surface_noise(normalized):
            continue
        seen.add(lower)
        surfaced.append(normalized)
        if len(surfaced) >= limit:
            break
    return surfaced


def _extract_job_match_skills(job: ScrapedJob, db: Session) -> list[str]:
    return [
        term["skill"] if isinstance(term, dict) else str(term)
        for term in _build_canonical_job_terms(job, db)
    ]


def _build_canonical_job_terms(job: ScrapedJob, db: Session | None = None) -> list[dict]:
    """Build a canonical ATS term list for a job.

    Parsed JD stays primary, but the shared ats_terms helper also layers in
    source tags, title hints, and safe single-word technical terms so score,
    job match, and Power Match stop drifting.
    """
    db_skills = _normalize_skill_strings(job.skills)
    parsed_jd = job.parsed_jd if isinstance(job.parsed_jd, dict) else None

    if not parsed_jd and (job.description or "").strip():
        parsed_jd = preparse_jd(
            job.description,
            skills=db_skills,
            db_session=db,
            job_title=job.title or "",
        )
        job.parsed_jd = parsed_jd
        if db is not None:
            db.flush()

    terms = build_job_ats_terms(
        jd_text=job.description or "",
        job_skills=db_skills,
        parsed_jd=parsed_jd,
        job_title=job.title or "",
        limit=24,
        db_session=db,
    )

    return [
        term for term in terms
        if not _is_power_skill_noise(term.get("skill", ""))
    ]


def _count_domain_hits(terms: list[str], domain_terms: set[str]) -> int:
    return sum(1 for term in terms if term.lower() in domain_terms)


def _parse_job_posted_at(posted_date: str, scraped_at: str = "") -> datetime:
    raw = str(posted_date or "").strip()
    lowered = raw.lower()
    now = datetime.now(timezone.utc)

    if lowered:
        if "today" in lowered:
            return now
        if "yesterday" in lowered:
            return now - timedelta(days=1)

        relative_patterns = (
            (r"(\d+)\s*\+?\s*hour", "hours"),
            (r"(\d+)\s*\+?\s*day", "days"),
            (r"(\d+)\s*\+?\s*week", "weeks"),
            (r"(\d+)\s*\+?\s*month", "months"),
        )
        for pattern, unit in relative_patterns:
            match = re.search(pattern, lowered)
            if not match:
                continue
            amount = int(match.group(1))
            if unit == "months":
                return now - timedelta(days=amount * 30)
            return now - timedelta(**{unit: amount})

        normalized = raw.replace("Z", "+00:00")
        for candidate in (normalized, normalized.split("T")[0]):
            try:
                parsed = datetime.fromisoformat(candidate)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.astimezone(timezone.utc)
            except ValueError:
                pass

        for fmt in ("%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y", "%Y/%m/%d", "%d/%m/%Y"):
            try:
                return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                pass

    if scraped_at:
        normalized_scraped = scraped_at.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized_scraped)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            pass

    return datetime.fromtimestamp(0, tz=timezone.utc)


def _posted_sort_iso(posted_date: str, scraped_at: str = "") -> str:
    return _parse_job_posted_at(posted_date, scraped_at).isoformat()


def _get_or_create_memory(user: Optional[User], db: Session) -> Optional[UserMemory]:
    if not user:
        return None
    mem = db.query(UserMemory).filter(UserMemory.user_id == user.id).first()
    if not mem:
        mem = UserMemory(user_id=user.id)
        db.add(mem)
        db.flush()
    return mem


def _persist_resume_to_memory(user: Optional[User], db: Session, resume_text: str) -> None:
    if not user or not resume_text.strip():
        return
    mem = _get_or_create_memory(user, db)
    if not mem:
        return
    mem.resume_text = sanitize_resume_text(resume_text)[:10000]
    _power_match_cache.pop(user.id, None)
    db.flush()


def _extract_careersgov_external_path(url: str) -> str:
    match = _CAREERSGOV_PATH_RE.search(url or "")
    return match.group(1) if match else ""


def _extract_careersgov_skills(detail: dict) -> list[str]:
    skills: list[str] = []
    for tag_section in detail.get("skillTags", []):
        if isinstance(tag_section, str):
            skills.append(tag_section)
        elif isinstance(tag_section, dict):
            value = tag_section.get("name", "")
            if value:
                skills.append(value)
    if not skills:
        tag_line = detail.get("tagLine", "")
        if tag_line:
            skills = [s.strip() for s in tag_line.split(",") if s.strip()]
    deduped: list[str] = []
    seen: set[str] = set()
    for skill in skills:
        normalized = re.sub(r"\s+", " ", (skill or "").strip())
        lowered = normalized.lower()
        if not normalized or lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(normalized)
    return deduped


def _has_rich_job_terms(terms: list[dict]) -> bool:
    useful = 0
    for term in terms or []:
        skill = re.sub(r"\s+", " ", str(term.get("skill", "")).strip())
        if not skill:
            continue
        if term.get("technical"):
            useful += 1
            continue
        if len(skill.split()) >= 2 and term.get("source") != "competency":
            useful += 1
    return useful >= 4


def _derive_careersgov_skill_cues(
    *,
    title: str,
    description: str,
    skills: list[str],
    db: Session,
) -> tuple[list[str], dict]:
    parsed = preparse_jd(
        description,
        skills=skills,
        db_session=db,
        job_title=title,
    )
    terms = build_job_ats_terms(
        jd_text=description,
        job_skills=skills,
        parsed_jd=parsed,
        job_title=title,
        limit=12,
        db_session=db,
    )
    cues: list[str] = []
    seen: set[str] = set()
    for term in terms:
        label = re.sub(r"\s+", " ", str(term.get("skill", "")).strip())
        lower = label.lower()
        if not label or lower in seen:
            continue
        if not (term.get("technical") or len(label.split()) >= 2):
            continue
        seen.add(lower)
        cues.append(label)
        if len(cues) >= 10:
            break
    return cues, parsed


def _title_case_skill(skill: str) -> str:
    """Title-case a skill label, preserving acronyms and known casing."""
    if not skill:
        return skill
    # Already has mixed case (e.g., "Power BI", "JavaScript") - keep it
    if skill != skill.lower() and skill != skill.upper():
        return skill
    # Known acronyms to preserve
    _ACRONYMS = {"ai", "ml", "bi", "hr", "it", "ux", "ui", "qa", "pm", "sql",
                 "api", "aws", "gcp", "ci", "cd", "iot", "erp", "crm", "sop",
                 "kpi", "roi", "seo", "cet", "amr", "dna", "wsq"}
    words = skill.split()
    result = []
    for w in words:
        if w.lower() in _ACRONYMS:
            result.append(w.upper())
        elif w.lower() in {"and", "&", "of", "for", "in", "to", "the", "with", "on", "or"}:
            result.append(w.lower())
        else:
            result.append(w.capitalize())
    # Always capitalize first word
    if result:
        result[0] = result[0].capitalize() if result[0] == result[0].lower() else result[0]
    return " ".join(result)


def _job_term_labels(terms: list[dict], limit: int = 8) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()
    for term in terms or []:
        raw = re.sub(r"\s+", " ", str(term.get("skill", "")).strip())
        lower = raw.lower()
        if not raw or lower in seen:
            continue
        seen.add(lower)
        labels.append(_title_case_skill(raw))
        if len(labels) >= limit:
            break
    return labels


def _compute_and_cache_term_preview(
    job: ScrapedJob,
    db: Session,
    *,
    limit: int = 8,
) -> list[str]:
    """Compute job_terms_preview, store it on the row, return labels."""
    terms = _build_canonical_job_terms(job, db)
    labels = _job_term_labels(terms, limit=limit)
    job.job_terms_preview = labels
    return labels


def _enrich_job_background(job_id: int) -> None:
    """Background worker: generate JD summary + cache term preview."""
    from database import SessionLocal

    db = SessionLocal()
    try:
        job = db.query(ScrapedJob).filter(ScrapedJob.id == job_id).first()
        if not job or not (job.description or "").strip():
            return

        # --- term preview ---
        if not job.job_terms_preview:
            _compute_and_cache_term_preview(job, db)
            db.commit()

        # --- JD summary (skip if already done) ---
        if (job.jd_summary or "").strip():
            return

        parsed = job.parsed_jd if isinstance(job.parsed_jd, dict) and job.parsed_jd else preparse_jd(
            job.description or "",
            skills=job.skills if isinstance(job.skills, list) else [],
            db_session=db,
            job_title=job.title or "",
        )
        if parsed and parsed != (job.parsed_jd or {}):
            job.parsed_jd = parsed

        job.jd_summary_status = "generating"
        db.commit()

        summary, model_used = summarize_job_description(
            job_title=job.title or "",
            description=job.description or "",
            parsed_jd=parsed,
        )

        now_iso = datetime.now(timezone.utc).isoformat()
        if summary:
            job.jd_summary = summary
            job.jd_summary_generated_at = now_iso
            job.jd_summary_status = model_used
        else:
            job.jd_summary_generated_at = now_iso
            job.jd_summary_status = "unavailable"
        db.commit()
    except Exception as exc:
        log.warning("JD enrichment failed for job_id=%s: %s", job_id, exc)
        try:
            db.rollback()
            job = db.query(ScrapedJob).filter(ScrapedJob.id == job_id).first()
            if job and not (job.jd_summary or "").strip():
                job.jd_summary_status = "failed"
                job.jd_summary_generated_at = datetime.now(timezone.utc).isoformat()
                db.commit()
        except Exception:
            pass
    finally:
        db.close()
        with _JD_ENRICHMENT_LOCK:
            _JD_ENRICHMENT_IN_FLIGHT.discard(job_id)


def _should_queue_enrichment(job: ScrapedJob) -> bool:
    """Check if this job needs background enrichment (summary or preview)."""
    if not job or not job.id or not (job.description or "").strip():
        return False
    needs_preview = not job.job_terms_preview
    needs_summary = not (job.jd_summary or "").strip()
    if not needs_preview and not needs_summary:
        return False
    # Allow retry for failed/unavailable summaries after cooldown
    status = (job.jd_summary_status or "").strip()
    if status in ("failed", "unavailable"):
        generated_at = job.jd_summary_generated_at or ""
        if generated_at:
            try:
                attempted_at = datetime.fromisoformat(generated_at)
                if (datetime.now(timezone.utc) - attempted_at).total_seconds() < _FAILED_RETRY_SECONDS:
                    return needs_preview  # only queue if preview still needed
            except (ValueError, TypeError):
                pass
    if status == "generating":
        return needs_preview  # already in progress for summary
    return True


def _queue_enrichment_if_needed(job: ScrapedJob) -> None:
    if not _should_queue_enrichment(job):
        return
    if not get_ai_health()["is_healthy"]:
        return
    with _JD_ENRICHMENT_LOCK:
        if job.id in _JD_ENRICHMENT_IN_FLIGHT:
            return
        if len(_JD_ENRICHMENT_IN_FLIGHT) >= 50:
            return
        _JD_ENRICHMENT_IN_FLIGHT.add(job.id)
    _JD_ENRICHMENT_POOL.submit(_enrich_job_background, job.id)


def _refresh_careersgov_terms_if_weak(job: ScrapedJob, db: Session) -> bool:
    if not job or job.source != "Careers@Gov" or not (job.description or "").strip():
        return False

    current_terms = _build_canonical_job_terms(job, db)
    if _has_rich_job_terms(current_terms):
        return False

    existing_skills = job.skills if isinstance(job.skills, list) else []
    derived_skills, parsed = _derive_careersgov_skill_cues(
        title=job.title or "",
        description=job.description or "",
        skills=existing_skills,
        db=db,
    )

    changed = False
    if parsed and parsed != (job.parsed_jd or {}):
        job.parsed_jd = parsed
        changed = True
    if derived_skills and derived_skills != existing_skills:
        job.skills = derived_skills
        changed = True
    if changed:
        _compute_and_cache_term_preview(job, db)
    return changed


def _enrich_careersgov_job(job: ScrapedJob, db: Session) -> bool:
    if not job or job.source != "Careers@Gov":
        return False
    external_path = _extract_careersgov_external_path(job.url or "")
    if not external_path:
        return False

    scraper = CareersGovScraper()
    detail = scraper.get_job_detail(external_path)
    if not detail:
        return False

    updated = False
    description = _clean_html(detail.get("jobDescription", ""))
    if description and description != (job.description or ""):
        job.description = description
        updated = True

    skills = _extract_careersgov_skills(detail)
    if skills and skills != (job.skills or []):
        job.skills = skills
        updated = True

    agency = detail.get("companyName", "") or detail.get("company", "")
    if agency and agency != (job.agency or ""):
        job.agency = agency
        updated = True

    if job.description:
        skills_list = job.skills if isinstance(job.skills, list) else []
        derived_skills, parsed = _derive_careersgov_skill_cues(
            title=job.title or "",
            description=job.description or "",
            skills=skills_list,
            db=db,
        )
        if parsed and parsed != (job.parsed_jd or {}):
            job.parsed_jd = parsed
            updated = True
        if derived_skills and derived_skills != skills_list:
            job.skills = derived_skills
            updated = True
    expected_sort = _posted_sort_iso(job.posted_date, job.scraped_at)
    if expected_sort != (job.posted_at_sort or ""):
        job.posted_at_sort = expected_sort
        updated = True
    if updated and job.description:
        _compute_and_cache_term_preview(job, db)
    return updated


def _hydrate_missing_careersgov_jobs(jobs: list, db: Session) -> int:
    target_ids: list[int] = []
    for job in jobs:
        source = getattr(job, "source", None)
        description = getattr(job, "description", None)
        job_id = getattr(job, "id", None)
        skills = getattr(job, "skills", None)
        parsed_jd = getattr(job, "parsed_jd", None)
        if (
            source == "Careers@Gov"
            and job_id is not None
            and (
                not (description or "").strip()
                or not (skills or [])
                or parsed_jd in (None, {})
            )
        ):
            target_ids.append(job_id)
    if not target_ids:
        return 0

    targets = (
        db.query(ScrapedJob)
        .filter(ScrapedJob.id.in_(target_ids))
        .all()
    )
    if not targets:
        return 0

    log.info("Hydrating %s Careers@Gov jobs with missing descriptions", len(targets))
    detail_results: dict[int, dict] = {}

    with ThreadPoolExecutor(max_workers=min(4, len(targets))) as pool:
        future_map = {}
        for job in targets:
            external_path = _extract_careersgov_external_path(job.url or "")
            if not external_path:
                continue
            future = pool.submit(CareersGovScraper().get_job_detail, external_path)
            future_map[future] = job.id

        for future in as_completed(future_map):
            job_id = future_map[future]
            try:
                detail_results[job_id] = future.result() or {}
            except Exception as exc:
                log.warning("Careers@Gov hydration failed for job_id=%s: %s", job_id, exc)

    updated = 0
    for job in targets:
        detail = detail_results.get(job.id)
        if not detail:
            continue
        description = _clean_html(detail.get("jobDescription", ""))
        if description:
            job.description = description
        skills = _extract_careersgov_skills(detail)
        if skills:
            job.skills = skills
        agency = detail.get("companyName", "") or detail.get("company", "")
        if agency:
            job.agency = agency
        if description:
            skills_list = job.skills if isinstance(job.skills, list) else []
            job.parsed_jd = preparse_jd(description, skills=skills_list)
        expected_sort = _posted_sort_iso(job.posted_date, job.scraped_at)
        if expected_sort != (job.posted_at_sort or ""):
            job.posted_at_sort = expected_sort
        updated += 1

    if updated:
        db.commit()
        log.info("Hydrated %s Careers@Gov jobs on-demand", updated)
    return updated


def _extract_resume_skills(resume_text: str, db: Session) -> tuple[list[str], str]:
    lower_text = resume_text.lower()
    extracted = extract_skill_phrases(
        resume_text,
        db_session=db,
        use_dynamic_skills=True,
    )
    supplemental: list[str] = []
    for skill in POWER_SKILL_TERMS:
        pattern = rf"(?<![a-z0-9]){re.escape(skill.lower())}(?![a-z0-9])"
        if re.search(pattern, lower_text):
            supplemental.append(skill)

    matched = _clean_power_skills(extracted + supplemental)
    if matched:
        ranked = sorted(
            matched,
            key=lambda skill: (
                0 if skill.lower() in SEMICONDUCTOR_DOMAIN_TERMS else 1,
                -len(skill.split()),
                skill.lower(),
            ),
        )
        return ranked[:30], "skill_corpus"

    fallback_terms = re.findall(r"\b[A-Z][A-Za-z0-9+#.]{2,}\b", resume_text)
    fallback_deduped: list[str] = []
    fallback_seen: set[str] = set()
    for term in fallback_terms:
        lower = term.lower()
        if lower in fallback_seen:
            continue
        fallback_seen.add(lower)
        fallback_deduped.append(term)
    return fallback_deduped[:20], "fallback_terms"


def _select_power_match_candidates(
    db: Session,
    resume_text: str,
    resume_skills: list[str],
    limit: int = 500,
) -> list[ScrapedJob]:
    hard_resume_terms = [
        skill for skill in resume_skills
        if skill.lower() in SEMICONDUCTOR_HARD_TERMS
    ]
    prioritized_terms = hard_resume_terms[:8] + [
        skill for skill in resume_skills[:12]
        if skill.lower() not in {term.lower() for term in hard_resume_terms[:8]}
    ]
    lower_resume = resume_text.lower()
    for term in SEMICONDUCTOR_HARD_TERMS:
        if term in lower_resume and term not in prioritized_terms:
            prioritized_terms.append(term)
        if len(prioritized_terms) >= 16:
            break

    prioritized_terms = [
        term for term in prioritized_terms
        if term and not _is_power_skill_noise(term)
    ]

    if not prioritized_terms:
        return db.query(ScrapedJob).order_by(ScrapedJob.id.desc()).limit(limit).all()

    conditions = []
    for term in prioritized_terms:
        pattern = f"%{term}%"
        conditions.extend(
            [
                ScrapedJob.title.ilike(pattern),
                ScrapedJob.search_keyword.ilike(pattern),
                cast(ScrapedJob.skills, String).ilike(pattern),
            ]
        )

    matched_jobs = (
        db.query(ScrapedJob)
        .filter(or_(*conditions))
        .order_by(ScrapedJob.id.desc())
        .limit(limit)
        .all()
    )

    if len(matched_jobs) >= min(80, limit):
        return matched_jobs

    seen_ids = {job.id for job in matched_jobs}
    backfill_jobs = (
        db.query(ScrapedJob)
        .order_by(ScrapedJob.id.desc())
        .limit(max(100, limit // 2))
        .all()
    )
    for job in backfill_jobs:
        if job.id in seen_ids:
            continue
        matched_jobs.append(job)
        seen_ids.add(job.id)
        if len(matched_jobs) >= limit:
            break

    return matched_jobs


def _extract_title_terms(title: str) -> list[str]:
    return [
        word for word in re.findall(r"[a-zA-Z][a-zA-Z+#.]{2,}", title.lower())
        if word not in POWER_ROLE_STOPWORDS
    ]


def _infer_resume_level(resume_text: str) -> int:
    lower = resume_text.lower()
    years_match = re.search(r"(\d+)\+?\s+years?", lower)
    years = int(years_match.group(1)) if years_match else 0

    if any(term in lower for term in {"vice president", "vp", "director", "head of", "general manager"}):
        return 5
    if any(term in lower for term in {"senior manager", "program manager", "manager", "principal", "lead"}):
        return 4
    if any(term in lower for term in {"senior engineer", "staff engineer", "senior executive", "professional"}):
        return 3
    if years >= 8:
        return 4
    if years >= 4:
        return 3
    if years >= 1:
        return 2
    return 1


def _infer_job_level(job: ScrapedJob) -> int:
    combined = f"{job.seniority or ''} {job.title or ''}".lower()
    if any(term in combined for term in {"vice president", "vp", "director", "head of", "general manager", "senior management"}):
        return 5
    if any(term in combined for term in {"senior manager", "manager", "principal", "lead"}):
        return 4
    if any(term in combined for term in {"senior executive", "staff", "professional", "engineer", "analyst", "specialist", "executive"}):
        return 3
    if any(term in combined for term in {"junior", "associate", "technician", "entry", "fresh", "non-executive"}):
        return 2
    if "intern" in combined:
        return 1
    return 3


def _build_bridge_plan(missing_skills: list[str]) -> list[dict]:
    plans: list[dict] = []
    seen_titles: set[str] = set()
    for skill in missing_skills[:6]:
        lower_skill = skill.lower()
        matched_path = None
        for path in POWER_BRIDGE_LIBRARY:
            if any(keyword in lower_skill for keyword in path["keywords"]):
                matched_path = path
                break

        if matched_path:
            if matched_path["title"] in seen_titles:
                continue
            seen_titles.add(matched_path["title"])
            plans.append({
                "skill": skill,
                "pathway": matched_path["title"],
                "suggestion": matched_path["suggestion"],
            })
        else:
            plans.append({
                "skill": skill,
                "pathway": "Role-specific bridging",
                "suggestion": f"Bridge {skill} with one short course, one practice project, and one credible resume bullet before prioritising similar roles.",
            })
        if len(plans) >= 3:
            break
    return plans


# ── Admin: Protected seed/refresh endpoint ────────────────────────────────────

_ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY", "")


@app.post("/api/admin/seed")
def admin_seed_jobs(
    body: dict,
    authorization: Optional[str] = Header(None),
) -> dict:
    """
    Trigger a job re-seed. Protected by ADMIN_API_KEY.
    Body: {sources: "mcf,careersgov", limit: 20, keywords: "software engineer,data analyst"}
    Or {full: true} for full crawl.

    Can be called by a Railway cron job or manually.
    """
    # Check admin API key
    token = ""
    if authorization:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1]
    if not _ADMIN_API_KEY or token != _ADMIN_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid admin API key")

    import threading
    from seed_jobs import seed_jobs, crawl_all_jobs

    if body.get("full"):
        # Run full crawl in background thread
        threading.Thread(target=crawl_all_jobs, daemon=True).start()
        return {"status": "started", "mode": "full_crawl", "message": "Full crawl started in background"}
    else:
        sources = body.get("sources", "mcf,careersgov").split(",")
        limit = body.get("limit", 20)
        keywords = body.get("keywords", "").split(",") if body.get("keywords") else None

        def run_seed():
            seed_jobs(keywords=keywords or [], sources=sources, limit_per_source=limit)

        threading.Thread(target=run_seed, daemon=True).start()
        return {"status": "started", "mode": "keyword_seed", "sources": sources, "limit": limit}


_backfill_progress: dict = {
    "running": False,
    "phase": "",
    "started_at": "",
    "preview_done": 0,
    "preview_total": 0,
    "summary_done": 0,
    "summary_failed": 0,
    "summary_total": 0,
    "rate_per_min": 0.0,
    "eta_minutes": 0.0,
    "last_updated": "",
}
_backfill_progress_lock = threading.Lock()


def _update_backfill_progress(**kwargs: object) -> None:
    with _backfill_progress_lock:
        _backfill_progress.update(kwargs)
        _backfill_progress["last_updated"] = datetime.now(timezone.utc).isoformat()


@app.get("/api/admin/backfill/status")
def admin_backfill_status(
    authorization: Optional[str] = Header(None),
) -> dict:
    """
    Get enrichment status. Protected by ADMIN_API_KEY.
    Returns progress, coverage stats, and ETA.
    """
    token = ""
    if authorization:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1]
    if not _ADMIN_API_KEY or token != _ADMIN_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid admin API key")

    from database import SessionLocal as _SessionLocal
    db = _SessionLocal()
    try:
        total = db.query(func.count(ScrapedJob.id)).scalar()
        has_desc = db.query(func.count(ScrapedJob.id)).filter(
            ScrapedJob.description != "", ScrapedJob.description.isnot(None)
        ).scalar()
        has_parsed = db.query(func.count(ScrapedJob.id)).filter(
            ScrapedJob.parsed_jd.isnot(None)
        ).scalar()
        has_preview = db.query(func.count(ScrapedJob.id)).filter(
            ScrapedJob.job_terms_preview.isnot(None)
        ).scalar()
        has_summary = db.query(func.count(ScrapedJob.id)).filter(
            ScrapedJob.jd_summary != "", ScrapedJob.jd_summary.isnot(None)
        ).scalar()
        summary_failed = db.query(func.count(ScrapedJob.id)).filter(
            ScrapedJob.jd_summary_status.in_(["failed", "unavailable"])
        ).scalar()
        summary_generating = db.query(func.count(ScrapedJob.id)).filter(
            ScrapedJob.jd_summary_status == "generating"
        ).scalar()
    finally:
        db.close()

    with _backfill_progress_lock:
        progress = dict(_backfill_progress)

    return {
        "coverage": {
            "total_jobs": total,
            "have_description": has_desc,
            "have_parsed_jd": has_parsed,
            "have_preview": has_preview,
            "have_summary": has_summary,
            "summary_failed": summary_failed,
            "summary_generating": summary_generating,
            "need_preview": has_desc - has_preview,
            "need_summary": max(0, has_desc - has_summary - summary_failed),
            "preview_pct": round(has_preview / max(1, has_desc) * 100, 1),
            "summary_pct": round(has_summary / max(1, has_desc) * 100, 1),
        },
        "backfill": progress,
    }


@app.get("/api/admin/jd-analysis")
def admin_jd_analysis(
    authorization: Optional[str] = Header(None),
    flag_type: str = "all",
    limit: int = 50,
) -> dict:
    """
    Get flagged JDs and quality stats. Protected by ADMIN_API_KEY.
    flag_type: "all", "injection", "red_flag", "low_quality", "duplicates"
    """
    token = ""
    if authorization:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1]
    if not _ADMIN_API_KEY or token != _ADMIN_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid admin API key")

    from jd_analyzer import compute_content_hash

    db = SessionLocal()
    try:
        # Get all jobs with analysis
        jobs_with_analysis = (
            db.query(ScrapedJob)
            .filter(ScrapedJob.parsed_jd.isnot(None))
            .all()
        )

        flagged: list[dict] = []
        quality_scores: list[int] = []
        content_hashes: dict[str, list[dict]] = {}
        injection_count = 0
        red_flag_count = 0

        for job in jobs_with_analysis:
            parsed = job.parsed_jd if isinstance(job.parsed_jd, dict) else {}
            analysis = parsed.get("_analysis", {})
            if not analysis or analysis.get("skipped"):
                continue

            quality = analysis.get("quality", {})
            score = quality.get("score", 0)
            quality_scores.append(score)

            # Track duplicates by content hash
            ch = analysis.get("content_hash", "")
            if ch:
                if ch not in content_hashes:
                    content_hashes[ch] = []
                content_hashes[ch].append({
                    "id": job.id,
                    "title": job.title,
                    "company": job.company,
                    "agency": job.agency or "",
                })

            has_injection = analysis.get("has_injection", False)
            has_red_flags = analysis.get("has_red_flags", False)
            if has_injection:
                injection_count += 1
            if has_red_flags:
                red_flag_count += 1

            should_include = False
            if flag_type == "all" and (has_injection or has_red_flags or score < 30):
                should_include = True
            elif flag_type == "injection" and has_injection:
                should_include = True
            elif flag_type == "red_flag" and has_red_flags:
                should_include = True
            elif flag_type == "low_quality" and score < 30:
                should_include = True

            if should_include and len(flagged) < limit:
                flagged.append({
                    "id": job.id,
                    "title": job.title,
                    "company": job.company,
                    "agency": job.agency or "",
                    "source": job.source,
                    "quality_score": score,
                    "injection_findings": analysis.get("prompt_injection", []),
                    "red_flags": analysis.get("red_flags", []),
                })

        # Find actual duplicates (same hash, multiple jobs)
        duplicates = [
            {"content_hash": h, "count": len(jobs), "jobs": jobs[:5]}
            for h, jobs in sorted(content_hashes.items(), key=lambda x: -len(x[1]))
            if len(jobs) > 1
        ]

        # Quality distribution
        total_analyzed = len(quality_scores)
        quality_dist = {
            "excellent_70_plus": sum(1 for s in quality_scores if s >= 70),
            "good_50_69": sum(1 for s in quality_scores if 50 <= s < 70),
            "fair_30_49": sum(1 for s in quality_scores if 30 <= s < 50),
            "poor_below_30": sum(1 for s in quality_scores if s < 30),
            "avg_score": round(sum(quality_scores) / max(1, total_analyzed), 1),
        }

        return {
            "summary": {
                "total_analyzed": total_analyzed,
                "injection_detected": injection_count,
                "red_flags_detected": red_flag_count,
                "duplicate_groups": len(duplicates),
                "duplicate_jobs": sum(d["count"] for d in duplicates),
                "quality_distribution": quality_dist,
            },
            "flagged_jobs": flagged[:limit],
            "top_duplicates": duplicates[:20] if flag_type in ("all", "duplicates") else [],
        }
    finally:
        db.close()


@app.post("/api/admin/backfill")
def admin_backfill_enrichment(
    body: dict,
    authorization: Optional[str] = Header(None),
) -> dict:
    """
    Trigger JD enrichment backfill. Protected by ADMIN_API_KEY.
    Body: {preview_only: true}  -- parsed_jd + term preview only (no LLM)
           {summary_limit: 500} -- limit summary generation count
           {}                   -- full backfill (preview + all summaries)
    """
    token = ""
    if authorization:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1]
    if not _ADMIN_API_KEY or token != _ADMIN_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid admin API key")

    with _backfill_progress_lock:
        if _backfill_progress.get("running"):
            return {"status": "already_running", "backfill": dict(_backfill_progress)}
        _backfill_progress["running"] = True

    from backfill_enrichment import backfill_previews, backfill_summaries

    preview_only = body.get("preview_only", False)
    summary_limit = body.get("summary_limit", 0)
    refresh_preview = body.get("refresh_preview", False)
    reparse = body.get("reparse", False)

    def run_backfill() -> None:
        _update_backfill_progress(
            running=True,
            phase="preview",
            started_at=datetime.now(timezone.utc).isoformat(),
            preview_done=0, preview_total=0,
            summary_done=0, summary_failed=0, summary_total=0,
            rate_per_min=0.0, eta_minutes=0.0,
        )
        try:
            backfill_previews(
                progress_callback=_update_backfill_progress,
                refresh_preview=refresh_preview,
                reparse=reparse,
            )
            if not preview_only:
                _update_backfill_progress(phase="summary")
                backfill_summaries(
                    limit=summary_limit,
                    progress_callback=_update_backfill_progress,
                )
        finally:
            _update_backfill_progress(running=False, phase="done")

    threading.Thread(target=run_backfill, daemon=True).start()
    return {
        "status": "started",
        "mode": "preview_only" if preview_only else "full",
        "summary_limit": summary_limit,
    }


@app.post("/api/admin/rebuild-skills-taxonomy")
def admin_rebuild_skills_taxonomy(
    body: dict | None = None,
    authorization: Optional[str] = Header(None),
) -> dict:
    """
    Rebuild the frequency-based learned skills taxonomy (Tier 2).
    Scans all job_terms_preview data and saves terms appearing in 50+ jobs.
    Body: {threshold: 50}  -- optional custom threshold
    """
    token = ""
    if authorization:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1]
    if not _ADMIN_API_KEY or token != _ADMIN_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid admin API key")

    from build_learned_skills import build_learned_skills, save_learned_skills
    from database import SessionLocal

    threshold = (body or {}).get("threshold", 50)
    db = SessionLocal()
    try:
        result = build_learned_skills(db, threshold=threshold)
        save_learned_skills(result)
    finally:
        db.close()

    return {
        "status": "completed",
        "total_jobs_scanned": result["total_jobs_scanned"],
        "tier2_skills_count": len(result["skills"]),
        "threshold": threshold,
        "generated_at": result["generated_at"],
    }


# ── Health ───────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health(db: Session = Depends(get_db)) -> dict:
    try:
        db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception:
        db_status = "error"
    return {"status": "ok", "service": "Job Hunter SG API", "db": db_status}


@app.get("/api/privacy")
def privacy() -> Response:
    """Privacy notice — returns a readable HTML page, not raw JSON."""
    contact = os.environ.get("CONTACT_EMAIL", "")
    contact_line = f"reach out at {contact}" if contact else "use the contact form on the Account page"
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Privacy Notice — Job Hunter SG</title>
<style>body{{font-family:-apple-system,system-ui,sans-serif;max-width:680px;margin:40px auto;padding:0 20px;color:#333;line-height:1.7}}
h1{{color:#4f46e5}}h2{{color:#1e293b;margin-top:2em}}p{{margin:0.5em 0}}.updated{{color:#94a3b8;font-size:0.85em}}</style></head>
<body>
<h1>How We Handle Your Data</h1>
<p class="updated">Last updated: 24 March 2026</p>

<h2>What We Store</h2>
<p>When you create an account, we store your email and name. Your password is hashed (one-way encryption) — we never store or see your actual password. When you use our AI resume features, we store your resume text to personalise your coaching experience across sessions. Your tracked job applications and notes are also stored.</p>

<h2>Why We Store Your Resume</h2>
<p>Your resume is stored solely to power the Memory feature — so our AI coach can remember your background, strengths, and goals across sessions. Your resume data will <strong>NOT</strong> be used for any other purpose.</p>

<h2>What We Don't Do</h2>
<p>We do <strong>NOT</strong> sell, share, or disclose your personal data to any third party. We do <strong>NOT</strong> use your resume to train AI models. We do <strong>NOT</strong> show your data to other users. Your data is never used for advertising or marketing purposes.</p>

<h2>AI Processing</h2>
<p>When you use AI features (resume review, bullet rewriting, formatting), your resume text is sent to an AI model for processing. The AI does not retain your data after generating a response.</p>

<h2>Your Control</h2>
<p>You can view everything we know about you via the Memory page. You can edit or delete any stored information at any time. You can delete your entire memory with one click. If you want your account and all data permanently removed, contact us and we will delete everything.</p>

<h2>Contact</h2>
<p>Job Hunter SG is built to help job seekers in Singapore. If you have any questions or concerns about your data, {contact_line}.</p>
</body></html>"""
    return Response(content=html, media_type="text/html")


# ═════════════════════════════════════════════════════════════════════════════
# AUTH
# ═════════════════════════════════════════════════════════════════════════════

@app.post("/api/auth/signup", response_model=AuthResponse)
def signup(body: SignupRequest, db: Session = Depends(get_db)) -> dict:
    # Rate limit signup attempts (abuse prevention)
    check_rate_limit(None, "search", db)
    validate_password(body.password)
    existing = db.query(User).filter(User.email == body.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )
    # Pro-tier email domains get upgraded automatically
    domain = body.email.split("@")[-1].lower()
    tier = "pro" if domain in _PRO_DOMAINS else "free"

    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        name=sanitize_user_input(body.name),
        tier=tier,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_token(user.id)
    return {"token": token, "user": user}


@app.post("/api/auth/login", response_model=AuthResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> dict:
    _email_hash = hashlib.sha256(body.email.lower().encode()).hexdigest()[:16]
    check_login_rate_limit(_email_hash, db)
    user = db.query(User).filter(User.email == body.email).first()
    if not user or not verify_password(body.password, user.password_hash):
        db.add(UsageLog(user_id=None, action="login_failed", detail=_email_hash))
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    user.last_login = datetime.now(timezone.utc)
    db.commit()
    token = create_token(user.id)
    return {"token": token, "user": user}


@app.get("/api/auth/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user


# ═════════════════════════════════════════════════════════════════════════════
# JOB SEARCH
# ═════════════════════════════════════════════════════════════════════════════

@app.get("/api/search", response_model=SearchResponse)
def search_jobs(
    q: str = Query(..., min_length=1, max_length=200, description="Search keyword"),
    sources: Optional[str] = Query(
        None,
        max_length=200,
        description="Comma-separated: mcf,careersgov,nodeflair,indeed,jobstreet",
    ),
    limit: int = Query(20, ge=1, le=100),
    skills: bool = Query(True, description="Enrich with SSG skills"),
    user: Optional[User] = Depends(get_optional_user),
    db: Session = Depends(get_db),
) -> dict:
    # Rate limit
    check_rate_limit(user, "search", db)

    # Log usage (sanitize search query before storing)
    usage = UsageLog(
        user_id=user.id if user else None,
        action="search",
        detail=sanitize_user_input(q),
    )
    db.add(usage)
    db.commit()

    source_list = [s.strip() for s in sources.split(",") if s.strip()] if sources else None

    results = aggregator.search_all(
        keyword=q,
        sources=source_list,
        limit_per_source=limit,
        enrich_skills=skills,
    )

    # Sanitize and cache jobs
    sanitized_jobs: list[dict] = []
    for job in results["jobs"]:
        raw = asdict(job)
        raw["dedup_key"] = job.dedup_key  # Property not included by asdict()
        clean = sanitize_job(raw)
        clean["search_keyword"] = sanitize_user_input(q)
        clean["posted_at_sort"] = _posted_sort_iso(clean.get("posted_date", ""), clean.get("scraped_at", ""))

        # Upsert into scraped_jobs by dedup_key
        existing = (
            db.query(ScrapedJob)
            .filter(ScrapedJob.dedup_key == clean["dedup_key"])
            .first()
        )
        if existing:
            for key, val in clean.items():
                if key not in ("id",):
                    setattr(existing, key, val)
            db.flush()
            clean["id"] = existing.id
        else:
            new_job = ScrapedJob(**clean)
            db.add(new_job)
            db.flush()
            clean["id"] = new_job.id

        sanitized_jobs.append(clean)

    db.commit()

    return {
        "keyword": results["keyword"],
        "searched_at": results["searched_at"],
        "total_raw": results["total_raw"],
        "total_deduped": results["total_deduped"],
        "duplicates_removed": results["duplicates_removed"],
        "ssg_recommended_skills": results["ssg_recommended_skills"],
        "by_source": results["by_source"],
        "jobs": sanitized_jobs,
    }


@app.get("/api/skills/trending")
def trending_skills(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[dict]:
    """Get most common skill phrases across all scraped JDs."""
    from skill_extractor import get_trending_skills
    return get_trending_skills(db, limit=limit)


# ── Sector classification keywords ────────────────────────────────────────────
_SECTOR_KEYWORDS: dict[str, list[str]] = {
    "Engineering": [
        "engineer", "engineering", "mechanical", "electrical", "civil",
        "structural", "chemical", "hardware", "firmware", "embedded",
    ],
    "IT / Tech": [
        "software", "developer", "devops", "sre", "cloud", "fullstack",
        "full-stack", "full stack", "frontend", "front-end", "backend",
        "back-end", "programmer", "sysadmin", "it ", "information technology",
        "cybersecurity", "cyber security", "infrastructure", "platform",
        "solutions architect", "tech lead", "technical lead",
    ],
    "Data & AI": [
        "data", "machine learning", "ml ", "ai ", "artificial intelligence",
        "analytics", "business intelligence", "bi ", "data scientist",
        "data engineer", "data analyst", "nlp", "deep learning",
    ],
    "Finance & Accounting": [
        "finance", "financial", "accountant", "accounting", "audit",
        "tax", "treasury", "credit", "banking", "investment", "fund",
        "compliance", "risk", "actuary", "actuarial",
    ],
    "Healthcare": [
        "nurse", "nursing", "doctor", "medical", "healthcare",
        "health care", "clinical", "pharmacy", "pharmacist",
        "therapist", "physiotherapist", "dental", "dentist",
    ],
    "Sales & Marketing": [
        "sales", "marketing", "business development", "account manager",
        "brand", "digital marketing", "seo", "sem ", "content",
        "communications", "public relations", "pr ", "advertising",
        "growth", "partnership",
    ],
    "Admin & Operations": [
        "admin", "administrator", "operations", "coordinator",
        "executive assistant", "office", "receptionist", "clerk",
        "procurement", "supply chain", "logistics", "warehouse",
    ],
    "Design & Creative": [
        "designer", "design", "ux", "ui ", "graphic", "creative",
        "art director", "visual", "illustrator", "copywriter",
    ],
    "HR & Recruitment": [
        "human resource", "hr ", "recruiter", "recruitment", "talent",
        "people", "compensation", "benefits", "payroll", "hrbp",
    ],
    "Education & Training": [
        "teacher", "lecturer", "professor", "trainer", "training",
        "education", "tutor", "curriculum", "instructor", "teaching",
    ],
    "Legal": [
        "lawyer", "legal", "counsel", "paralegal", "litigation",
        "contract", "regulatory",
    ],
    "Product & Project Management": [
        "product manager", "project manager", "scrum", "agile",
        "program manager", "product owner", "delivery manager",
    ],
}


def _classify_sector(title: str) -> str:
    """Classify a job title into a broad sector. Returns 'Other' if no match."""
    lower = f" {title.lower()} "
    for sector, keywords in _SECTOR_KEYWORDS.items():
        for kw in keywords:
            if kw in lower:
                return sector
    return "Other"


def _normalize_title(raw_title: str) -> str:
    """Normalize a job title for grouping (strip seniority prefixes, title case)."""
    import re
    t = raw_title.strip()
    # Remove common prefix patterns like "Senior ", "Junior ", "Lead ", etc.
    t = re.sub(
        r"^(Senior|Junior|Jr\.?|Sr\.?|Lead|Principal|Staff|Chief|Head of|"
        r"Associate|Assistant|Intern\b)[,\s]+",
        "", t, flags=re.IGNORECASE,
    ).strip()
    # Collapse multiple spaces
    t = re.sub(r"\s+", " ", t)
    # Title case normalization (fix "PROJECT ENGINEER" -> "Project Engineer")
    _SMALL_WORDS = {"a", "an", "and", "as", "at", "by", "for", "from", "in", "of", "on", "or", "the", "to", "with"}
    if t == t.upper() or t == t.lower():
        words = t.split()
        t = " ".join(
            w.lower() if w.lower() in _SMALL_WORDS and i > 0 else w.capitalize()
            for i, w in enumerate(words)
        )
    return t


@app.get("/api/analytics/skills")
def analytics_skills(
    limit: int = Query(50, ge=1, le=200),
    source: str | None = Query(None, max_length=50),
    q: str | None = Query(None, max_length=100),
    sector: str | None = Query(None, max_length=100),
    company: str | None = Query(None, max_length=200),
    title: str | None = Query(None, max_length=200),
    db: Session = Depends(get_db),
) -> dict:
    """Aggregate ATS skill demand, top titles, and sectors from scraped jobs."""
    global _analytics_cache, _analytics_cache_ts

    has_filter = source or sector or company or title

    # Serve from cache when no filters and cache is fresh
    if not has_filter and _analytics_cache is not None:
        if time.time() - _analytics_cache_ts < _ANALYTICS_CACHE_TTL:
            cached = _analytics_cache
            all_skills = cached["_all_skills"]
            if q:
                q_lower = q.lower()
                all_skills = [
                    s for s in all_skills
                    if q_lower in s["skill"].lower()
                ]
            return {
                "top_skills": all_skills[:limit],
                "total_jobs_with_terms": cached["total_jobs_with_terms"],
                "sources": cached["sources"],
                "top_titles": cached["top_titles"],
                "sectors": cached["sectors"],
                "top_companies": cached.get("top_companies", []),
            }

    db_query = db.query(ScrapedJob).filter(
        ScrapedJob.job_terms_preview.isnot(None),
    )
    if source:
        db_query = db_query.filter(ScrapedJob.source == source)
    if company:
        db_query = db_query.filter(
            ScrapedJob.company.ilike(f"%{company}%")
        )
    if title:
        db_query = db_query.filter(
            ScrapedJob.title.ilike(f"%{title}%")
        )

    skill_counts: dict[str, int] = {}
    source_counts: dict[str, int] = {}
    title_counts: dict[str, int] = {}
    sector_counts: dict[str, int] = {}
    company_counts: dict[str, int] = {}
    total_jobs = 0

    for job in db_query.yield_per(500):
        preview = job.job_terms_preview
        if not isinstance(preview, list) or not preview:
            continue

        # Sector filter: classify title and skip if not matching
        raw_title = (job.title or "").strip()
        if sector and raw_title:
            job_sector = _classify_sector(raw_title)
            if job_sector.lower() != sector.lower():
                continue

        total_jobs += 1

        src = job.source or "Unknown"
        source_counts[src] = source_counts.get(src, 0) + 1

        # Company aggregation
        comp = (job.company or "").strip()
        if comp:
            comp_key = comp.lower()
            if comp_key not in company_counts:
                company_counts[comp_key] = {"display": comp, "count": 0}
            company_counts[comp_key]["count"] += 1

        for term in preview:
            label = str(term).strip()
            if not label:
                continue
            key = label.lower()
            skill_counts[key] = skill_counts.get(key, 0) + 1

        # Aggregate title and sector
        if raw_title:
            norm = _normalize_title(raw_title)
            title_key = norm.lower()
            if title_key:
                if title_key not in title_counts:
                    title_counts[title_key] = {"display": norm, "count": 0}
                title_counts[title_key]["count"] += 1

            job_sector = _classify_sector(raw_title)
            sector_counts[job_sector] = sector_counts.get(job_sector, 0) + 1

    # Sort by count descending
    sorted_skills = sorted(skill_counts.items(), key=lambda x: -x[1])

    all_skills = [
        {"skill": term.title() if term == term.lower() else term, "count": count}
        for term, count in sorted_skills
    ]

    sources_list = [
        {"source": s, "count": c}
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

    # Cache the full result when no filters active
    if not has_filter:
        _analytics_cache = {
            "_all_skills": all_skills,
            "total_jobs_with_terms": total_jobs,
            "sources": sources_list,
            "top_titles": top_titles,
            "sectors": sectors,
            "top_companies": top_companies,
        }
        _analytics_cache_ts = time.time()

    # Apply skill search filter if provided
    filtered_skills = all_skills
    if q:
        q_lower = q.lower()
        filtered_skills = [
            s for s in all_skills if q_lower in s["skill"].lower()
        ]

    return {
        "top_skills": filtered_skills[:limit],
        "total_jobs_with_terms": total_jobs,
        "sources": sources_list,
        "top_titles": top_titles,
        "sectors": sectors,
        "top_companies": top_companies,
    }


@app.get("/api/jobs")
def list_cached_jobs(
    q: Optional[str] = Query(None, max_length=200, description="Filter by keyword"),
    employment_type: Optional[str] = Query(None, max_length=100),
    seniority: Optional[str] = Query(None, max_length=100),
    source: Optional[str] = Query(None, max_length=100),
    location: Optional[str] = Query(None, max_length=200),
    min_salary: Optional[int] = Query(None, ge=0),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict:
    def salary_floor(value: str) -> int:
        numbers = [int(part.replace(",", "")) for part in re.findall(r"\d[\d,]*", value or "")]
        return numbers[0] if numbers else 0

    query = db.query(ScrapedJob).options(
        load_only(
            ScrapedJob.id,
            ScrapedJob.title,
            ScrapedJob.company,
            ScrapedJob.location,
            ScrapedJob.salary,
            ScrapedJob.source,
            ScrapedJob.url,
            ScrapedJob.posted_date,
            ScrapedJob.employment_type,
            ScrapedJob.seniority,
            ScrapedJob.description,
            ScrapedJob.skills,
            ScrapedJob.agency,
            ScrapedJob.scraped_at,
            ScrapedJob.posted_at_sort,
            ScrapedJob.parsed_jd,
            ScrapedJob.jd_summary,
            ScrapedJob.jd_summary_status,
            ScrapedJob.jd_summary_generated_at,
            ScrapedJob.job_terms_preview,
        )
    )
    if q:
        # Split query into words — match ALL words (AND logic)
        # "micron i4" matches jobs with BOTH "micron" AND "i4" anywhere
        words = [w.strip() for w in q.split() if w.strip()]
        for word in words:
            word_pattern = f"%{word}%"
            query = query.filter(
                or_(
                    ScrapedJob.title.ilike(word_pattern),
                    ScrapedJob.company.ilike(word_pattern),
                    ScrapedJob.description.ilike(word_pattern),
                    ScrapedJob.search_keyword.ilike(word_pattern),
                    cast(ScrapedJob.skills, String).ilike(word_pattern),
                )
            )
    if employment_type:
        query = query.filter(ScrapedJob.employment_type.ilike(f"%{employment_type}%"))
    if seniority:
        query = query.filter(ScrapedJob.seniority.ilike(f"%{seniority}%"))
    if source:
        query = query.filter(ScrapedJob.source.ilike(f"%{source}%"))
    if location:
        query = query.filter(ScrapedJob.location.ilike(f"%{location}%"))

    offset = (page - 1) * per_page

    ordered_query = query.order_by(ScrapedJob.posted_at_sort.desc(), ScrapedJob.id.desc())

    if min_salary is None:
        total = query.count()
        jobs = ordered_query.offset(offset).limit(per_page).all()
    else:
        jobs = ordered_query.all()
        salary_matched = [job for job in jobs if salary_floor(job.salary) >= min_salary]
        salary_unknown = [job for job in jobs if salary_floor(job.salary) == 0]
        jobs = salary_matched + salary_unknown
        total = len(jobs)
        jobs = jobs[offset: offset + per_page]

    # Queue CareersGov hydration in background (don't block the response)
    cgov_missing = [
        j.id for j in jobs
        if j.source == "Careers@Gov" and (
            not (j.description or "").strip()
            or not (j.skills or [])
            or j.parsed_jd in (None, {})
        )
    ]
    if cgov_missing:
        def _bg_hydrate(job_ids: list[int]) -> None:
            from database import SessionLocal as _SL
            bg_db = _SL()
            try:
                _hydrate_missing_careersgov_jobs(
                    bg_db.query(ScrapedJob).filter(ScrapedJob.id.in_(job_ids)).all(),
                    bg_db,
                )
            finally:
                bg_db.close()
        _JD_ENRICHMENT_POOL.submit(_bg_hydrate, cgov_missing)

    refreshed_terms = False
    queued_count = 0
    for job in jobs:
        expected_sort = _posted_sort_iso(job.posted_date, job.scraped_at)
        if expected_sort != (job.posted_at_sort or ""):
            job.posted_at_sort = expected_sort
            refreshed_terms = True
        if job.source == "Careers@Gov" and _refresh_careersgov_terms_if_weak(job, db):
            refreshed_terms = True
            job.job_terms_preview = None  # invalidate stale cache
        if not (job.job_terms_preview or []) and (job.description or "").strip():
            preview = _compute_and_cache_term_preview(job, db)
            if preview:
                refreshed_terms = True
        if queued_count < 3 and _should_queue_enrichment(job):
            _queue_enrichment_if_needed(job)
            queued_count += 1

    if refreshed_terms:
        db.commit()

    # Build filter metadata (cached for 5 min to avoid 3 GROUP BY per page 1)
    filter_meta = {}
    if page == 1:
        global _filter_meta_cache, _filter_meta_ts
        now = time.monotonic()
        if _filter_meta_cache and (now - _filter_meta_ts) < _FILTER_META_TTL:
            filter_meta = _filter_meta_cache
        else:
            source_counts = (
                db.query(ScrapedJob.source, func.count())
                .filter(ScrapedJob.source != "")
                .group_by(ScrapedJob.source)
                .all()
            )
            emp_counts = (
                db.query(ScrapedJob.employment_type, func.count())
                .filter(ScrapedJob.employment_type != "")
                .group_by(ScrapedJob.employment_type)
                .all()
            )
            loc_counts = (
                db.query(ScrapedJob.location, func.count())
                .filter(ScrapedJob.location != "", ScrapedJob.location != "Singapore")
                .group_by(ScrapedJob.location)
                .order_by(func.count().desc())
                .limit(30)
                .all()
            )
            filter_meta = {
                "sources": [{"value": s, "count": c} for s, c in source_counts if s],
                "employment_types": [{"value": t, "count": c} for t, c in emp_counts if t],
                "locations": [{"value": loc, "count": c} for loc, c in loc_counts if loc],
            }
            _filter_meta_cache = filter_meta
            _filter_meta_ts = now

    return {
        "jobs": [
            {
                "id": j.id, "title": j.title, "company": j.company,
                "location": j.location, "salary": j.salary, "source": j.source,
                "url": j.url, "posted_date": j.posted_date,
                "employment_type": j.employment_type, "seniority": j.seniority,
                "description": j.description, "skills": j.skills or [],
                "job_terms_preview": j.job_terms_preview or [],
                "job_terms_preview_ready": j.job_terms_preview is not None,
                "jd_summary": j.jd_summary or "",
                "jd_summary_status": j.jd_summary_status or "",
                "experience_years": (j.parsed_jd or {}).get("experience_years", "") if isinstance(j.parsed_jd, dict) else "",
                "agency": j.agency, "scraped_at": j.scraped_at,
            }
            for j in jobs
        ],
        "total": total,
        "page": page,
        "pages": max(1, (total + per_page - 1) // per_page),
        "filter_meta": filter_meta,
    }


@app.get("/api/jobs/{job_id}/similar", response_model=list[JobOut])
def get_similar_jobs(
    job_id: int,
    limit: int = Query(5, ge=1, le=20),
    db: Session = Depends(get_db),
) -> list[ScrapedJob]:
    """Find similar jobs based on title keywords and skills overlap."""
    job = db.query(ScrapedJob).filter(ScrapedJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Extract key words from title (remove common filler)
    filler = {"senior", "junior", "lead", "staff", "principal", "intern", "contract", "the", "a", "an", "at", "in", "for", "and", "or"}
    title_words = [w.lower() for w in re.sub(r"[^a-zA-Z\s]", "", job.title).split() if w.lower() not in filler and len(w) > 2]

    if not title_words:
        return []

    # Build query: match any title keyword, exclude the same job
    conditions = [ScrapedJob.title.ilike(f"%{w}%") for w in title_words[:3]]
    similar = (
        db.query(ScrapedJob)
        .filter(ScrapedJob.id != job_id, or_(*conditions))
        .order_by(ScrapedJob.id.desc())
        .limit(limit)
        .all()
    )
    return similar


@app.get("/api/jobs/recommended", response_model=list[JobOut])
def get_recommended_jobs(
    resume_text: str = Query("", max_length=5000, description="Resume text or skills to match against"),
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
) -> list[ScrapedJob]:
    """
    Recommend jobs based on resume text or skills.
    Searches cached jobs for keyword matches from the resume.
    """
    if not resume_text or len(resume_text) < 20:
        raise HTTPException(
            status_code=400,
            detail="resume_text is required for recommendations. No fallback list is returned.",
        )

    # Extract likely skill keywords from the resume (capitalized words, tech terms)
    # Find capitalized multi-letter words and common tech terms
    words = set(re.findall(r'\b[A-Z][a-zA-Z+#.]{2,}\b', resume_text))
    # Also grab common tech keywords
    tech_terms = {"python", "java", "react", "node", "sql", "aws", "docker", "kubernetes",
                  "typescript", "javascript", "golang", "rust", "pytorch", "tensorflow",
                  "data", "machine learning", "devops", "cloud", "agile", "scrum"}
    lower_text = resume_text.lower()
    for term in tech_terms:
        if term in lower_text:
            words.add(term)

    if not words:
        return []

    # Search for jobs matching these keywords
    conditions = []
    for word in list(words)[:10]:  # Top 10 keywords
        conditions.append(ScrapedJob.title.ilike(f"%{word}%"))
        conditions.append(ScrapedJob.description.ilike(f"%{word}%"))

    results = (
        db.query(ScrapedJob)
        .filter(or_(*conditions))
        .order_by(ScrapedJob.id.desc())
        .limit(limit)
        .all()
    )

    # Deduplicate by dedup_key (in case the same job matched multiple keywords)
    seen = set()
    deduped = []
    for job in results:
        if job.dedup_key not in seen:
            seen.add(job.dedup_key)
            deduped.append(job)

    return deduped[:limit]


@app.get("/api/jobs/power-match")
def get_power_match(
    limit: int = Query(8, ge=1, le=20),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """
    Power-match cached jobs against the logged-in user's latest resume.
    Returns suitability, gaps, and bridge suggestions.
    """
    cached = _power_match_cache.get(user.id)
    if cached and time.monotonic() - cached["_ts"] < _POWER_MATCH_CACHE_TTL:
        return cached["data"]

    mem = db.query(UserMemory).filter(UserMemory.user_id == user.id).first()
    resume_text = (mem.resume_text or "").strip() if mem else ""
    if len(resume_text) < 50:
        return {
            "resume_ready": False,
            "message": "Upload or score a resume first so we can build your power matches.",
            "resume_skills": [],
            "top_gaps": [],
            "recommendations": [],
        }

    resume_skills, resume_signal_mode = _extract_resume_skills(resume_text, db)
    resume_skill_lookup = {skill.lower(): skill for skill in resume_skills}
    lower_resume = resume_text.lower()
    resume_level = _infer_resume_level(resume_text)

    candidate_jobs = _select_power_match_candidates(
        db=db,
        resume_text=resume_text,
        resume_skills=resume_skills,
        limit=200,
    )

    # Precompute resume-side domain hits (same for every job)
    resume_domain_hits = _count_domain_hits(resume_skills, SEMICONDUCTOR_DOMAIN_TERMS)
    resume_hard_hits = _count_domain_hits(resume_skills, SEMICONDUCTOR_HARD_TERMS)

    recommendations: list[dict] = []
    for job in candidate_jobs:
        # Use cached job_terms_preview when available (fast path),
        # fall back to full extraction only when needed
        preview = job.job_terms_preview
        if isinstance(preview, list) and preview:
            job_skills = [str(s) for s in preview if s]
        else:
            job_skills = _extract_job_match_skills(job, db)
        matched_skills = [
            skill for skill in job_skills
            if skill.lower() in resume_skill_lookup or skill.lower() in lower_resume
        ]
        missing_skills = [
            skill for skill in job_skills
            if skill.lower() not in resume_skill_lookup and skill.lower() not in lower_resume
        ]
        title_terms = _extract_title_terms(job.title)
        title_hits = [term for term in title_terms if term in lower_resume]
        job_domain_hits = _count_domain_hits(job_skills + title_terms, SEMICONDUCTOR_DOMAIN_TERMS)
        matched_domain_hits = _count_domain_hits(matched_skills + title_hits, SEMICONDUCTOR_DOMAIN_TERMS)
        job_hard_hits = _count_domain_hits(job_skills + title_terms, SEMICONDUCTOR_HARD_TERMS)
        matched_hard_hits = _count_domain_hits(matched_skills + title_hits, SEMICONDUCTOR_HARD_TERMS)
        job_level = _infer_job_level(job)
        level_text = f"{job.seniority or ''} {job.title or ''}".lower()

        if not matched_skills and not title_hits and not job_skills:
            continue

        skill_score = (len(matched_skills) / max(3, min(len(job_skills), 8))) * 72 if job_skills else 0
        title_score = min(18, len(title_hits) * 6)
        description_bonus = min(
            10,
            sum(1 for skill in matched_skills[:4] if skill.lower() in (job.description or "").lower()) * 3,
        ) if matched_skills else 0
        domain_bonus = 0
        domain_penalty = 0
        level_bonus = 0
        level_penalty = 0
        if resume_hard_hits > 0 and job_hard_hits > 0:
            domain_bonus = min(20, max(8, matched_hard_hits * 5 or 8))
        elif resume_domain_hits > 0 and job_domain_hits > 0:
            domain_bonus = min(10, max(4, matched_domain_hits * 3 or 4))
        if resume_hard_hits > 0 and job_hard_hits == 0:
            domain_penalty = 12
        level_gap = resume_level - job_level
        if abs(level_gap) <= 1:
            level_bonus = 4
        elif level_gap >= 2:
            level_penalty = min(18, level_gap * 7)
        elif level_gap <= -2:
            level_penalty = min(8, abs(level_gap) * 3)
        low_level_role = resume_level >= 4 and any(
            term in level_text
            for term in {"technician", "assistant", "associate", "entry", "fresh", "junior", "non-executive"}
        )
        if low_level_role:
            level_penalty = max(level_penalty, 24)
        suitability_score = round(
            min(
                98,
                max(
                    0,
                    skill_score
                    + title_score
                    + description_bonus
                    + domain_bonus
                    + level_bonus
                    - domain_penalty
                    - level_penalty,
                ),
            )
        )
        if low_level_role:
            suitability_score = min(suitability_score, 48)

        if suitability_score < 18:
            continue

        if suitability_score >= 75:
            suitability_label = "Strong Match"
        elif suitability_score >= 55:
            suitability_label = "Good Match"
        elif suitability_score >= 35:
            suitability_label = "Stretch Match"
        else:
            suitability_label = "Explore"

        if matched_hard_hits > 0:
            why = f"Semiconductor-domain overlap in {', '.join((matched_skills + title_hits)[:3])}."
        elif matched_domain_hits > 0:
            why = f"Domain overlap in {', '.join((matched_skills + title_hits)[:3])}."
        elif matched_skills:
            why = f"Matches on {', '.join(matched_skills[:3])}."
        elif title_hits:
            why = f"Your resume aligns with {', '.join(title_hits[:3])} from the role title."
        else:
            why = "Worth exploring, but the skill signal is still light."

        surfaced_matched_skills = _surface_power_skills(matched_skills, limit=6)
        surfaced_missing_skills = _surface_power_skills(missing_skills, limit=6)

        recommendations.append({
            "job": {
                "id": job.id,
                "title": job.title,
                "company": job.company,
                "location": job.location,
                "salary": job.salary,
                "source": job.source,
                "url": job.url,
                "posted_date": job.posted_date,
                "employment_type": job.employment_type,
                "seniority": job.seniority,
                "description": job.description,
                "skills": job.skills or [],
                "agency": job.agency,
                "scraped_at": job.scraped_at,
            },
            "suitability_score": suitability_score,
            "suitability_label": suitability_label,
            "matched_skills": surfaced_matched_skills,
            "missing_skills": surfaced_missing_skills,
            "why": why,
            "bridge_plan": _build_bridge_plan(surfaced_missing_skills or missing_skills),
        })

    recommendations.sort(
        key=lambda item: (
            item["suitability_score"],
            len(item["matched_skills"]),
            item["job"]["id"],
        ),
        reverse=True,
    )
    recommendations = recommendations[:limit]

    top_gap_counts = Counter(
        skill
        for item in recommendations
        for skill in item["missing_skills"][:3]
    )
    top_gaps = [
        {"skill": skill, "count": count}
        for skill, count in top_gap_counts.most_common(8)
        if count >= 2 and not _is_power_surface_noise(skill)
    ]

    recommended_queries = []
    seen_queries = set()
    for item in recommendations:
        if item["suitability_score"] < 50:
            continue
        title = item["job"]["title"]
        if title in seen_queries:
            continue
        seen_queries.add(title)
        recommended_queries.append(title)
        if len(recommended_queries) >= 5:
            break

    result = {
        "resume_ready": True,
        "message": "Power matches generated from your latest stored resume.",
        "resume_signal_mode": resume_signal_mode,
        "resume_skills": _surface_power_skills(resume_skills, limit=24),
        "top_gaps": top_gaps,
        "recommended_queries": recommended_queries,
        "recommendations": recommendations,
    }
    _power_match_cache[user.id] = {"data": result, "_ts": time.monotonic()}
    return result


@app.get("/api/jobs/{job_id}", response_model=JobOut)
def get_cached_job(job_id: int, db: Session = Depends(get_db)) -> ScrapedJob:
    job = db.query(ScrapedJob).filter(ScrapedJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.source == "Careers@Gov" and not (job.description or "").strip():
        _enrich_careersgov_job(job, db)
        db.commit()
    elif job.source == "Careers@Gov" and _refresh_careersgov_terms_if_weak(job, db):
        db.commit()
    _queue_enrichment_if_needed(job)
    return job


@app.post("/api/jobs/{job_id}/match")
def match_resume_to_job(
    job_id: int,
    body: ResumeScoreRequest,
    db: Session = Depends(get_db),
) -> dict:
    """Compare resume against a specific job's skills and description."""
    job = db.query(ScrapedJob).filter(ScrapedJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.source == "Careers@Gov" and not (job.description or "").strip():
        if _enrich_careersgov_job(job, db):
            db.commit()
    elif job.source == "Careers@Gov" and _refresh_careersgov_terms_if_weak(job, db):
        db.commit()

    import json as _json

    # Get skills from the job's database record + description
    db_skills = job.skills if isinstance(job.skills, list) else _json.loads(job.skills) if job.skills else []
    jd_text = job.description or ""
    canonical_terms = _build_canonical_job_terms(job, db)

    # Match against resume
    resume_text = sanitize_resume_text(body.resume_text)
    result = match_resume_against_job_terms(
        resume_text=resume_text,
        job_terms=canonical_terms,
        jd_text=jd_text,
    )
    resolved_terms = merge_job_terms_with_match(canonical_terms, result)

    return {
        "job_id": job_id,
        "job_title": job.title,
        "job_company": job.company,
        "job_skills": db_skills,
        "job_terms": resolved_terms,
        "matched": result.get("matched", []),
        "missing": result.get("missing", []),
        "match_percent": result.get("match_percent", 0),
        "total_skills": len(canonical_terms),
    }


@app.get("/api/skills")
def get_skills(q: str = Query(..., min_length=1, max_length=200, description="Role keyword")) -> dict:
    skills_list = ssg_api.get_skills_for_role(q)
    return {"keyword": q, "skills": skills_list}


@app.get("/api/sources")
def list_sources() -> dict:
    return {
        "sources": [
            {"key": k, "name": v[0]}
            for k, v in aggregator.SOURCE_MAP.items()
        ]
    }


# ═════════════════════════════════════════════════════════════════════════════
# TRACKED JOBS
# ═════════════════════════════════════════════════════════════════════════════

@app.get("/api/tracked", response_model=list[TrackedJobOut])
def list_tracked(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[TrackedJob]:
    return (
        db.query(TrackedJob)
        .filter(TrackedJob.user_id == user.id)
        .order_by(TrackedJob.created_at.desc())
        .all()
    )


@app.post("/api/tracked", response_model=TrackedJobOut, status_code=201)
def create_tracked(
    body: TrackedJobCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TrackedJob:
    # Check tier limit
    limits = TIER_LIMITS.get(user.tier, TIER_LIMITS["free"])
    current_count = (
        db.query(func.count(TrackedJob.id))
        .filter(TrackedJob.user_id == user.id)
        .scalar()
        or 0
    )
    if current_count >= limits["max_tracked_jobs"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Tracked job limit reached ({limits['max_tracked_jobs']}) for {user.tier} tier",
        )

    tracked = TrackedJob(
        user_id=user.id,
        company=sanitize_user_input(body.company),
        role=sanitize_user_input(body.role),
        date_applied=body.date_applied,
        status=body.status,
        source=sanitize_user_input(body.source),
        follow_up_date=body.follow_up_date,
        notes=sanitize_user_input(body.notes),
        scraped_job_id=body.scraped_job_id,
    )
    db.add(tracked)
    db.commit()
    db.refresh(tracked)
    return tracked


@app.put("/api/tracked/{job_id}", response_model=TrackedJobOut)
def update_tracked(
    job_id: int,
    body: TrackedJobUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TrackedJob:
    tracked = db.query(TrackedJob).filter(TrackedJob.id == job_id).first()
    if not tracked:
        raise HTTPException(status_code=404, detail="Tracked job not found")
    if tracked.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not your tracked job")

    updates = body.model_dump(exclude_unset=True)
    sanitize_fields = ("company", "role", "source", "notes")
    for key, val in updates.items():
        if key in sanitize_fields and isinstance(val, str):
            val = sanitize_user_input(val)
        setattr(tracked, key, val)

    db.commit()
    db.refresh(tracked)
    return tracked


@app.delete("/api/tracked/{job_id}")
def delete_tracked(
    job_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    tracked = db.query(TrackedJob).filter(TrackedJob.id == job_id).first()
    if not tracked:
        raise HTTPException(status_code=404, detail="Tracked job not found")
    if tracked.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not your tracked job")
    db.delete(tracked)
    db.commit()
    return {"ok": True}


@app.get("/api/tracked/export")
def export_tracked(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    limits = TIER_LIMITS.get(user.tier, TIER_LIMITS["free"])
    if not limits["can_export"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSV export requires Pro or Admin tier",
        )

    jobs = (
        db.query(TrackedJob)
        .filter(TrackedJob.user_id == user.id)
        .order_by(TrackedJob.created_at.desc())
        .all()
    )

    def _csv_safe(val: str) -> str:
        """Prefix formula-triggering characters to prevent CSV injection in Excel."""
        if val and val[0] in ("=", "+", "-", "@", "\t", "\r"):
            return f"'{val}"
        return val

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "Company", "Role", "Date Applied", "Status",
        "Source", "Follow Up Date", "Notes",
    ])
    for j in jobs:
        writer.writerow([
            _csv_safe(j.company), _csv_safe(j.role), j.date_applied or "",
            j.status, _csv_safe(j.source), j.follow_up_date or "",
            _csv_safe(j.notes),
        ])

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=tracked_jobs.csv"},
    )


# ═════════════════════════════════════════════════════════════════════════════
# RESUME SCORING
# ═════════════════════════════════════════════════════════════════════════════

@app.post("/api/resume/score")
def score_resume(
    body: ResumeScoreRequest,
    user: Optional[User] = Depends(get_optional_user),
    db: Session = Depends(get_db),
) -> dict:
    started_at = datetime.now(timezone.utc)
    check_rate_limit(user, "search", db)
    db.add(UsageLog(user_id=user.id if user else None, action="resume_score"))
    resume_text = sanitize_resume_text(body.resume_text)
    _persist_resume_to_memory(user, db, resume_text)
    db.commit()

    jd_text = sanitize_user_input(body.job_description)

    # Resolve parsed_jd: prefer stored data from job_id, fall back to
    # parsing the raw JD text provided in the request body.
    scored_parsed_jd: dict | None = None
    if body.job_id:
        job_row = db.query(ScrapedJob).filter(ScrapedJob.id == body.job_id).first()
        if job_row:
            import json as _json
            raw = job_row.parsed_jd
            if isinstance(raw, dict):
                scored_parsed_jd = raw
            elif isinstance(raw, str) and raw.strip():
                try:
                    scored_parsed_jd = _json.loads(raw)
                except (ValueError, TypeError):
                    scored_parsed_jd = None
            # Use the job's description as JD text if caller didn't supply one
            if not jd_text.strip() and job_row.description:
                jd_text = sanitize_user_input(job_row.description)

    log.info(
        "Resume score requested words=%s jd_chars=%s job_id=%s user=%s",
        len(resume_text.split()),
        len(jd_text),
        body.job_id,
        user.id if user else "anon",
    )
    # Resolve template sections for section-completeness scoring
    template_sections: list[str] | None = None
    if body.template_id:
        from resume_templates import get_template_sections
        template_sections = get_template_sections(body.template_id)

    result = _scorer.analyze(
        resume_text=resume_text,
        job_description=jd_text,
        parsed_jd=scored_parsed_jd,
        template_sections=template_sections,
    )
    analyze_ms = int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)

    # Enhance with canonical ATS term matching.
    if jd_text.strip():
        parsed_jd = preparse_jd(jd_text, db_session=db)
        job_terms = build_job_ats_terms(
            jd_text=jd_text,
            parsed_jd=parsed_jd,
        )
        skill_match = match_resume_against_job_terms(
            resume_text=resume_text,
            job_terms=job_terms,
            jd_text=jd_text,
        )
        result["keyword_match"] = {
            "matched": skill_match.get("matched", []),
            "missing": skill_match.get("missing", []),
            "score_percent": skill_match.get("match_percent", 0),
        }
        result["skill_match"] = skill_match
    else:
        result["keyword_match"] = {
            "matched": [],
            "missing": [],
            "score_percent": 0,
        }
        result["skill_match"] = {
            "matched": [],
            "missing": [],
            "match_percent": 0,
        }

    total_ms = int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)
    log.info(
        "Resume score completed overall=%s analyze_ms=%s total_ms=%s matched=%s missing=%s",
        result.get("overall_score"),
        analyze_ms,
        total_ms,
        len(result["skill_match"].get("matched", [])),
        len(result["skill_match"].get("missing", [])),
    )

    return result


# ═════════════════════════════════════════════════════════════════════════════
# USER MEMORY — persistent context for AI coaching
# ═════════════════════════════════════════════════════════════════════════════


@app.get("/api/memory")
def get_memory(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Get the user's memory. Users can see everything the AI knows about them."""
    mem = db.query(UserMemory).filter(UserMemory.user_id == user.id).first()
    if not mem:
        return {"has_memory": False}
    return {
        "has_memory": True,
        "target_roles": mem.target_roles,
        "target_companies": mem.target_companies,
        "career_goals": mem.career_goals,
        "strengths": mem.strengths,
        "areas_to_improve": mem.areas_to_improve,
        "preferred_industry": mem.preferred_industry,
        "years_experience": mem.years_experience,
        "education_level": mem.education_level,
        "coaching_notes": mem.coaching_notes,
        "session_count": mem.session_count,
        "updated_at": mem.updated_at.isoformat() if mem.updated_at else None,
    }


@app.put("/api/memory")
def update_memory(
    body: dict,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Update the user's memory. Users can edit/delete anything."""
    mem = db.query(UserMemory).filter(UserMemory.user_id == user.id).first()
    if not mem:
        mem = UserMemory(user_id=user.id)
        db.add(mem)

    editable = (
        "target_roles", "target_companies", "career_goals", "strengths",
        "areas_to_improve", "preferred_industry", "years_experience",
        "education_level", "coaching_notes",
    )
    for field in editable:
        if field in body:
            setattr(mem, field, sanitize_user_input(str(body[field])))

    db.commit()
    db.refresh(mem)
    return {"ok": True, "message": "Memory updated"}


@app.delete("/api/memory")
def clear_memory(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Clear all memory. Fresh start."""
    mem = db.query(UserMemory).filter(UserMemory.user_id == user.id).first()
    if mem:
        db.delete(mem)
        db.commit()
    return {"ok": True, "message": "Memory cleared"}


def _get_memory_context(user: Optional[User], db: Session) -> str:
    """Build memory context string for AI prompts. Returns empty for anonymous users."""
    if not user:
        return ""
    mem = db.query(UserMemory).filter(UserMemory.user_id == user.id).first()
    if not mem:
        return ""

    parts = []
    if mem.target_roles:
        parts.append(f"Target roles: {mem.target_roles}")
    if mem.target_companies:
        parts.append(f"Target companies: {mem.target_companies}")
    if mem.career_goals:
        parts.append(f"Career goals: {mem.career_goals}")
    if mem.strengths:
        parts.append(f"Known strengths: {mem.strengths}")
    if mem.areas_to_improve:
        parts.append(f"Areas to improve: {mem.areas_to_improve}")
    if mem.years_experience:
        parts.append(f"Experience: {mem.years_experience}")
    if mem.coaching_notes:
        parts.append(f"Notes from previous sessions: {mem.coaching_notes}")
    if mem.session_count:
        parts.append(f"This is session #{mem.session_count + 1}")

    if not parts:
        return ""
    return "\n\nContext about this user (from previous sessions):\n" + "\n".join(parts)


# ═════════════════════════════════════════════════════════════════════════════
# AI — powered resume features
# ═════════════════════════════════════════════════════════════════════════════


@app.get("/api/ai/status")
def ai_status() -> dict:
    """Check AI service availability and queue status."""
    return get_ai_status()


def _get_client_ip(request: Request) -> str:
    """Get client IP, respecting proxy headers."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@app.post("/api/ai/coach")
def ai_coach_resume(
    request: Request,
    response: Response,
    body: ResumeScoreRequest,
    user: Optional[User] = Depends(get_optional_user),
    jh_anon: str = Cookie(None),
    db: Session = Depends(get_db),
) -> dict:
    """
    Start an AI resume review session. This counts as 1 credit.
    Free: 3 sessions/day. AISG: 50/day.
    Returns a session_id — all rewrites using that session are free.
    """

    free_limit = TIER_LIMITS["free"]["ai_per_day"]

    # For anonymous users, track by BOTH cookie and IP
    if not user:
        anon_id = jh_anon or ""
        client_ip = _get_client_ip(request)

        if not anon_id:
            anon_id = secrets.token_hex(16)
            response.set_cookie(
                "jh_anon", anon_id, max_age=86400, httponly=True, samesite="lax",
            )

        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

        # Check by cookie
        cookie_count = (
            db.query(func.count(UsageLog.id))
            .filter(
                UsageLog.action == "ai",
                UsageLog.detail.contains(f"anon:{anon_id}"),
                UsageLog.created_at >= today_start,
            )
            .scalar() or 0
        )

        # Check by IP (catches incognito / cleared cookies)
        ip_count = (
            db.query(func.count(UsageLog.id))
            .filter(
                UsageLog.action == "ai",
                UsageLog.detail.contains(f"ip:{client_ip}"),
                UsageLog.created_at >= today_start,
            )
            .scalar() or 0
        )

        if cookie_count >= free_limit or ip_count >= free_limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"You've used your {free_limit} free AI reviews today. Sign up with @aisg.sg for more!",
            )
        detail_prefix = f"anon:{anon_id}|ip:{client_ip}|session"
    else:
        check_rate_limit(user, "ai", db)
        detail_prefix = "session"

    session_id = secrets.token_hex(16)

    db.add(UsageLog(
        user_id=user.id if user else None,
        action="ai",
        detail=f"{detail_prefix}:{session_id}",
    ))
    db.commit()

    # Inject memory context for logged-in users
    memory_context = _get_memory_context(user, db)
    resume_text = sanitize_resume_text(body.resume_text)
    jd = sanitize_user_input(body.job_description)

    result = coach_resume(
        resume_text=resume_text + memory_context,
        job_description=jd,
    )
    if not result:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI service unavailable — rate limit or API error. Try again shortly.",
        )

    # Update memory for logged-in users (increment session count, store resume)
    if user:
        mem = db.query(UserMemory).filter(UserMemory.user_id == user.id).first()
        if not mem:
            mem = UserMemory(user_id=user.id)
            db.add(mem)
        mem.resume_text = resume_text[:10000]
        mem.session_count = (mem.session_count or 0) + 1
        _power_match_cache.pop(user.id, None)
        db.commit()

    result["session_id"] = session_id
    return result


@app.post("/api/ai/rewrite")
def ai_rewrite_bullet(
    request: Request,
    body: RewriteBulletRequest,
    user: Optional[User] = Depends(get_optional_user),
    jh_anon: str = Cookie(None),
    db: Session = Depends(get_db),
) -> dict:
    """
    Rewrite a single resume bullet. Free if a valid session_id is provided
    (from /api/ai/coach). Otherwise counts as a new AI credit.
    """
    # Check if this rewrite belongs to an active session
    session_id = body.session_id or ""
    session_valid = False
    MAX_REWRITES_PER_SESSION = 999  # Essentially unlimited within a session — real protection is global rate limiter

    if session_id:
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        # Verify the session exists and was created today
        session_log = db.query(UsageLog).filter(
            UsageLog.action == "ai",
            UsageLog.detail.contains(f"session:{session_id}"),
            UsageLog.created_at >= today_start,
        ).first()
        if session_log:
            session_owned = False
            if user and session_log.user_id == user.id:
                session_owned = True
            elif not user and jh_anon:
                detail = session_log.detail or ""
                client_ip = _get_client_ip(request)
                session_owned = (
                    f"anon:{jh_anon}" in detail
                    and f"ip:{client_ip}" in detail
                )

            # Count how many rewrites already used this session
            rewrite_count = (
                db.query(func.count(UsageLog.id))
                .filter(
                    UsageLog.action == "ai_rewrite",
                    UsageLog.detail == f"session:{session_id}",
                    UsageLog.created_at >= today_start,
                )
                .scalar() or 0
            )
            if session_owned and rewrite_count < MAX_REWRITES_PER_SESSION:
                session_valid = True

    if session_valid:
        # Log the rewrite against the session (free, doesn't count as AI credit)
        db.add(UsageLog(
            user_id=user.id if user else None,
            action="ai_rewrite",
            detail=f"session:{session_id}",
        ))
        db.commit()
    else:
        # No valid session or session exhausted — counts as a new AI credit
        check_rate_limit(user, "ai", db)
        db.add(UsageLog(
            user_id=user.id if user else None,
            action="ai",
            detail="rewrite:standalone",
        ))
        db.commit()

    bullet = sanitize_user_input(body.bullet)
    job_title = sanitize_user_input(body.job_title)
    job_description = sanitize_user_input(body.job_description) if hasattr(body, "job_description") else ""
    used_verbs = sanitize_user_input(body.used_verbs) if hasattr(body, "used_verbs") else ""
    rewrite_focus = sanitize_user_input(body.rewrite_focus) if hasattr(body, "rewrite_focus") else ""
    focused_feedback = sanitize_user_input(body.focused_feedback) if hasattr(body, "focused_feedback") else ""

    # Build structured JD context (parsed skills, not raw blob)
    jd_context = job_description
    if hasattr(body, "job_id") and body.job_id:
        target_job = db.query(ScrapedJob).filter(ScrapedJob.id == body.job_id).first()
        if target_job and isinstance(target_job.parsed_jd, dict):
            parsed = target_job.parsed_jd
            req = parsed.get("required_skills", [])[:6]
            pref = parsed.get("preferred_skills", [])[:4]
            jd_context = (
                f"Target role: {target_job.title} at {target_job.company}. "
                f"Key skills: {', '.join(req)}. "
                f"Preferred: {', '.join(pref)}."
            )
        elif target_job:
            jd_context = (target_job.description or "")[:500]

    # Generate options, validate each, retry up to 3 times
    from validation_gates import validate_and_fix
    from ai_phrases import clean_ai_phrases

    max_attempts = 3
    validated_options = []

    for attempt in range(max_attempts):
        result = rewrite_bullet(
            bullet,
            job_title=job_title,
            job_description=jd_context,
            used_verbs=used_verbs,
            rewrite_focus=rewrite_focus,
            focused_feedback=focused_feedback,
        )
        if result is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="AI service unavailable. Try again shortly.",
            )
        if result == []:
            return {"original": bullet, "options": [], "no_change": True, "message": "This bullet is already strong -- no changes needed."}

        # Validate each option through the gates + AI phrase cleanup
        validated_options = []
        for option in result:
            # Run AI phrase cleanup first (remove overused words)
            cleaned_option, _phrase_changes = clean_ai_phrases(option, jd_text=jd_context)
            final_text, gate_results = validate_and_fix(
                original=bullet,
                tailored=cleaned_option,
                jd_text=job_description,
            )
            # If critical gate reverted to original, skip this option
            if final_text == bullet:
                continue
            validated_options.append({
                "text": final_text,
                "gates": [
                    {"gate": g.gate_name, "passed": g.passed, "message": g.message}
                    for g in gate_results
                    if not g.passed or g.auto_fixed
                ],
            })

        if validated_options:
            break
        # All options failed gates -- retry with more specific feedback
        focused_feedback = (
            f"{focused_feedback} IMPORTANT: Your previous rewrites failed quality checks. "
            f"Preserve ALL original numbers and facts. Do not add skills or tools not in the original. "
            f"Keep the rewrite under 35 words."
        )

    # Return validated options (or original options if validation produced nothing)
    if validated_options:
        return {
            "original": bullet,
            "options": [opt["text"] for opt in validated_options],
            "gates": [opt["gates"] for opt in validated_options],
            "model": "AI",
            "validated": True,
        }
    # Fallback: return raw options with a warning
    return {
        "original": bullet,
        "options": result or [],
        "model": "AI",
        "validated": False,
        "warning": "These rewrites could not be fully validated. Review carefully before accepting.",
    }


@app.post("/api/ai/integrate-keywords")
def ai_integrate_keywords(
    request: Request,
    body: IntegrateKeywordsRequest,
    user: Optional[User] = Depends(get_optional_user),
    jh_anon: str = Cookie(None),
    db: Session = Depends(get_db),
) -> dict:
    """
    Smart keyword integration — suggests where and how to add missing keywords.
    Free if a valid session_id is provided (from /api/ai/coach).
    Otherwise counts as 1 AI credit.
    """
    # Check if this request belongs to an active session
    session_id = body.session_id or ""
    session_valid = False

    if session_id:
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0,
        )
        session_log = db.query(UsageLog).filter(
            UsageLog.action == "ai",
            UsageLog.detail.contains(f"session:{session_id}"),
            UsageLog.created_at >= today_start,
        ).first()
        if session_log:
            session_owned = False
            if user and session_log.user_id == user.id:
                session_owned = True
            elif not user and jh_anon:
                detail = session_log.detail or ""
                client_ip = _get_client_ip(request)
                session_owned = (
                    f"anon:{jh_anon}" in detail
                    and f"ip:{client_ip}" in detail
                )
            if session_owned:
                session_valid = True

    if session_valid:
        db.add(UsageLog(
            user_id=user.id if user else None,
            action="ai_integrate",
            detail=f"session:{session_id}",
        ))
        db.commit()
    else:
        check_rate_limit(user, "ai", db)
        db.add(UsageLog(
            user_id=user.id if user else None,
            action="ai",
            detail="integrate:standalone",
        ))
        db.commit()

    resume_text = sanitize_resume_text(body.resume_text)
    job_title = sanitize_user_input(body.job_title)
    keywords = [sanitize_user_input(kw) for kw in body.missing_keywords if kw.strip()]

    if not keywords:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No valid keywords provided.",
        )

    suggestions = integrate_keywords(
        resume_text=resume_text,
        missing_keywords=keywords,
        job_title=job_title,
    )
    if suggestions is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI service unavailable — rate limit or API error. Try again shortly.",
        )

    return {"suggestions": suggestions, "model": "AI"}


@app.post("/api/ai/regenerate-summary")
def ai_regenerate_summary(
    body: RegenerateSummaryRequest,
    user: Optional[User] = Depends(get_optional_user),
    db: Session = Depends(get_db),
) -> dict:
    """
    Generate a professional summary from the resume content,
    optionally tailored to a target job description.
    """
    check_rate_limit(user, "ai", db)
    db.add(UsageLog(
        user_id=user.id if user else None,
        action="ai",
        detail="regenerate_summary",
    ))
    db.commit()

    resume_text = sanitize_resume_text(body.resume_text)

    # Load parsed JD context if a job is selected
    parsed_jd: dict = {}
    jd_text = ""
    if body.job_id:
        job = db.query(ScrapedJob).filter(ScrapedJob.id == body.job_id).first()
        if job:
            jd_text = job.description or ""
            parsed_jd = job.parsed_jd if isinstance(job.parsed_jd, dict) else {}
            if not parsed_jd and jd_text:
                skills_list = job.skills if isinstance(job.skills, list) else []
                parsed_jd = preparse_jd(jd_text, skills=skills_list, db_session=db)
                job.parsed_jd = parsed_jd
                db.commit()

    # Build bullet context from the resume (first ~15 non-empty lines that look like bullets or content)
    bullet_lines = []
    for line in resume_text.split("\n"):
        stripped = line.strip()
        if stripped and len(stripped) > 15:
            bullet_lines.append(f"- {stripped}")
        if len(bullet_lines) >= 15:
            break

    # Build the prompt (mirrors Stage 5 logic from tailoring_pipeline.py)
    system = """You are an expert resume writer specializing in Singapore's job market.

Generate a compelling professional summary (2-4 sentences, ~40-60 words) that:
1. Opens with years of experience + core expertise
2. Highlights 2-3 key strengths relevant to the target role
3. Mentions a quantified achievement if possible
4. Sounds natural, not AI-generated

CRITICAL: Only reference achievements and skills that appear in the bullet points below. Do NOT invent.

Return ONLY the summary text, nothing else."""

    user_msg = ""
    if parsed_jd:
        skills = parsed_jd.get("required_skills", [])[:8]
        exp = parsed_jd.get("experience_years", "")
        if skills:
            user_msg += f"TARGET ROLE SKILLS: {', '.join(skills)}\n"
        if exp:
            user_msg += f"EXPERIENCE LEVEL: {exp}\n"
    if jd_text and not parsed_jd:
        user_msg += f"TARGET JOB DESCRIPTION (excerpt):\n{jd_text[:1500]}\n\n"

    user_msg += f"KEY CONTENT FROM RESUME:\n" + "\n".join(bullet_lines)

    content = _call_sealion(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
        max_tokens=200,
        model=SEALION_MODEL,
        temperature=0.3,
    )

    if not content:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI service unavailable — rate limit or API error. Try again shortly.",
        )

    summary = content.strip().strip('"')
    if len(summary) < 30:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI returned an unusable summary. Please try again.",
        )

    return {"summary": summary}


# ═════════════════════════════════════════════════════════════════════════════
# RESUME UPLOAD + FORMAT
# ═════════════════════════════════════════════════════════════════════════════


@app.post("/api/resume/upload")
async def upload_resume(
    file: UploadFile = File(...),
    user: Optional[User] = Depends(get_optional_user),
    db: Session = Depends(get_db),
) -> dict:
    """
    Upload a PDF or DOCX resume. Returns full extracted text + metadata.
    No truncation — everything is returned.
    """
    file_bytes = await file.read()
    try:
        result = parse_resume(
            filename=file.filename or "resume",
            content_type=file.content_type or "",
            file_bytes=file_bytes,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    db.add(UsageLog(
        user_id=user.id if user else None,
        action="resume_upload",
        detail=f"{result['file_type']}:{result['word_count']}words",
    ))
    _persist_resume_to_memory(user, db, result["text"])
    db.commit()

    return result


@app.post("/api/ai/review-all")
def review_all_bullets(
    body: ResumeScoreRequest,
    user: Optional[User] = Depends(get_optional_user),
    db: Session = Depends(get_db),
) -> dict:
    """
    Review ALL bullets at once — returns per-bullet suggestions WITHOUT changing anything.
    User reviews each suggestion, accepts/rejects individually, then applies all.
    This replaces the old "AI Improve All" which blindly rewrote everything.
    """
    check_rate_limit(user, "ai", db)
    db.add(UsageLog(user_id=user.id if user else None, action="ai", detail="review_all"))
    db.commit()

    resume_text = sanitize_resume_text(body.resume_text)
    jd = sanitize_user_input(body.job_description)

    system = """You are an expert resume reviewer. Analyze each bullet point in the resume and provide specific improvement suggestions.

For EACH bullet that needs improvement, provide:
- The original bullet text (exact match)
- What's wrong with it (weak verb, no metrics, vague impact, etc.)
- A rewritten version that fixes the issue
- Whether it's a minor fix or major rewrite

For bullets that are already STRONG (action verb + metrics + clear impact), mark them as "keep" with no changes.

CRITICAL:
- NEVER change facts, dates, company names, or metrics
- If no numbers exist, use [X%] or [N] placeholders
- The keyword from the job description must appear VERBATIM if you add it
- Preserve the original meaning — only improve the phrasing

Return a JSON array:
[
  {"original": "exact bullet text", "status": "keep", "reason": "Strong action verb with measurable impact"},
  {"original": "exact bullet text", "status": "improve", "issue": "Weak opening verb", "suggested": "Rewritten version here", "reason": "Replaced 'Responsible for' with 'Directed'"},
  ...
]"""

    user_msg = f"Resume:\n{resume_text}"
    if jd:
        user_msg += f"\n\nTarget job description:\n{jd}"
        user_msg += "\n\nWeave in missing keywords from the JD where they fit naturally. Keywords must be EXACT MATCH."

    content = _call_sealion(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
        max_tokens=3000,
        temperature=0.3,
    )

    if not content:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI service unavailable. Try again shortly.",
        )

    # Parse JSON from AI response
    suggestions = []
    try:
        start = content.find("[")
        end = content.rfind("]") + 1
        if start >= 0 and end > start:
            suggestions = json.loads(content[start:end])
    except (json.JSONDecodeError, ValueError):
        suggestions = [{"error": "Could not parse AI response", "raw": content[:500]}]

    keep_count = sum(1 for s in suggestions if s.get("status") == "keep")
    improve_count = sum(1 for s in suggestions if s.get("status") == "improve")

    return {
        "suggestions": suggestions,
        "summary": {
            "total_bullets": len(suggestions),
            "keep": keep_count,
            "improve": improve_count,
            "message": f"{keep_count} bullets are strong. {improve_count} can be improved."
        }
    }


@app.post("/api/resume/format")
def format_resume(
    body: ResumeScoreRequest,
    user: Optional[User] = Depends(get_optional_user),
    db: Session = Depends(get_db),
) -> dict:
    """
    AI-powered resume formatting — takes raw resume text and returns
    a clean, ATS-friendly formatted version. Counts as 1 AI credit.
    """
    check_rate_limit(user, "ai", db)
    db.add(UsageLog(
        user_id=user.id if user else None,
        action="ai",
        detail="format",
    ))
    db.commit()

    system = """You are an expert resume formatter. Take the raw resume text and return a perfectly formatted, ATS-friendly resume.

CRITICAL — DO NOT HALLUCINATE:
- NEVER change, invent, or alter: names, email addresses, phone numbers, dates, company names, job titles, degree names, university names, certifications, or any factual information
- ONLY improve: formatting, structure, bullet point wording, action verbs, and section organization
- If you're unsure about a detail, keep the original text exactly as-is
- Do NOT add achievements, metrics, or skills that are not in the original resume

CRITICAL STRUCTURE RULES:
- NEVER turn job titles into bullet points
- Preserve this hierarchy exactly:
  SECTION HEADER (ALL CAPS)
  Company Name — Location
  Job Title | Date Range
  • Achievement bullet 1
  • Achievement bullet 2
- Job titles with dates (e.g., "Program Manager | Aug 2022 – Jan 2025") are SUBHEADINGS, not bullets
- Only achievement/responsibility lines should be bullets (starting with •)
- NEVER merge or reorder sections
- NEVER change dates, company names, or job titles

Formatting rules:
- Use clear section headers: PROFESSIONAL SUMMARY, EXPERIENCE, EDUCATION, SKILLS, CERTIFICATIONS
- Each job entry: Company Name — Location on one line, then Job Title | Date Range on the next line
- Bullet points start with strong action verbs
- Remove filler words and weak phrases
- Keep ALL content — do not remove or summarize anything. Reorganize and clean up formatting only.
- Use consistent date formats throughout
- Put skills in a comma-separated list, grouped by category
- If residency status is mentioned, keep it prominent
- Output as clean PLAIN TEXT — no markdown, no **bold**, no _italic_, no # headers
- Section headers must be ALL CAPS on their own line (e.g., PROFESSIONAL EXPERIENCE)
- Do NOT wrap anything in **asterisks** or markdown formatting
- Do NOT add any commentary — return ONLY the formatted resume"""

    resume_text = sanitize_resume_text(body.resume_text)
    jd = sanitize_user_input(body.job_description)

    user_msg = f"Format this resume into a clean, ATS-friendly structure:\n\n{resume_text}"
    if jd:
        user_msg += f"\n\n---\nOptimize the ordering and keywords for this job:\n{jd}"

    content = _call_sealion(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
        max_tokens=4000,  # Enough for a full 2-3 page resume output
        temperature=0.3,
    )

    if not content:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI service unavailable. Try again shortly.",
        )

    return {"formatted_resume": content, "original_word_count": len(resume_text.split())}


@app.post("/api/resume/download")
def download_resume(
    body: dict,
    user: Optional[User] = Depends(get_optional_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """
    Generate and download a formatted DOCX resume.
    Body: {resume_text, template, name, email, phone, location}
    Templates: classic, modern, singapore, compact
    """
    resume_text = body.get("resume_text", "")
    if not resume_text or len(resume_text) < 50:
        raise HTTPException(status_code=400, detail="Resume text too short")

    template_id = body.get("template", "modern")
    name = sanitize_user_input(body.get("name", ""))
    email_addr = sanitize_user_input(body.get("email", ""))
    phone = sanitize_user_input(body.get("phone", ""))
    location = sanitize_user_input(body.get("location", ""))
    sanitized_resume = sanitize_resume_text(resume_text)
    export_hash = hashlib.sha256(sanitized_resume.encode("utf-8")).hexdigest()[:12]
    export_debug = inspect_resume_export(sanitized_resume, template_id)

    log.info(
        "DOCX export requested hash=%s template=%s words=%s chars=%s sections=%s missing=%s header_lines=%s",
        export_hash,
        template_id,
        export_debug["word_count"],
        export_debug["char_count"],
        export_debug["non_header_sections"],
        export_debug["missing_expected"],
        export_debug["header_lines"],
    )
    if export_debug["looks_header_only"]:
        log.warning(
            "DOCX export looks header-only before generation hash=%s template=%s line_counts=%s",
            export_hash,
            template_id,
            export_debug["section_line_counts"],
        )

    try:
        docx_bytes = generate_docx(
            resume_text=sanitized_resume,
            template_id=template_id,
            name=name,
            email=email_addr,
            phone=phone,
            location=location,
        )
    except Exception as e:
        log.exception(
            "DOCX generation failed hash=%s template=%s sections=%s",
            export_hash,
            template_id,
            export_debug["sections_found"],
        )
        raise HTTPException(status_code=500, detail="Failed to generate resume document")

    log.info(
        "DOCX export completed hash=%s template=%s bytes=%s",
        export_hash,
        template_id,
        len(docx_bytes),
    )

    db.add(UsageLog(
        user_id=user.id if user else None,
        action="resume_download",
        detail=f"template:{template_id}",
    ))
    db.commit()

    safe_name = re.sub(r"[^a-zA-Z0-9]", "_", name)[:30] if name else "resume"
    filename = f"{safe_name}_resume.docx"

    return StreamingResponse(
        io.BytesIO(docx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/resume/download-pdf")
def download_resume_pdf(
    body: dict,
    user: Optional[User] = Depends(get_optional_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Generate and download a PDF resume via weasyprint."""
    resume_text = body.get("resume_text", "")
    if not resume_text or len(resume_text) < 50:
        raise HTTPException(status_code=400, detail="Resume text too short")

    template_id = body.get("template", "modern")
    name = sanitize_user_input(body.get("name", ""))
    email_addr = sanitize_user_input(body.get("email", ""))
    phone = sanitize_user_input(body.get("phone", ""))

    sanitized_resume = sanitize_resume_text(resume_text)
    sections = _parse_sections_for_pdf(sanitized_resume)

    contact_parts = [p for p in [email_addr, phone] if p]
    contact_line = " | ".join(contact_parts) if contact_parts else ""

    html = _build_resume_html(
        name=name or "Resume",
        contact=contact_line,
        sections=sections,
        template_id=template_id,
    )

    try:
        import weasyprint
        pdf_bytes = weasyprint.HTML(string=html).write_pdf()
    except ImportError as e:
        log.exception("weasyprint import failed; missing system deps: %s", e)
        raise HTTPException(status_code=500, detail="PDF engine not available (system libraries missing)")
    except Exception as e:
        log.exception("PDF generation failed: %s", e)
        raise HTTPException(status_code=500, detail="PDF generation failed")

    db.add(UsageLog(
        user_id=user.id if user else None,
        action="resume_download_pdf",
        detail=f"template:{template_id}",
    ))
    db.commit()

    safe_name = re.sub(r"[^a-zA-Z0-9]", "_", name)[:30] if name else "resume"
    filename = f"{safe_name}_resume.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _parse_sections_for_pdf(text: str) -> list[dict]:
    """Parse resume text into sections for HTML rendering."""
    from resume_templates import _parse_sections
    raw = _parse_sections(text)
    result = []
    for key, content in raw.items():
        if key == "header":
            continue
        lines = [ln.strip() for ln in content.split("\n") if ln.strip()]
        result.append({"key": key, "lines": lines})
    return result


def _build_resume_html(
    name: str, contact: str, sections: list[dict], template_id: str,
) -> str:
    """Build an A4-formatted HTML resume for PDF conversion."""
    import html as html_mod
    _n = html_mod.escape

    section_labels = {
        "summary": "Professional Summary", "experience": "Professional Experience",
        "education": "Education", "skills": "Skills", "certifications": "Certifications",
        "projects": "Projects", "activities": "Activities & Leadership",
        "languages": "Languages", "awards": "Awards",
    }

    date_re = re.compile(
        r"\b(?:19|20)\d{2}\b|present|current|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec",
        re.I,
    )
    sep_re = re.compile(r"\s*[|\u2014\u2013]\s*")

    body_parts = []
    for sec in sections:
        key = sec["key"]
        label = section_labels.get(key, key.replace("_", " ").title())
        body_parts.append(f'<h2>{_n(label.upper())}</h2>')
        for line in sec["lines"]:
            if line.startswith(("-", "*", "\u2022", "\u2013")) or re.match(r"^\d+\.", line):
                text = re.sub(r"^[-*\u2022\u2013]\s*", "", line)
                text = re.sub(r"^\d+\.\s*", "", text)
                body_parts.append(f"<li>{_n(text)}</li>")
            elif key in ("experience", "education", "projects") and (
                date_re.search(line) or sep_re.search(line)
            ):
                parts = sep_re.split(line)
                if len(parts) >= 2:
                    body_parts.append(
                        f'<div class="entry"><strong>{_n(parts[0])}</strong>'
                        f'<span class="date">{_n(" | ".join(parts[1:]))}</span></div>'
                    )
                else:
                    body_parts.append(f'<div class="entry"><strong>{_n(line)}</strong></div>')
            else:
                body_parts.append(f"<p>{_n(line)}</p>")

    body_html = "\n".join(body_parts)

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8">
<style>
@page {{ size: A4; margin: 0.6in 0.7in; }}
body {{ font-family: Calibri, Arial, sans-serif; font-size: 10.5pt; line-height: 1.4; color: #1a1a1a; margin: 0; }}
h1 {{ font-size: 18pt; margin: 0 0 2pt 0; text-align: center; }}
.contact {{ text-align: center; font-size: 9.5pt; color: #555; margin-bottom: 12pt; }}
h2 {{ font-size: 11pt; font-weight: bold; text-transform: uppercase; letter-spacing: 1.5pt;
     border-bottom: 1px solid #333; padding-bottom: 2pt; margin: 14pt 0 6pt 0; }}
.entry {{ display: flex; justify-content: space-between; align-items: baseline; margin: 8pt 0 1pt 0; }}
.entry strong {{ font-size: 10.5pt; }}
.date {{ font-size: 9.5pt; color: #555; white-space: nowrap; }}
li {{ margin: 2pt 0; margin-left: 18pt; font-size: 10.5pt; }}
p {{ margin: 2pt 0; font-size: 10.5pt; }}
ul {{ padding-left: 18pt; margin: 0; }}
</style>
</head>
<body>
<h1>{_n(name)}</h1>
{f'<div class="contact">{_n(contact)}</div>' if contact else ''}
{body_html}
</body>
</html>"""


@app.get("/api/resume/templates")
def get_templates() -> list[dict]:
    """List available resume templates."""
    return list_templates()


# ═════════════════════════════════════════════════════════════════════════════
# ENCOURAGEMENT — small touches that keep job seekers going
# ═════════════════════════════════════════════════════════════════════════════

_ENCOURAGEMENTS = {
    "search": [
        "Every search brings you closer to the right opportunity.",
        "Keep exploring — the perfect role is out there.",
        "You're putting in the work, and it shows.",
    ],
    "track": [
        "Another one tracked! Staying organised is half the battle.",
        "You're building real momentum. Keep it going.",
        "That's a solid pick. Fingers crossed for this one!",
    ],
    "resume_score": [
        "Taking the time to improve your resume is already a step ahead of most candidates.",
        "Every small improvement adds up. You've got this.",
        "Smart move getting your resume checked — preparation pays off.",
    ],
    "ai_coach": [
        "You're investing in yourself, and that's never wasted.",
        "The fact that you're refining your resume shows real dedication.",
        "Great resumes get interviews. You're on the right track.",
    ],
    "download": [
        "Looking sharp! Go get that role.",
        "Your resume is ready. Now go make them an offer they can't refuse.",
        "All the best with your applications — you've done the hard work!",
    ],
    "general": [
        "Job hunting is tough, but so are you.",
        "Remember: every 'no' gets you closer to the right 'yes'.",
        "Take it one application at a time. You're doing great.",
        "It only takes one yes. Keep going.",
        "The right company is looking for someone exactly like you.",
    ],
}


@app.get("/api/encouragement")
def get_encouragement(context: str = Query("general", description="Context: search, track, resume_score, ai_coach, download, general")) -> dict:
    """Return a contextual word of encouragement."""
    messages = _ENCOURAGEMENTS.get(context, _ENCOURAGEMENTS["general"])
    return {"message": random.choice(messages), "context": context}


# ═════════════════════════════════════════════════════════════════════════════
# UTILITY
# ═════════════════════════════════════════════════════════════════════════════

@app.get("/api/tiers", response_model=list[TierInfo])
def get_tiers() -> list[dict]:
    return [
        {
            "name": "Free",
            "price": "Free",
            "limits": TIER_LIMITS["free"],
            "features": [
                "Search all SG job portals",
                "AI resume scoring",
                "AI resume coaching",
                "AI bullet rewriting",
                "ATS keyword matching",
                "3 AI reviews per day",
                "No login required",
            ],
        },
        {
            "name": "AISG",
            "price": "Free (@aisg.sg)",
            "limits": TIER_LIMITS["pro"],
            "features": [
                "Everything in Free",
                "Save & track job applications",
                "Resume profile persistence",
                "Follow-up reminders",
                "CSV export of tracked jobs",
                "50 AI reviews per day",
            ],
        },
        {
            "name": "Admin",
            "price": "Internal",
            "limits": TIER_LIMITS["admin"],
            "features": [
                "Unlimited searches",
                "Unlimited tracked jobs",
                "CSV export",
                "Full access",
            ],
        },
    ]


@app.post("/api/contact", status_code=201)
def contact(body: ContactRequest, db: Session = Depends(get_db)) -> dict:
    # Rate limit contact form submissions (abuse prevention)
    check_rate_limit(None, "search", db)
    log.info("Contact form submission received")
    usage = UsageLog(
        user_id=None,
        action="contact",
        detail="contact_form_submission",
    )
    db.add(usage)
    db.commit()
    return {"message": "Thanks! We'll get back to you soon."}


@app.get("/api/usage")
def get_usage(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    searches_today = (
        db.query(func.count(UsageLog.id))
        .filter(
            UsageLog.user_id == user.id,
            UsageLog.action == "search",
            UsageLog.created_at >= today_start,
        )
        .scalar()
        or 0
    )
    tracked_count = (
        db.query(func.count(TrackedJob.id))
        .filter(TrackedJob.user_id == user.id)
        .scalar()
        or 0
    )
    limits = TIER_LIMITS.get(user.tier, TIER_LIMITS["free"])
    return {
        "tier": user.tier,
        "searches_today": searches_today,
        "searches_limit": limits["searches_per_day"],
        "tracked_jobs": tracked_count,
        "tracked_limit": limits["max_tracked_jobs"],
        "can_export": limits["can_export"],
    }


# ── Resume Versions ────────────────────────────────────────────────────────


@app.get("/api/resume/versions")
def list_resume_versions(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    """List all resume versions for the current user."""
    from models import ResumeVersion

    versions = (
        db.query(ResumeVersion)
        .filter(ResumeVersion.user_id == user.id, ResumeVersion.is_active == True)
        .order_by(ResumeVersion.updated_at.desc())
        .all()
    )
    return [
        {
            "id": v.id,
            "label": v.label,
            "source": v.source,
            "job_id": v.job_id,
            "job_title": v.job_title,
            "job_company": v.job_company,
            "score": v.score,
            "word_count": v.word_count,
            "is_master": v.is_master,
            "created_at": v.created_at.isoformat() if v.created_at else "",
            "updated_at": v.updated_at.isoformat() if v.updated_at else "",
        }
        for v in versions
    ]


@app.post("/api/resume/versions")
def save_resume_version(
    body: dict,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """
    Save a new resume version.
    Body: {label, resume_text, resume_structured?, job_id?, score?, is_master?}
    """
    from models import ResumeVersion

    label = sanitize_user_input(body.get("label", "")).strip()
    resume_text = body.get("resume_text", "").strip()
    if not label:
        raise HTTPException(status_code=400, detail="Label is required")
    if not resume_text or len(resume_text) < 50:
        raise HTTPException(status_code=400, detail="Resume text too short")

    is_master = body.get("is_master", False)
    # If setting as master, unset previous master
    if is_master:
        db.query(ResumeVersion).filter(
            ResumeVersion.user_id == user.id,
            ResumeVersion.is_master == True,
        ).update({"is_master": False})

    # Look up job details if job_id provided
    job_title = ""
    job_company = ""
    job_id = body.get("job_id")
    if job_id:
        job = db.query(ScrapedJob).filter(ScrapedJob.id == job_id).first()
        if job:
            job_title = job.title or ""
            job_company = job.company or ""

    version = ResumeVersion(
        user_id=user.id,
        label=label,
        source=body.get("source", "manual"),
        resume_text=resume_text,
        resume_structured=body.get("resume_structured"),
        job_id=job_id,
        job_title=job_title,
        job_company=job_company,
        score=body.get("score"),
        word_count=len(resume_text.split()),
        is_master=is_master,
    )
    db.add(version)
    db.commit()
    db.refresh(version)

    return {"id": version.id, "label": version.label, "created_at": version.created_at.isoformat()}


@app.get("/api/resume/versions/{version_id}")
def get_resume_version(
    version_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Load a specific resume version."""
    from models import ResumeVersion

    version = (
        db.query(ResumeVersion)
        .filter(
            ResumeVersion.id == version_id,
            ResumeVersion.user_id == user.id,
            ResumeVersion.is_active == True,
        )
        .first()
    )
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")

    return {
        "id": version.id,
        "label": version.label,
        "source": version.source,
        "resume_text": version.resume_text,
        "resume_structured": version.resume_structured,
        "job_id": version.job_id,
        "job_title": version.job_title,
        "job_company": version.job_company,
        "score": version.score,
        "word_count": version.word_count,
        "is_master": version.is_master,
        "created_at": version.created_at.isoformat() if version.created_at else "",
        "updated_at": version.updated_at.isoformat() if version.updated_at else "",
    }


@app.put("/api/resume/versions/{version_id}")
def update_resume_version(
    version_id: int,
    body: dict,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Update label, text, or master status of a resume version."""
    from models import ResumeVersion

    version = (
        db.query(ResumeVersion)
        .filter(
            ResumeVersion.id == version_id,
            ResumeVersion.user_id == user.id,
            ResumeVersion.is_active == True,
        )
        .first()
    )
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")

    if "label" in body:
        version.label = sanitize_user_input(body["label"]).strip()
    if "resume_text" in body:
        version.resume_text = body["resume_text"]
        version.word_count = len(body["resume_text"].split())
    if "resume_structured" in body:
        version.resume_structured = body["resume_structured"]
    if "score" in body:
        version.score = body["score"]
    if "is_master" in body and body["is_master"]:
        db.query(ResumeVersion).filter(
            ResumeVersion.user_id == user.id,
            ResumeVersion.is_master == True,
        ).update({"is_master": False})
        version.is_master = True

    db.commit()
    return {"id": version.id, "label": version.label, "updated": True}


@app.delete("/api/resume/versions/{version_id}")
def delete_resume_version(
    version_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Soft-delete a resume version."""
    from models import ResumeVersion

    version = (
        db.query(ResumeVersion)
        .filter(
            ResumeVersion.id == version_id,
            ResumeVersion.user_id == user.id,
            ResumeVersion.is_active == True,
        )
        .first()
    )
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")

    version.is_active = False
    db.commit()
    return {"id": version.id, "deleted": True}


# ── Resume Tailoring Pipeline ───────────────────────────────────────────────


@app.post("/api/resume/tailor")
def start_tailoring(
    body: dict,
    user: Optional[User] = Depends(get_optional_user),
    db: Session = Depends(get_db),
) -> dict:
    """
    Start the multi-pass resume tailoring pipeline for a specific job.

    Body: {resume_text, job_id, intensity: "nudge"|"keywords"|"full"}
    Returns session_id to poll for progress.
    """
    resume_text = sanitize_resume_text(body.get("resume_text", ""))
    job_id = body.get("job_id")
    intensity = body.get("intensity", "full")

    if not resume_text or len(resume_text) < 50:
        raise HTTPException(status_code=400, detail="Resume text is too short (min 50 chars).")
    if intensity not in ("nudge", "keywords", "full"):
        raise HTTPException(status_code=400, detail="Intensity must be nudge, keywords, or full.")

    # Load job and its pre-parsed JD
    jd_text = ""
    parsed_jd = None
    if job_id:
        job = db.query(ScrapedJob).filter(ScrapedJob.id == job_id).first()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found.")
        jd_text = job.description or ""
        parsed_jd = job.parsed_jd
        # Pre-parse on the fly if missing
        if not parsed_jd and jd_text:
            skills_list = job.skills if isinstance(job.skills, list) else []
            parsed_jd = preparse_jd(jd_text, skills=skills_list, db_session=db)
            job.parsed_jd = parsed_jd
            db.commit()
    else:
        jd_text = sanitize_user_input(body.get("job_description", ""))

    if user:
        check_rate_limit(user, "ai", db)
        db.add(UsageLog(user_id=user.id, action="ai", detail="tailor_pipeline"))
        db.commit()
    else:
        # Rate-limit anonymous users too to prevent LLM abuse
        check_rate_limit(None, "ai", db)

    state = run_pipeline(
        resume_text=resume_text,
        job_description=jd_text,
        parsed_jd=parsed_jd,
        intensity=intensity,
    )

    return {
        "session_id": state.session_id,
        "status": "started",
        "estimated_seconds": 45 if intensity == "full" else 15 if intensity == "keywords" else 5,
    }


@app.get("/api/resume/tailor/{session_id}/status")
def get_tailoring_status(session_id: str) -> dict:
    """Poll for pipeline progress."""
    state = get_pipeline_state(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Tailoring session not found.")
    return state.to_dict()


@app.get("/api/resume/tailor/{session_id}/result")
def get_tailoring_result(
    session_id: str,
    user: Optional[User] = Depends(get_optional_user),
    db: Session = Depends(get_db),
) -> dict:
    """Get the tailoring result (available even before pipeline completes)."""
    state = get_pipeline_state(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Tailoring session not found.")
    if state.error:
        raise HTTPException(status_code=500, detail=state.error)
    if not state.result:
        return {
            "session_id": session_id,
            "complete": False,
            "stage": state.stage_name,
            "message": state.message,
        }

    # Auto-save as a resume version on first complete fetch
    result = state.result
    if user and not result.get("_version_saved"):
        from models import ResumeVersion, TailoredResume
        tailored_text = result.get("tailored_text", "")
        job_title = ""
        job_company = ""
        job_id = None
        # Get job info from the TailoredResume record
        tr = db.query(TailoredResume).filter(TailoredResume.session_id == session_id).first()
        if tr:
            job_id = tr.job_id
            job = db.query(ScrapedJob).filter(ScrapedJob.id == tr.job_id).first() if tr.job_id else None
            if job:
                job_title = job.title or ""
                job_company = job.company or ""

        if tailored_text and len(tailored_text) >= 50:
            score_after = result.get("score", {}).get("after")
            label = f"Tailored for {job_title[:40]}" if job_title else f"Tailored {session_id[:8]}"
            version = ResumeVersion(
                user_id=user.id,
                label=label,
                source="tailored",
                resume_text=tailored_text,
                job_id=job_id,
                job_title=job_title,
                job_company=job_company,
                score=score_after,
                word_count=len(tailored_text.split()),
            )
            db.add(version)
            db.commit()
            result["_version_saved"] = True
            result["version_id"] = version.id

    return result


@app.get("/api/jobs/{job_id}/parsed")
def get_parsed_jd(
    job_id: int,
    db: Session = Depends(get_db),
) -> dict:
    """Get the pre-parsed JD data for a job (skills, requirements, etc.)."""
    job = db.query(ScrapedJob).filter(ScrapedJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.source == "Careers@Gov" and not (job.description or "").strip():
        if _enrich_careersgov_job(job, db):
            db.commit()
    elif job.source == "Careers@Gov" and _refresh_careersgov_terms_if_weak(job, db):
        db.commit()

    # Parse on the fly if not already done
    if not job.parsed_jd and job.description:
        skills_list = job.skills if isinstance(job.skills, list) else []
        job.parsed_jd = preparse_jd(
            job.description,
            skills=skills_list,
            db_session=db,
            job_title=job.title or "",
        )
        db.commit()

    # Compute terms once, cache preview, queue summary if needed
    terms = _build_canonical_job_terms(job, db)
    preview = _job_term_labels(terms, limit=8)
    if preview != (job.job_terms_preview or []):
        job.job_terms_preview = preview
        db.commit()
    _queue_enrichment_if_needed(job)

    return {
        "job_id": job_id,
        "title": job.title,
        "company": job.company,
        "parsed_jd": job.parsed_jd or {},
        "job_terms": terms,
        "job_terms_preview": preview,
        "job_terms_preview_ready": job.job_terms_preview is not None,
        "jd_summary": job.jd_summary or "",
        "jd_summary_status": job.jd_summary_status or "",
        "has_parsed_jd": job.parsed_jd is not None,
    }


@app.post("/api/resume/tailor/{session_id}/feedback")
def submit_tailoring_feedback(
    session_id: str,
    body: dict,
) -> dict:
    """Accept, reject, or edit an individual change from the pipeline."""
    state = get_pipeline_state(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Tailoring session not found.")
    if not state.result:
        raise HTTPException(status_code=400, detail="Pipeline has not completed yet.")

    bullet_id = body.get("bullet_id", "")
    action = body.get("action", "")  # "accept" | "reject" | "edit"
    edited_text = body.get("edited_text", "")

    if action not in ("accept", "reject", "edit"):
        raise HTTPException(status_code=400, detail="Action must be accept, reject, or edit.")
    if action == "edit" and not edited_text.strip():
        raise HTTPException(status_code=400, detail="edited_text required when action is edit.")

    changes = state.result.get("changes", [])
    found = False
    for change in changes:
        if change.get("bullet_id") == bullet_id or change.get("type") == "summary_rewrite":
            if change.get("type") == "summary_rewrite" and bullet_id == "summary":
                change["user_status"] = action
                if action == "edit":
                    change["user_edited_text"] = edited_text
                found = True
                break
            elif change.get("bullet_id") == bullet_id:
                change["user_status"] = action
                if action == "edit":
                    change["user_edited_text"] = edited_text
                found = True
                break

    if not found:
        raise HTTPException(status_code=404, detail=f"Change for bullet_id '{bullet_id}' not found.")

    accepted = sum(1 for c in changes if c.get("user_status") == "accept")
    rejected = sum(1 for c in changes if c.get("user_status") == "reject")
    pending = sum(1 for c in changes if c.get("user_status") == "pending")

    return {
        "bullet_id": bullet_id,
        "action": action,
        "accepted": accepted,
        "rejected": rejected,
        "pending": pending,
    }


@app.post("/api/resume/tailor/{session_id}/apply")
def apply_tailoring_changes(
    session_id: str,
) -> dict:
    """Apply all accepted changes and return the final tailored resume text."""
    state = get_pipeline_state(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Tailoring session not found.")
    if not state.result:
        raise HTTPException(status_code=400, detail="Pipeline has not completed yet.")

    original_text = state.result.get("original_text", "")
    changes = state.result.get("changes", [])

    # Start from original text and apply only accepted changes
    lines = original_text.replace("\r\n", "\n").split("\n")

    applied_count = 0
    rejected_count = 0

    for change in changes:
        user_status = change.get("user_status", "pending")

        if user_status == "reject":
            rejected_count += 1
            continue
        if user_status == "pending":
            continue  # skip unreviewed changes

        # Determine the final text for this change
        if user_status == "edit":
            final_text = change.get("user_edited_text", change.get("tailored", ""))
        else:
            final_text = change.get("tailored", "")

        original = change.get("original", "")
        if not original or not final_text:
            continue

        # Find and replace in lines
        normalize = lambda s: re.sub(r"\s+", " ", s.strip().lower())
        for i, line in enumerate(lines):
            # Strip bullet markers for comparison
            stripped = re.sub(
                r"^[\s]*(?:[-*\u2022\u2023\u25E6\u2043\u2219]|\d+[.)]\s)\s*",
                "", line,
            ).strip()
            if normalize(stripped) == normalize(original):
                # Preserve the original bullet marker
                marker_match = re.match(
                    r"^([\s]*(?:[-*\u2022\u2023\u25E6\u2043\u2219]|\d+[.)]\s)\s*)",
                    line,
                )
                marker = marker_match.group(1) if marker_match else ""
                lines[i] = f"{marker}{final_text}"
                applied_count += 1
                break

    tailored_text = "\n".join(lines)

    # Re-score the final version
    scorer = ResumeScorer()
    final_score = scorer.analyze(tailored_text)

    return {
        "tailored_text": tailored_text,
        "applied": applied_count,
        "rejected": rejected_count,
        "skipped_pending": sum(1 for c in changes if c.get("user_status") == "pending"),
        "score_after": final_score.get("overall_score", 0),
        "ats_gaps": state.result.get("ats_gaps", []),
    }


# ── Static frontend (single-service deploy) ─────────────────────────────────
# IMPORTANT: This MUST be the last thing registered. app.mount("/") catches
# all paths, so any API routes defined after this will get 405 errors.

_static_dir = Path(__file__).resolve().parent / "static"
if _static_dir.is_dir():
    log.info("Serving frontend from %s", _static_dir)

    @app.middleware("http")
    async def _spa_middleware(request: Request, call_next):
        """Serve SPA -- fall back to index.html for non-API, non-file routes."""
        response = await call_next(request)
        if (
            response.status_code == 404
            and not request.url.path.startswith("/api")
            and not request.url.path.startswith("/docs")
            and not request.url.path.startswith("/openapi")
        ):
            return FileResponse(_static_dir / "index.html")
        return response

    app.mount("/", StaticFiles(directory=str(_static_dir)), name="static")


# ── Run ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
