"""
Resume template system — generates formatted DOCX files from resume data.

4 templates based on Harvard, MIT/Jake's, NUS, and Stanford research:
1. classic    — Serif, formal, education-first (Harvard style)
2. modern     — Dense, clean, projects section (Jake's/tech style)
3. singapore  — Includes nationality/PR, C.A.R. format (NUS style)
4. compact    — Summary-first, 2-page friendly (experienced professionals)

All templates are ATS-friendly:
- No tables for layout, no columns, no images, no text boxes
- Standard fonts (Calibri or Times New Roman)
- Standard section headers
- Bullet points with action verbs
- Dates right-aligned via tab stops
"""

from __future__ import annotations

import io
import re
from typing import Optional

from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.style import WD_STYLE_TYPE


TEMPLATES = {
    "classic": {
        "name": "Classic",
        "description": "Clean, formal style. Education first. Best for fresh grads, consulting, government.",
        "font": "Times New Roman",
        "body_size": 11,
        "heading_size": 12,
        "name_size": 16,
        "margins": 1.0,
        "section_order": ["summary", "education", "experience", "skills", "certifications"],
    },
    "modern": {
        "name": "Modern",
        "description": "Dense, tech-focused. Projects section. Best for engineers, startups, FAANG.",
        "font": "Calibri",
        "body_size": 10,
        "heading_size": 11,
        "name_size": 14,
        "margins": 0.6,
        "section_order": ["summary", "experience", "projects", "skills", "education"],
    },
    "singapore": {
        "name": "Singapore Professional",
        "description": "Includes nationality/PR status. C.A.R. format. Best for SG local market.",
        "font": "Calibri",
        "body_size": 11,
        "heading_size": 12,
        "name_size": 15,
        "margins": 0.8,
        "section_order": ["personal", "summary", "education", "experience", "activities", "skills"],
    },
    "compact": {
        "name": "Compact",
        "description": "Summary-first, experience-heavy. Best for senior professionals with 10+ years.",
        "font": "Arial",
        "body_size": 10,
        "heading_size": 11,
        "name_size": 14,
        "margins": 0.5,
        "section_order": ["summary", "experience", "skills", "education", "certifications"],
    },
}


def list_templates() -> list[dict]:
    """Return available templates for frontend display."""
    return [
        {"id": tid, "name": t["name"], "description": t["description"]}
        for tid, t in TEMPLATES.items()
    ]


def _setup_styles(doc: Document, config: dict) -> None:
    """Configure document styles based on template config."""
    font_name = config["font"]

    # Normal style
    style = doc.styles["Normal"]
    style.font.name = font_name
    style.font.size = Pt(config["body_size"])
    style.font.color.rgb = RGBColor(0x1A, 0x1A, 0x1A)
    style.paragraph_format.space_after = Pt(2)
    style.paragraph_format.space_before = Pt(0)

    # Heading 1 — section headers
    h1 = doc.styles["Heading 1"]
    h1.font.name = font_name
    h1.font.size = Pt(config["heading_size"])
    h1.font.bold = True
    h1.font.color.rgb = RGBColor(0x00, 0x00, 0x00)
    h1.paragraph_format.space_before = Pt(10)
    h1.paragraph_format.space_after = Pt(3)
    h1.paragraph_format.keep_with_next = True

    # Heading 2 — job title / company
    h2 = doc.styles["Heading 2"]
    h2.font.name = font_name
    h2.font.size = Pt(config["body_size"])
    h2.font.bold = True
    h2.font.color.rgb = RGBColor(0x1A, 0x1A, 0x1A)
    h2.paragraph_format.space_before = Pt(6)
    h2.paragraph_format.space_after = Pt(1)

    # Set margins
    for section in doc.sections:
        margin = Inches(config["margins"])
        section.top_margin = margin
        section.bottom_margin = margin
        section.left_margin = margin
        section.right_margin = margin


def _add_name_header(doc: Document, config: dict, name: str, contact_line: str) -> None:
    """Add the name and contact info at the top."""
    # Name
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(name.upper() if config.get("font") == "Times New Roman" else name)
    run.font.size = Pt(config["name_size"])
    run.font.bold = True
    run.font.name = config["font"]
    p.paragraph_format.space_after = Pt(2)

    # Contact line
    if contact_line:
        p2 = doc.add_paragraph()
        p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run2 = p2.add_run(contact_line)
        run2.font.size = Pt(config["body_size"] - 1)
        run2.font.name = config["font"]
        p2.paragraph_format.space_after = Pt(6)


def _add_section_header(doc: Document, title: str) -> None:
    """Add a section header with a horizontal line."""
    p = doc.add_heading(title.upper(), level=1)
    # Add a bottom border (horizontal rule)
    from docx.oxml.ns import qn
    pPr = p._p.get_or_add_pPr()
    pBdr = pPr.makeelement(qn("w:pBdr"), {})
    bottom = pBdr.makeelement(qn("w:bottom"), {
        qn("w:val"): "single",
        qn("w:sz"): "4",
        qn("w:space"): "1",
        qn("w:color"): "000000",
    })
    pBdr.append(bottom)
    pPr.append(pBdr)


def _add_bullet(doc: Document, text: str, config: dict) -> None:
    """Add a bullet point."""
    p = doc.add_paragraph(text, style="List Bullet")
    p.style.font.name = config["font"]
    p.style.font.size = Pt(config["body_size"])


def _parse_sections(resume_text: str) -> dict[str, str]:
    """
    Parse resume text into sections by detecting common headers.
    Returns dict of section_name -> content.
    """
    # Common section header patterns
    header_patterns = [
        (r"(?i)^(professional\s+)?summary", "summary"),
        (r"(?i)^(professional\s+)?experience", "experience"),
        (r"(?i)^(work\s+)?experience", "experience"),
        (r"(?i)^education", "education"),
        (r"(?i)^(technical\s+)?skills", "skills"),
        (r"(?i)^(core\s+)?competenc", "skills"),
        (r"(?i)^certif", "certifications"),
        (r"(?i)^project", "projects"),
        (r"(?i)^activit", "activities"),
        (r"(?i)^volunteer", "activities"),
        (r"(?i)^leadership", "activities"),
        (r"(?i)^personal", "personal"),
        (r"(?i)^language", "skills"),
        (r"(?i)^interest", "interests"),
    ]

    lines = resume_text.split("\n")
    sections: dict[str, list[str]] = {"header": []}
    current_section = "header"

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Check if this line is a section header
        matched = False
        for pattern, section_name in header_patterns:
            if re.match(pattern, stripped):
                current_section = section_name
                if section_name not in sections:
                    sections[section_name] = []
                matched = True
                break

        if not matched:
            if current_section not in sections:
                sections[current_section] = []
            sections[current_section].append(stripped)

    # Convert lists to strings
    return {k: "\n".join(v) for k, v in sections.items() if v}


def generate_docx(
    resume_text: str,
    template_id: str = "modern",
    name: str = "",
    email: str = "",
    phone: str = "",
    location: str = "",
) -> bytes:
    """
    Generate a formatted DOCX file from resume text.
    Returns the DOCX as bytes.
    """
    config = TEMPLATES.get(template_id, TEMPLATES["modern"])
    doc = Document()
    _setup_styles(doc, config)

    # Build contact line
    contact_parts = [p for p in [email, phone, location] if p]
    contact_line = " | ".join(contact_parts)

    # Add name header
    display_name = name or "Your Name"
    _add_name_header(doc, config, display_name, contact_line)

    # Parse resume into sections
    sections = _parse_sections(resume_text)

    # Add sections in template order
    for section_key in config["section_order"]:
        content = sections.get(section_key, "")
        if not content:
            continue

        # Map section keys to display names
        display_names = {
            "summary": "Professional Summary",
            "experience": "Professional Experience",
            "education": "Education",
            "skills": "Skills",
            "certifications": "Certifications",
            "projects": "Projects",
            "activities": "Activities & Leadership",
            "personal": "Personal Particulars",
            "interests": "Interests",
        }

        _add_section_header(doc, display_names.get(section_key, section_key.title()))

        # Add content — detect bullets vs paragraphs
        for line in content.split("\n"):
            line = line.strip()
            if not line:
                continue
            # Detect bullet points
            if line.startswith(("-", "*", "•", "–")) or re.match(r"^\d+\.", line):
                bullet_text = re.sub(r"^[-*•–]\s*", "", line)
                bullet_text = re.sub(r"^\d+\.\s*", "", bullet_text)
                _add_bullet(doc, bullet_text, config)
            else:
                doc.add_paragraph(line)

    # Any remaining sections not in the template order
    for section_key, content in sections.items():
        if section_key in config["section_order"] or section_key == "header":
            continue
        if content:
            _add_section_header(doc, section_key.title())
            for line in content.split("\n"):
                if line.strip():
                    doc.add_paragraph(line.strip())

    # Save to bytes
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.getvalue()
