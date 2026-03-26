"""Extract text from curated resume PDFs and save as .txt fixtures.

Uses pdfplumber to extract text from 12 diverse resume PDFs and writes
them to tests/fixtures/resumes_curated/ for use in automated testing.
"""

from __future__ import annotations

import pathlib

import pdfplumber

RESUMES_DIR = pathlib.Path("/Users/koohaoming/Documents/Resumes")
OUTPUT_DIR = pathlib.Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "resumes_curated"

PDF_FILES: list[str] = [
    "Haoming_Koo_Dyson_Resume.pdf",
    "Haoming_Koo_Generic_Resume.pdf",
    "Haoming_Koo_Govt_Resume.pdf",
    "Haoming_Koo_Emerald.pdf",
    "Haoming_Koo_Mondelez.pdf",
    "Haoming_Koo_KLA_TPM_Resume.pdf",
    "Haoming_Koo_Apple_BusinessProcessReengineeringManager_Resume.pdf",
    "Haoming_Koo_TikTok_DataProductManager_Resume.pdf",
    "Haoming_Koo_DBS_VP_DataScientist_Chapter_Resume.pdf",
    "Haoming_Koo_CAG_CommercialStrategyAnalytics_Resume.pdf",
    "Haoming_Koo_HTX_LeadEngineer_Resume.pdf",
    "Haoming_Koo_CapGemini_ProgramManager_328506_Resume.pdf",
]


def extract_text_from_pdf(pdf_path: pathlib.Path) -> str:
    """Extract all text from a PDF using pdfplumber."""
    pages: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
    return "\n".join(pages)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for pdf_name in PDF_FILES:
        pdf_path = RESUMES_DIR / pdf_name
        if not pdf_path.exists():
            print(f"SKIP (not found): {pdf_path}")
            continue

        text = extract_text_from_pdf(pdf_path)
        txt_name = pdf_path.stem + ".txt"
        out_path = OUTPUT_DIR / txt_name

        out_path.write_text(text, encoding="utf-8")
        print(f"OK: {txt_name} ({len(text)} chars, {text.count(chr(10))+1} lines)")

    print(f"\nFixtures saved to: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
