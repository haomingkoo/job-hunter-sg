import io
import sys
from pathlib import Path

from docx import Document


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from resume_templates import generate_docx, inspect_resume_export, list_templates


SAMPLE_RESUME = """
Haoming Koo
haoming@example.com | Singapore

Professional Summary
Transformation leader with experience across AI, cloud, operations, and stakeholder delivery.

Core Competencies
Program Management | AI Transformation | Python | SQL | AWS | Change Management

Professional Experience
Example Company - Singapore
Program Manager | Jan 2022 - Present
• Led cross-functional delivery across engineering, data, and operations teams.
• Reduced deployment time by 40% through workflow automation.

Education
M.Sc., Smart Industries & Digital Transformation — National University of Singapore (2022)

Certifications
Full Stack Development with AI (NUS x Emeritus, 2025)
GA100 – Generative AI (Heicoders Academy, WSQ Accredited, 2025)
PMP (in progress, expected 2025)
""".strip()


def test_all_templates_are_listed_with_metadata():
    templates = list_templates()
    ids = [template["id"] for template in templates]
    assert ids == [
        "classic",
        "modern",
        "singapore",
        "compact",
        "executive",
        "creative",
        "technical",
        "minimal",
    ]
    assert all(template["section_order"] for template in templates)


def test_each_template_generates_readable_docx():
    for template in list_templates():
        template_id = template["id"]
        diagnostics = inspect_resume_export(SAMPLE_RESUME, template_id)
        assert diagnostics["looks_header_only"] is False
        assert "summary" in diagnostics["sections_found"]
        assert "experience" in diagnostics["sections_found"]

        docx_bytes = generate_docx(SAMPLE_RESUME, template_id=template_id)
        assert len(docx_bytes) > 10_000
        doc = Document(io.BytesIO(docx_bytes))
        document_text = "\n".join(paragraph.text for paragraph in doc.paragraphs)
        assert "professional summary" in document_text.lower()
        assert "Full Stack Development with AI" in document_text
        assert "PMP (in progress, expected 2025)" in document_text
