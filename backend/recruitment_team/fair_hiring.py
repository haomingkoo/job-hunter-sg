"""Deterministic fair-hiring boundaries shared by role and assessment flows."""

from __future__ import annotations

import re


_PROTECTED_STATUS = re.compile(
    r"\b(?:"
    r"citizens?(?:hip)?|"
    r"nationality|national\s+origin|"
    r"permanent\s+residen(?:t|cy)|"
    r"(?:singapore|sg)\s+residen(?:t|cy)|"
    r"residen(?:t|cy)\s+status|"
    r"immigration\s+status|"
    r"singaporeans?"
    r")\b",
    re.IGNORECASE,
)


def mentions_protected_status(text: str) -> bool:
    """Whether text uses nationality, citizenship, or residency status.

    Work-authorisation phrases intentionally do not match. A genuine legal
    constraint may therefore be represented as "authorised to work" or
    "right to work", without asking for a protected identity or status.
    """

    return _PROTECTED_STATUS.search(text or "") is not None


def without_protected_status_sentences(text: str) -> str:
    """Remove protected-status requirements from model-facing posting prose.

    The original posting remains unchanged in storage and candidate-facing job
    views. This copy exists only so an assessment agent cannot treat a
    discriminatory preference as a role-success criterion.
    """

    sentences = re.split(r"(?<=[.!?])\s+|[\r\n]+", text or "")
    return " ".join(
        sentence.strip()
        for sentence in sentences
        if sentence.strip() and not mentions_protected_status(sentence)
    )
