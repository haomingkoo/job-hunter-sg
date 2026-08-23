"""
Input sanitization for scraped data and user inputs.
"""

from __future__ import annotations

import html
import re
from urllib.parse import urlsplit


_TAG_RE = re.compile(r"<[^>]+>", re.DOTALL)
_WHITESPACE_RE = re.compile(r"\s+")
_SCRIPT_RE = re.compile(
    r"<\s*script[^>]*>.*?<\s*/\s*script\s*>",
    re.DOTALL | re.IGNORECASE,
)
_STYLE_RE = re.compile(
    r"<\s*style[^>]*>.*?<\s*/\s*style\s*>",
    re.DOTALL | re.IGNORECASE,
)
_EVENT_HANDLER_RE = re.compile(
    r"""\s+on\w+\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]*)""",
    re.IGNORECASE,
)
_INLINE_WHITESPACE_RE = re.compile(r"[^\S\n]+")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")
_URL_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f\u200b\u200c\u200d\ufeff]")

MAX_USER_INPUT_LEN = 1000


def sanitize_html(text: str) -> str:
    """Strip ALL HTML tags, decode entities, collapse whitespace."""
    if not text:
        return ""
    text = _SCRIPT_RE.sub("", text)
    text = _STYLE_RE.sub("", text)
    text = _EVENT_HANDLER_RE.sub("", text)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text


def sanitize_url(url: str) -> str:
    """Return a normalized HTTP(S) URL or an empty string for unsafe input."""
    if not url:
        return ""
    candidate = str(url)
    if not candidate.strip():
        return ""
    if _URL_CONTROL_RE.search(candidate):
        return ""
    candidate = candidate.strip()
    if any(character.isspace() for character in candidate):
        return ""
    try:
        parsed = urlsplit(candidate)
        hostname = parsed.hostname
        port = parsed.port
    except (TypeError, ValueError):
        return ""
    if parsed.scheme.lower() not in {"http", "https"} or not hostname:
        return ""
    if parsed.username is not None or parsed.password is not None:
        return ""
    # Accessing parsed.port above rejects malformed and out-of-range ports.
    del port
    return candidate


def validate_http_url(url: str | None) -> str | None:
    """Validate a stored optional URL while preserving blank and ``None`` values."""
    if url is None:
        return None
    if not str(url).strip():
        return ""
    normalized = sanitize_url(url)
    if not normalized:
        raise ValueError("must be blank or a valid HTTP(S) URL")
    return normalized


def sanitize_job(job_dict: dict) -> dict:
    """Sanitize scraped job fields. Returns a new dict."""
    sanitized = dict(job_dict)
    for field in (
        "title",
        "company",
        "location",
        "salary",
        "source",
        "agency",
        "source_posting_id",
        "company_ssic_code",
        "company_ssic_description",
        "company_ssic_source",
    ):
        if field in sanitized and isinstance(sanitized[field], str):
            sanitized[field] = sanitize_html(sanitized[field])
    if "description" in sanitized and isinstance(sanitized["description"], str):
        sanitized["description"] = sanitize_html(sanitized["description"])
    if "url" in sanitized:
        sanitized["url"] = sanitize_url(sanitized.get("url", ""))
    try:
        sanitized["openings"] = max(1, min(int(sanitized.get("openings") or 1), 10000))
    except (TypeError, ValueError):
        sanitized["openings"] = 1
    # Stamped here because this is the one point every write path shares, and the
    # hash has to be taken after sanitising so the same listing hashes identically
    # regardless of how much markup its source shipped.
    from job_store import compute_content_hash

    sanitized["content_hash"] = compute_content_hash(sanitized)
    return sanitized


def sanitize_resume_text(text: str) -> str:
    """
    Strip HTML from resume text while preserving line structure.
    No length truncation — resumes need full text and section breaks.
    """
    if not text:
        return ""
    text = _SCRIPT_RE.sub("", text)
    text = _STYLE_RE.sub("", text)
    text = _EVENT_HANDLER_RE.sub("", text)
    # Preserve existing line structure for resume parsing/export.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(?i)<\s*br\s*/?\s*>", "\n", text)
    text = re.sub(r"(?i)</\s*(p|div|li|tr|h[1-6])\s*>", "\n", text)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = _INLINE_WHITESPACE_RE.sub(" ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = _MULTI_NEWLINE_RE.sub("\n\n", text)
    return text.strip()


def sanitize_user_input(text: str, *, max_length: int = MAX_USER_INPUT_LEN) -> str:
    """Strip HTML and enforce the caller's declared storage limit."""
    if not text:
        return ""
    cleaned = sanitize_html(text)
    return cleaned[:max_length]
