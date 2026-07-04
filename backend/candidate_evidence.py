"""Candidate evidence graph tracer bullet stored on application workspaces."""

from __future__ import annotations

import hashlib

from fastapi import HTTPException
from models import TrackedJob
from sqlalchemy.orm import Session


EVIDENCE_GRAPH_METADATA_KEY = "candidate_evidence_graph"
CLAIMS_KEY = "claims"
EVIDENCE_KEY = "evidence"
APPLICATION_LINKS_KEY = "application_links"
ARTIFACT_LINKS_KEY = "artifact_links"

PROOF_SUPPORTED = "supported"
PROOF_NEEDS_CONFIRMATION = "needs_confirmation"
PROOF_UNSUPPORTED = "unsupported"
PROOF_STATUSES = (PROOF_SUPPORTED, PROOF_NEEDS_CONFIRMATION, PROOF_UNSUPPORTED)

EVIDENCE_ID_HASH_CHARS = 12
CONFIRMATION_QUESTION_TEMPLATE = "Can you confirm whether this evidence supports: {claim_text}"


def record_claim_evidence(
    db: Session,
    user_id: int,
    workspace_id: int,
    *,
    claim_key: str,
    claim_text: str,
    source_text: str,
    source_type: str,
    proof_status: str,
    artifact_id: str = "",
    artifact_kind: str = "",
) -> dict:
    tracked = _owned_workspace(db, user_id, workspace_id)
    clean_claim_key = _required("claim_key", claim_key)
    clean_claim_text = _required("claim_text", claim_text)
    clean_source_text = _required("source_text", source_text)
    clean_source_type = _required("source_type", source_type)
    clean_proof_status = _proof_status(proof_status)
    clean_artifact_id = (artifact_id or "").strip()
    clean_artifact_kind = (artifact_kind or "").strip()
    if bool(clean_artifact_id) != bool(clean_artifact_kind):
        raise HTTPException(
            status_code=400,
            detail="artifact_id and artifact_kind must be provided together.",
        )

    role_metadata = dict(tracked.role_metadata or {})
    graph = _graph(role_metadata)
    claim_id = _stable_id("claim", clean_claim_key, clean_source_text)
    evidence_id = _stable_id("evidence", clean_claim_key, clean_source_text)
    confirmation_question = (
        ""
        if clean_proof_status == PROOF_SUPPORTED
        else CONFIRMATION_QUESTION_TEMPLATE.format(claim_text=clean_claim_text)
    )

    graph[CLAIMS_KEY][claim_id] = {
        "id": claim_id,
        "claim_key": clean_claim_key,
        "candidate_claim": clean_claim_text,
        "resume_claim": clean_claim_text if clean_proof_status == PROOF_SUPPORTED else "",
        "proof_status": clean_proof_status,
        "confirmation_question": confirmation_question,
    }
    graph[EVIDENCE_KEY][evidence_id] = {
        "id": evidence_id,
        "claim_id": claim_id,
        "source_type": clean_source_type,
        "source_text": clean_source_text,
        "source_hash": _stable_id("source", clean_source_text),
        "proof_status": clean_proof_status,
    }
    _append_unique(
        graph[APPLICATION_LINKS_KEY],
        {
            "workspace_id": workspace_id,
            "claim_id": claim_id,
            "evidence_id": evidence_id,
            "proof_status": clean_proof_status,
        },
    )
    if clean_artifact_id:
        _append_unique(
            graph[ARTIFACT_LINKS_KEY],
            {
                "workspace_id": workspace_id,
                "artifact_id": clean_artifact_id,
                "artifact_kind": clean_artifact_kind,
                "claim_id": claim_id,
                "evidence_id": evidence_id,
            },
        )

    role_metadata[EVIDENCE_GRAPH_METADATA_KEY] = graph
    tracked.role_metadata = role_metadata
    db.commit()
    db.refresh(tracked)
    return dict(tracked.role_metadata or {}).get(EVIDENCE_GRAPH_METADATA_KEY, {})


def _owned_workspace(db: Session, user_id: int, workspace_id: int) -> TrackedJob:
    tracked = db.query(TrackedJob).filter(TrackedJob.id == workspace_id).first()
    if not tracked:
        raise HTTPException(status_code=404, detail="Application workspace not found")
    if tracked.user_id != user_id:
        raise HTTPException(status_code=403, detail="Not your application workspace")
    return tracked


def _required(name: str, value: str) -> str:
    clean = (value or "").strip()
    if not clean:
        raise HTTPException(status_code=400, detail=f"{name} is required.")
    return " ".join(clean.split())


def _proof_status(value: str) -> str:
    clean = (value or "").strip()
    if clean not in PROOF_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"proof_status must be one of: {', '.join(PROOF_STATUSES)}",
        )
    return clean


def _graph(role_metadata: dict) -> dict:
    current = role_metadata.get(EVIDENCE_GRAPH_METADATA_KEY)
    graph = current if isinstance(current, dict) else {}
    return {
        CLAIMS_KEY: dict(graph.get(CLAIMS_KEY) or {}),
        EVIDENCE_KEY: dict(graph.get(EVIDENCE_KEY) or {}),
        APPLICATION_LINKS_KEY: list(graph.get(APPLICATION_LINKS_KEY) or []),
        ARTIFACT_LINKS_KEY: list(graph.get(ARTIFACT_LINKS_KEY) or []),
    }


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()
    return f"{prefix}_{digest[:EVIDENCE_ID_HASH_CHARS]}"


def _append_unique(items: list[dict], item: dict) -> None:
    if item not in items:
        items.append(item)
