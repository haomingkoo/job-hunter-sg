"""
Resume upload + parsing — extracts text from PDF and DOCX files.
Returns the full text without truncation.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile
import zipfile

from shared_classification import SHARED_HEADINGS, classify_section_heading
from resume_document import create_resume_document

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
_PHONE_CANDIDATE_RE = re.compile(
    r"(?<!\w)(?:\+\d{1,3}[ .\-]?)?(?:\(\d{1,4}\)[ .\-]?)?\d(?:[\d .\-]{5,16}\d)(?!\w)"
)
_YEAR_RANGE_RE = re.compile(r"^(?:19|20)\d{2}\s*[-–—]\s*(?:19|20)\d{2}$")

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
    return classify_section_heading(value) is not None


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


def _list_marker(value: str) -> str | None:
    match = _BULLET_PREFIX_RE.match(value or "")
    return match.group("marker") if match else None


def _docx_paragraph_record(paragraph, *, source_kind: str) -> dict | None:
    text = _extract_docx_paragraph_text(paragraph)
    if not text:
        return None
    paragraph_format = paragraph.paragraph_format
    left_indent = getattr(paragraph_format, "left_indent", None)
    first_line_indent = getattr(paragraph_format, "first_line_indent", None)
    indentation = left_indent or first_line_indent
    runs = [run for run in paragraph.runs if (run.text or "").strip()]
    font_sizes = [float(run.font.size.pt) for run in runs if run.font.size is not None]
    style_name = (getattr(getattr(paragraph, "style", None), "name", "") or "").strip()
    heading_match = re.match(r"heading\s+(\d+)$", style_name, re.I)
    return {
        "text": text,
        "page": None,
        "list_marker": _list_marker(text),
        "indentation": float(indentation.pt) if indentation is not None else None,
        "x_position": None,
        "heading_emphasis": bool(heading_match or any(run.bold is True for run in runs)),
        "font_size": max(font_sizes, default=None),
        "heading_level": int(heading_match.group(1)) if heading_match else None,
        "style_name": style_name or None,
        "source_kind": source_kind,
    }


def _merge_docx_row_records(records: list[dict]) -> dict:
    return {
        "text": " | ".join(record["text"] for record in records),
        "page": None,
        "list_marker": next((record["list_marker"] for record in records if record["list_marker"]), None),
        "indentation": next((record["indentation"] for record in records if record["indentation"] is not None), None),
        "x_position": None,
        "heading_emphasis": any(record["heading_emphasis"] for record in records),
        "font_size": max((record["font_size"] for record in records if record["font_size"] is not None), default=None),
        "heading_level": next((record["heading_level"] for record in records if record["heading_level"] is not None), None),
        "style_name": next((record["style_name"] for record in records if record["style_name"]), None),
        "source_kind": "table_row",
    }


def extract_phone_number(text: str) -> str | None:
    for match in _PHONE_CANDIDATE_RE.finditer(text or ""):
        candidate = match.group().strip()
        digits = sum(char.isdigit() for char in candidate)
        has_phone_formatting = bool(re.search(r"[+().\-\s]", candidate))
        looks_like_sg_local = digits == 8 and candidate[:1] in {"3", "6", "8", "9"}
        if (
            7 <= digits <= 15
            and not _YEAR_RANGE_RE.fullmatch(candidate)
            and (has_phone_formatting or looks_like_sg_local)
        ):
            return candidate
    return None


def _extract_docx_container(container, *, source_kind: str = "body") -> list[dict]:
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    records: list[dict] = []
    for block in container.iter_inner_content():
        if isinstance(block, Paragraph):
            record = _docx_paragraph_record(block, source_kind=source_kind)
            if record:
                records.append(record)
            continue
        if isinstance(block, Table):
            for row in block.rows:
                row_cells: list[list[dict]] = []
                seen_cells: set[int] = set()
                for cell in row.cells:
                    cell_id = id(cell._tc)
                    if cell_id in seen_cells:
                        continue
                    seen_cells.add(cell_id)
                    cell_records = _extract_docx_container(cell, source_kind="table_cell")
                    if cell_records:
                        row_cells.append(cell_records)
                for line_index in range(max((len(items) for items in row_cells), default=0)):
                    line_records = [
                        items[line_index]
                        for items in row_cells
                        if line_index < len(items)
                    ]
                    if line_records:
                        records.append(_merge_docx_row_records(line_records))
    return records


def _materialize_layout_records(records: list[dict]) -> tuple[str, list[dict]]:
    parts: list[str] = []
    layout: list[dict] = []
    cursor = 0
    previous_page = None
    for record in records:
        page = record.get("page")
        separator = "\n\n" if parts and page is not None and page != previous_page else ("\n" if parts else "")
        if separator:
            parts.append(separator)
            cursor += len(separator)
        value = str(record.get("text") or "")
        start = cursor
        parts.append(value)
        cursor += len(value)
        layout.append({**record, "raw_span": [start, cursor]})
        previous_page = page
    return "".join(parts), layout


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


def _parse_quality(text: str, file_type: str, *, possible_multi_column_layout: bool = False) -> dict:
    """Return lightweight diagnostics so the UI can warn on weak extraction.

    This is intentionally heuristic. The parser should still return the text it
    can read, but users deserve a visible warning when the extraction looks
    incomplete or layout-damaged.
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    words = text.split()
    section_hits = len({
        line.lower().rstrip(":")
        for line in lines
        if classify_section_heading(line) is not None
    })
    bullet_lines = sum(1 for line in lines if _BULLET_PREFIX_RE.match(line))
    long_tokens = [word for word in words if len(word) > 45]
    email_found = bool(re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text))
    phone_found = extract_phone_number(text) is not None
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

    if possible_multi_column_layout:
        score -= 20
        warnings.append("This PDF appears to use multiple columns, so reading order may need review. A DOCX upload is safer.")

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
            "possible_multi_column_layout": possible_multi_column_layout,
        },
    }


def _content_warnings(text: str) -> list[str]:
    bracketed = re.findall(r"\[[^\]\n]{1,120}\]", text or "")
    unresolved = [
        value
        for value in bracketed
        if re.search(r"\b(?:confirm|verify|todo|tbc|insert|placeholder)\b|\b[XS$%]*X\b|^\[N\]$", value, re.I)
    ]
    if not unresolved:
        return []
    return [f"Found {len(unresolved)} unresolved placeholder(s). Replace or remove them before exporting."]


def _page_has_multiple_columns(page) -> bool:
    words = page.extract_words() or []
    if len(words) < 30:
        return False
    rows: list[list[dict]] = []
    for word in sorted(words, key=lambda item: (float(item["top"]), float(item["x0"]))):
        if not rows or abs(float(word["top"]) - float(rows[-1][0]["top"])) > 3:
            rows.append([word])
        else:
            rows[-1].append(word)

    midpoint = float(page.width) / 2
    wide_gap_rows = 0
    for row in rows:
        left = [word for word in row if float(word["x1"]) < midpoint]
        right = [word for word in row if float(word["x0"]) > midpoint]
        if not left or not right:
            continue
        gap = min(float(word["x0"]) for word in right) - max(float(word["x1"]) for word in left)
        if gap > float(page.width) * 0.12:
            wide_gap_rows += 1
    return wide_gap_rows >= 6 and wide_gap_rows >= len(rows) * 0.2


def _pdf_line_record(line: dict, page_number: int) -> dict:
    chars = line.get("chars") or []
    font_sizes = [float(char["size"]) for char in chars if char.get("size") is not None]
    font_names = {str(char.get("fontname") or "") for char in chars}
    return {
        "text": str(line.get("text") or "").strip(),
        "page": page_number,
        "list_marker": _list_marker(str(line.get("text") or "")),
        "indentation": float(line.get("x0")) if line.get("x0") is not None else None,
        "x_position": float(line.get("x0")) if line.get("x0") is not None else None,
        "heading_emphasis": any(
            re.search(r"bold|black|heavy|semibold", name, re.I)
            for name in font_names
        ),
        "font_size": max(font_sizes, default=None),
        "heading_level": None,
        "style_name": None,
        "source_kind": "pdf_line",
    }


def _extract_pdf(file_bytes: bytes) -> tuple[str, bool, int, list[dict]]:
    """Extract full text from a PDF file. No truncation.

    Uses pdfplumber's proportional spacing tolerance for tightly-set PDFs.
    """
    import pdfplumber

    records: list[dict] = []
    possible_multi_column_layout = False
    page_count = 0
    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            page_count = len(pdf.pages)
            if len(pdf.pages) > MAX_PDF_PAGES:
                raise ValueError(f"PDF has too many pages. Maximum is {MAX_PDF_PAGES}.")
            for page_number, page in enumerate(pdf.pages, start=1):
                possible_multi_column_layout = possible_multi_column_layout or _page_has_multiple_columns(page)
                page_lines = page.extract_text_lines(
                    x_tolerance_ratio=PDF_X_TOLERANCE_RATIO,
                )
                for line in page_lines:
                    record = _pdf_line_record(line, page_number)
                    if record["text"]:
                        records.append(record)
                    if sum(len(item["text"]) for item in records) > MAX_EXTRACTED_CHARS:
                        raise ValueError("PDF contains too much text.")
    except ValueError:
        raise
    except Exception as e:
        log.warning(f"PDF extraction failed: {e}")
        raise ValueError("Could not read this PDF. Make sure it's not a scanned image — we need text-based PDFs.")

    full_text, layout = _materialize_layout_records(records)
    if not full_text.strip():
        raise ValueError("No text found in PDF. If your resume is a scanned image, please upload a DOCX or text-based PDF instead.")

    return full_text, possible_multi_column_layout, page_count, layout


def _extract_docx(file_bytes: bytes) -> tuple[str, list[dict]]:
    from docx import Document

    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as archive:
            entries = archive.infolist()
            names = {entry.filename for entry in entries}
            if not {"[Content_Types].xml", "word/document.xml"}.issubset(names):
                raise ValueError("File content does not match DOCX format.")
            if any(
                entry.flag_bits & 0x1
                or PurePosixPath(entry.filename).is_absolute()
                or ".." in PurePosixPath(entry.filename).parts
                for entry in entries
            ):
                raise ValueError("DOCX contains unsafe archive entries.")
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

    records: list[dict] = []
    seen_parts: set[int] = set()
    for section in doc.sections:
        if id(section.header.part) not in seen_parts:
            records.extend(_extract_docx_container(section.header, source_kind="header"))
            seen_parts.add(id(section.header.part))
    records.extend(_extract_docx_container(doc))
    for section in doc.sections:
        if id(section.footer.part) not in seen_parts:
            records.extend(_extract_docx_container(section.footer, source_kind="footer"))
            seen_parts.add(id(section.footer.part))

    full_text, layout = _materialize_layout_records(records)
    if not full_text.strip():
        raise ValueError("No text found in DOCX file.")

    if len(full_text) > MAX_EXTRACTED_CHARS:
        raise ValueError("DOCX contains too much text.")
    return full_text, layout


def parse_resume(filename: str, content_type: str, file_bytes: bytes) -> dict:
    """
    Parse an uploaded resume file. Returns full extracted text + metadata.
    No truncation — returns everything.
    """
    file_type = validate_upload(filename, content_type, len(file_bytes))
    if file_type == "pdf" and not file_bytes.startswith(b"%PDF-"):
        raise ValueError("File content does not match PDF format.")
    if file_type == "docx" and not file_bytes.startswith(b"PK\x03\x04"):
        raise ValueError("File content does not match DOCX format.")

    possible_multi_column_layout = False
    page_count = 0
    if file_type in ("pdf",):
        text, possible_multi_column_layout, page_count, layout_blocks = _extract_pdf(file_bytes)
    elif file_type == "docx":
        text, layout_blocks = _extract_docx(file_bytes)
    else:
        raise ValueError(f"Unsupported file type: {file_type}")

    # Basic metadata extraction
    lines = text.split("\n")
    word_count = len(text.split())
    line_count = len([l for l in lines if l.strip()])

    # Try to find email, phone, and name
    email_match = re.search(r'[\w.+-]+@[\w-]+\.[\w.]+', text)

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

    parse_quality = _parse_quality(
        text,
        file_type,
        possible_multi_column_layout=possible_multi_column_layout,
    )
    document_warnings = [
        {
            "code": "extraction_review",
            "severity": "review",
            "message": warning,
            "block_ids": [],
            "section_ids": [],
        }
        for warning in parse_quality.get("warnings", [])
    ]
    document = create_resume_document(
        text,
        source_format=file_type,
        filename=filename,
        source_sha256=hashlib.sha256(file_bytes).hexdigest(),
        warnings=document_warnings,
        layout_blocks=layout_blocks,
    )

    return {
        "text": text,  # FULL text, no truncation
        "document": document,
        "filename": filename,
        "file_type": file_type,
        "word_count": word_count,
        "line_count": line_count,
        "parse_quality": parse_quality,
        "content_warnings": _content_warnings(text),
        "name": name,
        "email": email_match.group() if email_match else None,
        "phone": extract_phone_number(text),
        "page_estimate": page_count or max(1, word_count // 500),
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
