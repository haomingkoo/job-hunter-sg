"""Evidence-grounded interview prep pack for application workspaces."""

from __future__ import annotations

import hashlib

import candidate_evidence
import role_research
from fastapi import HTTPException
from models import TrackedJob
from sqlalchemy.orm import Session


INTERVIEW_PREP_METADATA_KEY = "interview_prep_pack"
QUESTION_CLUSTERS_KEY = "question_clusters"
EVIDENCE_QUESTIONS_KEY = "evidence_questions"
SOURCE_LEADS_KEY = "source_leads"

STATUS_READY = "ready"
STATUS_DEGRADED = "degraded"
DEGRADED_REASON_NO_RESEARCH = "No source-backed role research is saved for this workspace."

QUESTION_TECHNICAL = "technical"
QUESTION_ROLE_FIT = "role_fit"
QUESTION_TYPES = (QUESTION_TECHNICAL, QUESTION_ROLE_FIT)

SCAFFOLD_EVIDENCE_BACKED = "evidence_backed"
SCAFFOLD_NEEDS_USER_INPUT = "needs_user_input"
QUESTION_ID_HASH_CHARS = 12


def generate_prep_pack(db: Session, user_id: int, workspace_id: int) -> dict:
    tracked = _owned_workspace(db, user_id, workspace_id)
    role_metadata = dict(tracked.role_metadata or {})
    role_brief = role_metadata.get(role_research.ROLE_RESEARCH_METADATA_KEY)
    evidence_graph = role_metadata.get(candidate_evidence.EVIDENCE_GRAPH_METADATA_KEY) or {}
    if not isinstance(role_brief, dict) or role_brief.get("empty"):
        return _save_pack(tracked, role_metadata, _degraded_pack(), db)

    supported_claims = _supported_claims(evidence_graph)
    evidence_by_claim = _evidence_by_claim(evidence_graph)
    clusters = {}
    evidence_questions = []
    for item in role_brief.get(role_research.ATS_KEYWORDS_KEY) or []:
        _add_question(
            clusters,
            evidence_questions,
            item,
            QUESTION_TECHNICAL,
            f"How have you used {item.get('value')} in work relevant to this role?",
            supported_claims,
            evidence_by_claim,
        )
    for item in role_brief.get(role_research.COMPARABLE_TITLES_KEY) or []:
        _add_question(
            clusters,
            evidence_questions,
            item,
            QUESTION_ROLE_FIT,
            f"What experience makes you credible for {item.get('value')} work?",
            supported_claims,
            evidence_by_claim,
        )
    for claim in _uncertain_claims(evidence_graph):
        _append_unique(
            evidence_questions,
            {
                "claim_id": claim.get("id", ""),
                "question": claim.get("confirmation_question")
                or f"What evidence supports: {claim.get('candidate_claim', '')}",
            },
        )

    pack = {
        "status": STATUS_READY,
        "degraded_reason": "",
        "summary": {
            "question_count": len(clusters),
            "evidence_question_count": len(evidence_questions),
            "source_count": len(role_brief.get(role_research.SOURCES_KEY) or []),
        },
        QUESTION_CLUSTERS_KEY: list(clusters.values()),
        EVIDENCE_QUESTIONS_KEY: evidence_questions,
        SOURCE_LEADS_KEY: _source_leads(role_brief),
    }
    return _save_pack(tracked, role_metadata, pack, db)


def _add_question(
    clusters: dict[str, dict],
    evidence_questions: list[dict],
    item: dict,
    question_type: str,
    question: str,
    supported_claims: list[dict],
    evidence_by_claim: dict[str, dict],
) -> None:
    value = str(item.get("value") or "").strip()
    source_id = str(item.get("source_id") or "").strip()
    if not value or not source_id:
        return
    question_key = _stable_id(question_type, source_id, value.lower())
    if question_key in clusters:
        return
    claim = _matching_claim(value, supported_claims, evidence_by_claim)
    evidence = evidence_by_claim.get(str(claim.get("id") or ""), {})
    needs_input = not claim
    if needs_input:
        _append_unique(
            evidence_questions,
            {
                "claim_id": "",
                "question": f"What specific candidate evidence supports your ability to handle {value}?",
            },
        )
    clusters[question_key] = {
        "question_key": question_key,
        "type": question_type,
        "confidence": item.get("confidence") or role_research.CONFIDENCE_UNKNOWN,
        "question": question,
        "source_id": source_id,
        "source_url": item.get("source_url", ""),
        "source_type": item.get("source_type", ""),
        "retrieved_at": item.get("retrieved_at", ""),
        "answer_scaffold": {
            "status": SCAFFOLD_NEEDS_USER_INPUT if needs_input else SCAFFOLD_EVIDENCE_BACKED,
            "claim_id": claim.get("id", ""),
            "evidence_id": evidence.get("id", ""),
            "prompt": ""
            if needs_input
            else f"Anchor answer on supported evidence: {claim.get('resume_claim', '')}",
        },
    }


def _supported_claims(evidence_graph: dict) -> list[dict]:
    claims = evidence_graph.get(candidate_evidence.CLAIMS_KEY) if isinstance(evidence_graph, dict) else {}
    if not isinstance(claims, dict):
        return []
    return [
        claim
        for claim in claims.values()
        if claim.get("proof_status") == candidate_evidence.PROOF_SUPPORTED and claim.get("resume_claim")
    ]


def _uncertain_claims(evidence_graph: dict) -> list[dict]:
    claims = evidence_graph.get(candidate_evidence.CLAIMS_KEY) if isinstance(evidence_graph, dict) else {}
    if not isinstance(claims, dict):
        return []
    return [
        claim
        for claim in claims.values()
        if claim.get("proof_status") != candidate_evidence.PROOF_SUPPORTED
    ]


def _evidence_by_claim(evidence_graph: dict) -> dict[str, dict]:
    evidence = evidence_graph.get(candidate_evidence.EVIDENCE_KEY) if isinstance(evidence_graph, dict) else {}
    if not isinstance(evidence, dict):
        return {}
    return {str(item.get("claim_id") or ""): item for item in evidence.values() if item.get("claim_id")}


def _matching_claim(value: str, supported_claims: list[dict], evidence_by_claim: dict[str, dict]) -> dict:
    needle = _clean_key(value)
    if not needle:
        return {}
    for claim in supported_claims:
        evidence = evidence_by_claim.get(str(claim.get("id") or ""), {})
        haystack = _clean_key(
            f"{claim.get('candidate_claim', '')} "
            f"{claim.get('resume_claim', '')} "
            f"{evidence.get('source_text', '')}"
        )
        if needle in haystack:
            return claim
    return {}


def _source_leads(role_brief: dict) -> list[dict]:
    return [
        {
            "value": lead.get("value", ""),
            "source_url": lead.get("source_url", ""),
            "source_type": lead.get("source_type", ""),
            "retrieved_at": lead.get("retrieved_at", ""),
            "evidence_note": lead.get("evidence_note", ""),
        }
        for lead in role_brief.get(role_research.SOURCE_LEADS_KEY) or []
    ]


def _degraded_pack() -> dict:
    return {
        "status": STATUS_DEGRADED,
        "degraded_reason": DEGRADED_REASON_NO_RESEARCH,
        "summary": {
            "question_count": 0,
            "evidence_question_count": 0,
            "source_count": 0,
        },
        QUESTION_CLUSTERS_KEY: [],
        EVIDENCE_QUESTIONS_KEY: [],
        SOURCE_LEADS_KEY: [],
    }


def _save_pack(tracked: TrackedJob, role_metadata: dict, pack: dict, db: Session) -> dict:
    role_metadata[INTERVIEW_PREP_METADATA_KEY] = pack
    tracked.role_metadata = role_metadata
    db.commit()
    db.refresh(tracked)
    return dict(tracked.role_metadata or {}).get(INTERVIEW_PREP_METADATA_KEY, {})


def _owned_workspace(db: Session, user_id: int, workspace_id: int) -> TrackedJob:
    tracked = db.query(TrackedJob).filter(TrackedJob.id == workspace_id).first()
    if not tracked:
        raise HTTPException(status_code=404, detail="Application workspace not found")
    if tracked.user_id != user_id:
        raise HTTPException(status_code=403, detail="Not your application workspace")
    return tracked


def _stable_id(*parts: str) -> str:
    digest = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()
    return f"question_{digest[:QUESTION_ID_HASH_CHARS]}"


def _append_unique(items: list[dict], item: dict) -> None:
    if item not in items:
        items.append(item)


def _clean_key(value: str) -> str:
    return " ".join((value or "").lower().strip().split())
