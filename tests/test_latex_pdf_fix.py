"""
Playwright test: verify LaTeX PDF space-stripping fix.

Creates a synthetic PDF where pdfplumber strips spaces (mimicking LaTeX behavior),
uploads it to /api/resume/upload, and asserts that the parsed text has proper spaces.

The fix has two components:
1. _has_missing_spaces(): camelCase merge detection (e.g. 'VikneshJayaKumar')
2. _extract_text_from_chars(): space insertion using char x-positions with a low
   threshold (15% of avg char width) to catch tight LaTeX word spacing (1.5-2pt gaps)

Run:
    /opt/anaconda3/bin/python3 tests/test_latex_pdf_fix.py
"""
from __future__ import annotations

import asyncio
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))


# ---------------------------------------------------------------------------
# Build a test PDF that simulates LaTeX space-stripping:
# - Words positioned with 2pt visual gaps (pdfplumber misses spaces here)
# - No actual space characters in the text stream
# - pdfplumber.extract_text() strips spaces; page.chars has gaps for our fix
# ---------------------------------------------------------------------------


def _make_latex_style_pdf(word_gap: float = 2.0) -> bytes:
    """Create a PDF with individually-positioned words and no space glyphs."""
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    font = "Helvetica"
    size = 12

    def row(words: list[str], y: float) -> None:
        x = 50.0
        c.setFont(font, size)
        for word in words:
            c.drawString(x, y, word)
            x += c.stringWidth(word, font, size) + word_gap

    # Resume-like content
    row(["Viknesh", "Jaya", "Kumar"], 780)
    row(["Data", "Scientist"], 762)
    row(["Singapore"], 744)
    row(["viknesh@example.com"], 726)
    row(["EDUCATION"], 696)
    row(["National", "University", "of", "Singapore"], 678)
    row(["Bachelor", "of", "Science", "in", "Computer", "Science", "2018-2022"], 660)
    row(["WORK", "EXPERIENCE"], 630)
    row(["Senior", "Data", "Scientist", "ABC", "Tech", "Pte", "Ltd", "2022-Present"], 612)
    row(["Lead", "machine", "learning", "initiatives", "across", "product", "teams", "in", "Singapore"], 594)
    row(["Build", "predictive", "models", "using", "Python", "and", "TensorFlow"], 576)

    c.showPage()
    c.save()
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _has_missing_spaces_str(text: str) -> bool:
    """Mirror of the backend function (kept local so test can import independently)."""
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


# ---------------------------------------------------------------------------
# Test 1: Confirm raw extraction strips spaces
# ---------------------------------------------------------------------------


def test_raw_extraction_strips_spaces(pdf_bytes: bytes) -> None:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        raw = pdf.pages[0].extract_text() or ""

    assert "VikneshJayaKumar" in raw, (
        f"Expected space-stripped text in raw extraction, got: {raw[:100]!r}"
    )
    print("  [OK] Raw extraction confirmed space-stripped ('VikneshJayaKumar' present)")


# ---------------------------------------------------------------------------
# Test 2: _has_missing_spaces() detects camelCase merges
# ---------------------------------------------------------------------------


def test_has_missing_spaces_detection(pdf_bytes: bytes) -> None:
    import pdfplumber
    from resume_parser import _has_missing_spaces

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        raw = pdf.pages[0].extract_text() or ""

    print(f"  Raw text sample: {raw[:80]!r}")
    assert _has_missing_spaces(raw), (
        f"_has_missing_spaces() should detect merged words in:\n{raw[:200]!r}"
    )
    print("  [OK] _has_missing_spaces() correctly detected the problem")

    # Sanity: normal text should not trigger
    normal = "Viknesh Jaya Kumar\nData Scientist\nNational University of Singapore"
    assert not _has_missing_spaces(normal), (
        "_has_missing_spaces() incorrectly flagged normal spaced text"
    )
    print("  [OK] _has_missing_spaces() correctly passes normal text")


# ---------------------------------------------------------------------------
# Test 3: _extract_text_from_chars() restores spaces
# ---------------------------------------------------------------------------


def test_char_level_fix_restores_spaces(pdf_bytes: bytes) -> None:
    import pdfplumber
    from resume_parser import _has_missing_spaces, _extract_text_from_chars

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        page = pdf.pages[0]
        fixed = _extract_text_from_chars(page)

    print(f"  Fixed text sample: {fixed[:100]!r}")
    assert not _has_missing_spaces(fixed), (
        f"_extract_text_from_chars() should restore spaces but got:\n{fixed[:300]!r}"
    )
    assert "Viknesh" in fixed and "Jaya" in fixed and "Kumar" in fixed, (
        f"Expected individual name tokens in fixed text, got: {fixed[:100]!r}"
    )
    print("  [OK] _extract_text_from_chars() restored spaces")


# ---------------------------------------------------------------------------
# Test 4: extract_text_from_pdf() end-to-end
# ---------------------------------------------------------------------------


def test_end_to_end_parser(pdf_bytes: bytes) -> None:
    from resume_parser import _has_missing_spaces, extract_text_from_pdf

    full = extract_text_from_pdf(pdf_bytes)
    print(f"  Full parse sample: {full[:120]!r}")
    assert not _has_missing_spaces(full), (
        f"extract_text_from_pdf() should return spaced text, got:\n{full[:300]!r}"
    )
    # Check specific tokens are separated
    for token in ["Viknesh", "Jaya", "Kumar", "Data", "Scientist"]:
        assert token in full, f"Expected token '{token}' in parsed text"
    print("  [OK] extract_text_from_pdf() end-to-end: spaces restored")


# ---------------------------------------------------------------------------
# Test 5: Playwright API test
# ---------------------------------------------------------------------------


async def test_api_upload(pdf_bytes: bytes) -> None:
    """Upload the space-stripped PDF to the live API and verify the response."""
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        request = await pw.request.new_context(base_url="http://localhost:8001")
        try:
            resp = await request.post(
                "/api/resume/upload",
                multipart={
                    "file": {
                        "name": "viknesh_resume.pdf",
                        "mimeType": "application/pdf",
                        "buffer": pdf_bytes,
                    }
                },
            )

            assert resp.ok, (
                f"Upload failed: HTTP {resp.status}\n{await resp.text()}"
            )
            body = await resp.json()
            text: str = body.get("text", "")

            print(f"  API response sample: {text[:120]!r}")

            assert not _has_missing_spaces_str(text), (
                f"API returned space-stripped text — fix not applied on server.\n"
                f"Text: {text[:300]!r}"
            )
            print("  [OK] API returned properly spaced text")

            # Spot-check individual tokens are present and separated
            for token in ["Viknesh", "Jaya", "Kumar"]:
                assert token in text, (
                    f"Token '{token}' missing from API response — may still be merged.\n"
                    f"Text: {text[:200]!r}"
                )
            print("  [OK] Name tokens are individually present in API response")

        finally:
            await request.dispose()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    print("=" * 65)
    print("TEST: LaTeX PDF space-stripping fix")
    print("  Word gap: 2.0pt (below old 35% threshold, above new 15% threshold)")
    print("=" * 65)

    pdf_bytes = _make_latex_style_pdf(word_gap=2.0)

    print("\n[1] Confirm raw extraction strips spaces:")
    test_raw_extraction_strips_spaces(pdf_bytes)

    print("\n[2] Detection: _has_missing_spaces() sees camelCase merges:")
    test_has_missing_spaces_detection(pdf_bytes)

    print("\n[3] Fix: _extract_text_from_chars() restores spaces:")
    test_char_level_fix_restores_spaces(pdf_bytes)

    print("\n[4] End-to-end: extract_text_from_pdf():")
    test_end_to_end_parser(pdf_bytes)

    print("\n[5] Playwright: live API upload and parse:")
    asyncio.run(test_api_upload(pdf_bytes))

    print("\n" + "=" * 65)
    print("ALL TESTS PASSED")
    print("=" * 65)


if __name__ == "__main__":
    main()
