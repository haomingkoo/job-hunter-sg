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
from resume_parser import _join_broken_lines, extract_phone_number
from shared_classification import SHARED_HEADINGS, SHARED_KEY_MAP, SHARED_TITLE_PATTERNS, classify_section_heading

log = logging.getLogger("jobhunter.structurer")

# ── Regex patterns ───────────────────────────────────────────────────────────

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_LINKEDIN_RE = re.compile(
    r"(?:https?://)?(?:www\.)?linkedin\.com/in/[\w\-]+/?", re.I
)

_DATE_RANGE_RE = re.compile(
    r"("
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}"
    r"|\d{1,2}/\d{4}"
    r"|\d{4}"
    r")"
    r"\s*[-\u2013\u2014]{1,2}\s*"
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
    r"^[\s]*(?:[-*\u2022\u2023\u25E6\u2043\u2219]|o\s|\d+[.)]\s)",
)
_TITLE_LINE_RE = re.compile(
    r"\b(?:"
    + "|".join(re.escape(pattern) for pattern in SHARED_TITLE_PATTERNS)
    + r")\b",
    re.I,
)
_COMPANY_LINE_RE = re.compile(
    r"\b(?:technology|technologies|corp(?:oration)?|inc|ltd|pte|limited|group|bank|systems|solutions|services|manufacturing|semiconductor|"
    r"micron|dyson|apple|meta|tiktok|kla|mondelez|singapore|japan|taiwan|usa|us|boise|hiroshima|taichung|manassas|global|regional|apac|emea|americas)\b",
    re.I,
)
_YEAR_ONLY_RE = re.compile(r"^(?:19|20)\d{2}$")
_ROLE_DESCRIPTION_RE = re.compile(
    r"^(?:selected\s+(?:into|for|as|to|via|through)\b|currently\b|joined\b|appointed\b)",
    re.I,
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
    "career_break",
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
    phone = extract_phone_number("\n".join(header_lines)) or ""
    location = ""
    linkedin = ""

    section_headers_lower = {s.lower() for s in STANDARD_SECTIONS} | SHARED_HEADINGS

    for line in header_lines:
        cleaned = _clean_line(line)
        if not cleaned:
            continue

        # Grab email if present on any header line
        email_match = _EMAIL_RE.search(cleaned)
        if email_match and not email:
            email = email_match.group()

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
        if lower in SHARED_KEY_MAP:
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

    # Lines with GPA, dates, or numeric content are NOT headings
    if _GPA_RE.search(stripped):
        return None
    if _EDUCATION_DETAIL_RE.search(stripped):
        return None
    # Lines that are mostly digits/symbols (e.g., "4.85 / 5.00") are not headings
    letters_only = re.sub(r"[^A-Za-z]", "", stripped)
    if len(letters_only) < 2:
        return None

    section_key = classify_section_heading(stripped)
    if section_key:
        return section_key

    # Line ending with colon and short enough to be a header
    if stripped.endswith(":") and len(stripped.split()) <= 5:
        return _section_key(stripped)

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


def _is_date_only_line(line: str) -> bool:
    stripped = _clean_line(line)
    if not stripped:
        return False

    normalized = stripped.replace("—", "-").replace("–", "-").strip()
    if _YEAR_ONLY_RE.fullmatch(normalized):
        return True
    if _DATE_RANGE_RE.fullmatch(normalized):
        return True
    if _SINGLE_DATE_RE.fullmatch(normalized):
        return True
    return False


def _looks_like_title_line(line: str) -> bool:
    stripped = _clean_line(line)
    if not stripped or _is_date_only_line(stripped):
        return False
    words = stripped.split()
    if len(words) > 12:
        return False
    if _starts_with_action_verb(stripped) and len(words) > 4:
        return False
    return bool(_TITLE_LINE_RE.search(stripped)) or (
        len(words) <= 8 and "(" in stripped and not stripped.endswith(".")
    )


def _looks_like_company_line(line: str) -> bool:
    stripped = _clean_line(line)
    if not stripped or _is_date_only_line(stripped) or _looks_like_title_line(stripped):
        return False
    words = stripped.split()
    if len(words) > 12:
        return False
    return bool(_COMPANY_LINE_RE.search(stripped)) or "/" in stripped


def _merge_date_parts(parts: list[str]) -> str:
    unique_parts = [part for index, part in enumerate(parts) if part and part not in parts[:index]]
    if not unique_parts:
        return ""
    if (
        len(unique_parts) == 2
        and all(_is_date_only_line(part) for part in unique_parts)
        and not any("-" in part or "–" in part or "—" in part for part in unique_parts)
    ):
        return f"{unique_parts[0]} – {unique_parts[1]}"
    return unique_parts[0]


def _is_entry_heading(line: str) -> bool:
    """Heuristic: is this line an entry heading (company/role/date)?"""
    stripped = _clean_line(line)
    if not stripped:
        return False

    has_date = bool(_DATE_RANGE_RE.search(stripped)) or bool(
        _SINGLE_DATE_RE.search(stripped)
    )
    is_caps = bool(_ALL_CAPS_HEADER_RE.match(stripped))
    is_bullet = bool(_BULLET_CHAR_RE.match(line))

    # Check for pipe separator, but exclude pipes inside number ranges
    # like "6 | 9 engineers" or "80 | 90% answer relevance"
    has_separator = False
    if _ROLE_SEPARATOR_RE.search(stripped):
        # Only count as separator if at least one side looks like a
        # role/company/location (not a number or sentence fragment)
        parts = re.split(r"\s*[|\u2014\u2013]\s*", stripped)
        if len(parts) >= 2:
            left = parts[0].strip()
            right = parts[-1].strip()
            words = stripped.split()
            # Reject if pipe is between numbers: "6 | 9", "80 | 90%"
            left_is_number = bool(re.match(r"^[\d,.%$+><=~]+$", left.split()[-1] if left else ""))
            right_is_number = bool(re.match(r"^[\d,.%$+><=~]+", right.split()[0] if right else ""))
            # Reject if line is too long to be a heading (likely a sentence)
            if left_is_number and right_is_number:
                has_separator = False
            elif len(words) > 15:
                has_separator = False
            else:
                has_separator = True

    # Lines with dates AND separators are entry headings
    if has_date and has_separator:
        return True

    # Lines with ONLY a date range (no long sentence) are entry headings
    if has_date and not is_bullet and len(stripped.split()) <= 10:
        return True

    # Lines with separators but no date — only if short enough to be a heading
    if has_separator and len(stripped.split()) <= 12:
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
    company = ""
    title = ""
    date_parts: list[str] = []
    info_lines: list[str] = []

    for raw_line in heading_lines:
        stripped = _clean_line(raw_line)
        if not stripped:
            continue

        if _is_date_only_line(stripped):
            date_parts.append(stripped)
            continue

        line_date = ""
        date_match = _DATE_RANGE_RE.search(stripped)
        single_date_match = _SINGLE_DATE_RE.search(stripped) if not date_match else None
        year_match = _YEAR_ONLY_RE.search(stripped) if not date_match and not single_date_match else None
        if date_match:
            line_date = date_match.group(0).strip()
        elif single_date_match:
            line_date = single_date_match.group(0).strip()
        elif year_match:
            line_date = year_match.group(0).strip()

        if line_date:
            date_parts.append(line_date)
            stripped = _DATE_RANGE_RE.sub("", stripped).strip()
            stripped = _SINGLE_DATE_RE.sub("", stripped).strip()
            stripped = re.sub(r"\b(?:19|20)\d{2}\b", "", stripped).strip()

        cleaned = stripped.strip().strip(",").strip("|").strip("-").strip()
        if cleaned:
            if "|" in cleaned:
                info_lines.extend(
                    part.strip() for part in cleaned.split("|") if part.strip()
                )
            else:
                info_lines.append(cleaned)

    expanded_info_lines: list[str] = []
    for info_line in info_lines:
        title_match = _TITLE_LINE_RE.search(info_line)
        if title_match and title_match.start() > 0:
            prefix = info_line[:title_match.start()].strip(" |,-–—")
            suffix = info_line[title_match.start():].strip()
            if prefix and suffix and _looks_like_company_line(prefix):
                expanded_info_lines.extend([prefix, suffix])
                continue
        expanded_info_lines.append(info_line)
    info_lines = expanded_info_lines

    date_range = _merge_date_parts(date_parts)

    title_candidates = [line for line in info_lines if _looks_like_title_line(line)]
    company_candidates = [
        line for line in info_lines
        if line not in title_candidates and _looks_like_company_line(line)
    ]

    if title_candidates:
        title = title_candidates[0]
    if company_candidates:
        company = company_candidates[0]

    if not title and info_lines:
        if len(info_lines) >= 2:
            first, second = info_lines[0], info_lines[1]
            if _looks_like_company_line(first) and _looks_like_title_line(second):
                company, title = first, second
            elif _looks_like_title_line(first):
                title = first
                company = second
            else:
                company, title = first, second
        elif _looks_like_title_line(info_lines[0]):
            title = info_lines[0]

    if not company:
        remaining = [line for line in info_lines if line != title]
        if remaining:
            company = remaining[0]
        elif info_lines and not title:
            company = info_lines[0]

    return {
        "company": company,
        "title": title,
        "date_range": date_range,
    }


# ── Education-specific entry builder ────────────────────────────────────────

def _is_education_entry_start(line: str) -> bool:
    """Check if a line starts a new education entry (degree or institution)."""
    stripped = _strip_bullet_prefix(_clean_line(line))
    if not stripped:
        return False
    if _EDUCATION_DETAIL_RE.search(stripped) and not _DEGREE_PREFIX_RE.match(stripped):
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
    id_prefix: str = "edu",
) -> dict[str, Any]:
    """Parse a group of education lines into structured fields."""
    degree = ""
    institution = ""
    date_range = ""
    gpa = ""
    details: list[str] = []

    for line in lines:
        stripped = _strip_bullet_prefix(_clean_line(line))
        if not stripped:
            continue

        is_degree_line = bool(_DEGREE_PREFIX_RE.match(stripped))
        is_institution_line = bool(
            _INSTITUTION_RE.search(stripped)
            and not _EDUCATION_DETAIL_RE.search(stripped)
        )
        is_detail_line = bool(_EDUCATION_DETAIL_RE.search(stripped))
        should_extract_date = (
            is_degree_line
            or is_institution_line
            or _is_date_only_line(stripped)
        )

        date_match = _DATE_RANGE_RE.search(stripped) if should_extract_date else None
        single_date_match = (
            _SINGLE_DATE_RE.search(stripped)
            if should_extract_date and not date_match
            else None
        )
        year_match = (
            re.search(r"\b(?:19|20)\d{2}\b", stripped)
            if should_extract_date and not date_match and not single_date_match
            else None
        )
        line_date = ""
        if date_match:
            line_date = date_match.group(0).strip()
        elif single_date_match:
            line_date = single_date_match.group(0).strip()
        elif year_match:
            line_date = year_match.group(0).strip()

        if line_date and not date_range:
            date_range = line_date

        # Extract GPA
        gpa_match = _GPA_RE.search(stripped)
        if gpa_match and not gpa:
            gpa = gpa_match.group(0).strip()

        # Classify the line
        text_no_date = stripped
        if line_date:
            text_no_date = _DATE_RANGE_RE.sub("", text_no_date).strip()
            text_no_date = _SINGLE_DATE_RE.sub("", text_no_date).strip()
            text_no_date = re.sub(r"\b(?:19|20)\d{2}\b", "", text_no_date).strip()
        text_no_date = re.sub(r"\s+", " ", text_no_date).strip(",").strip()

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

    entry_id = f"{id_prefix}-{entry_idx}"
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
    id_prefix: str = "edu",
) -> list[dict[str, Any]]:
    """Parse education section into structured entries with rich fields."""
    entries: list[dict[str, Any]] = []
    current_lines: list[str] = []

    def _flush() -> None:
        nonlocal current_lines
        if not current_lines:
            return
        entry = _parse_education_entry(current_lines, len(entries), id_prefix)
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

        if is_bullet and current_lines:
            _flush()
        elif current_lines and clean_text[:1].islower():
            current_lines[-1] = f"{current_lines[-1]} {clean_text}"
            continue

        if _is_education_entry_start(clean_text) and current_lines:
            # Check if this line belongs to the current entry
            # (e.g., degree line after institution line in the same entry)
            has_degree = any(
                _DEGREE_PREFIX_RE.match(_strip_bullet_prefix(_clean_line(ln)))
                for ln in current_lines
            )
            has_institution = any(
                _INSTITUTION_RE.search(_strip_bullet_prefix(_clean_line(ln)))
                and not _EDUCATION_DETAIL_RE.search(_strip_bullet_prefix(_clean_line(ln)))
                for ln in current_lines
            )
            is_new_degree = bool(_DEGREE_PREFIX_RE.match(clean_text))
            is_new_institution = bool(
                _INSTITUTION_RE.search(clean_text)
                and not _EDUCATION_DETAIL_RE.search(clean_text)
            )

            # Start new entry if we already have both degree + institution,
            # or if we see a second degree/institution
            if (has_degree and is_new_degree) or (
                has_institution and is_new_institution
            ) or (has_degree and has_institution):
                _flush()

        if not current_lines and not _is_education_entry_start(clean_text):
            # Stray detail line before any entry; still collect it
            if _EDUCATION_DETAIL_RE.search(clean_text):
                current_lines.append(clean_text)
                continue
            # Otherwise start a new entry
            current_lines = [clean_text]
            continue

        current_lines.append(clean_text)

    _flush()
    return entries


def _should_append_heading_line(
    current_heading_lines: list[str],
    line: str,
    section_key_str: str,
) -> bool:
    if section_key_str not in {"experience", "projects", "activities", "career_break"}:
        return False
    if not current_heading_lines:
        return False

    candidate = _clean_line(line)
    if not candidate:
        return False

    existing = [_clean_line(item) for item in current_heading_lines if _clean_line(item)]
    if not existing:
        return False
    if len(existing) >= 3 and not _is_date_only_line(candidate):
        return False
    if _is_date_only_line(candidate):
        return True
    if any(_is_date_only_line(item) for item in existing):
        return False
    if not any(_looks_like_title_line(item) for item in existing) and _looks_like_title_line(candidate):
        return True
    if not any(_looks_like_company_line(item) for item in existing) and _looks_like_company_line(candidate):
        return True
    return len(existing) == 1


def _build_entries(
    section_lines: list[str], section_key_str: str, id_prefix: str | None = None,
) -> list[dict[str, Any]]:
    """Parse lines within an entry-based section into structured entries."""
    entries: list[dict[str, Any]] = []
    current_heading_lines: list[str] = []
    current_description: list[str] = []
    current_bullets: list[str] = []
    prefix = id_prefix or section_key_str[:3]

    def _flush() -> None:
        nonlocal current_heading_lines, current_description, current_bullets
        if not current_heading_lines and not current_description and not current_bullets:
            return
        idx = len(entries)
        entry_id = f"{prefix}-{idx}"
        parsed = _parse_entry_heading(current_heading_lines)

        heading = parsed["title"] or parsed["company"] or (
            _clean_line(current_heading_lines[0])
            if current_heading_lines
            else ""
        )
        subheading_parts: list[str] = []
        if parsed["company"]:
            subheading_parts.append(parsed["company"])
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
            "description": " ".join(current_description),
            "bullets": bullets_out,
        })
        current_heading_lines = []
        current_description = []
        current_bullets = []

    for line_index, line in enumerate(section_lines):
        stripped = _clean_line(line)
        if not stripped:
            continue

        is_bullet_line = bool(_BULLET_CHAR_RE.match(line))

        # Bullets ALWAYS take priority — a line starting with •/-/* is a bullet,
        # even if it contains pipes or dates
        if is_bullet_line:
            bullet_text = _strip_bullet_prefix(line)
            if bullet_text:
                current_bullets.append(bullet_text)
            continue

        is_heading = _is_entry_heading(line)

        # When we're inside a bullet list, only break for a new entry
        # if the line has a clear date or is ALL-CAPS (not just a pipe)
        if is_heading and current_bullets:
            has_date = bool(_DATE_RANGE_RE.search(stripped)) or bool(
                _SINGLE_DATE_RE.search(stripped)
            )
            is_caps = bool(_ALL_CAPS_HEADER_RE.match(stripped))
            next_line = next(
                (
                    _clean_line(candidate)
                    for candidate in section_lines[line_index + 1:]
                    if _clean_line(candidate)
                ),
                "",
            )
            if not has_date and not is_caps and not _is_date_only_line(next_line):
                current_bullets[-1] += " " + stripped
                continue

        if is_heading:
            if current_heading_lines and not current_bullets and _should_append_heading_line(
                current_heading_lines, line, section_key_str,
            ):
                current_heading_lines.append(line)
            else:
                _flush()
                current_heading_lines = [line]
                current_bullets = []
        elif current_bullets and stripped[:1].islower():
            current_bullets[-1] += " " + stripped
        elif current_heading_lines and not current_bullets and _ROLE_DESCRIPTION_RE.match(stripped):
            current_description.append(stripped)
        elif (
            _starts_with_action_verb(stripped)
            and len(stripped.split()) >= 5
        ):
            # Implicit bullet (no marker but starts with action verb)
            current_bullets.append(stripped)
        elif (
            current_heading_lines
            and not current_bullets
            and any(
                _DATE_RANGE_RE.search(_clean_line(item))
                or _SINGLE_DATE_RE.search(_clean_line(item))
                for item in current_heading_lines
            )
            and not (
                _is_date_only_line(stripped)
                or _looks_like_title_line(stripped)
                or _looks_like_company_line(stripped)
            )
        ):
            # A long paragraph after a dated role is role context, not a bullet.
            current_description.append(stripped)
        elif current_heading_lines and not current_bullets and _should_append_heading_line(
            current_heading_lines, line, section_key_str,
        ):
            # Second heading line (title on separate line from company)
            current_heading_lines.append(line)
        elif current_bullets:
            # Continuation of the previous bullet
            current_bullets[-1] += " " + stripped
        elif current_heading_lines:
            current_description.append(stripped)
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
    tokens = re.split(r"[,;|\u2022\u2023\u25E6\u2043\u2219\u00B7\n]+", raw)
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

    normalized_text = _join_broken_lines(text)
    all_lines = _iter_resume_lines(normalized_text)

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
    section_occurrences: dict[str, int] = {}

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
            occurrence = section_occurrences.get(key, 0)
            section_occurrences[key] = occurrence + 1
            id_prefix = key[:3] if occurrence == 0 else f"{key[:3]}{occurrence + 1}"
            if key == "education":
                entries = _build_education_entries(sec_lines, id_prefix)
            else:
                entries = _build_entries(sec_lines, key, id_prefix)
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
