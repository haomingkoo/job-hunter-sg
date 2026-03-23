"""
Input sanitization for scraped data and user inputs.
"""

from __future__ import annotations

import html
import re


# Pre-compiled patterns
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

MAX_DESCRIPTION_LEN = 5000
MAX_USER_INPUT_LEN = 1000


def sanitize_html(text: str) -> str:
    """Strip ALL HTML tags, decode entities, collapse whitespace."""
    if not text:
        return ""
    # Remove script and style blocks first
    text = _SCRIPT_RE.sub("", text)
    text = _STYLE_RE.sub("", text)
    # Remove event handlers
    text = _EVENT_HANDLER_RE.sub("", text)
    # Strip remaining tags
    text = _TAG_RE.sub(" ", text)
    # Decode HTML entities (e.g. &amp; → &)
    text = html.unescape(text)
    # Collapse whitespace
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text


def sanitize_url(url: str) -> str:
    """Only allow http:// and https:// URLs. Block javascript:, data:, etc."""
    if not url:
        return ""
    # Strip whitespace and ASCII control characters; remove zero-width unicode chars
    url = re.sub(r"[\x00-\x1f\x7f\u200b\u200c\u200d\ufeff]", "", url).strip()
    if url.lower().startswith(("http://", "https://")):
        return url
    return ""


def sanitize_job(job_dict: dict) -> dict:
    """Sanitize scraped job fields. Returns a new dict."""
    sanitized = dict(job_dict)
    for field in ("title", "company", "location", "salary"):
        if field in sanitized and isinstance(sanitized[field], str):
            sanitized[field] = sanitize_html(sanitized[field])
    if "description" in sanitized and isinstance(sanitized["description"], str):
        desc = sanitize_html(sanitized["description"])
        sanitized["description"] = desc[:MAX_DESCRIPTION_LEN]
    if "url" in sanitized:
        sanitized["url"] = sanitize_url(sanitized.get("url", ""))
    return sanitized


def sanitize_user_input(text: str) -> str:
    """Strip HTML, trim whitespace, limit length for user-supplied text."""
    if not text:
        return ""
    cleaned = sanitize_html(text)
    return cleaned[:MAX_USER_INPUT_LEN]
