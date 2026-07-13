"""Workspace role-research source ledger."""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

from fastapi import HTTPException
from models import TrackedJob
from sqlalchemy.orm import Session


ROLE_RESEARCH_METADATA_KEY = "role_research"
SOURCES_KEY = "sources"
COMPARABLE_TITLES_KEY = "comparable_titles"
ATS_KEYWORDS_KEY = "ats_keywords"
SOURCE_LEADS_KEY = "source_leads"

STATUS_READY = "ready"
STATUS_DEGRADED = "degraded"
DEGRADED_REASON_NO_SOURCES = "No source-backed role research was found."

SOURCE_COMPANY = "company"
SOURCE_JOB_BOARD = "job_board"
SOURCE_GLASSDOOR = "glassdoor"
SOURCE_REDDIT = "reddit"
SOURCE_WEB = "web"
SOURCE_TYPES = (SOURCE_COMPANY, SOURCE_JOB_BOARD, SOURCE_GLASSDOOR, SOURCE_REDDIT, SOURCE_WEB)

CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW = "low"
CONFIDENCE_UNKNOWN = "unknown"
CONFIDENCE_LABELS = (CONFIDENCE_HIGH, CONFIDENCE_MEDIUM, CONFIDENCE_LOW, CONFIDENCE_UNKNOWN)


def save_role_brief(
    db: Session,
    user_id: int,
    workspace_id: int,
    *,
    company_notes: str = "",
    role_notes: str = "",
    comparable_titles: list[dict] | None = None,
    ats_keywords: list[dict] | None = None,
    source_leads: list[dict] | None = None,
) -> dict:
    tracked = _owned_workspace(db, user_id, workspace_id)
    sources: dict[str, dict] = {}
    now = datetime.now(timezone.utc).isoformat()
    titles = _items(comparable_titles or [], sources, now)
    keywords = _items(ats_keywords or [], sources, now)
    leads = _items(source_leads or [], sources, now)
    empty = not (titles or keywords or leads)
    brief = {
        "status": STATUS_DEGRADED if empty else STATUS_READY,
        "empty": empty,
        "degraded_reason": DEGRADED_REASON_NO_SOURCES if empty else "",
        "company_notes": _clean(company_notes),
        "role_notes": _clean(role_notes),
        "candidate_experience_used": False,
        "resume_claims": [],
        SOURCES_KEY: sorted(
            sources.values(),
            key=lambda item: (item["source_type"], item["source_url"]),
        ),
        COMPARABLE_TITLES_KEY: titles,
        ATS_KEYWORDS_KEY: keywords,
        SOURCE_LEADS_KEY: leads,
    }

    role_metadata = dict(tracked.role_metadata or {})
    role_metadata[ROLE_RESEARCH_METADATA_KEY] = brief
    tracked.role_metadata = role_metadata
    db.commit()
    db.refresh(tracked)
    return dict(tracked.role_metadata or {}).get(ROLE_RESEARCH_METADATA_KEY, {})


def _items(items: list[dict], sources: dict[str, dict], default_retrieved_at: str) -> list[dict]:
    return [_item(item, sources, default_retrieved_at) for item in items]


def _item(item: dict, sources: dict[str, dict], default_retrieved_at: str) -> dict:
    value = _required("value", str(item.get("value") or ""))
    source_url = _canonical_url(_required("source_url", str(item.get("source_url") or "")))
    source_type = _source_type(str(item.get("source_type") or ""))
    confidence = _confidence(str(item.get("confidence") or CONFIDENCE_UNKNOWN))
    retrieved_at = _clean(str(item.get("retrieved_at") or "")) or default_retrieved_at
    evidence_note = _required("evidence_note", str(item.get("evidence_note") or ""))
    source_id = f"{source_type}:{source_url}"
    sources[source_id] = {
        "id": source_id,
        "source_url": source_url,
        "source_type": source_type,
        "retrieved_at": retrieved_at,
        "confidence": confidence,
        "evidence_note": evidence_note,
    }
    return {
        "value": value,
        "source_id": source_id,
        "source_url": source_url,
        "source_type": source_type,
        "retrieved_at": retrieved_at,
        "confidence": confidence,
        "evidence_note": evidence_note,
    }


def _owned_workspace(db: Session, user_id: int, workspace_id: int) -> TrackedJob:
    tracked = db.query(TrackedJob).filter(TrackedJob.id == workspace_id).first()
    if not tracked:
        raise HTTPException(status_code=404, detail="Application workspace not found")
    if tracked.user_id != user_id:
        raise HTTPException(status_code=403, detail="Not your application workspace")
    return tracked


def _required(name: str, value: str) -> str:
    clean = _clean(value)
    if not clean:
        raise HTTPException(status_code=400, detail=f"{name} is required.")
    return clean


def _clean(value: str) -> str:
    return " ".join((value or "").strip().split())


def _source_type(value: str) -> str:
    clean = _clean(value)
    if clean not in SOURCE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"source_type must be one of: {', '.join(SOURCE_TYPES)}",
        )
    return clean


def _confidence(value: str) -> str:
    clean = _clean(value)
    if clean not in CONFIDENCE_LABELS:
        raise HTTPException(
            status_code=400,
            detail=f"confidence must be one of: {', '.join(CONFIDENCE_LABELS)}",
        )
    return clean


def _canonical_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail="source_url must be an http(s) URL.")
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, parsed.query, ""))
