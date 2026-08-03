"""Canonical, JSON-serialisable resume document and safe text replacement."""

from __future__ import annotations

from copy import deepcopy
from collections import Counter
import hashlib
import re
from typing import Any

from resume_identity import SCHEMA_VERSION, block_id, document_id, document_revision
from shared_classification import classify_section_heading


_BULLET_MARKER = r"(?:[•\-*▪\u2023\u25E6\u2043\u2219]|\d+[.)])"


class ResumePatchError(ValueError):
    """Raised when a patch cannot be safely applied."""


class StaleResumeRevision(ResumePatchError):
    """Raised when a patch targets an older document revision."""


def is_resume_document(value: Any) -> bool:
    """Return whether a value satisfies the current canonical interface."""
    return bool(
        isinstance(value, dict)
        and value.get("schema_version") == SCHEMA_VERSION
        and isinstance(value.get("raw_text"), str)
        and isinstance(value.get("blocks"), list)
        and isinstance(value.get("sections"), list)
        and isinstance(value.get("warnings"), list)
    )


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


def _block_layout(
    item: dict[str, Any],
    layout_blocks: list[dict[str, Any]],
) -> dict[str, Any]:
    overlapping = [
        block
        for block in layout_blocks
        if isinstance(block.get("raw_span"), list)
        and len(block["raw_span"]) == 2
        and item["start"] < block["raw_span"][1]
        and item["end"] > block["raw_span"][0]
    ]
    source_text = str(item.get("source_text") or "")
    marker_match = re.match(rf"^\s*({_BULLET_MARKER})", source_text)
    pages = list(dict.fromkeys(block.get("page") for block in overlapping if block.get("page") is not None))
    font_sizes = [float(block["font_size"]) for block in overlapping if block.get("font_size") is not None]
    first = overlapping[0] if overlapping else {}
    leading = len(source_text) - len(source_text.lstrip(" \t"))
    return {
        "page": pages[0] if pages else None,
        "pages": pages,
        "list_marker": first.get("list_marker") or (marker_match.group(1) if marker_match else None),
        "indentation": first.get("indentation") if first.get("indentation") is not None else leading,
        "x_position": first.get("x_position"),
        "heading_emphasis": any(bool(block.get("heading_emphasis")) for block in overlapping),
        "font_size": max(font_sizes, default=None),
        "heading_level": next((block.get("heading_level") for block in overlapping if block.get("heading_level") is not None), None),
        "style_name": next((block.get("style_name") for block in overlapping if block.get("style_name")), None),
    }


def _layout_heading_candidate(
    layout: dict[str, Any],
    *,
    body_font_size: float | None,
    top_heading_font_size: float | None,
    top_heading_indentation: float | None,
    top_heading_level: int | None,
) -> bool:
    heading_level = layout.get("heading_level")
    if heading_level is not None:
        return top_heading_level is None or int(heading_level) <= top_heading_level
    if not layout.get("heading_emphasis"):
        return False
    font_size = layout.get("font_size")
    indentation = layout.get("indentation")
    large_enough = (
        font_size is not None
        and (
            (top_heading_font_size is not None and float(font_size) >= top_heading_font_size)
            or (top_heading_font_size is None and body_font_size is not None and float(font_size) > body_font_size)
        )
    )
    aligned = (
        top_heading_indentation is None
        or indentation is None
        or float(indentation) <= top_heading_indentation
    )
    return bool(large_enough and aligned)


def _top_heading_evidence(
    source_blocks: list[dict[str, Any]],
    layout_blocks: list[dict[str, Any]],
) -> tuple[float | None, float | None, int | None]:
    layouts = [
        _block_layout(item, layout_blocks)
        for item in source_blocks
        if classify_section_heading(str(item.get("text") or "").strip()) is not None
    ]
    font_sizes = [float(item["font_size"]) for item in layouts if item.get("font_size") is not None]
    indentations = [float(item["indentation"]) for item in layouts if item.get("indentation") is not None]
    heading_levels = [int(item["heading_level"]) for item in layouts if item.get("heading_level") is not None]
    return (
        max(font_sizes, default=None),
        min(indentations, default=None),
        min(heading_levels, default=None),
    )


def _layout_indicates_nested_heading(
    layout: dict[str, Any],
    *,
    top_heading_font_size: float | None,
    top_heading_indentation: float | None,
    top_heading_level: int | None,
) -> bool:
    heading_level = layout.get("heading_level")
    if heading_level is not None and top_heading_level is not None:
        return int(heading_level) > top_heading_level
    indentation = layout.get("indentation")
    if indentation is not None and top_heading_indentation is not None:
        if float(indentation) > top_heading_indentation:
            return True
    font_size = layout.get("font_size")
    return bool(
        font_size is not None
        and top_heading_font_size is not None
        and float(font_size) < top_heading_font_size
    )


def _structured_bullet_spans(text: str) -> list[dict[str, Any]]:
    from resume_structurer import get_all_bullets, structure_resume

    bullets = get_all_bullets(structure_resume(text))
    spans: list[dict[str, Any]] = []
    for bullet in bullets:
        source_span = bullet.get("source_span")
        if not isinstance(source_span, list) or len(source_span) != 2:
            continue
        start, end = source_span
        if not isinstance(start, int) or not isinstance(end, int) or start >= end:
            continue
        source_text = text[start:end]
        normalized = re.sub(r"\s+", " ", source_text).strip()
        spans.append({
            "start": start,
            "end": end,
            "text": re.sub(r"-\s+", "-", normalized),
            "source_text": source_text,
            "id": str(bullet.get("id") or ""),
            "section_key": str(bullet.get("section_key") or ""),
            "entry_id": str(bullet.get("entry_id") or ""),
        })
    return spans


def _content_kind(value: str, section_key: str) -> str:
    if section_key not in {"experience", "projects", "activities", "career_break", "education"}:
        return "paragraph"
    from resume_structurer import is_entry_heading

    return "entry_heading" if is_entry_heading(value) else "paragraph"


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


def _looks_like_role_header(value: str) -> bool:
    return bool(
        re.search(r"\b(?:19|20)\d{2}\s*[-–—].*(?:19|20)\d{2}|\b(?:19|20)\d{2}\s*[-–—]\s*(?:Present|Current)\b", value, re.I)
    )


def _starts_new_paragraph(value: str) -> bool:
    return bool(
        classify_section_heading(value)
        or _candidate_custom_heading(value)
        or re.match(rf"^\s*{_BULLET_MARKER}\s+", value)
        or _looks_like_role_header(value)
        or re.match(r"^[A-Z][^:\n]{1,60}:\s", value)
    )


def _join_wrapped_line_spans(text: str, spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    joined: list[dict[str, Any]] = []
    seen_section = False
    for item in spans:
        item_is_section = classify_section_heading(str(item["text"]).strip()) is not None
        if not joined:
            joined.append(item)
            seen_section = seen_section or item_is_section
            continue
        previous = joined[-1]
        gap = text[previous["end"]:item["start"]]
        previous_text = str(previous["text"]).rstrip()
        current_text = str(item["text"]).strip()
        continues = (
            bool(re.fullmatch(r"[ \t]*\n[ \t]*", gap))
            and seen_section
            and not previous_text.endswith((".", "!", "?", ";"))
            and classify_section_heading(previous_text) is None
            and not _candidate_custom_heading(previous_text)
            and not _looks_like_role_header(previous_text)
            and not _starts_new_paragraph(current_text)
        )
        if not continues:
            joined.append(item)
            seen_section = seen_section or item_is_section
            continue
        separator = "" if previous_text.endswith("-") else " "
        previous["text"] = f"{previous_text}{separator}{current_text}"
        previous["end"] = item["end"]
        previous["source_text"] = text[previous["start"]:item["end"]]
    return joined


def create_resume_document(
    text: str,
    *,
    source_format: str = "text",
    filename: str | None = None,
    source_sha256: str | None = None,
    warnings: list[dict[str, Any]] | None = None,
    layout_blocks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return one canonical document for uploaded or pasted resume text."""
    raw_text = str(text or "")
    source_hash = source_sha256 or hashlib.sha256(raw_text.encode()).hexdigest()
    source_layout = list(layout_blocks or [])
    font_counts = Counter(
        float(block["font_size"])
        for block in source_layout
        if block.get("font_size") is not None
    )
    body_font_size = font_counts.most_common(1)[0][0] if font_counts else None
    content_document_id = document_id(raw_text)
    bullet_spans = _structured_bullet_spans(raw_text)
    occupied = [(item["start"], item["end"]) for item in bullet_spans]
    source_blocks = sorted(
        [*bullet_spans, *_join_wrapped_line_spans(raw_text, _line_spans(raw_text, occupied))],
        key=lambda item: (item["start"], item["end"]),
    )
    (
        top_heading_font_size,
        top_heading_indentation,
        top_heading_level,
    ) = _top_heading_evidence(source_blocks, source_layout)

    blocks: list[dict[str, Any]] = []
    sections: list[dict[str, Any]] = []
    current_section_id: str | None = None
    current_section_key = ""
    seen_known_section = False
    heading_candidates: list[dict[str, Any]] = []
    for order, item in enumerate(source_blocks):
        value = item["text"].strip()
        layout = _block_layout(item, source_layout)
        section_key = classify_section_heading(value)
        has_top_heading_layout = _layout_heading_candidate(
            layout,
            body_font_size=body_font_size,
            top_heading_font_size=top_heading_font_size,
            top_heading_indentation=top_heading_indentation,
            top_heading_level=top_heading_level,
        )
        has_nested_heading_layout = _layout_indicates_nested_heading(
            layout,
            top_heading_font_size=top_heading_font_size,
            top_heading_indentation=top_heading_indentation,
            top_heading_level=top_heading_level,
        )
        looks_like_heading = (
            seen_known_section
            and not _looks_like_role_header(value)
            and not re.search(r"\d|@|https?://|\|", value, re.I)
            and not value.endswith((".", "!", "?", ";"))
            and (_candidate_custom_heading(value) or bool(layout.get("heading_emphasis")))
        )
        is_known_heading = section_key is not None and not has_nested_heading_layout
        is_custom_heading = section_key is None and looks_like_heading and has_top_heading_layout
        is_candidate_heading = looks_like_heading and not is_custom_heading
        if section_key is not None and has_nested_heading_layout:
            is_candidate_heading = True
        kind = "bullet" if item in bullet_spans else _content_kind(
            value,
            str(item.get("section_key") or current_section_key),
        )
        classification = "content"
        if is_known_heading or is_custom_heading:
            kind = "section_heading"
            classification = "known_section" if is_known_heading else "custom_section"
        elif is_candidate_heading:
            kind = "candidate_heading"
            classification = "candidate_heading"

        locator = f"chars:{item['start']}-{item['end']}"
        canonical_block_id = item.get("id") or block_id(
            raw_text, item["start"], item["end"], item["source_text"]
        )
        if kind == "section_heading":
            seen_known_section = seen_known_section or is_known_heading
            current_section_id = f"s_{canonical_block_id[2:]}"
            current_section_key = section_key if is_known_heading else ""
            sections.append({
                "id": current_section_id,
                "key": section_key if is_known_heading else None,
                "label": value,
                "classification": classification,
                "status": "confirmed",
                "heading_block_id": canonical_block_id,
                "parent_entry_id": None,
            })
        elif is_candidate_heading:
            heading_candidates.append({
                "block_id": canonical_block_id,
                "label": value,
                "suggested_key": section_key,
                "reason": "Heading-like text has weaker layout evidence than confirmed top-level sections.",
            })

        block_section_key = item.get("section_key") or current_section_key
        blocks.append({
            "id": canonical_block_id,
            "order": order,
            "kind": kind,
            "text": value,
            "source_text": item["source_text"],
            "raw_span": [item["start"], item["end"]],
            "section_id": current_section_id,
            "section_key": block_section_key,
            "entry_id": item.get("entry_id") or "",
            "classification": classification,
            **layout,
            "source": {
                "locator": locator,
                "format": source_format,
            },
        })

    return {
        "schema_version": SCHEMA_VERSION,
        "document_id": content_document_id,
        "revision": document_revision(raw_text),
        "source": {
            "format": source_format,
            "filename": filename,
            "sha256": source_hash,
        },
        "raw_text": raw_text,
        "blocks": blocks,
        "sections": sections,
        "heading_candidates": heading_candidates,
        "decisions": [],
        "warnings": list(warnings or []),
    }


def _rebuild_sections(document: dict[str, Any]) -> None:
    sections: list[dict[str, Any]] = []
    current_section_id: str | None = None
    current_section_key = ""
    for block in sorted(document.get("blocks", []), key=lambda item: item.get("order", 0)):
        if block.get("kind") == "section_heading":
            current_section_id = f"s_{str(block['id'])[2:]}"
            current_section_key = str(block.get("section_key") or "")
            sections.append({
                "id": current_section_id,
                "key": current_section_key or None,
                "label": block.get("text", ""),
                "classification": block.get("classification", "custom_section"),
                "status": "confirmed",
                "heading_block_id": block["id"],
                "parent_entry_id": None,
            })
        block["section_id"] = current_section_id
        if block.get("kind") != "section_heading":
            block["section_key"] = current_section_key
    document["sections"] = sections


def confirm_resume_heading(
    document: dict[str, Any],
    *,
    block_id_value: str,
    expected_revision: str,
    section_key: str | None = None,
) -> dict[str, Any]:
    """Promote one candidate heading without modifying extracted source text."""
    if not is_resume_document(document):
        raise ResumePatchError("Unsupported resume document schema.")
    if expected_revision != document.get("revision"):
        raise StaleResumeRevision("Resume changed after this heading review was opened.")
    updated = deepcopy(document)
    block = next(
        (item for item in updated["blocks"] if item.get("id") == block_id_value),
        None,
    )
    if not block or block.get("classification") != "candidate_heading":
        raise ResumePatchError("Unknown resume heading candidate.")
    normalized_key = str(section_key or "").strip() or None
    block["kind"] = "section_heading"
    block["section_key"] = normalized_key or ""
    block["classification"] = "known_section" if normalized_key else "custom_section"
    updated["heading_candidates"] = [
        item
        for item in updated.get("heading_candidates", [])
        if item.get("block_id") != block_id_value
    ]
    decisions = [
        *updated.get("decisions", []),
        {
            "type": "confirm_heading",
            "block_id": block_id_value,
            "section_key": normalized_key,
        },
    ]
    updated["decisions"] = decisions
    _rebuild_sections(updated)
    updated["revision"] = document_revision(updated["raw_text"], decisions)
    return updated


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
    updated["revision"] = document_revision(
        updated["raw_text"],
        updated.get("decisions", []),
    )
    return updated
