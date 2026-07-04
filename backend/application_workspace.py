"""Application Workspace behavior behind a small module interface."""

from __future__ import annotations

import base64
import secrets
from datetime import datetime, timezone
from typing import Callable, Iterable

import config
from auth import TIER_LIMITS
from fastapi import HTTPException, status
from models import ResumeVersion, TrackedJob, User
from resume_parser import parse_resume
from sanitizer import sanitize_resume_text, sanitize_user_input
from schemas import ApplicationWorkspaceCreate, TrackedJobCreate, TrackedJobUpdate
from sqlalchemy import func
from sqlalchemy.orm import Session


AGENT_REVIEW_METADATA_KEY = "agent_review"
SUBMITTED_RESUME_METADATA_KEY = "submitted_resume"
SUBMITTED_RESUME_ARTIFACTS_METADATA_KEY = "submitted_resume_artifacts"
WORKSPACE_SOURCE_CREATED = "created"
WORKSPACE_SOURCE_MANUAL = "manual"
WORKSPACE_SOURCE_AGENT_REVIEW = "agent_review"
WORKSPACE_SOURCE_AGENT_REVIEW_ERROR = "agent_review_error"
WORKSPACE_RESUME_SOURCE_AGENT_REVIEW = "agent_review"
WORKSPACE_DRAFT_STATUS = "draft"

APPLICATION_OUTCOME_GROUPS = {
    "submitted": {"applied"},
    "interview": {"screening", "interview", "assessment", "final_round"},
    "offer": {"offer", "accepted"},
    "rejected": {"rejected"},
    "withdrawn": {"withdrawn"},
    "no_response": {"no_response"},
}


def tracked_stage_event(stage: str, source: str, date: str | None = None, notes: str = "") -> dict:
    return {
        "stage": stage,
        "date": date or datetime.now(timezone.utc).date().isoformat(),
        "source": source,
        "notes": notes,
    }


def ensure_resume_version_owner(db: Session, user_id: int, version_id: int | None) -> None:
    if version_id is None:
        return
    version = (
        db.query(ResumeVersion)
        .filter(
            ResumeVersion.id == version_id,
            ResumeVersion.user_id == user_id,
            ResumeVersion.is_active == True,
        )
        .first()
    )
    if not version:
        raise HTTPException(status_code=404, detail="Resume version not found")


def workspace_response(tracked: TrackedJob) -> dict:
    return {
        "id": tracked.id,
        "user_id": tracked.user_id,
        "company": tracked.company,
        "title": tracked.role,
        "role": tracked.role,
        "job_description": tracked.job_description or "",
        "source_url": tracked.source_url or "",
        "source": tracked.source or "",
        "status": tracked.status,
        "date_applied": tracked.date_applied,
        "follow_up_date": tracked.follow_up_date,
        "notes": tracked.notes or "",
        "scraped_job_id": tracked.scraped_job_id,
        "resume_version_id": tracked.resume_version_id,
        "role_metadata": tracked.role_metadata or {},
        "stage_history": tracked.stage_history or [],
        "created_at": tracked.created_at,
        "updated_at": tracked.updated_at,
    }


def _owned_tracked_job(db: Session, user_id: int, job_id: int, *, workspace: bool = False) -> TrackedJob:
    tracked = db.query(TrackedJob).filter(TrackedJob.id == job_id).first()
    if not tracked:
        detail = "Application workspace not found" if workspace else "Tracked job not found"
        raise HTTPException(status_code=404, detail=detail)
    if tracked.user_id != user_id:
        detail = "Not your application workspace" if workspace else "Not your tracked job"
        raise HTTPException(status_code=403, detail=detail)
    return tracked


def _workspace_agent_review_prompt(tracked: TrackedJob) -> str:
    return "\n\n".join(
        [
            "Run a deep application review for this workspace.",
            f"Company: {tracked.company}",
            f"Role: {tracked.role}",
            f"Job description:\n{tracked.job_description or ''}",
            (
                "Return practical recommendations and propose evidence-bound resume edits. "
                "Do not invent unsupported metrics, employers, tools, dates, or outcomes."
            ),
        ]
    )


def _empty_application_outcome_counts() -> dict[str, int]:
    return {key: 0 for key in APPLICATION_OUTCOME_GROUPS}


def _application_outcome_key(status_value: str | None) -> str:
    status_key = (status_value or "").strip()
    for outcome, statuses in APPLICATION_OUTCOME_GROUPS.items():
        if status_key in statuses:
            return outcome
    return ""


def _count_current_application_outcomes(tracked_jobs: list[TrackedJob]) -> dict[str, int]:
    counts = _empty_application_outcome_counts()
    for tracked in tracked_jobs:
        outcome = _application_outcome_key(tracked.status)
        if outcome:
            counts[outcome] += 1
    return counts


def _count_stage_history_outcomes(tracked_jobs: list[TrackedJob]) -> dict[str, int]:
    counts = _empty_application_outcome_counts()
    for tracked in tracked_jobs:
        seen: set[str] = set()
        for event in tracked.stage_history or []:
            stage = event.get("stage") if isinstance(event, dict) else ""
            outcome = _application_outcome_key(str(stage))
            if outcome and outcome not in seen:
                counts[outcome] += 1
                seen.add(outcome)
    return counts


def _workspace_debate_summary(agent_state: dict, recommendations: list[str], trace_id: str) -> dict:
    saved = agent_state.get("debate_summary") if isinstance(agent_state.get("debate_summary"), dict) else {}
    persona_roles = [
        str(item.get("persona"))
        for item in agent_state.get("persona_findings", [])
        if isinstance(item, dict) and item.get("persona")
    ]
    return {
        "roles": saved.get("roles") or persona_roles or list(config.WORKSPACE_AGENT_REVIEW_DEFAULT_ROLES),
        "key_disagreements": saved.get("key_disagreements") or saved.get("disagreements") or [],
        "final_recommendation": saved.get("final_recommendation")
        or saved.get("recommendation")
        or (recommendations[-1] if recommendations else "Review completed. Inspect pending diffs before applying changes."),
        "confidence": saved.get("confidence") or ("medium" if recommendations else "low"),
        "trace_id": saved.get("trace_id") or trace_id or None,
    }


def build_tailored_draft_text(source_text: str, agent_state: dict) -> str:
    explicit = agent_state.get("tailored_draft") or agent_state.get("tailored_text")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()

    draft = source_text
    for diff in agent_state.get("pending_diffs", []):
        if not isinstance(diff, dict):
            continue
        original = str(diff.get("original") or "")
        rewrite = str(diff.get("rewrite") or "")
        if original and rewrite:
            draft = draft.replace(original, rewrite, 1)
    return draft if draft != source_text else ""


def _save_tailored_draft(
    db: Session,
    user_id: int,
    tracked: TrackedJob,
    source_resume_version_id: int | None,
    source_text: str,
    agent_state: dict,
) -> dict | None:
    draft_text = build_tailored_draft_text(source_text, agent_state)
    if len(draft_text) < config.WORKSPACE_AGENT_DRAFT_MIN_CHARS:
        return None

    version = ResumeVersion(
        user_id=user_id,
        label=f"Agent draft for {tracked.role[:config.WORKSPACE_AGENT_DRAFT_LABEL_ROLE_CHARS]}",
        source=WORKSPACE_RESUME_SOURCE_AGENT_REVIEW,
        resume_text=draft_text,
        job_id=tracked.scraped_job_id,
        job_title=tracked.role,
        job_company=tracked.company,
        word_count=len(draft_text.split()),
        is_master=False,
    )
    db.add(version)
    db.flush()
    return {
        "resume_version_id": version.id,
        "source_resume_version_id": source_resume_version_id,
        "label": version.label,
        "status": WORKSPACE_DRAFT_STATUS,
    }


def application_outcomes(db: Session, user_id: int) -> dict:
    tracked_jobs = (
        db.query(TrackedJob)
        .filter(TrackedJob.user_id == user_id)
        .order_by(TrackedJob.created_at.desc())
        .all()
    )
    resume_versions: dict[int, dict] = {}
    unlinked_applications = 0
    for tracked in tracked_jobs:
        if tracked.resume_version_id is None:
            unlinked_applications += 1
            continue
        row = resume_versions.setdefault(
            tracked.resume_version_id,
            {
                "resume_version_id": tracked.resume_version_id,
                "applications": 0,
                "counts": _empty_application_outcome_counts(),
            },
        )
        row["applications"] += 1
        outcome = _application_outcome_key(tracked.status)
        if outcome:
            row["counts"][outcome] += 1

    return {
        "total_applications": len(tracked_jobs),
        "counts": _count_current_application_outcomes(tracked_jobs),
        "stage_counts": _count_stage_history_outcomes(tracked_jobs),
        "resume_versions": sorted(
            resume_versions.values(),
            key=lambda item: (-item["applications"], item["resume_version_id"]),
        ),
        "unlinked_applications": unlinked_applications,
    }


def create_tracked_job(
    db: Session,
    user: User,
    body: TrackedJobCreate,
    on_tracked: Callable[[TrackedJob], None] | None = None,
) -> TrackedJob:
    ensure_resume_version_owner(db, user.id, body.resume_version_id)
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
        source_url=sanitize_user_input(body.source_url),
        job_description=sanitize_user_input(body.job_description),
        role_metadata=body.role_metadata,
        follow_up_date=body.follow_up_date,
        notes=sanitize_user_input(body.notes),
        scraped_job_id=body.scraped_job_id,
        resume_version_id=body.resume_version_id,
        stage_history=[
            tracked_stage_event(body.status, WORKSPACE_SOURCE_CREATED, body.date_applied)
        ],
    )
    db.add(tracked)
    if on_tracked:
        on_tracked(tracked)
    db.commit()
    db.refresh(tracked)
    return tracked


def update_tracked_job(db: Session, user: User, job_id: int, body: TrackedJobUpdate) -> TrackedJob:
    tracked = _owned_tracked_job(db, user.id, job_id)
    updates = body.model_dump(exclude_unset=True)
    ensure_resume_version_owner(db, user.id, updates.get("resume_version_id"))
    previous_status = tracked.status
    sanitize_fields = ("company", "role", "source", "source_url", "job_description", "notes")
    for key, val in updates.items():
        if key in sanitize_fields and isinstance(val, str):
            val = sanitize_user_input(val)
        setattr(tracked, key, val)

    next_status = updates.get("status")
    if next_status and next_status != previous_status:
        tracked.stage_history = list(tracked.stage_history or []) + [
            tracked_stage_event(next_status, WORKSPACE_SOURCE_MANUAL)
        ]

    db.commit()
    db.refresh(tracked)
    return tracked


def create_application_workspace(
    db: Session,
    user: User,
    body: ApplicationWorkspaceCreate,
    on_tracked: Callable[[TrackedJob], None] | None = None,
) -> dict:
    tracked = create_tracked_job(
        db,
        user,
        TrackedJobCreate(
            company=body.company,
            role=body.title,
            date_applied=body.date_applied,
            status=body.status,
            source=body.source,
            source_url=body.source_url,
            job_description=body.job_description,
            role_metadata=body.role_metadata,
            follow_up_date=body.follow_up_date,
            notes=body.notes,
            scraped_job_id=body.scraped_job_id,
            resume_version_id=body.resume_version_id,
        ),
        on_tracked=on_tracked,
    )
    return workspace_response(tracked)


def get_application_workspace(db: Session, user_id: int, workspace_id: int) -> dict:
    return workspace_response(_owned_tracked_job(db, user_id, workspace_id, workspace=True))


def run_agent_review(
    db: Session,
    user: User,
    workspace_id: int,
    body: dict | None,
    stream_events: Callable[[dict], Iterable[dict]],
    get_agent_state: Callable[..., dict],
) -> dict:
    tracked = _owned_tracked_job(db, user.id, workspace_id, workspace=True)
    body = body or {}
    resume_text = sanitize_resume_text(str(body.get("resume_text") or ""))
    if not resume_text and tracked.resume_version_id:
        version = (
            db.query(ResumeVersion)
            .filter(
                ResumeVersion.id == tracked.resume_version_id,
                ResumeVersion.user_id == user.id,
                ResumeVersion.is_active == True,
            )
            .first()
        )
        if not version:
            raise HTTPException(status_code=404, detail="Resume version not found")
        resume_text = version.resume_text or ""
    if not resume_text:
        raise HTTPException(
            status_code=400,
            detail="Attach a resume version or provide resume_text before running agent review.",
        )

    owner_key = f"user:{user.id}"
    agent_body = {
        "message": str(body.get("message") or _workspace_agent_review_prompt(tracked)),
        "resume_text": resume_text,
        "profile_context": str(body.get("profile_context") or ""),
        "_owner_key": owner_key,
    }
    if tracked.scraped_job_id:
        agent_body["job_id"] = tracked.scraped_job_id
    if body.get("session_id"):
        agent_body["session_id"] = str(body["session_id"])

    session_id = ""
    recommendations: list[str] = []
    error_message = ""
    trace_id = str(body.get("trace_id") or "")
    for event in stream_events(agent_body):
        event_name = event.get("event")
        if event_name == "session":
            session_id = str(event.get("session_id") or "")
            trace_id = trace_id or str(event.get("trace_id") or "")
        elif event_name == "token" and str(event.get("content") or "").strip():
            recommendations.append(str(event["content"]).strip())
        elif event_name == "error":
            error_message = str(event.get("message") or "Agent review failed.")

    agent_state = get_agent_state(session_id, owner_key=owner_key) if session_id else {}
    tailored_draft = None
    if not error_message:
        tailored_draft = _save_tailored_draft(
            db,
            user.id,
            tracked,
            tracked.resume_version_id,
            resume_text,
            agent_state,
        )
    role_metadata = dict(tracked.role_metadata or {})
    role_metadata[AGENT_REVIEW_METADATA_KEY] = {
        "status": "error" if error_message else "completed",
        "session_id": session_id,
        "role_brief": {
            "company": tracked.company,
            "title": tracked.role,
            "job_description": tracked.job_description or "",
            "source_url": tracked.source_url or "",
        },
        "recommendations": recommendations,
        "pending_diffs": agent_state.get("pending_diffs", []),
        "debate_summary": _workspace_debate_summary(agent_state, recommendations, trace_id),
        "tailored_draft": tailored_draft,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
    }
    tracked.role_metadata = role_metadata
    tracked.stage_history = list(tracked.stage_history or []) + [
        tracked_stage_event(
            tracked.status,
            WORKSPACE_SOURCE_AGENT_REVIEW_ERROR if error_message else WORKSPACE_SOURCE_AGENT_REVIEW,
            notes=error_message or "Deep agent review completed.",
        )
    ]
    db.commit()
    db.refresh(tracked)
    if error_message:
        raise HTTPException(status_code=503, detail=error_message)
    return workspace_response(tracked)


def save_submitted_resume(
    db: Session,
    user: User,
    workspace_id: int,
    *,
    filename: str,
    content_type: str,
    file_bytes: bytes,
    submitted_date: str = "",
    notes: str = "",
) -> dict:
    tracked = _owned_tracked_job(db, user.id, workspace_id, workspace=True)
    try:
        parsed = parse_resume(
            filename=filename or "resume",
            content_type=content_type or "",
            file_bytes=file_bytes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    now = datetime.now(timezone.utc)
    clean_filename = sanitize_user_input(filename or "resume")
    artifact = {
        "artifact_id": secrets.token_urlsafe(config.WORKSPACE_SUBMITTED_ARTIFACT_TOKEN_BYTES),
        "filename": clean_filename,
        "content_type": content_type or "",
        "file_type": parsed.get("file_type", ""),
        "size_bytes": len(file_bytes),
        "submitted_date": sanitize_user_input(submitted_date) or now.date().isoformat(),
        "notes": sanitize_user_input(notes),
        "text": parsed.get("text", ""),
        "word_count": parsed.get("word_count", 0),
        "line_count": parsed.get("line_count", 0),
        "parse_quality": parsed.get("parse_quality", {}),
        "content_base64": base64.b64encode(file_bytes).decode("ascii"),
        "created_at": now.isoformat(),
    }
    role_metadata = dict(tracked.role_metadata or {})
    history = list(role_metadata.get(SUBMITTED_RESUME_ARTIFACTS_METADATA_KEY) or [])
    history.append(artifact)
    role_metadata[SUBMITTED_RESUME_ARTIFACTS_METADATA_KEY] = history
    role_metadata[SUBMITTED_RESUME_METADATA_KEY] = {
        key: artifact[key]
        for key in (
            "artifact_id",
            "filename",
            "content_type",
            "file_type",
            "size_bytes",
            "submitted_date",
            "notes",
            "text",
            "word_count",
            "line_count",
            "parse_quality",
            "created_at",
        )
    }
    tracked.role_metadata = role_metadata
    db.commit()
    db.refresh(tracked)
    return workspace_response(tracked)
