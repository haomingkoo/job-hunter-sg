"""
Shared resume classification config -- loads the single source of truth
from ``../shared/resume-classification.json``.

Exports:
    SHARED_HEADINGS        set[str]  -- all recognised section headings (lowercase)
    SHARED_KEY_MAP         dict[str, str] -- heading -> normalised section key
    SHARED_TITLE_PATTERNS  list[str] -- common job title patterns
"""

from __future__ import annotations

import json
from pathlib import Path
import re

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "shared" / "resume-classification.json"

with _CONFIG_PATH.open(encoding="utf-8") as _f:
    _config: dict = json.load(_f)

SHARED_HEADINGS: set[str] = set(_config["section_headings"])
SHARED_KEY_MAP: dict[str, str] = dict(_config["section_key_map"])
SHARED_TITLE_PATTERNS: list[str] = list(_config["title_patterns"])

_HEADING_CONNECTORS = {"and", "of", "the", "for", "in", "to", "&", "/"}


def classify_section_heading(value: str) -> str | None:
    """Return a semantic section key for a heading-shaped line."""
    stripped = re.sub(r"(\*\*|__)", "", value or "").strip().rstrip(":").strip()
    normalized = re.sub(r"\s+", " ", stripped.lower())
    if not normalized:
        return None
    if normalized in SHARED_KEY_MAP:
        return SHARED_KEY_MAP[normalized]
    if (
        len(stripped) > 100
        or not 1 <= len(stripped.split()) <= 10
        or re.search(r"\d|@|https?://|\|", stripped, re.I)
        or re.match(r"^[•\-*▪]", stripped)
        or stripped.endswith((".", "!", "?", ";"))
    ):
        return None

    words = re.findall(r"[A-Za-z][A-Za-z'-]*|[&/]", stripped)
    is_upper = any(char.isalpha() for char in stripped) and stripped == stripped.upper()
    is_title = bool(words) and all(
        word.lower() in _HEADING_CONNECTORS or word[0].isupper()
        for word in words
    )
    if not (is_upper or is_title):
        return None

    if "career break" in normalized:
        return "career_break"
    if any(term in normalized for term in ("co-curricular", "extra-curricular", "volunteer", "activit")):
        return "activities"
    if "project" in normalized:
        return "projects"
    if any(term in normalized for term in ("education", "academic")):
        return "education"
    if re.search(r"\bskills?\b|competenc|proficienc|expertise", normalized):
        return "skills"
    if any(term in normalized for term in ("certification", "licen", "upskilling")):
        return "certifications"
    if any(term in normalized for term in ("summary", "profile", "qualification")):
        return "summary"
    if "objective" in normalized:
        return "objective"
    if any(term in normalized for term in ("award", "honor", "publication", "achievement")):
        return "awards"
    if "language" in normalized:
        return "languages"
    if any(term in normalized for term in ("personal", "additional information")):
        return "personal"
    if any(term in normalized for term in ("experience", "employment history", "career history", "professional background")):
        return "experience"
    return None
