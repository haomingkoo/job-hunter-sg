"""
Resume upload + parsing — extracts text from PDF and DOCX files.
Returns the full text without truncation.
"""

from __future__ import annotations

import io
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import zipfile

from shared_classification import SHARED_HEADINGS

log = logging.getLogger("jobhunter.parser")

MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB
MAX_EXTRACTED_CHARS = 200_000
MAX_PDF_PAGES = 50
MAX_DOCX_ENTRIES = 2_000
MAX_DOCX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
MAX_DOCX_COMPRESSION_RATIO = 100
MAX_PARSER_OUTPUT_BYTES = 2 * 1024 * 1024
PARSER_WALL_TIMEOUT_SECONDS = 8
PDF_X_TOLERANCE_RATIO = 0.15
ALLOWED_TYPES = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
}
ALLOWED_EXTENSIONS = {".pdf", ".docx"}

SECTION_HEADER_ALIASES = set(SHARED_HEADINGS)

_BULLET_PREFIX_RE = re.compile(
    r"^[\t ]*(?P<marker>[•\-*▪\u2022\u2023\u25E6\u2043\u2219]|\d+[.)])[\t ]*",
    re.MULTILINE,
)
_WRAPPED_HYPHEN_RE = re.compile(r"(?<=\w)-\n[\t ]*(?=\w)")

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
    return stripped.lower().rstrip(":") in SECTION_HEADER_ALIASES


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
    """Apply only mechanical repairs; preserve PDF line boundaries."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = _WRAPPED_HYPHEN_RE.sub("-", normalized)
    return _BULLET_PREFIX_RE.sub(
        lambda match: f"{match.group('marker')} ",
        normalized,
    )


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
    if _looks_like_docx_list_paragraph(paragraph) and not _BULLET_PREFIX_RE.match(cleaned):
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
    words = text.split()
    if not words:
        return False
    camel_merge = re.compile(r"[a-z][A-Z]")
    merged = sum(1 for w in words if camel_merge.search(w))
    if merged > len(words) * 0.10:
        return True
    long_words = sum(1 for w in words if len(w) > 40)
    return long_words > len(words) * 0.15


def _parse_quality(text: str, file_type: str) -> dict:
    """Return lightweight diagnostics so the UI can warn on weak extraction.

    This is intentionally heuristic. The parser should still return the text it
    can read, but users deserve a visible warning when the extraction looks
    incomplete or layout-damaged.
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    words = text.split()
    lower_lines = {line.lower().rstrip(":") for line in lines}
    section_hits = sum(1 for line in lower_lines if line in SECTION_HEADER_ALIASES)
    bullet_lines = sum(1 for line in lines if _BULLET_PREFIX_RE.match(line))
    long_tokens = [word for word in words if len(word) > 45]
    email_found = bool(re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text))
    phone_found = bool(re.search(r"[\+]?[\d\s\-\(\)]{8,15}", text))
    merged_words = _has_missing_spaces(text)

    score = 100
    warnings: list[str] = []

    if len(words) < 120:
        score -= 35
        warnings.append(
            f"Only {len(words)} words were extracted. If this is a full resume, the file may be image-based or protected."
        )
    elif len(words) < 220:
        score -= 10

    if len(lines) < 8:
        score -= 20
        warnings.append("Very few text lines were extracted; review the parsed text before scoring or tailoring.")

    if section_hits < 2 and len(words) >= 120:
        score -= 18
        warnings.append("Few standard resume sections were detected; headings may have been lost or merged by the PDF parser.")

    if bullet_lines == 0 and len(words) >= 180:
        score -= 12
        warnings.append("No bullet lines were detected. Achievements may have been flattened into paragraphs.")

    if merged_words:
        score -= 25
        warnings.append("Some words still look merged after extraction. A DOCX upload or pasted text may parse better.")
    elif long_tokens:
        score -= 10
        warnings.append("Some unusually long tokens were found; quickly check for missing spaces in the parsed resume.")

    if not email_found and not phone_found and len(words) >= 120:
        score -= 8
        warnings.append("Contact details were not detected. Check the header if it was laid out with icons or columns.")

    label = "good"
    if score < 60:
        label = "review"
    elif warnings:
        label = "check"

    return {
        "label": label,
        "score": max(0, min(100, score)),
        "warnings": warnings[:4],
        "signals": {
            "file_type": file_type,
            "word_count": len(words),
            "line_count": len(lines),
            "section_count": section_hits,
            "bullet_line_count": bullet_lines,
            "email_found": email_found,
            "phone_found": phone_found,
            "possible_merged_words": merged_words,
            "long_token_count": len(long_tokens),
        },
    }


def extract_text_from_pdf(file_bytes: bytes) -> str:
    """Extract full text from a PDF file. No truncation.

    Uses pdfplumber's proportional spacing tolerance for tightly-set PDFs.
    """
    import pdfplumber

    text_parts = []
    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            if len(pdf.pages) > MAX_PDF_PAGES:
                raise ValueError(f"PDF has too many pages. Maximum is {MAX_PDF_PAGES}.")
            for page in pdf.pages:
                page_text = page.extract_text(
                    x_tolerance_ratio=PDF_X_TOLERANCE_RATIO,
                )
                if page_text:
                    text_parts.append(page_text)
                    if sum(len(part) for part in text_parts) > MAX_EXTRACTED_CHARS:
                        raise ValueError("PDF contains too much text.")
    except ValueError:
        raise
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
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_DOCX_ENTRIES:
                raise ValueError("DOCX contains too many files.")
            total_compressed = sum(max(entry.compress_size, 1) for entry in entries)
            total_uncompressed = sum(entry.file_size for entry in entries)
            if total_uncompressed > MAX_DOCX_UNCOMPRESSED_BYTES:
                raise ValueError("DOCX expands beyond the safe size limit.")
            if (
                total_uncompressed / total_compressed > MAX_DOCX_COMPRESSION_RATIO
                or any(
                    entry.file_size / max(entry.compress_size, 1) > MAX_DOCX_COMPRESSION_RATIO
                    for entry in entries
                )
            ):
                raise ValueError("DOCX compression ratio is unsafe.")
        doc = Document(io.BytesIO(file_bytes))
    except ValueError:
        raise
    except zipfile.BadZipFile:
        raise ValueError("Could not read this DOCX file. It may be corrupted.") from None
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

    if len(full_text) > MAX_EXTRACTED_CHARS:
        raise ValueError("DOCX contains too much text.")
    return _join_broken_lines(full_text)


def parse_resume(filename: str, content_type: str, file_bytes: bytes) -> dict:
    """
    Parse an uploaded resume file. Returns full extracted text + metadata.
    No truncation — returns everything.
    """
    file_type = validate_upload(filename, content_type, len(file_bytes))

    if file_type in ("pdf",):
        text = extract_text_from_pdf(file_bytes)
    elif file_type == "docx":
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
        "parse_quality": _parse_quality(text, file_type),
        "name": name,
        "email": email_match.group() if email_match else None,
        "phone": phone_match.group().strip() if phone_match else None,
        "page_estimate": max(1, word_count // 500),
    }


def parse_resume_isolated(filename: str, content_type: str, file_bytes: bytes) -> dict:
    """Parse an upload in a resource-limited, short-lived subprocess."""
    validate_upload(filename, content_type, len(file_bytes))
    header = json.dumps(
        {"filename": filename, "content_type": content_type, "size": len(file_bytes)},
        separators=(",", ":"),
    ).encode()
    if len(header) > 16 * 1024:
        raise ValueError("Resume filename is too long.")

    worker = Path(__file__).with_name("resume_parser_worker.py")
    with tempfile.TemporaryFile() as output:
        try:
            process = subprocess.Popen(
                [sys.executable, str(worker)],
                stdin=subprocess.PIPE,
                stdout=output,
                stderr=subprocess.DEVNULL,
                env={"PATH": os.defpath, "PYTHONHASHSEED": "random"},
            )
            process.communicate(header + b"\n" + file_bytes, timeout=PARSER_WALL_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            raise ValueError("Resume parsing took too long. Please try a simpler PDF or DOCX.") from None
        except (OSError, subprocess.SubprocessError):
            raise ValueError("Could not safely parse this resume.") from None

        output.seek(0)
        raw_result = output.read(MAX_PARSER_OUTPUT_BYTES + 1)

    if process.returncode != 0 or len(raw_result) > MAX_PARSER_OUTPUT_BYTES:
        raise ValueError("Could not safely parse this resume.")

    try:
        response = json.loads(raw_result)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError("Could not safely parse this resume.") from None

    if not isinstance(response, dict):
        raise ValueError("Could not safely parse this resume.")
    if not response.get("ok"):
        error = response.get("error")
        raise ValueError(error if isinstance(error, str) and len(error) <= 500 else "Could not safely parse this resume.")
    result = response.get("result")
    if not isinstance(result, dict):
        raise ValueError("Could not safely parse this resume.")
    return result
