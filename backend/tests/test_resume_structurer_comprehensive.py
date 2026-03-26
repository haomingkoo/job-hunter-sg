"""Comprehensive property-based tests for resume_structurer.structure_resume.

Loads 12 diverse curated resume text fixtures and validates structural
invariants that must hold for every parsed resume.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pathlib

import pytest

from resume_structurer import structure_resume

FIXTURES_DIR = pathlib.Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "resumes_curated"

# Collect all .txt fixture files
_fixture_files = sorted(FIXTURES_DIR.glob("*.txt"))
_fixture_ids = [f.stem for f in _fixture_files]


def _load_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


@pytest.fixture(params=_fixture_files, ids=_fixture_ids)
def resume_result(request: pytest.FixtureRequest) -> dict:
    """Parse a resume fixture and return the structured result."""
    text = request.param.read_text(encoding="utf-8")
    return structure_resume(text)


# ── Contact tests ────────────────────────────────────────────────────────────


def test_returns_contact_dict(resume_result: dict) -> None:
    """Result has contact dict with name, email, phone, location keys."""
    contact = resume_result.get("contact")
    assert isinstance(contact, dict), "contact must be a dict"
    for key in ("name", "email", "phone", "location"):
        assert key in contact, f"contact missing key: {key}"


# ── Sections tests ───────────────────────────────────────────────────────────


def test_returns_sections_list(resume_result: dict) -> None:
    """sections is a list."""
    sections = resume_result.get("sections")
    assert isinstance(sections, list), "sections must be a list"
    assert len(sections) > 0, "sections must not be empty for a real resume"


def test_every_section_has_required_keys(resume_result: dict) -> None:
    """Each section has key, display_name, type."""
    for section in resume_result["sections"]:
        for key in ("key", "display_name", "type"):
            assert key in section, f"section missing key: {key} in {section}"


VALID_SECTION_TYPES = {"text", "entries", "skills"}


def test_section_type_is_valid(resume_result: dict) -> None:
    """type is text, entries, or skills."""
    for section in resume_result["sections"]:
        assert section["type"] in VALID_SECTION_TYPES, (
            f"invalid section type: {section['type']} for section {section['key']}"
        )


def test_entries_have_ids_and_headings(resume_result: dict) -> None:
    """Entry sections have entries with id, heading, bullets."""
    for section in resume_result["sections"]:
        if section["type"] != "entries":
            continue
        entries = section.get("entries", [])
        for entry in entries:
            assert "id" in entry, f"entry missing 'id' in section {section['key']}"
            assert "heading" in entry, f"entry missing 'heading' in section {section['key']}"
            assert "bullets" in entry, f"entry missing 'bullets' in section {section['key']}"


def test_bullets_have_required_keys(resume_result: dict) -> None:
    """Bullets have id, text, has_action_verb, has_metric, word_count, issues."""
    required = {"id", "text", "has_action_verb", "has_metric", "word_count", "issues"}
    for section in resume_result["sections"]:
        if section["type"] != "entries":
            continue
        for entry in section.get("entries", []):
            for bullet in entry.get("bullets", []):
                missing = required - set(bullet.keys())
                assert not missing, (
                    f"bullet missing keys {missing} in entry {entry['id']}"
                )


def test_bullet_ids_unique(resume_result: dict) -> None:
    """No duplicate bullet IDs across the entire resume."""
    ids: list[str] = []
    for section in resume_result["sections"]:
        if section["type"] != "entries":
            continue
        for entry in section.get("entries", []):
            for bullet in entry.get("bullets", []):
                ids.append(bullet["id"])

    assert len(ids) == len(set(ids)), (
        f"duplicate bullet IDs found: {[bid for bid in ids if ids.count(bid) > 1]}"
    )


def test_stats_consistent(resume_result: dict) -> None:
    """stats.total_bullets matches actual count of bullets across all entries."""
    actual_count = 0
    for section in resume_result["sections"]:
        if section["type"] != "entries":
            continue
        for entry in section.get("entries", []):
            actual_count += len(entry.get("bullets", []))

    stats = resume_result.get("stats", {})
    assert stats.get("total_bullets") == actual_count, (
        f"stats.total_bullets={stats.get('total_bullets')} "
        f"but actual count is {actual_count}"
    )


def test_no_empty_section_keys(resume_result: dict) -> None:
    """Heading sections have non-empty keys."""
    for section in resume_result["sections"]:
        assert section["key"], (
            f"section has empty key; display_name={section.get('display_name')}"
        )


def test_experience_section_detected(resume_result: dict) -> None:
    """At least one section has key 'experience'."""
    keys = [s["key"] for s in resume_result["sections"]]
    assert "experience" in keys, (
        f"no 'experience' section found; keys={keys}"
    )


def test_education_section_detected(resume_result: dict) -> None:
    """At least one section has key 'education'."""
    keys = [s["key"] for s in resume_result["sections"]]
    assert "education" in keys, (
        f"no 'education' section found; keys={keys}"
    )


def test_dyson_groups_company_title_and_date_into_one_entry() -> None:
    result = structure_resume(_load_fixture("Haoming_Koo_Dyson_Resume.txt"))
    experience_sections = [section for section in result["sections"] if section["key"] == "experience"]
    assert len(experience_sections) == 1

    entries = experience_sections[0]["entries"]
    manager_entry = next(
        entry for entry in entries if "Manager, Central Engineering" in (entry.get("title") or entry.get("heading") or "")
    )
    assert "Micron Technology" in (manager_entry.get("company") or "")
    assert manager_entry.get("date_range") == "2022 – 2025"


def test_kla_keeps_company_location_with_first_experience_entry() -> None:
    result = structure_resume(_load_fixture("Haoming_Koo_KLA_TPM_Resume.txt"))
    experience = next(section for section in result["sections"] if section["key"] == "experience")
    first_entry = experience["entries"][0]

    assert "Manager, Front End Central Process Integration Engineering" in (first_entry.get("title") or first_entry.get("heading") or "")
    assert "Micron Technology" in (first_entry.get("company") or "")
    assert "Singapore" in (first_entry.get("company") or "")
    assert first_entry.get("date_range") == "2022 –2025"


def test_mondelez_experience_count_stays_near_expected() -> None:
    result = structure_resume(_load_fixture("Haoming_Koo_Mondelez.txt"))
    experience = next(section for section in result["sections"] if section["key"] == "experience")
    assert len(experience["entries"]) == 4


def test_mondelez_education_entries_keep_degree_school_and_dates() -> None:
    result = structure_resume(_load_fixture("Haoming_Koo_Mondelez.txt"))
    education = next(section for section in result["sections"] if section["key"] == "education")
    assert len(education["entries"]) == 2
    assert all(entry.get("degree") for entry in education["entries"])
    assert all(entry.get("institution") for entry in education["entries"])
    assert all(entry.get("date_range") for entry in education["entries"])
