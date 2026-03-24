"""
FastAPI backend for Job Hunter SG.
"""

from __future__ import annotations

import csv
import hashlib
import io
import logging
import os
import random
import re
import secrets
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Cookie, Depends, FastAPI, File, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, text
from sqlalchemy.orm import Session

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
from ai_service import _call_sealion, coach_resume, get_ai_status, integrate_keywords, rewrite_bullet
from resume_parser import parse_resume
from resume_scorer import ResumeScorer
from resume_templates import generate_docx, list_templates
from skill_extractor import extract_skill_phrases, match_resume_skills_with_context
from scraper import JobAggregator, SSGSkillsFrameworkAPI

log = logging.getLogger("jobhunter")

# Disable OpenAPI docs in production to reduce attack surface
_is_production = "postgresql" in os.environ.get("DATABASE_URL", "")
app = FastAPI(
    title="Job Hunter SG API",
    version="2.0.0",
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


# ── Startup ──────────────────────────────────────────────────────────────────

@app.on_event("startup")
def on_startup() -> None:
    init_db()
    from database import SessionLocal
    # Auto-cleanup jobs older than 30 days on startup
    try:
        db = SessionLocal()
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        stale = db.query(ScrapedJob).filter(ScrapedJob.scraped_at < cutoff.isoformat()).count()
        if stale > 0:
            db.query(ScrapedJob).filter(ScrapedJob.scraped_at < cutoff.isoformat()).delete()
            db.commit()
            log.info(f"Cleaned up {stale} stale jobs (older than 30 days)")
        db.close()
    except Exception as e:
        log.warning(f"Stale job cleanup failed: {e}")

    # Auto-create admin account if it doesn't exist
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
    db.flush()


def _extract_resume_skills(resume_text: str, db: Session) -> tuple[list[str], str]:
    lower_text = resume_text.lower()
    skill_map: dict[str, str] = {}

    recent_skill_rows = (
        db.query(ScrapedJob.skills)
        .order_by(ScrapedJob.id.desc())
        .limit(1500)
        .all()
    )
    for (raw_skills,) in recent_skill_rows:
        for skill in _normalize_skill_strings(raw_skills):
            skill_map.setdefault(skill.lower(), skill)

    for skill in POWER_SKILL_TERMS:
        skill_map.setdefault(skill.lower(), skill)

    matched: list[str] = []
    seen: set[str] = set()
    for lower_skill, display in sorted(skill_map.items(), key=lambda item: len(item[0]), reverse=True):
        pattern = rf"(?<![a-z0-9]){re.escape(lower_skill)}(?![a-z0-9])"
        if re.search(pattern, lower_text):
            if lower_skill not in seen:
                matched.append(display)
                seen.add(lower_skill)

    if matched:
        return matched[:30], "skill_corpus"

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


def _extract_title_terms(title: str) -> list[str]:
    return [
        word for word in re.findall(r"[a-zA-Z][a-zA-Z+#.]{2,}", title.lower())
        if word not in POWER_ROLE_STOPWORDS
    ]


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


# ── Health ───────────────────────────────────────────────────────────────────

@app.get("/")
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

    query = db.query(ScrapedJob)
    if q:
        pattern = f"%{q}%"
        query = query.filter(
            (ScrapedJob.title.ilike(pattern))
            | (ScrapedJob.company.ilike(pattern))
            | (ScrapedJob.search_keyword.ilike(pattern))
        )
    if employment_type:
        query = query.filter(ScrapedJob.employment_type.ilike(f"%{employment_type}%"))
    if seniority:
        query = query.filter(ScrapedJob.seniority.ilike(f"%{seniority}%"))
    if source:
        query = query.filter(ScrapedJob.source.ilike(f"%{source}%"))
    if location:
        query = query.filter(ScrapedJob.location.ilike(f"%{location}%"))

    jobs = query.order_by(ScrapedJob.id.desc()).all()
    if min_salary:
        salary_matched = [job for job in jobs if salary_floor(job.salary) >= min_salary]
        salary_unknown = [job for job in jobs if salary_floor(job.salary) == 0]
        jobs = salary_matched + salary_unknown

    total = len(jobs)
    offset = (page - 1) * per_page
    jobs = jobs[offset: offset + per_page]
    return {
        "jobs": [
            {
                "id": j.id, "title": j.title, "company": j.company,
                "location": j.location, "salary": j.salary, "source": j.source,
                "url": j.url, "posted_date": j.posted_date,
                "employment_type": j.employment_type, "seniority": j.seniority,
                "description": j.description, "skills": j.skills or [],
                "agency": j.agency, "scraped_at": j.scraped_at,
            }
            for j in jobs
        ],
        "total": total,
        "page": page,
        "pages": max(1, (total + per_page - 1) // per_page),
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

    candidate_jobs = (
        db.query(ScrapedJob)
        .order_by(ScrapedJob.id.desc())
        .limit(300)
        .all()
    )

    recommendations: list[dict] = []
    for job in candidate_jobs:
        job_skills = _normalize_skill_strings(job.skills)
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

        if not matched_skills and not title_hits and not job_skills:
            continue

        skill_score = (len(matched_skills) / max(3, min(len(job_skills), 8))) * 72 if job_skills else 0
        title_score = min(18, len(title_hits) * 6)
        description_bonus = min(
            10,
            sum(1 for skill in matched_skills[:4] if skill.lower() in (job.description or "").lower()) * 3,
        )
        suitability_score = round(min(98, skill_score + title_score + description_bonus))

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

        if matched_skills:
            why = f"Matches on {', '.join(matched_skills[:3])}."
        elif title_hits:
            why = f"Your resume aligns with {', '.join(title_hits[:3])} from the role title."
        else:
            why = "Worth exploring, but the skill signal is still light."

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
            "matched_skills": matched_skills[:6],
            "missing_skills": missing_skills[:6],
            "why": why,
            "bridge_plan": _build_bridge_plan(missing_skills),
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
    ]

    recommended_queries = []
    seen_queries = set()
    for item in recommendations:
        title = item["job"]["title"]
        if title in seen_queries:
            continue
        seen_queries.add(title)
        recommended_queries.append(title)
        if len(recommended_queries) >= 5:
            break

    return {
        "resume_ready": True,
        "message": "Power matches generated from your latest stored resume.",
        "resume_signal_mode": resume_signal_mode,
        "resume_skills": resume_skills[:24],
        "top_gaps": top_gaps,
        "recommended_queries": recommended_queries,
        "recommendations": recommendations,
    }


@app.get("/api/jobs/{job_id}", response_model=JobOut)
def get_cached_job(job_id: int, db: Session = Depends(get_db)) -> ScrapedJob:
    job = db.query(ScrapedJob).filter(ScrapedJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


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
    check_rate_limit(user, "search", db)
    db.add(UsageLog(user_id=user.id if user else None, action="resume_score"))
    resume_text = sanitize_resume_text(body.resume_text)
    _persist_resume_to_memory(user, db, resume_text)
    db.commit()

    jd_text = sanitize_user_input(body.job_description)
    result = _scorer.analyze(
        resume_text=resume_text,
        job_description=jd_text,
    )

    # Enhance with multi-word skill phrase matching
    if jd_text.strip():
        jd_skill_phrases = extract_skill_phrases(jd_text)
        skill_match = match_resume_skills_with_context(
            resume_text=resume_text,
            jd_skills=jd_skill_phrases,
            jd_text=jd_text,
        )
        result["skill_match"] = skill_match
    else:
        result["skill_match"] = {
            "matched": [],
            "missing": [],
            "match_percent": 0,
        }

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
    used_verbs = sanitize_user_input(body.used_verbs) if hasattr(body, "used_verbs") else ""

    result = rewrite_bullet(bullet, job_title=job_title, used_verbs=used_verbs)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI service unavailable. Try again shortly.",
        )
    if result == []:
        return {"original": bullet, "options": [], "no_change": True, "message": "This bullet is already strong — no changes needed."}
    return {"original": bullet, "options": result, "model": "AI"}


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
- Output as clean plain text that can be copied directly into a .docx template
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

    try:
        docx_bytes = generate_docx(
            resume_text=sanitize_resume_text(resume_text),
            template_id=template_id,
            name=name,
            email=email_addr,
            phone=phone,
            location=location,
        )
    except Exception as e:
        log.warning(f"DOCX generation failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate resume document")

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


# ── Run ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
