from __future__ import annotations

import pytest

from resume_document import (
    ResumePatchError,
    StaleResumeRevision,
    apply_resume_patch,
    create_resume_document,
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


def test_document_preserves_custom_heading_as_candidate_section():
    document = create_resume_document(SAMPLE, source_format="text")

    custom = next(
        section
        for section in document["sections"]
        if section["label"] == "SELECTED TALKS AND COMMUNITY"
    )

    assert custom["key"] is None
    assert custom["status"] == "candidate"
    assert "Speaker at PyCon Singapore" in document["raw_text"]


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
