"""V3-specific tools bound to the open-agent orchestrator. search_jobs is reused
unmodified from resume_agent.tools -- it needs no per-request context."""

from __future__ import annotations

from dataclasses import asdict

from langchain_core.tools import tool

import config
from validation_gates import _extract_numbers, run_all_gates

from . import context


@tool
def ask_candidate(question: str) -> dict:
    """Ask the candidate one focused question about a real evidence gap.

    This tool must be bound with interrupt_on={"ask_candidate": True} on the
    orchestrator agent -- calling it pauses the graph before any further tool
    call executes. The candidate's next message answers it; that answer
    becomes citable evidence for later propose_resume_edit calls in this
    thread. This is enforced by the interrupt, not by prompted convention.
    """
    return {"ok": True, "question": question}


@tool
def read_candidate_evidence() -> dict:
    """Read the candidate's evidence-cited profile fields for the active run.

    Returns each field with its resume_evidence_ids, so a citation in a
    persona submission or a proposed edit can point at real evidence.
    """
    request = context.current_request()
    if request is None:
        return {"ok": False, "failure_type": "business", "reason": "No active assessment context."}
    return {
        "ok": True,
        "fields": [asdict(field) for field in request.candidate_profile.fields],
    }


@tool
def read_target_job() -> dict:
    """Read the target job posting and its derived role-success criteria for the active run."""
    request = context.current_request()
    if request is None:
        return {"ok": False, "failure_type": "business", "reason": "No active assessment context."}
    return {
        "ok": True,
        "target_job": asdict(request.target_job),
        "role_profile": asdict(request.role_profile),
    }


@tool
def propose_resume_edit(block_id: str, rewrite: str) -> dict:
    """Draft an in-place, evidence-safe rewrite of one existing resume block.

    `block_id` must be a canonical block ID visible in the active resume
    document. `rewrite` must replace that block's text without introducing
    new numeric facts and must stay within one block (no line breaks) -- this
    tool cannot insert or delete a block. A valid proposal remains pending
    until the candidate explicitly accepts it.
    """
    document = context.current_document()
    edits = context.proposed_edits()
    if document is None or edits is None:
        return {"accepted": False, "reason": "No active assessment context.", "block_id": block_id}
    if len(edits) >= config.OPEN_AGENT_MAX_PROPOSED_EDITS:
        return {
            "accepted": False,
            "reason": "Per-run proposed-edit cap reached; checkpoint back to the candidate before proposing more.",
            "block_id": block_id,
            "checkpoint_required": True,
        }
    block = next((b for b in document.get("blocks", []) if b.get("id") == block_id), None)
    if not block:
        return {"accepted": False, "reason": "Unknown resume block.", "block_id": block_id}

    clean_rewrite = (rewrite or "").strip()
    if "\n" in clean_rewrite or "\r" in clean_rewrite:
        return {"accepted": False, "reason": "A replacement must stay within one resume block.", "block_id": block_id}

    original_text = str(block.get("text") or "")
    new_numbers = _extract_numbers(clean_rewrite) - _extract_numbers(original_text)
    if new_numbers:
        return {
            "accepted": False,
            "reason": f"Unsupported numeric facts: {', '.join(sorted(new_numbers))}",
            "block_id": block_id,
        }

    failed = [gate for gate in run_all_gates(original_text, clean_rewrite) if not gate.passed]
    if failed:
        return {"accepted": False, "reason": "; ".join(gate.message for gate in failed), "block_id": block_id}

    edits.append({
        "block_id": block_id,
        "section_key": block.get("section_key", ""),
        "entry_id": block.get("entry_id", ""),
        "original": original_text,
        "rewrite": clean_rewrite,
        "document_revision": document.get("revision"),
        "status": "pending",
    })
    return {"accepted": True, "application_status": "pending_user_review", "block_id": block_id, "rewrite": clean_rewrite}
