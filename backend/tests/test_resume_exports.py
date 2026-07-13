from resume_templates import _group_export_lines, _parse_sections


def test_export_preserves_skill_labels_and_joins_wrapped_lines():
    text = """CORE SKILLS
Leadership and Delivery: programme management, change management and
adoption, mentoring, stakeholder management
Agentic AI and LLM Engineering: LangGraph, RAG and
text-to-SQL
PROFESSIONAL EXPERIENCE
Associate AI Engineer | AI Singapore Jan 2026 - Present
Selected into a competitive programme delivered with
a three-apprentice engineering team.
• Built a production multi-agent system with four
LangGraph agents behind FastAPI.
• Designed trust guardrails.
"""

    sections = _parse_sections(text)

    assert "activities" not in sections
    assert _group_export_lines(sections["skills"], "skills") == [
        "Leadership and Delivery: programme management, change management and adoption, mentoring, stakeholder management",
        "Agentic AI and LLM Engineering: LangGraph, RAG and text-to-SQL",
    ]
    assert _group_export_lines(sections["experience"], "experience") == [
        "Associate AI Engineer | AI Singapore Jan 2026 - Present",
        "Selected into a competitive programme delivered with a three-apprentice engineering team.",
        "• Built a production multi-agent system with four LangGraph agents behind FastAPI.",
        "• Designed trust guardrails.",
    ]


def test_export_recognises_common_qualified_section_headers():
    sections = _parse_sections(
        """PROJECT EXPERIENCE
• Built an AI prototype.
TECHNICAL SKILLS & TOOLS
Python, SQL
EDUCATION & TRAINING
BEng, Example University
AWARDS & HONORS
Engineering Award
CERTIFICATIONS & LICENSES
PMP
SKILLS & COMPETENCIES
Programme delivery"""
    )

    assert sections["projects"] == "• Built an AI prototype."
    assert sections["skills"] == "Python, SQL\nProgramme delivery"
    assert sections["education"] == "BEng, Example University"
    assert sections["awards"] == "Engineering Award"
    assert sections["certifications"] == "PMP"
