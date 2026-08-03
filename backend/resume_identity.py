"""Content-derived identity shared by every resume consumer."""

from __future__ import annotations

import hashlib
import json


SCHEMA_VERSION = 3


def _hash(prefix: str, value: str) -> str:
    return f"{prefix}_{hashlib.sha256(value.encode()).hexdigest()[:20]}"


def document_id(text: str) -> str:
    """Identify semantic source content, independent of its file container."""
    return _hash("d", f"{SCHEMA_VERSION}\0{text}")


def document_revision(text: str, decisions: list[dict] | None = None) -> str:
    decision_payload = json.dumps(
        decisions or [],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return _hash("r", f"{SCHEMA_VERSION}\0{text}\0{decision_payload}")


def block_id(text: str, start: int, end: int, source_text: str) -> str:
    locator = f"chars:{start}-{end}"
    return _hash("b", f"{document_id(text)}\0{locator}\0{source_text}")
