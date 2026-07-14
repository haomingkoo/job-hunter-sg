"""Canonical, JSON-serialisable resume document and safe text replacement."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import re
from typing import Any

from shared_classification import classify_section_heading


SCHEMA_VERSION = 1
_BULLET_MARKER = r"(?:[•\-*▪\u2023\u25E6\u2043\u2219]|\d+[.)])"


class ResumePatchError(ValueError):
    """Raised when a patch cannot be safely applied."""


class StaleResumeRevision(ResumePatchError):
    """Raised when a patch targets an older document revision."""


def _hash(prefix: str, value: str) -> str:
    return f"{prefix}_{hashlib.sha256(value.encode()).hexdigest()[:20]}"


def _revision(text: str) -> str:
    return _hash("r", text)


def _candidate_custom_heading(text: str) -> bool:
    words = text.split()
    return (
        2 <= len(words) <= 10
        and len(text) <= 100
        and any(char.isalpha() for char in text)
        and text == text.upper()
        and not re.search(r"\d|@|https?://|\|", text, re.I)
        and not text.endswith((".", "!", "?", ";"))
    )


def _flexible_text_pattern(text: str) -> str:
    parts = re.split(r"\s+", text.strip())
    return r"\s+".join(re.escape(part) for part in parts if part)


def _structured_bullet_spans(text: str) -> list[dict[str, Any]]:
    from resume_structurer import get_all_bullets, structure_resume

    bullets = get_all_bullets(structure_resume(text))
    spans: list[dict[str, Any]] = []
    cursor = 0
    for bullet in bullets:
        content_pattern = _flexible_text_pattern(str(bullet.get("text") or ""))
        if not content_pattern:
            continue
        pattern = re.compile(
            rf"(?m)^[\t ]*{_BULLET_MARKER}[\t ]*(?P<content>{content_pattern})",
        )
        match = pattern.search(text, cursor)
        if not match:
            continue
        start, end = match.span("content")
        spans.append({
            "start": start,
            "end": end,
            "text": re.sub(r"\s+", " ", match.group("content")).strip(),
            "source_text": match.group("content"),
            "section_key": str(bullet.get("section_key") or ""),
            "entry_id": str(bullet.get("entry_id") or ""),
        })
        cursor = end
    return spans


def _line_spans(text: str, occupied: list[tuple[int, int]]) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    for match in re.finditer(r"[^\n]+", text):
        raw = match.group()
        leading = len(raw) - len(raw.lstrip())
        trailing = len(raw.rstrip())
        start = match.start() + leading
        end = match.start() + trailing
        if start >= end or any(start < taken_end and end > taken_start for taken_start, taken_end in occupied):
            continue
        spans.append({
            "start": start,
            "end": end,
            "text": text[start:end],
            "source_text": text[start:end],
            "section_key": "",
            "entry_id": "",
        })
    return spans


def create_resume_document(
    text: str,
    *,
    source_format: str = "text",
    filename: str | None = None,
    source_sha256: str | None = None,
    warnings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return one canonical document for uploaded or pasted resume text."""
    raw_text = str(text or "")
    source_hash = source_sha256 or hashlib.sha256(raw_text.encode()).hexdigest()
    document_id = f"d_{source_hash[:20]}"
    bullet_spans = _structured_bullet_spans(raw_text)
    occupied = [(item["start"], item["end"]) for item in bullet_spans]
    source_blocks = sorted(
        [*bullet_spans, *_line_spans(raw_text, occupied)],
        key=lambda item: (item["start"], item["end"]),
    )

    blocks: list[dict[str, Any]] = []
    sections: list[dict[str, Any]] = []
    current_section_id: str | None = None
    current_section_key = ""
    seen_known_section = False
    for order, item in enumerate(source_blocks):
        value = item["text"].strip()
        section_key = classify_section_heading(value)
        is_custom_heading = (
            section_key is None
            and seen_known_section
            and _candidate_custom_heading(value)
        )
        kind = "bullet" if item in bullet_spans else "paragraph"
        if section_key or is_custom_heading:
            kind = "section_heading"

        locator = f"chars:{item['start']}-{item['end']}"
        block_id = _hash(
            "b",
            f"{document_id}\0{locator}\0{item['source_text']}",
        )
        if kind == "section_heading":
            seen_known_section = seen_known_section or section_key is not None
            current_section_id = f"s_{block_id[2:]}"
            current_section_key = section_key or ""
            sections.append({
                "id": current_section_id,
                "key": section_key,
                "label": value,
                "status": "confirmed" if section_key else "candidate",
                "heading_block_id": block_id,
                "parent_entry_id": None,
            })

        block_section_key = item.get("section_key") or current_section_key
        blocks.append({
            "id": block_id,
            "order": order,
            "kind": kind,
            "text": value,
            "source_text": item["source_text"],
            "raw_span": [item["start"], item["end"]],
            "section_id": current_section_id,
            "section_key": block_section_key,
            "entry_id": item.get("entry_id") or "",
            "source": {
                "locator": locator,
                "format": source_format,
            },
        })

    return {
        "schema_version": SCHEMA_VERSION,
        "document_id": document_id,
        "revision": _revision(raw_text),
        "source": {
            "format": source_format,
            "filename": filename,
            "sha256": source_hash,
        },
        "raw_text": raw_text,
        "blocks": blocks,
        "sections": sections,
        "warnings": list(warnings or []),
    }


def apply_resume_patch(document: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Replace one addressed block after checking revision, text and numeric facts."""
    if document.get("schema_version") != SCHEMA_VERSION:
        raise ResumePatchError("Unsupported resume document schema.")
    if patch.get("expected_revision") != document.get("revision"):
        raise StaleResumeRevision("Resume changed after this suggestion was created.")

    block_id = str(patch.get("block_id") or "")
    block = next((item for item in document.get("blocks", []) if item.get("id") == block_id), None)
    if not block:
        raise ResumePatchError("Unknown resume block.")
    if str(patch.get("expected_text") or "") != block.get("text"):
        raise ResumePatchError("Resume block text no longer matches this suggestion.")

    replacement = str(patch.get("text") or "").strip()
    if not replacement:
        raise ResumePatchError("Replacement text is required.")
    if "\n" in replacement or "\r" in replacement:
        raise ResumePatchError("A replacement must stay within one resume block.")

    from validation_gates import _extract_numbers

    new_numbers = _extract_numbers(replacement) - _extract_numbers(str(block.get("text") or ""))
    if new_numbers:
        raise ResumePatchError(f"Unsupported numeric facts: {', '.join(sorted(new_numbers))}")

    updated = deepcopy(document)
    updated_block = next(item for item in updated["blocks"] if item["id"] == block_id)
    start, end = updated_block["raw_span"]
    old_source = updated_block["source_text"]
    raw_text = str(updated["raw_text"])
    updated["raw_text"] = raw_text[:start] + replacement + raw_text[end:]
    delta = len(replacement) - len(old_source)
    updated_block["text"] = replacement
    updated_block["source_text"] = replacement
    updated_block["raw_span"] = [start, start + len(replacement)]
    updated_block["source"]["locator"] = f"chars:{start}-{start + len(replacement)}"
    for other in updated["blocks"]:
        if other["id"] == block_id or other["raw_span"][0] < end:
            continue
        other["raw_span"] = [other["raw_span"][0] + delta, other["raw_span"][1] + delta]
        other["source"]["locator"] = f"chars:{other['raw_span'][0]}-{other['raw_span'][1]}"
    updated["revision"] = _revision(updated["raw_text"])
    return updated
