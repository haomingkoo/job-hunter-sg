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

    # Try to find email and phone
    email_match = re.search(r'[\w.+-]+@[\w-]+\.[\w.]+', text)
    phone_match = re.search(r'[\+]?[\d\s\-\(\)]{8,15}', text)

    return {
        "text": text,  # FULL text, no truncation
        "filename": filename,
        "file_type": file_type,
        "word_count": word_count,
        "line_count": line_count,
        "email": email_match.group() if email_match else None,
        "phone": phone_match.group().strip() if phone_match else None,
        "page_estimate": max(1, word_count // 500),
    }
