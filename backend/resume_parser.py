"""
Resume upload + parsing — extracts text from PDF and DOCX files.
Returns the full text without truncation.
"""

from __future__ import annotations

import io
import logging
import re
from typing import Optional

log = logging.getLogger("jobhunter.parser")

MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB
ALLOWED_TYPES = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/msword": "doc",
}
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc"}


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
    # Known section headers
    _section_words = {
        "experience", "education", "skills", "summary", "objective",
        "certifications", "projects", "awards", "languages", "interests",
        "volunteer", "activities", "publications", "references",
        "professional summary", "professional experience", "work experience",
        "core skills", "core competencies", "technical skills",
    }

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
            if prev.endswith((".", ";", ":", "!")) and stripped[0].isupper():
                starts_new = True

        if starts_new or not merged or merged[-1] == "":
            merged.append(stripped)
        else:
            # Continuation — join to previous line
            merged[-1] = merged[-1] + " " + stripped

    return "\n".join(merged)


def extract_text_from_pdf(file_bytes: bytes) -> str:
    """Extract full text from a PDF file. No truncation."""
    import pdfplumber

    text_parts = []
    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
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
        if para.text.strip():
            text_parts.append(para.text)

    # Also extract from tables (some resumes use tables for layout)
    for table in doc.tables:
        for row in table.rows:
            row_text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
            if row_text:
                text_parts.append(row_text)

    full_text = "\n".join(text_parts)
    if not full_text.strip():
        raise ValueError("No text found in DOCX file.")

    return full_text


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
    section_headers = {"experience", "education", "skills", "summary", "objective",
                       "certifications", "professional", "work", "projects", "contact"}
    for line in lines:
        cleaned = line.strip()
        if not cleaned or len(cleaned) < 3:
            continue
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
