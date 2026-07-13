from __future__ import annotations

import io
from pathlib import Path
import sys
import time

import pytest


PDF_TYPE = "application/pdf"
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def test_isolated_parser_returns_normal_pdf_result():
    from resume_parser import parse_resume_isolated

    path = Path(__file__).parents[1] / "templates/nus/NUS Guidelines.pdf"
    result = parse_resume_isolated(path.name, PDF_TYPE, path.read_bytes())

    assert result["file_type"] == "pdf"
    assert result["text"]


def test_isolated_parser_returns_normal_docx_result():
    from docx import Document
    from resume_parser import parse_resume_isolated

    document = Document()
    document.add_paragraph("Jane Doe")
    document.add_paragraph("jane@example.com")
    document.add_paragraph("EXPERIENCE")
    document.add_paragraph("Software Engineer at Example")
    buffer = io.BytesIO()
    document.save(buffer)

    result = parse_resume_isolated("resume.docx", DOCX_TYPE, buffer.getvalue())

    assert result["file_type"] == "docx"
    assert result["name"] == "Jane Doe"


@pytest.mark.parametrize(
    ("path", "content_type"),
    [
        (Path("/tmp/jobhunter-redteam-flate-bomb.pdf"), PDF_TYPE),
        (Path("/tmp/jobhunter-redteam-docx-dom-bomb.docx"), DOCX_TYPE),
    ],
)
def test_redteam_parser_bombs_are_rejected_without_growing_parent(path: Path, content_type: str):
    if not path.exists():
        pytest.skip("local red-team repro is not present")

    import resource
    from resume_parser import parse_resume_isolated

    rss_unit = 1 if sys.platform == "darwin" else 1024
    before_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * rss_unit
    started = time.monotonic()

    with pytest.raises(ValueError):
        parse_resume_isolated(path.name, content_type, path.read_bytes())

    elapsed = time.monotonic() - started
    after_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * rss_unit
    assert elapsed < 10
    assert after_rss - before_rss < 32 * 1024 * 1024
