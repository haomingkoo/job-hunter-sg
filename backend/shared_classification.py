"""
Shared resume classification config -- loads the single source of truth
from ``../shared/resume-classification.json``.

Exports:
    SHARED_HEADINGS        set[str]  -- all recognised section headings (lowercase)
    SHARED_KEY_MAP         dict[str, str] -- heading -> normalised section key
    SHARED_TITLE_PATTERNS  list[str] -- common job title patterns
    SHARED_BULLET_MARKERS  list[str] -- bullet marker characters
"""

from __future__ import annotations

import json
from pathlib import Path

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "shared" / "resume-classification.json"

with _CONFIG_PATH.open(encoding="utf-8") as _f:
    _config: dict = json.load(_f)

SHARED_HEADINGS: set[str] = set(_config["section_headings"])
SHARED_KEY_MAP: dict[str, str] = dict(_config["section_key_map"])
SHARED_TITLE_PATTERNS: list[str] = list(_config["title_patterns"])
SHARED_BULLET_MARKERS: list[str] = list(_config["bullet_markers"])
