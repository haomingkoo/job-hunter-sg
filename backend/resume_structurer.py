"""
Resume structurer -- parses raw resume text into a section/entry/bullet hierarchy.

All local computation, no LLM calls. Reuses helpers and constants from
resume_scorer for action-verb detection, metric matching, and section
normalisation.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from resume_scorer import (
    ACTION_VERBS,
    AVOIDED_PHRASES,
    STANDARD_SECTIONS,
    _METRIC_RE,
    _NORMALIZED_SECTION_KEYS,
    _clean_line,
    _iter_resume_lines,
    _section_key,
    _starts_with_action_verb,
)

log = logging.getLogger("jobhunter.structurer")

# ── Regex patterns ───────────────────────────────────────────────────────────

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_RE = re.compile(
    r"(?:\+?\d{1,3}[\s\-]?)?"           # country code
    r"(?:\(?\d{1,4}\)?[\s\-]?)?"         # area code
    r"\d[\d\s\-]{6,12}\d"               # main number
)
_LINKEDIN_RE = re.compile(
    r"(?:https?://)?(?:www\.)?linkedin\.com/in/[\w\-]+/?", re.I
)

_DATE_RANGE_RE = re.compile(
    r"("
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}"
    r"|\d{1,2}/\d{4}"
    r"|\d{4}"
    r")"
    r"\s*[-\u2013\u2014]\s*"
    r"("
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}"
    r"|\d{1,2}/\d{4}"
    r"|\d{4}"
    r"|[Pp]resent"
    r"|[Cc]urrent"
    r")",
    re.I,
)

_SINGLE_DATE_RE = re.compile(
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}"
    r"|\d{1,2}/\d{4}",
    re.I,
)

_ROLE_SEPARATOR_RE = re.compile(r"\s*[|\u2014\u2013]\s*")
_ALL_CAPS_HEADER_RE = re.compile(r"^[A-Z][A-Z &/\-]{2,}$")
_BULLET_CHAR_RE = re.compile(
    r"^[\s]*(?:[-*\u2022\u2023\u25E6\u2043\u2219]|\d+[.)]\s)",
)

# Education-specific patterns
_DEGREE_PREFIX_RE = re.compile(
    r"^(?:M\.?Sc|B\.?Sc|B\.?Eng|M\.?Eng|B\.?A|M\.?A|MBA|Ph\.?D|"
    r"Doctorate|Diploma|Advanced Diploma|Associate|"
    r"Graduate Cert(?:ificate)?|Certificate|Bachelor|Master)\b",
    re.I,
)
_INSTITUTION_RE = re.compile(
    r"\b(?:university|polytechnic|college|school|institute|academy|faculty|"
    r"national university|nanyang|singapore management|"
    r"nus|ntu|smu|sutd|sit|suss)\b",
    re.I,
)
_GPA_RE = re.compile(
    r"(?:gpa|cgpa|cap)\s*[:.]?\s*\d+\.?\d*\s*[/]?\s*\d*\.?\d*",
    re.I,
)
_EDUCATION_DETAIL_RE = re.compile(
    r"\b(?:gpa|cgpa|cap|exchange|capstone|thesis|dissertation|"
    r"minor|major|focus|specializ|concentration|"
    r"distinction|honou?r|magna|summa|cum laude|"
    r"dean.?s list|first class|second class|merit)\b",
    re.I,
)

# Sections that contain entries (role + bullets)
_ENTRY_SECTIONS = {
    "experience", "projects", "activities", "education", "certifications",
}
# Sections rendered as plain text blocks
_TEXT_SECTIONS = {"summary", "objective"}
# Sections rendered as skill lists
_SKILL_SECTIONS = {"skills"}


# ── Contact extraction ───────────────────────────────────────────────────────

def _extract_contact(lines: list[str]) -> dict[str, str]:
    """Extract contact info from the first few lines of the resume."""
    header_lines = lines[:8]
    name = ""
    email = ""
    phone = ""
    location = ""
    linkedin = ""

    section_headers_lower = {s.lower() for s in STANDARD_SECTIONS}

    for line in header_lines:
        cleaned = _clean_line(line)
        if not cleaned:
            continue

        # Grab email if present on any header line
        email_match = _EMAIL_RE.search(cleaned)
        if email_match and not email:
            email = email_match.group()

        # Grab phone
        phone_match = _PHONE_RE.search(cleaned)
        if phone_match and not phone:
            candidate = phone_match.group().strip()
            # Require at least 7 digits to avoid matching short numbers
            if sum(c.isdigit() for c in candidate) >= 7:
                phone = candidate

        # Grab LinkedIn
        li_match = _LINKEDIN_RE.search(cleaned)
        if li_match and not linkedin:
            linkedin = li_match.group()

    # Name: first non-empty line that is not a section header, email,
    # phone-only, or URL
    for line in header_lines:
        cleaned = _clean_line(line)
        if not cleaned or len(cleaned) < 2:
            continue
        lower = cleaned.lower().rstrip(":")
        if lower in section_headers_lower:
            continue
        if lower in _NORMALIZED_SECTION_KEYS:
            continue
        if "@" in cleaned or "http" in cleaned.lower():
            continue
        if re.match(r"^[\+\d\s\-\(\)]+$", cleaned):
            continue
        if _LINKEDIN_RE.match(cleaned):
            continue
        words = cleaned.split()
        if 1 <= len(words) <= 5 and all(
            re.match(r"^[A-Za-z.\-\']+$", w) for w in words
        ):
            name = cleaned
            break

    contact: dict[str, str] = {
        "name": name,
        "email": email,
        "phone": phone,
        "location": location,
    }
    if linkedin:
        contact["linkedin"] = linkedin
    return contact


# ── Section splitting ────────────────────────────────────────────────────────

def _is_section_heading(line: str) -> str | None:
    """Return the normalised section key if line is a heading, else None."""
    stripped = _clean_line(line)
    if not stripped:
        return None

    lower = stripped.lower().rstrip(":")

    # Lines with GPA, dates, or numeric content are NOT headings
    if _GPA_RE.search(stripped):
        return None
    if _EDUCATION_DETAIL_RE.search(stripped):
        return None
    # Lines that are mostly digits/symbols (e.g., "4.85 / 5.00") are not headings
    letters_only = re.sub(r"[^A-Za-z]", "", stripped)
    if len(letters_only) < 2:
        return None

    # Exact match against known sections
    if lower in (s.lower() for s in STANDARD_SECTIONS):
        return _section_key(stripped)

    # ALL-CAPS short line with at least one letter
    if (
        len(stripped) >= 2
        and stripped == stripped.upper()
        and re.search(r"[A-Z]", stripped)
        and len(stripped.split()) <= 6
    ):
        return _section_key(stripped)

    # Line ending with colon and short enough to be a header
    if stripped.endswith(":") and len(stripped.split()) <= 5:
        return _section_key(lower)

    return None


def _split_into_sections(
    lines: list[str],
) -> list[dict[str, Any]]:
    """Walk through lines and group them into sections.

    Returns a list of dicts: {key, display_name, lines}.
    Lines before the first detected heading are ignored (contact header).
    """
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for line in lines:
        heading_key = _is_section_heading(line)
        if heading_key is not None:
            display = _clean_line(line).rstrip(":")
            current = {
                "key": heading_key,
                "display_name": display,
                "lines": [],
            }
            sections.append(current)
        elif current is not None:
            current["lines"].append(line)

    return sections


# ── Entry detection ──────────────────────────────────────────────────────────

def _strip_bullet_prefix(line: str) -> str:
    """Remove leading bullet character from a line."""
    return re.sub(
        r"^[\s]*(?:[-*\u2022\u2023\u25E6\u2043\u2219]|\d+[.)]\s)\s*",
        "",
        line,
    ).strip()


def _is_entry_heading(line: str) -> bool:
    """Heuristic: is this line an entry heading (company/role/date)?"""
    stripped = _clean_line(line)
    if not stripped:
        return False

    has_date = bool(_DATE_RANGE_RE.search(stripped)) or bool(
        _SINGLE_DATE_RE.search(stripped)
    )
    has_separator = bool(_ROLE_SEPARATOR_RE.search(stripped))
    is_caps = bool(_ALL_CAPS_HEADER_RE.match(stripped))
    is_bullet = bool(_BULLET_CHAR_RE.match(line))

    # Lines with dates or separators are almost always entry headings,
    # even if they start with a bullet char (some resumes bullet job titles)
    if has_date or has_separator:
        return True

    if is_bullet:
        return False

    # ALL-CAPS short line inside a section (company name)
    if is_caps and len(stripped.split()) <= 8:
        return True

    return False


def _parse_entry_heading(
    heading_lines: list[str],
) -> dict[str, str]:
    """Extract company, title, and date_range from heading lines."""
    combined = " ".join(
        _clean_line(ln) for ln in heading_lines if _clean_line(ln)
    )

    date_range = ""
    date_match = _DATE_RANGE_RE.search(combined)
    if date_match:
        date_range = date_match.group(0).strip()

    # Remove date from the text to isolate company/title
    text_no_date = _DATE_RANGE_RE.sub("", combined).strip()
    text_no_date = _SINGLE_DATE_RE.sub("", text_no_date).strip()

    # Split on separators (|, em-dash, en-dash)
    parts = _ROLE_SEPARATOR_RE.split(text_no_date)
    parts = [p.strip().strip(",").strip() for p in parts if p.strip()]

    company = ""
    title = ""

    if len(parts) >= 2:
        company = parts[0]
        title = parts[1]
    elif len(parts) == 1:
        company = parts[0]

    return {
        "company": company,
        "title": title,
        "date_range": date_range,
    }


# ── Education-specific entry builder ────────────────────────────────────────

def _is_education_entry_start(line: str) -> bool:
    """Check if a line starts a new education entry (degree or institution)."""
    stripped = _clean_line(line)
    if not stripped:
        return False
    if _DEGREE_PREFIX_RE.match(stripped):
        return True
    if _INSTITUTION_RE.search(stripped) and not _EDUCATION_DETAIL_RE.search(stripped):
        return True
    has_date = bool(_DATE_RANGE_RE.search(stripped)) or bool(
        _SINGLE_DATE_RE.search(stripped)
    )
    has_separator = bool(_ROLE_SEPARATOR_RE.search(stripped))
    if has_date or has_separator:
        return True
    is_caps = bool(_ALL_CAPS_HEADER_RE.match(stripped))
    if is_caps and len(stripped.split()) <= 8:
        return True
    return False


def _parse_education_entry(
    lines: list[str],
    entry_idx: int,
) -> dict[str, Any]:
    """Parse a group of education lines into structured fields."""
    degree = ""
    institution = ""
    date_range = ""
    gpa = ""
    details: list[str] = []

    for line in lines:
        stripped = _clean_line(line)
        if not stripped:
            continue

        # Extract date range from any line
        date_match = _DATE_RANGE_RE.search(stripped)
        single_date_match = _SINGLE_DATE_RE.search(stripped) if not date_match else None
        line_date = ""
        if date_match:
            line_date = date_match.group(0).strip()
        elif single_date_match:
            line_date = single_date_match.group(0).strip()

        if line_date and not date_range:
            date_range = line_date

        # Extract GPA
        gpa_match = _GPA_RE.search(stripped)
        if gpa_match and not gpa:
            gpa = gpa_match.group(0).strip()

        # Classify the line
        text_no_date = _DATE_RANGE_RE.sub("", stripped).strip()
        text_no_date = _SINGLE_DATE_RE.sub("", text_no_date).strip()
        text_no_date = text_no_date.strip(",").strip()

        is_degree_line = bool(_DEGREE_PREFIX_RE.match(stripped))
        is_institution_line = bool(
            _INSTITUTION_RE.search(stripped)
            and not _EDUCATION_DETAIL_RE.search(stripped)
        )
        is_detail_line = bool(_EDUCATION_DETAIL_RE.search(stripped))

        if is_degree_line and not degree:
            # Remove date from degree text
            degree = text_no_date or stripped
        elif is_institution_line and not institution:
            institution = text_no_date or stripped
        elif is_detail_line:
            # GPA is already extracted; add other details
            if not gpa_match:
                details.append(stripped)
            elif stripped != gpa_match.group(0).strip():
                # Line has more than just GPA
                remaining = _GPA_RE.sub("", stripped).strip().strip(",").strip()
                if remaining:
                    details.append(remaining)
        elif not degree and not institution:
            # First line, could be institution or degree
            if _DEGREE_PREFIX_RE.match(text_no_date):
                degree = text_no_date
            else:
                institution = text_no_date or stripped
        elif institution and not degree:
            degree = text_no_date or stripped
        elif degree and not institution:
            institution = text_no_date or stripped
        else:
            # Extra line - treat as detail
            if stripped not in (degree, institution, date_range, gpa):
                details.append(stripped)

    # Build heading/subheading for backward compatibility
    heading = degree or institution
    subheading_parts: list[str] = []
    if degree and institution:
        heading = degree
        subheading_parts.append(institution)
    if date_range:
        subheading_parts.append(date_range)
    subheading = " | ".join(subheading_parts) if subheading_parts else ""

    entry_id = f"edu-{entry_idx}"
    return {
        "id": entry_id,
        "heading": heading,
        "subheading": subheading,
        "company": institution,
        "title": degree,
        "date_range": date_range,
        # Education-specific structured fields
        "degree": degree,
        "institution": institution,
        "gpa": gpa,
        "details": details,
        "bullets": [],
    }


def _build_education_entries(
    section_lines: list[str],
) -> list[dict[str, Any]]:
    """Parse education section into structured entries with rich fields."""
    entries: list[dict[str, Any]] = []
    current_lines: list[str] = []

    def _flush() -> None:
        nonlocal current_lines
        if not current_lines:
            return
        entry = _parse_education_entry(current_lines, len(entries))
        # Only add if there's meaningful content
        if entry["heading"] or entry["degree"] or entry["institution"]:
            entries.append(entry)
        current_lines = []

    for line in section_lines:
        stripped = _clean_line(line)
        if not stripped:
            continue

        # Strip bullet prefix for education lines
        is_bullet = bool(_BULLET_CHAR_RE.match(line))
        clean_text = _strip_bullet_prefix(line) if is_bullet else stripped

        if _is_education_entry_start(line) and current_lines:
            # Check if this line belongs to the current entry
            # (e.g., degree line after institution line in the same entry)
            has_degree = any(
                _DEGREE_PREFIX_RE.match(_clean_line(ln))
                for ln in current_lines
            )
            has_institution = any(
                _INSTITUTION_RE.search(_clean_line(ln))
                and not _EDUCATION_DETAIL_RE.search(_clean_line(ln))
                for ln in current_lines
            )
            is_new_degree = bool(_DEGREE_PREFIX_RE.match(stripped))
            is_new_institution = bool(
                _INSTITUTION_RE.search(stripped)
                and not _EDUCATION_DETAIL_RE.search(stripped)
            )

            # Start new entry if we already have both degree + institution,
            # or if we see a second degree/institution
            if (has_degree and is_new_degree) or (
                has_institution and is_new_institution
            ) or (has_degree and has_institution):
                _flush()

        if not current_lines and not _is_education_entry_start(line):
            # Stray detail line before any entry; still collect it
            if _EDUCATION_DETAIL_RE.search(stripped):
                current_lines.append(line)
                continue
            # Otherwise start a new entry
            current_lines = [line]
            continue

        current_lines.append(line)

    _flush()
    return entries


def _build_entries(
    section_lines: list[str], section_key_str: str,
) -> list[dict[str, Any]]:
    """Parse lines within an entry-based section into structured entries."""
    entries: list[dict[str, Any]] = []
    current_heading_lines: list[str] = []
    current_bullets: list[str] = []
    prefix = section_key_str[:3]

    def _flush() -> None:
        nonlocal current_heading_lines, current_bullets
        if not current_heading_lines and not current_bullets:
            return
        idx = len(entries)
        entry_id = f"{prefix}-{idx}"
        parsed = _parse_entry_heading(current_heading_lines)

        heading = parsed["company"] or (
            _clean_line(current_heading_lines[0])
            if current_heading_lines
            else ""
        )
        subheading_parts: list[str] = []
        if parsed["title"]:
            subheading_parts.append(parsed["title"])
        if parsed["date_range"]:
            subheading_parts.append(parsed["date_range"])
        subheading = (
            " | ".join(subheading_parts) if subheading_parts else ""
        )

        bullets_out: list[dict[str, Any]] = []
        for bi, btext in enumerate(current_bullets):
            bullets_out.append(
                _analyze_bullet(btext, f"{entry_id}-b{bi}")
            )

        entries.append({
            "id": entry_id,
            "heading": heading,
            "subheading": subheading,
            "company": parsed["company"],
            "title": parsed["title"],
            "date_range": parsed["date_range"],
            "bullets": bullets_out,
        })
        current_heading_lines = []
        current_bullets = []

    for line in section_lines:
        stripped = _clean_line(line)
        if not stripped:
            continue

        if _is_entry_heading(line):
            _flush()
            current_heading_lines = [line]
            current_bullets = []
        elif _BULLET_CHAR_RE.match(line):
            bullet_text = _strip_bullet_prefix(line)
            if bullet_text:
                current_bullets.append(bullet_text)
        elif (
            _starts_with_action_verb(stripped)
            and len(stripped.split()) >= 5
        ):
            # Implicit bullet (no marker but starts with action verb)
            current_bullets.append(stripped)
        elif current_heading_lines and not current_bullets:
            # Second heading line (title on separate line from company)
            current_heading_lines.append(line)
        elif current_bullets:
            # Continuation of the previous bullet
            current_bullets[-1] += " " + stripped
        else:
            # Stray line before any entry -- treat as heading start
            _flush()
            current_heading_lines = [line]
            current_bullets = []

    _flush()
    return entries


# ── Bullet analysis ──────────────────────────────────────────────────────────

def _analyze_bullet(text: str, bullet_id: str) -> dict[str, Any]:
    """Compute metrics and issues for a single bullet."""
    cleaned = _clean_line(text)
    words = cleaned.split()
    word_count = len(words)

    has_action_verb = _starts_with_action_verb(cleaned)
    action_verb = ""
    if has_action_verb and words:
        action_verb = words[0].lower().rstrip(",;:")

    has_metric = bool(_METRIC_RE.search(cleaned))

    issues: list[str] = []
    if not has_action_verb:
        issues.append("no_action_verb")
    if not has_metric:
        issues.append("no_metric")
    if word_count > 35:
        issues.append("too_long")
    if word_count < 8:
        issues.append("too_short")

    # Check for weak/avoided verbs at the start
    lower_text = cleaned.lower()
    for phrase in AVOIDED_PHRASES:
        if lower_text.startswith(phrase):
            issues.append("weak_verb")
            break

    return {
        "id": bullet_id,
        "text": cleaned,
        "has_action_verb": has_action_verb,
        "action_verb": action_verb,
        "has_metric": has_metric,
        "word_count": word_count,
        "issues": issues,
    }


# ── Skills parsing ───────────────────────────────────────────────────────────

def _parse_skill_list(lines: list[str]) -> list[str]:
    """Extract individual skills from a skills section."""
    raw = " ".join(_clean_line(ln) for ln in lines if _clean_line(ln))
    if not raw:
        return []

    # Split on commas, semicolons, bullet chars, pipes, or newlines
    tokens = re.split(r"[,;|\u2022\u2023\u25E6\u2043\u2219\n]+", raw)
    skills: list[str] = []
    for token in tokens:
        cleaned = token.strip().strip("-").strip("*").strip()
        if cleaned and len(cleaned) < 80:
            skills.append(cleaned)
    return skills


# ── Section type classification ──────────────────────────────────────────────

def _classify_section(key: str) -> str:
    """Return 'text', 'entries', or 'skills' for a given section key."""
    if key in _SKILL_SECTIONS:
        return "skills"
    if key in _TEXT_SECTIONS:
        return "text"
    if key in _ENTRY_SECTIONS:
        return "entries"
    return "text"


# ── Main entry point ─────────────────────────────────────────────────────────

def structure_resume(resume_text: str) -> dict[str, Any]:
    """Parse raw resume text into a structured section/entry/bullet hierarchy.

    Returns a dict suitable for JSON serialization and storage in the DB.
    All local computation, no LLM calls.
    """
    text = resume_text.strip()
    if not text:
        return {
            "contact": {
                "name": "", "email": "", "phone": "", "location": "",
            },
            "sections": [],
            "stats": {
                "total_bullets": 0,
                "bullets_with_action_verb": 0,
                "bullets_with_metric": 0,
                "bullets_with_issues": 0,
                "word_count": 0,
                "section_count": 0,
            },
        }

    all_lines = _iter_resume_lines(text)

    # 1. Extract contact info from raw lines (before noise filtering)
    contact = _extract_contact(text.split("\n"))

    # 2. Split into sections
    raw_sections = _split_into_sections(all_lines)

    # 3. Build structured sections
    sections: list[dict[str, Any]] = []
    total_bullets = 0
    bullets_with_action_verb = 0
    bullets_with_metric = 0
    bullets_with_issues = 0

    for sec in raw_sections:
        key = sec["key"]
        display_name = sec["display_name"]
        sec_lines: list[str] = sec["lines"]
        sec_type = _classify_section(key)

        section_out: dict[str, Any] = {
            "key": key,
            "display_name": display_name,
            "type": sec_type,
            "content": "",
            "entries": [],
        }

        if sec_type == "skills":
            content_text = "\n".join(
                _clean_line(ln) for ln in sec_lines if _clean_line(ln)
            )
            section_out["content"] = content_text
            section_out["skill_list"] = _parse_skill_list(sec_lines)

        elif sec_type == "entries":
            if key == "education":
                entries = _build_education_entries(sec_lines)
            else:
                entries = _build_entries(sec_lines, key)
            section_out["entries"] = entries

            for entry in entries:
                for bullet in entry["bullets"]:
                    total_bullets += 1
                    if bullet["has_action_verb"]:
                        bullets_with_action_verb += 1
                    if bullet["has_metric"]:
                        bullets_with_metric += 1
                    if bullet["issues"]:
                        bullets_with_issues += 1

        else:
            content_text = "\n".join(
                _clean_line(ln) for ln in sec_lines if _clean_line(ln)
            )
            section_out["content"] = content_text

        sections.append(section_out)

    word_count = len(text.split())

    result: dict[str, Any] = {
        "contact": contact,
        "sections": sections,
        "stats": {
            "total_bullets": total_bullets,
            "bullets_with_action_verb": bullets_with_action_verb,
            "bullets_with_metric": bullets_with_metric,
            "bullets_with_issues": bullets_with_issues,
            "word_count": word_count,
            "section_count": len(sections),
        },
    }
    log.debug(
        f"Structured resume: {len(sections)} sections, "
        f"{total_bullets} bullets, {word_count} words"
    )
    return result


# ── Utilities ────────────────────────────────────────────────────────────────

def flatten_to_text(structured: dict[str, Any]) -> str:
    """Convert a structured resume back to plain text.

    Used after modifications to regenerate the raw text form.
    """
    parts: list[str] = []

    # Contact header
    contact = structured.get("contact", {})
    name = contact.get("name", "")
    if name:
        parts.append(name)
    contact_bits: list[str] = []
    if contact.get("email"):
        contact_bits.append(contact["email"])
    if contact.get("phone"):
        contact_bits.append(contact["phone"])
    if contact.get("linkedin"):
        contact_bits.append(contact["linkedin"])
    if contact.get("location"):
        contact_bits.append(contact["location"])
    if contact_bits:
        parts.append(" | ".join(contact_bits))
    if parts:
        parts.append("")  # blank line after contact

    for section in structured.get("sections", []):
        display = section.get(
            "display_name", section.get("key", "")
        )
        parts.append(
            display.upper() if display == display.lower() else display
        )

        sec_type = section.get("type", "text")

        if sec_type == "text":
            content = section.get("content", "")
            if content:
                parts.append(content)

        elif sec_type == "skills":
            content = section.get("content", "")
            if content:
                parts.append(content)

        elif sec_type == "entries":
            for entry in section.get("entries", []):
                heading = entry.get("heading", "")
                subheading = entry.get("subheading", "")
                if heading:
                    if subheading:
                        parts.append(f"{heading} | {subheading}")
                    else:
                        parts.append(heading)
                elif subheading:
                    parts.append(subheading)

                for bullet in entry.get("bullets", []):
                    parts.append(f"- {bullet['text']}")

        parts.append("")  # blank line between sections

    return "\n".join(parts).strip()


def get_all_bullets(
    structured: dict[str, Any],
) -> list[dict[str, Any]]:
    """Extract all bullets from all sections as a flat list.

    Each returned dict includes the bullet analysis fields plus
    ``section_key`` and ``entry_id`` for context.
    """
    results: list[dict[str, Any]] = []
    for section in structured.get("sections", []):
        sec_key = section.get("key", "")
        for entry in section.get("entries", []):
            entry_id = entry.get("id", "")
            for bullet in entry.get("bullets", []):
                results.append({
                    **bullet,
                    "section_key": sec_key,
                    "entry_id": entry_id,
                })
    return results
