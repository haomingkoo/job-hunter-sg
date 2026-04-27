"""Scheduled matched-job email digests.

This module avoids importing the FastAPI app so it can run safely as a Railway
scheduled command.
"""

from __future__ import annotations

import hashlib
import html
import hmac
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session, load_only

from ats_terms import ATS_ALLOWED_SINGLE_TERMS
from database import SessionLocal
from email_service import send_email, smtp_configured
from employer_filter import direct_employer_condition, normalize_employer_name
from models import JobAlertDelivery, JobAlertPreference, ScrapedJob, TrackedJob, User, UserMemory
from skill_extractor import extract_skill_phrases


ALERT_SINGLE_TERMS = ATS_ALLOWED_SINGLE_TERMS | {
    "gcp",
    "node.js",
    "ci/cd",
    "power bi",
    "semiconductor",
    "metrology",
    "lithography",
    "feol",
    "beol",
}

SEMICONDUCTOR_DOMAIN_TERMS = {
    "semiconductor",
    "semiconductor manufacturing",
    "process integration",
    "process control",
    "yield engineering",
    "yield optimization",
    "yield ramp",
    "lithography",
    "metrology",
    "wafer fabrication",
    "fab operations",
    "quality systems",
    "spc",
    "root cause analysis",
    "design of experiments",
    "equipment engineering",
    "defect metrology",
    "feol",
    "beol",
    "hbm3e",
    "lpddr5x",
}

ALERT_ROLE_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "lead",
    "senior",
    "junior",
    "staff",
    "principal",
    "manager",
    "engineer",
    "executive",
    "associate",
    "specialist",
    "analyst",
    "intern",
    "contract",
    "full",
    "time",
    "part",
    "level",
}

ALERT_SKILL_ALIASES = {
    "amazon web services": {"aws"},
    "aws": {"amazon web services"},
    "google cloud platform": {"gcp"},
    "gcp": {"google cloud platform"},
    "microsoft azure": {"azure"},
    "azure": {"microsoft azure"},
    "node.js": {"node", "nodejs"},
    "node": {"node.js", "nodejs"},
    "power bi": {"powerbi"},
    "powerbi": {"power bi"},
    "ci/cd": {"continuous integration", "continuous deployment", "continuous delivery"},
}


@dataclass(frozen=True)
class AlertMatch:
    job: ScrapedJob
    score: int
    matched_skills: list[str]
    missing_skills: list[str]
    why: str


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _resume_hash(resume_text: str) -> str:
    return hashlib.sha256((resume_text or "").encode("utf-8")).hexdigest()


def _unsubscribe_secret() -> str:
    secret = os.environ.get("ALERT_UNSUBSCRIBE_SECRET") or os.environ.get("JWT_SECRET")
    if not secret:
        raise RuntimeError("JWT_SECRET or ALERT_UNSUBSCRIBE_SECRET is required for unsubscribe links")
    return secret


def create_unsubscribe_token(user_id: int) -> str:
    payload = str(int(user_id))
    signature = hmac.new(
        _unsubscribe_secret().encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{payload}.{signature}"


def verify_unsubscribe_token(token: str) -> int | None:
    raw = str(token or "").strip()
    if "." not in raw:
        return None
    payload, signature = raw.split(".", 1)
    if not payload.isdigit() or not signature:
        return None
    expected = hmac.new(
        _unsubscribe_secret().encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    return int(payload)


def _normalise_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()


def _normalise_skill(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(value or "").strip(" -•\t"))
    return cleaned.lower()


def _identity_key(title: str, company: str) -> str:
    title_key = re.sub(r"\b(?:jr|job|req|r)\s*[-#:]?\s*\d+\b", " ", str(title or "").lower())
    title_key = re.sub(r"[^a-z0-9]+", " ", title_key).strip()
    return f"{title_key}|{normalize_employer_name(company)}"


def _job_duplicate_key(job: ScrapedJob) -> tuple[str, ...]:
    source_id = (job.source_posting_id or "").strip().lower()
    if source_id:
        return ("source_id", (job.source or "").strip().lower(), source_id)
    return (
        "fallback",
        _identity_key(job.title, job.company),
        _normalise_text(job.location),
        _normalise_text(job.salary),
    )


def _split_keywords(raw_keywords: str) -> list[str]:
    parts = re.split(r"[,;\n]+", raw_keywords or "")
    keywords = []
    seen = set()
    for part in parts:
        keyword = re.sub(r"\s+", " ", part.strip())
        key = keyword.lower()
        if keyword and key not in seen:
            seen.add(key)
            keywords.append(keyword)
    return keywords[:8]


def _normalise_skill_strings(raw_skills) -> list[str]:
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
        if not cleaned or len(cleaned) < 2 or len(cleaned) > 80:
            continue
        if lower in seen:
            continue
        seen.add(lower)
        deduped.append(cleaned)
    return deduped


def _extract_title_terms(title: str) -> list[str]:
    return [
        word
        for word in re.findall(r"[a-zA-Z][a-zA-Z+#.]{2,}", str(title or "").lower())
        if word not in ALERT_ROLE_STOPWORDS
    ]


def extract_resume_alert_skills(resume_text: str) -> list[str]:
    lower_text = (resume_text or "").lower()
    extracted = extract_skill_phrases(
        resume_text,
        use_dynamic_skills=False,
    )
    supplemental = [
        term
        for term in ALERT_SINGLE_TERMS
        if re.search(rf"(?<![a-z0-9]){re.escape(term.lower())}(?![a-z0-9])", lower_text)
    ]
    return _surface_skills(extracted + supplemental, limit=40)


def _job_alert_terms(job: ScrapedJob) -> list[str]:
    preview = job.job_terms_preview
    if isinstance(preview, list) and preview:
        terms = [str(term) for term in preview if str(term or "").strip()]
    else:
        terms = _normalise_skill_strings(job.skills)
        if not terms and (job.description or "").strip():
            terms = extract_skill_phrases(
                job.description or "",
                _normalise_skill_strings(job.skills),
                use_dynamic_skills=False,
            )
    if not terms:
        terms = _extract_title_terms(job.title)
    return _surface_skills(terms, limit=24)


def _term_variants(term: str) -> set[str]:
    normalised = _normalise_skill(term)
    variants = {normalised}
    variants.update(ALERT_SKILL_ALIASES.get(normalised, set()))
    return {variant for variant in variants if variant}


def _term_matches_resume(term: str, resume_lookup: set[str], lower_resume: str) -> bool:
    for variant in _term_variants(term):
        if variant in resume_lookup:
            return True
        if re.search(rf"(?<![a-z0-9]){re.escape(variant)}(?![a-z0-9])", lower_resume):
            return True
    return False


def _surface_skills(skills: list[str], limit: int) -> list[str]:
    surfaced: list[str] = []
    seen: set[str] = set()
    for skill in skills:
        cleaned = re.sub(r"\s+", " ", str(skill or "").strip(" -•\t"))
        lower = cleaned.lower()
        if not cleaned or lower in seen:
            continue
        if len(lower.split()) == 1 and lower not in ALERT_SINGLE_TERMS:
            continue
        if lower in {"experience", "professional", "development", "engineering", "responsibilities"}:
            continue
        seen.add(lower)
        surfaced.append(cleaned)
        if len(surfaced) >= limit:
            break
    return surfaced


def score_job_for_alert(
    resume_text: str,
    resume_skills: list[str],
    job: ScrapedJob,
) -> AlertMatch | None:
    lower_resume = (resume_text or "").lower()
    resume_lookup = {_normalise_skill(skill) for skill in resume_skills}
    job_skills = _job_alert_terms(job)
    title_terms = _extract_title_terms(job.title)

    matched_skills = [
        skill
        for skill in job_skills
        if _term_matches_resume(skill, resume_lookup, lower_resume)
    ]
    missing_skills = [
        skill
        for skill in job_skills
        if not _term_matches_resume(skill, resume_lookup, lower_resume)
    ]
    title_hits = [
        term
        for term in title_terms
        if _term_matches_resume(term, resume_lookup, lower_resume)
    ]

    if not matched_skills and not title_hits:
        return None

    skill_score = (len(matched_skills) / max(3, min(len(job_skills), 8))) * 72 if job_skills else 0
    title_score = min(18, len(title_hits) * 6)
    description_bonus = min(
        8,
        sum(1 for skill in matched_skills[:4] if skill.lower() in (job.description or "").lower()) * 2,
    )
    domain_bonus = 0
    if any(_normalise_skill(skill) in SEMICONDUCTOR_DOMAIN_TERMS for skill in resume_skills):
        domain_bonus = min(
            18,
            sum(1 for skill in matched_skills + title_hits if _normalise_skill(skill) in SEMICONDUCTOR_DOMAIN_TERMS)
            * 5,
        )

    score = round(min(98, max(0, skill_score + title_score + description_bonus + domain_bonus)))
    if score < 18:
        return None

    surfaced_matched = _surface_skills(matched_skills, limit=6)
    surfaced_missing = _surface_skills(missing_skills, limit=6)
    if surfaced_matched:
        why = f"Matches on {', '.join(surfaced_matched[:3])}."
    else:
        why = f"Title overlap on {', '.join(title_hits[:3])}."
    return AlertMatch(
        job=job,
        score=score,
        matched_skills=surfaced_matched,
        missing_skills=surfaced_missing,
        why=why,
    )


def _preference_due(pref: JobAlertPreference, now: datetime) -> bool:
    last_run_at = _as_utc(pref.last_run_at)
    if last_run_at is None:
        return True
    interval = timedelta(days=7 if pref.frequency == "weekly" else 1)
    return now - last_run_at >= interval


def _tracked_suppression(db: Session, user_id: int) -> tuple[set[int], set[str]]:
    tracked_rows = db.query(TrackedJob).filter(TrackedJob.user_id == user_id).all()
    tracked_ids = {row.scraped_job_id for row in tracked_rows if row.scraped_job_id}
    tracked_keys = {_identity_key(row.role, row.company) for row in tracked_rows}
    return tracked_ids, tracked_keys


def find_alert_matches(
    db: Session,
    pref: JobAlertPreference,
    resume_text: str,
    now: datetime | None = None,
) -> list[AlertMatch]:
    now = now or _utcnow()
    since = _as_utc(pref.last_run_at) or (now - timedelta(days=1))
    since_iso = since.isoformat()
    keywords = _split_keywords(pref.keywords)

    query = (
        db.query(ScrapedJob)
        .options(
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
                ScrapedJob.source_posting_id,
                ScrapedJob.job_terms_preview,
                ScrapedJob.skills_flat,
                ScrapedJob.scraped_at,
                ScrapedJob.posted_at_sort,
                ScrapedJob.company_ssic_description,
            )
        )
        .filter(
            ScrapedJob.hidden == 0,
            or_(ScrapedJob.scraped_at >= since_iso, ScrapedJob.posted_at_sort >= since_iso),
        )
    )

    if pref.direct_employers_only:
        query = query.filter(
            direct_employer_condition(ScrapedJob.company, ScrapedJob.company_ssic_description)
        )

    if keywords:
        keyword_conditions = []
        for keyword in keywords:
            pattern = f"%{keyword}%"
            keyword_conditions.extend(
                [
                    ScrapedJob.title.ilike(pattern),
                    ScrapedJob.company.ilike(pattern),
                    ScrapedJob.search_keyword.ilike(pattern),
                    ScrapedJob.skills_flat.ilike(pattern),
                ]
            )
        query = query.filter(or_(*keyword_conditions))

    delivered_ids = {
        row[0]
        for row in (
            db.query(JobAlertDelivery.scraped_job_id)
            .filter(JobAlertDelivery.user_id == pref.user_id)
            .all()
        )
    }
    tracked_ids, tracked_keys = _tracked_suppression(db, pref.user_id)
    resume_skills = extract_resume_alert_skills(resume_text)

    matches: list[AlertMatch] = []
    seen_keys: set[tuple[str, ...]] = set()
    for job in query.order_by(ScrapedJob.id.desc()).limit(400).all():
        if job.id in delivered_ids or job.id in tracked_ids:
            continue
        if _identity_key(job.title, job.company) in tracked_keys:
            continue
        duplicate_key = _job_duplicate_key(job)
        if duplicate_key in seen_keys:
            continue
        scored = score_job_for_alert(resume_text, resume_skills, job)
        if not scored or scored.score < pref.min_score:
            continue
        seen_keys.add(duplicate_key)
        matches.append(scored)
        if len(matches) >= pref.max_jobs:
            break

    matches.sort(key=lambda item: (item.score, item.job.id), reverse=True)
    return matches[: pref.max_jobs]


def _job_url(job: ScrapedJob) -> str:
    return (job.url or "").strip() or os.environ.get("APP_BASE_URL", "https://job.kooexperience.com").rstrip("/")


def render_alert_email(user: User, pref: JobAlertPreference, matches: list[AlertMatch]) -> tuple[str, str, str, str]:
    app_base_url = os.environ.get("APP_BASE_URL", "https://job.kooexperience.com").rstrip("/")
    unsubscribe_url = f"{app_base_url}/api/job-alerts/unsubscribe?token={create_unsubscribe_token(user.id)}"
    subject = f"{len(matches)} new Job Hunter SG matches above {pref.min_score}"

    text_lines = [
        f"Hi {user.name},",
        "",
        f"New roles matched your saved resume at or above {pref.min_score}.",
        "",
    ]
    html_rows: list[str] = []
    for match in matches:
        job = match.job
        matched = ", ".join(match.matched_skills[:5]) or "Role/title overlap"
        missing = ", ".join(match.missing_skills[:4])
        url = _job_url(job)
        salary = f" · {job.salary}" if job.salary else ""
        text_lines.extend(
            [
                f"{match.score} - {job.title} at {job.company}",
                f"{job.location or 'Singapore'}{salary}",
                f"Matched: {matched}",
                f"View: {url}",
                "",
            ]
        )
        missing_html = (
            f"<div style=\"color:#6b7280;font-size:13px;margin-top:4px;\">Gaps: {html.escape(missing)}</div>"
            if missing
            else ""
        )
        html_rows.append(
            "<div style=\"border:1px solid #dbe7f3;border-radius:10px;padding:14px 16px;margin:12px 0;\">"
            f"<div style=\"font-size:13px;font-weight:700;color:#0f766e;\">Suitability {match.score}</div>"
            f"<div style=\"font-size:16px;font-weight:700;color:#243447;margin-top:4px;\">"
            f"{html.escape(job.title)}</div>"
            f"<div style=\"color:#4b6478;margin-top:2px;\">{html.escape(job.company)}</div>"
            f"<div style=\"color:#6b7280;font-size:13px;margin-top:4px;\">"
            f"{html.escape(job.location or 'Singapore')}{html.escape(salary)}</div>"
            f"<div style=\"color:#374151;font-size:13px;margin-top:10px;\">Matched: {html.escape(matched)}</div>"
            f"{missing_html}"
            f"<a href=\"{html.escape(url)}\" style=\"display:inline-block;margin-top:12px;"
            "background:#384959;color:white;text-decoration:none;border-radius:8px;padding:8px 12px;"
            "font-size:13px;font-weight:700;\">View posting</a>"
            "</div>"
        )

    text_lines.extend(
        [
            "Already applied or not interested? Track the job in Job Hunter SG so we stop sending it.",
            f"Manage alerts: {app_base_url}",
            f"Unsubscribe: {unsubscribe_url}",
        ]
    )
    text_body = "\n".join(text_lines)
    html_body = (
        "<div style=\"font-family:Inter,Arial,sans-serif;background:#f6f9fc;padding:24px;color:#243447;\">"
        "<div style=\"max-width:640px;margin:0 auto;background:white;border:1px solid #dbe7f3;"
        "border-radius:12px;padding:24px;\">"
        f"<h1 style=\"font-size:20px;margin:0 0 8px;\">New matched jobs for {html.escape(user.name)}</h1>"
        f"<p style=\"color:#4b6478;margin:0 0 18px;\">These roles scored at or above {pref.min_score} "
        "against your saved resume.</p>"
        f"{''.join(html_rows)}"
        "<p style=\"color:#6b7280;font-size:13px;margin-top:20px;\">"
        "Track jobs you apply to or want to suppress, and Job Hunter SG will avoid repeat alerts. "
        f"You can manage alerts from Account: <a href=\"{html.escape(app_base_url)}\">{html.escape(app_base_url)}</a>"
        "</p>"
        "<p style=\"color:#6b7280;font-size:12px;margin-top:12px;\">"
        f"<a href=\"{html.escape(unsubscribe_url)}\" style=\"color:#6b7280;\">Unsubscribe from job alerts</a>. "
        "Job match alerts are informational only and are not job offers."
        "</p>"
        "</div></div>"
    )
    return subject, text_body, html_body, unsubscribe_url


def run_job_alerts(dry_run: bool = False, limit_users: int | None = None) -> dict:
    stats = {
        "smtp_configured": smtp_configured(),
        "dry_run": dry_run,
        "users_checked": 0,
        "users_due": 0,
        "emails_sent": 0,
        "jobs_sent": 0,
        "skipped_no_resume": 0,
        "skipped_not_due": 0,
        "errors": [],
    }
    if not dry_run and not stats["smtp_configured"]:
        return stats

    now = _utcnow()
    db = SessionLocal()
    try:
        query = (
            db.query(JobAlertPreference)
            .filter(JobAlertPreference.enabled == 1)
            .order_by(JobAlertPreference.id.asc())
        )
        if limit_users:
            query = query.limit(limit_users)

        for pref in query.all():
            stats["users_checked"] += 1
            if not _preference_due(pref, now):
                stats["skipped_not_due"] += 1
                continue
            stats["users_due"] += 1
            try:
                user = db.get(User, pref.user_id)
                mem = db.query(UserMemory).filter(UserMemory.user_id == pref.user_id).first()
                resume_text = (mem.resume_text or "").strip() if mem else ""
                if not user or len(resume_text) < 50:
                    stats["skipped_no_resume"] += 1
                    if not dry_run:
                        pref.last_run_at = now
                        pref.updated_at = now
                        db.commit()
                    continue

                matches = find_alert_matches(db, pref, resume_text, now=now)
                if matches and not dry_run:
                    subject, text_body, html_body, unsubscribe_url = render_alert_email(user, pref, matches)
                    send_email(
                        user.email,
                        subject,
                        text_body,
                        html_body,
                        list_unsubscribe_url=unsubscribe_url,
                    )
                    resume_digest = _resume_hash(resume_text)
                    for match in matches:
                        db.add(
                            JobAlertDelivery(
                                user_id=user.id,
                                preference_id=pref.id,
                                scraped_job_id=match.job.id,
                                resume_hash=resume_digest,
                                match_score=match.score,
                                action="sent",
                                sent_at=now,
                            )
                        )
                    stats["emails_sent"] += 1
                    stats["jobs_sent"] += len(matches)

                if not dry_run:
                    pref.last_run_at = now
                    pref.updated_at = now
                    db.commit()
                else:
                    db.rollback()
            except Exception as exc:
                db.rollback()
                stats["errors"].append({"user_id": pref.user_id, "error": type(exc).__name__})
    finally:
        db.close()

    return stats
