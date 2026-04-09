"""
Resume upload + parsing — extracts text from PDF and DOCX files.
Returns the full text without truncation.
"""

from __future__ import annotations

import io
import logging
import re
from typing import Optional

from shared_classification import SHARED_HEADINGS

log = logging.getLogger("jobhunter.parser")

MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB
ALLOWED_TYPES = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/msword": "doc",
}
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc"}

SECTION_HEADER_ALIASES = {
    "experience", "professional experience", "work experience", "employment history",
    "career history", "professional background", "education", "academic background",
    "skills", "technical skills", "technical proficiencies", "core skills",
    "core competencies", "competencies", "summary", "professional summary",
    "executive summary", "career summary", "professional profile", "profile",
    "summary of qualifications", "qualifications", "objective", "projects",
    "selected projects", "leadership", "activities", "volunteer", "volunteering",
    "certifications", "certification", "licenses", "licenses & certifications",
    "certifications & technical upskilling", "additional information",
    "languages", "interests", "awards", "publications", "personal", "personal particulars",
} | set(SHARED_HEADINGS)

DOCX_BULLET_STYLE_TOKENS = (
    "list bullet",
    "bullet",
    "list paragraph",
)

DOCX_NUMBER_STYLE_TOKENS = (
    "list number",
    "number",
)


def _looks_like_section_header(value: str) -> bool:
    stripped = value.strip()
    if not stripped:
        return False

    lower = stripped.lower().rstrip(":")
    if lower in SECTION_HEADER_ALIASES:
        return True

    if re.fullmatch(r"[A-Z][A-Z &/\-]{3,}", stripped):
        return True

    return False


def validate_upload(filename: str, content_type: str, size: int) -> str:
    """Validate file upload. Returns file type or raises ValueError."""
    # Check size
    if size > MAX_FILE_SIZE:
        raise ValueError(f"File too large ({size // 1024}KB). Maximum is 5MB.")
    if size == 0:
        raise ValueError("File is empty.")

    # Check extension
    ext = ""
    if filename:
        ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Unsupported file type. Please upload PDF or DOCX.")

    # Check content type
    file_type = ALLOWED_TYPES.get(content_type, "")
    if not file_type:
        # Fall back to extension-based detection
        file_type = ext.lstrip(".")

    return file_type


def _join_broken_lines(text: str) -> str:
    """Rejoin lines that pdfplumber broke mid-sentence.

    The key insight: PDF line breaks are layout-driven, not semantic.
    A sentence like "Led cross-functional delivery" might become two lines:
      "Led cross-"
      "functional delivery"

    We join aggressively and only keep lines separate when they clearly
    start a new semantic block (section header, bullet, role/date line).
    """
    _bullet_start = re.compile(r"^[\s]*[•\-\*▪\u2022\u2023\u25E6\u2043\u2219]\s")
    _date_pattern = re.compile(
        r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}"
        r"|\d{1,2}/\d{4}"
        r"|\d{4}\s*[-–—]\s*(?:\d{4}|[Pp]resent|[Cc]urrent)",
    )
    _all_caps_header = re.compile(r"^[A-Z][A-Z &/\-]{3,}$")
    _role_separator = re.compile(r"\s[|—–]\s")
    _contact_signal = re.compile(r"@|linkedin|github|portfolio|https?://", re.IGNORECASE)
    _phone_only = re.compile(r"^[\+]?[\d\s\-\(\)]{8,}$")
    # Known section headers
    _section_words = SECTION_HEADER_ALIASES

    lines = text.split("\n")
    merged: list[str] = []

    for line in lines:
        stripped = line.strip()

        # Preserve blank lines
        if not stripped:
            merged.append("")
            continue

        # Check if PREVIOUS line ends with hyphen (word split across lines)
        if merged and merged[-1] and merged[-1].endswith("-"):
            # Join without space, removing the trailing hyphen
            merged[-1] = merged[-1][:-1] + stripped
            continue

        # Determine if this line starts a new semantic block
        starts_new = False
        lower = stripped.lower()

        # Bullet point (• Led..., - Built..., etc)
        if _bullet_start.match(stripped):
            starts_new = True
        elif _contact_signal.search(stripped) or _phone_only.match(stripped):
            starts_new = True
        # ALL CAPS section header (PROFESSIONAL EXPERIENCE, EDUCATION, etc)
        elif _all_caps_header.match(stripped):
            starts_new = True
        # Known section header words
        elif lower in _section_words or lower.rstrip(":") in _section_words:
            starts_new = True
        # Line with a date (likely a role/company line)
        elif _date_pattern.search(stripped):
            starts_new = True
        # Line with role separator (Company | Location, Title — Date)
        elif _role_separator.search(stripped):
            starts_new = True
        # Short line that looks like a company/institution name (< 60 chars, starts with caps)
        elif len(stripped) < 60 and stripped[0].isupper() and not stripped[0:1].islower():
            # Check if it looks like a heading (no period at end, mostly proper nouns)
            if not stripped.endswith((".",";")):
                words = stripped.split()
                # If most words are capitalized, likely a heading/company name
                caps_words = sum(1 for w in words if w[0].isupper())
                if caps_words >= len(words) * 0.6 and len(words) <= 8:
                    starts_new = True

        # If previous line ends with period/semicolon AND this starts with caps, new line
        if not starts_new and merged and merged[-1]:
            prev = merged[-1]
            prev_lower = prev.strip().lower().rstrip(":")
            prev_is_section = _looks_like_section_header(prev.strip())
            prev_is_subheading = bool(_date_pattern.search(prev)) or bool(_role_separator.search(prev))

            # Never join content onto a section header or dated role line.
            if prev_is_section or prev_is_subheading:
                starts_new = True
            elif _contact_signal.search(prev) or _phone_only.match(prev.strip()):
                starts_new = True

        if not starts_new and merged and merged[-1]:
            prev = merged[-1]
            if prev.endswith((".", ";", ":", "!")) and stripped[0].isupper():
                starts_new = True

        if starts_new or not merged or merged[-1] == "":
            merged.append(stripped)
        else:
            # Continuation — join to previous line
            merged[-1] = merged[-1] + " " + stripped

    return "\n".join(merged)


def _looks_like_docx_list_paragraph(paragraph) -> bool:
    style_name = (getattr(getattr(paragraph, "style", None), "name", "") or "").strip().lower()
    if any(token in style_name for token in DOCX_BULLET_STYLE_TOKENS + DOCX_NUMBER_STYLE_TOKENS):
        return True

    paragraph_props = getattr(getattr(paragraph, "_p", None), "pPr", None)
    numbering_props = getattr(paragraph_props, "numPr", None)
    return numbering_props is not None


def _extract_docx_paragraph_text(paragraph) -> str:
    raw = getattr(paragraph, "text", "") or ""
    lines = [segment.strip() for segment in raw.splitlines() if segment.strip()]
    if not lines:
        return ""

    cleaned = "\n".join(lines)
    if _looks_like_docx_list_paragraph(paragraph) and not re.match(r"^\s*(?:[•\-\*▪\u2022\u2023\u25E6\u2043\u2219]|\d+[.)])\s+", cleaned):
        cleaned = f"• {cleaned}"
    return cleaned


def _append_text_lines(target: list[str], value: str) -> None:
    for line in str(value or "").splitlines():
        cleaned = line.strip()
        if cleaned:
            target.append(cleaned)


def _has_missing_spaces(text: str) -> bool:
    """Detect if extracted text has space-stripping (common in LaTeX PDFs).

    Two signals:
    1. CamelCase merges: lowercase immediately followed by uppercase (e.g. 'hJ' in
       'VikneshJayaKumar') - reliable indicator of merged words.
    2. Very long tokens: words >40 chars that span multiple merged words.
    Either signal affecting >10% of tokens triggers the fix.
    """
    import re
    words = text.split()
    if not words:
        return False
    camel_merge = re.compile(r"[a-z][A-Z]")
    merged = sum(1 for w in words if camel_merge.search(w))
    if merged > len(words) * 0.10:
        return True
    long_words = sum(1 for w in words if len(w) > 40)
    return long_words > len(words) * 0.15


def _extract_text_from_chars(page) -> str:
    """Reconstruct text from character-level positions when extract_text() fails.

    LaTeX PDFs often have correct character positions but missing space
    characters. This function detects gaps between characters and inserts
    spaces where the visual layout implies them.
    """
    chars = page.chars
    if not chars:
        return ""

    # Group chars into lines by top position (within 3pt tolerance)
    lines: dict[float, list] = {}
    for c in chars:
        top = round(float(c["top"]) / 3) * 3  # bucket by ~3pt
        lines.setdefault(top, []).append(c)

    # Determine typical character width for space threshold.
    # Use 15% of avg char width (not 35%) to catch tight LaTeX word spacing
    # (typically 1.5-3pt gaps). Within-word char gaps are ~0pt, so 15% is safe.
    all_widths = [float(c["x1"]) - float(c["x0"]) for c in chars if c["text"].strip()]
    avg_width = sum(all_widths) / len(all_widths) if all_widths else 5.0
    space_threshold = avg_width * 0.15  # gap > 15% of avg char width = space

    result_lines = []
    for top in sorted(lines.keys()):
        line_chars = sorted(lines[top], key=lambda c: float(c["x0"]))
        text = ""
        prev_x1 = 0.0
        for c in line_chars:
            gap = float(c["x0"]) - prev_x1
            if prev_x1 > 0 and gap > space_threshold:
                text += " "
            text += c["text"]
            prev_x1 = float(c["x1"])
        if text.strip():
            result_lines.append(text.strip())

    return "\n".join(result_lines)


def extract_text_from_pdf(file_bytes: bytes) -> str:
    """Extract full text from a PDF file. No truncation.

    Uses standard extraction first, then falls back to character-level
    reconstruction for LaTeX PDFs with missing spaces.
    """
    import pdfplumber

    text_parts = []
    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    # Detect LaTeX space-stripping and fall back to char-level
                    if _has_missing_spaces(page_text):
                        char_text = _extract_text_from_chars(page)
                        if char_text and not _has_missing_spaces(char_text):
                            log.info("PDF page %d: LaTeX space fix applied", page.page_number)
                            page_text = char_text
                    text_parts.append(page_text)
    except Exception as e:
        log.warning(f"PDF extraction failed: {e}")
        raise ValueError("Could not read this PDF. Make sure it's not a scanned image — we need text-based PDFs.")

    full_text = "\n\n".join(text_parts)
    if not full_text.strip():
        raise ValueError("No text found in PDF. If your resume is a scanned image, please upload a DOCX or text-based PDF instead.")

    full_text = _join_broken_lines(full_text)
    return full_text


def extract_text_from_docx(file_bytes: bytes) -> str:
    """Extract full text from a DOCX file. No truncation."""
    from docx import Document

    try:
        doc = Document(io.BytesIO(file_bytes))
    except Exception as e:
        log.warning(f"DOCX extraction failed: {e}")
        raise ValueError("Could not read this DOCX file. It may be corrupted.")

    text_parts = []
    for para in doc.paragraphs:
        paragraph_text = _extract_docx_paragraph_text(para)
        if paragraph_text:
            _append_text_lines(text_parts, paragraph_text)

    # Also extract from tables (some resumes use tables for layout)
    for table in doc.tables:
        for row in table.rows:
            row_values: list[str] = []
            for cell in row.cells:
                cell_lines: list[str] = []
                for para in cell.paragraphs:
                    paragraph_text = _extract_docx_paragraph_text(para)
                    if paragraph_text:
                        _append_text_lines(cell_lines, paragraph_text)
                if cell_lines:
                    row_values.append(" ".join(cell_lines).strip())
            row_text = " | ".join(value for value in row_values if value)
            if row_text:
                text_parts.append(row_text)

    full_text = "\n".join(text_parts)
    if not full_text.strip():
        raise ValueError("No text found in DOCX file.")

    return _join_broken_lines(full_text)


def parse_resume(filename: str, content_type: str, file_bytes: bytes) -> dict:
    """
    Parse an uploaded resume file. Returns full extracted text + metadata.
    No truncation — returns everything.
    """
    file_type = validate_upload(filename, content_type, len(file_bytes))

    if file_type in ("pdf",):
        text = extract_text_from_pdf(file_bytes)
    elif file_type in ("docx", "doc"):
        text = extract_text_from_docx(file_bytes)
    else:
        raise ValueError(f"Unsupported file type: {file_type}")

    # Basic metadata extraction
    lines = text.split("\n")
    word_count = len(text.split())
    line_count = len([l for l in lines if l.strip()])

    # Try to find email, phone, and name
    email_match = re.search(r'[\w.+-]+@[\w-]+\.[\w.]+', text)
    phone_match = re.search(r'[\+]?[\d\s\-\(\)]{8,15}', text)

    # Name detection — first non-empty line that looks like a name
    # (2-4 words, no special chars, not an email/phone/url, not a section header)
    name = None
    top_block = []
    for line in lines:
        cleaned = line.strip()
        if not cleaned or len(cleaned) < 3:
            continue
        if _looks_like_section_header(cleaned):
            break
        top_block.append(cleaned)
        if len(top_block) >= 6:
            break

    section_headers = SECTION_HEADER_ALIASES | {"professional", "work", "contact"}
    for cleaned in top_block:
        lower = cleaned.lower()
        # Skip emails, phones, URLs, section headers
        if "@" in cleaned or "http" in lower or "linkedin" in lower:
            continue
        if any(h in lower for h in section_headers):
            continue
        if re.match(r'^[\+\d\s\-\(\)]+$', cleaned):  # Skip phone-only lines
            continue
        # Looks like a name: 2-5 words, mostly letters
        words = cleaned.split()
        if 1 <= len(words) <= 5 and all(re.match(r'^[A-Za-z\.\-\']+$', w) for w in words):
            name = cleaned
            break

    return {
        "text": text,  # FULL text, no truncation
        "filename": filename,
        "file_type": file_type,
        "word_count": word_count,
        "line_count": line_count,
        "name": name,
        "email": email_match.group() if email_match else None,
        "phone": phone_match.group().strip() if phone_match else None,
        "page_estimate": max(1, word_count // 500),
    }
