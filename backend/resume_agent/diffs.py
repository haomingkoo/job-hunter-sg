"""Per-bullet diff helpers for Resume Deep Agent v2."""

from __future__ import annotations

from typing import Any

from resume_structurer import get_all_bullets, structure_resume

from .tools import bullet_context, propose_edit


def _bullet_lookup(resume_text: str) -> tuple[dict[str, str], dict[str, dict]]:
    bullets = get_all_bullets(structure_resume(resume_text))
    text_by_id = {bullet["id"]: bullet["text"] for bullet in bullets}
    meta_by_id = {bullet["id"]: bullet for bullet in bullets}
    return text_by_id, meta_by_id


def build_pending_diffs(
    resume_text: str,
    proposals: list[dict[str, Any]],
) -> list[dict]:
    """Validate rewrite proposals and return pending per-bullet diffs."""
    text_by_id, meta_by_id = _bullet_lookup(resume_text)
    pending: list[dict] = []
    seen: set[str] = set()

    with bullet_context(text_by_id):
        for proposal in proposals:
            bullet_id = str(proposal.get("bullet_id", ""))
            if not bullet_id or bullet_id in seen or bullet_id not in text_by_id:
                continue
            seen.add(bullet_id)
            result = propose_edit.invoke(
                {
                    "bullet_id": bullet_id,
                    "rewrite": str(proposal.get("rewrite", "")),
                }
            )
            rewrite = result.get("rewrite", "")
            if not result.get("accepted") or rewrite == text_by_id[bullet_id]:
                continue
            meta = meta_by_id[bullet_id]
            pending.append(
                {
                    "bullet_id": bullet_id,
                    "section_key": meta.get("section_key", ""),
                    "entry_id": meta.get("entry_id", ""),
                    "original": text_by_id[bullet_id],
                    "rewrite": rewrite,
                    "status": "pending",
                }
            )
    return pending
