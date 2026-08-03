from __future__ import annotations

import pytest

from resume_document import (
    ResumePatchError,
    StaleResumeRevision,
    apply_resume_patch,
    confirm_resume_heading,
    create_resume_document,
    is_resume_document,
)


SAMPLE = """Jane Doe

EXPERIENCE
Acme | Engineer | 2022 - Present
- Built the reporting platform
- Built the reporting platform

SELECTED TALKS AND COMMUNITY
Speaker at PyCon Singapore
"""


def test_document_assigns_distinct_stable_ids_to_duplicate_bullets():
    first = create_resume_document(SAMPLE, source_format="text")
    second = create_resume_document(SAMPLE, source_format="text")

    first_bullets = [block for block in first["blocks"] if block["kind"] == "bullet"]
    second_bullets = [block for block in second["blocks"] if block["kind"] == "bullet"]

    assert [block["id"] for block in first_bullets] == [
        block["id"] for block in second_bullets
    ]
    assert len({block["id"] for block in first_bullets}) == 2
    assert all(block["text"] == "Built the reporting platform" for block in first_bullets)


def test_text_adapter_preserves_unknown_heading_as_confirmation_candidate():
    document = create_resume_document(SAMPLE, source_format="text")

    candidate = next(
        item
        for item in document["heading_candidates"]
        if item["label"] == "SELECTED TALKS AND COMMUNITY"
    )

    block = next(item for item in document["blocks"] if item["id"] == candidate["block_id"])
    assert block["classification"] == "candidate_heading"
    assert all(section["label"] != candidate["label"] for section in document["sections"])
    assert "Speaker at PyCon Singapore" in document["raw_text"]


def test_layout_evidence_distinguishes_custom_and_nested_headings():
    text = """EXPERIENCE
Micron Technology
Additional Projects
Built a local dashboard.
PATENTS & INVENTIONS
Filed a process-control patent.
"""
    lines = text.splitlines()
    layout = []
    cursor = 0
    for index, line in enumerate(lines):
        start = text.index(line, cursor)
        end = start + len(line)
        cursor = end
        layout.append({
            "text": line,
            "raw_span": [start, end],
            "page": 1,
            "indentation": 24 if line == "Additional Projects" else 0,
            "x_position": 24 if line == "Additional Projects" else 0,
            "heading_emphasis": line in {"EXPERIENCE", "Additional Projects", "PATENTS & INVENTIONS"},
            "font_size": 11 if line == "Additional Projects" else 14 if line in {"EXPERIENCE", "PATENTS & INVENTIONS"} else 10,
            "heading_level": None,
            "style_name": None,
        })

    document = create_resume_document(text, layout_blocks=layout)

    assert [section["label"] for section in document["sections"]] == [
        "EXPERIENCE",
        "PATENTS & INVENTIONS",
    ]
    assert document["sections"][1]["classification"] == "custom_section"
    nested = next(item for item in document["blocks"] if item["text"] == "Additional Projects")
    assert nested["classification"] == "candidate_heading"
    assert nested["section_key"] == "experience"


def test_confirming_candidate_updates_boundaries_without_changing_raw_text():
    document = create_resume_document(SAMPLE)
    candidate = document["heading_candidates"][0]

    updated = confirm_resume_heading(
        document,
        block_id_value=candidate["block_id"],
        expected_revision=document["revision"],
    )

    assert updated["raw_text"] == document["raw_text"]
    assert updated["revision"] != document["revision"]
    assert updated["sections"][-1]["label"] == "SELECTED TALKS AND COMMUNITY"
    assert updated["sections"][-1]["classification"] == "custom_section"
    assert updated["decisions"] == [{
        "type": "confirm_heading",
        "block_id": candidate["block_id"],
        "section_key": None,
    }]
    assert is_resume_document(updated)


def test_document_does_not_promote_uppercase_contact_name_to_section():
    document = create_resume_document(
        "HUI SHAN ANG\nhui@example.com\n\nPROFESSIONAL SUMMARY\nFinance transformation leader"
    )

    assert [section["label"] for section in document["sections"]] == [
        "PROFESSIONAL SUMMARY"
    ]


def test_patch_targets_one_duplicate_and_rejects_stale_revision():
    document = create_resume_document(SAMPLE, source_format="text")
    bullets = [block for block in document["blocks"] if block["kind"] == "bullet"]
    patch = {
        "block_id": bullets[1]["id"],
        "expected_revision": document["revision"],
        "expected_text": bullets[1]["text"],
        "text": "Improved the reporting platform",
    }

    updated = apply_resume_patch(document, patch)

    assert updated["raw_text"].count("Built the reporting platform") == 1
    assert updated["raw_text"].count("Improved the reporting platform") == 1
    assert updated["blocks"][bullets[0]["order"]]["text"] == bullets[0]["text"]
    assert updated["blocks"][bullets[1]["order"]]["id"] == bullets[1]["id"]
    with pytest.raises(StaleResumeRevision):
        apply_resume_patch(updated, patch)


def test_patch_rejects_new_numeric_claims():
    document = create_resume_document(SAMPLE, source_format="text")
    bullet = next(block for block in document["blocks"] if block["kind"] == "bullet")

    with pytest.raises(ResumePatchError, match="Unsupported numeric facts"):
        apply_resume_patch(
            document,
            {
                "block_id": bullet["id"],
                "expected_revision": document["revision"],
                "expected_text": bullet["text"],
                "text": "Built the reporting platform for 500 users",
            },
        )


def test_wrapped_bullet_is_one_addressable_block():
    text = """EXPERIENCE
Acme | Engineer | 2022 - Present
• Built a reporting platform used by finance
  teams across the company
"""

    document = create_resume_document(text, source_format="text")
    bullets = [block for block in document["blocks"] if block["kind"] == "bullet"]

    assert len(bullets) == 1
    assert bullets[0]["text"] == "Built a reporting platform used by finance teams across the company"
    assert "\n" in bullets[0]["source_text"]


def test_role_header_with_separate_date_is_not_absorbed_by_previous_bullet():
    text = """PROFESSIONAL EXPERIENCE
Analyst | Acme Pte Ltd
Jan 2020 - Dec 2022
• Built the reporting workflow.
Operations Lead | Northstar Pte Ltd
Jan 2023 - Present
• Led the finance transformation.
"""

    document = create_resume_document(text)
    bullets = [block for block in document["blocks"] if block["kind"] == "bullet"]

    assert [block["text"] for block in bullets] == [
        "Built the reporting workflow.",
        "Led the finance transformation.",
    ]
    assert all("Operations Lead" not in block["text"] for block in bullets)
    assert any(
        block["text"] == "Operations Lead | Northstar Pte Ltd"
        for block in document["blocks"]
    )


def test_wrapped_summary_skills_and_role_description_are_logical_blocks():
    text = """HUI SHAN ANG
hui@example.com

PROFESSIONAL SUMMARY
AI leader delivering production systems across
regional operations and engineering teams.

CORE SKILLS
Agentic AI: LangGraph, evaluation, guardrails and
human-in-the-loop workflows

PROFESSIONAL EXPERIENCE
AI Engineer | Example Pte Ltd | Jan 2024 - Present
Selected to build a platform used across three
regional teams, with evidence-backed reporting.
"""

    document = create_resume_document(text)
    texts = [block["text"] for block in document["blocks"]]

    assert "AI leader delivering production systems across regional operations and engineering teams." in texts
    assert "Agentic AI: LangGraph, evaluation, guardrails and human-in-the-loop workflows" in texts
    assert "Selected to build a platform used across three regional teams, with evidence-backed reporting." in texts
    assert "AI Engineer | Example Pte Ltd | Jan 2024 - Present" in texts


def test_wrapped_hyphenated_bullet_keeps_one_word_and_one_source_span():
    text = """EXPERIENCE
• Scaled AI-
  based detection across the fab.
"""

    document = create_resume_document(text)
    bullet = next(block for block in document["blocks"] if block["kind"] == "bullet")

    assert bullet["text"] == "Scaled AI-based detection across the fab."
    assert "AI-\n" in bullet["source_text"]


def test_preview_scorer_tailoring_and_agent_share_section_keys_and_bullet_ids():
    from resume_agent.session import _resume_bullet_maps
    from resume_scorer import ResumeScorer
    from resume_structurer import get_all_bullets, structure_resume

    text = """EXPERIENCE
Engineering Manager | Example | 2022 - Present
- Built a reporting platform used across eight markets.
PROJECTS
- Created an evidence review dashboard.
"""
    document = create_resume_document(text)
    preview_bullets = [block for block in document["blocks"] if block["kind"] == "bullet"]
    structured_bullets = get_all_bullets(structure_resume(text))
    scorer = ResumeScorer().analyze(text, resume_document=document)
    agent_text_by_id, _ = _resume_bullet_maps(text, document)

    expected = [(block["id"], block["section_key"]) for block in preview_bullets]
    assert [(bullet["id"], bullet["section_key"]) for bullet in structured_bullets] == expected
    assert [
        (bullet["id"], bullet["section_key"])
        for bullet in scorer["resume_evidence"]["bullets"]
    ] == expected
    assert list(agent_text_by_id) == [block["id"] for block in preview_bullets]
