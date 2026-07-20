"""Versioned, cited recruiting-persona packs loaded outside orchestration code."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import config
from resume_agent.contracts import TARGET_JOB_PERSONAS


_PACK_ROOT = Path(__file__).with_name("persona_packs")
_VERSION_RE = re.compile(r"v[1-9][0-9]*\Z")


@dataclass(frozen=True)
class PersonaSource:
    source_id: str
    title: str
    url: str
    publisher: str
    publication_date: str | None
    accessed_date: str
    supports: str


@dataclass(frozen=True)
class PersonaFixture:
    fixture_id: str
    input_pattern: str
    expected_label: str


@dataclass(frozen=True)
class PersonaPack:
    persona_id: str
    display_name: str
    purpose: str
    job_scope: str
    criteria: tuple[str, ...]
    examples: tuple[str, ...]
    counterexamples: tuple[str, ...]
    source_ids: tuple[str, ...]
    limitations: tuple[str, ...]
    labelled_fixtures: tuple[PersonaFixture, ...]


@dataclass(frozen=True)
class PersonaPackRegistry:
    pack_version: str
    jurisdiction: str
    sources: tuple[PersonaSource, ...]
    output_schema: dict
    personas: tuple[PersonaPack, ...]

    def pack(self, persona_id: str) -> PersonaPack:
        matches = [pack for pack in self.personas if pack.persona_id == persona_id]
        if len(matches) != 1:
            raise KeyError(persona_id)
        return matches[0]


def _nonempty_strings(value, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item.strip() for item in value):
        raise ValueError(f"{field_name} must contain non-empty strings")
    return tuple(item.strip() for item in value)


def _required_text(item: dict, field_name: str) -> str:
    value = item.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    return value.strip()


def _parse_registry(payload: dict, version: str) -> PersonaPackRegistry:
    if not _VERSION_RE.fullmatch(version):
        raise ValueError("Recruitment persona pack version must use v<positive integer>")
    if payload.get("pack_version") != f"recruitment-personas-{version}":
        raise ValueError("Recruitment persona pack identity does not match its configured version")
    jurisdiction = str(payload.get("jurisdiction") or "").strip()
    if not jurisdiction:
        raise ValueError("Recruitment persona pack jurisdiction is required")

    sources = tuple(
        PersonaSource(
            source_id=_required_text(item, "source_id"),
            title=_required_text(item, "title"),
            url=_required_text(item, "url"),
            publisher=_required_text(item, "publisher"),
            publication_date=(str(item["publication_date"]).strip() if item.get("publication_date") else None),
            accessed_date=_required_text(item, "accessed_date"),
            supports=_required_text(item, "supports"),
        )
        for item in payload.get("sources") or []
    )
    source_ids = [source.source_id for source in sources]
    if not sources or len(source_ids) != len(set(source_ids)):
        raise ValueError("Recruitment persona source IDs must be present and unique")
    if any(not source.url.startswith("https://") for source in sources):
        raise ValueError("Recruitment persona sources must use HTTPS URLs")

    personas = []
    for item in payload.get("personas") or []:
        fixtures = tuple(
            PersonaFixture(
                fixture_id=_required_text(fixture, "fixture_id"),
                input_pattern=_required_text(fixture, "input_pattern"),
                expected_label=_required_text(fixture, "expected_label"),
            )
            for fixture in item.get("labelled_fixtures") or []
        )
        fixture_ids = [fixture.fixture_id for fixture in fixtures]
        if not fixtures or len(fixture_ids) != len(set(fixture_ids)):
            raise ValueError("Each persona must have unique labelled fixture IDs")
        pack_source_ids = _nonempty_strings(item.get("source_ids"), "source_ids")
        if any(source_id not in source_ids for source_id in pack_source_ids):
            raise ValueError("Persona references an unknown source ID")
        personas.append(
            PersonaPack(
                persona_id=_required_text(item, "persona_id"),
                display_name=_required_text(item, "display_name"),
                purpose=_required_text(item, "purpose"),
                job_scope=_required_text(item, "job_scope"),
                criteria=_nonempty_strings(item.get("criteria"), "criteria"),
                examples=_nonempty_strings(item.get("examples"), "examples"),
                counterexamples=_nonempty_strings(
                    item.get("counterexamples"),
                    "counterexamples",
                ),
                source_ids=pack_source_ids,
                limitations=_nonempty_strings(item.get("limitations"), "limitations"),
                labelled_fixtures=fixtures,
            )
        )
    persona_ids = [pack.persona_id for pack in personas]
    if tuple(persona_ids) != TARGET_JOB_PERSONAS:
        raise ValueError("Recruitment persona packs must match the bounded reviewer contract")

    output_schema = payload.get("output_schema")
    if not isinstance(output_schema, dict):
        raise ValueError("Recruitment persona output schema is required")
    required = _nonempty_strings(output_schema.get("required"), "output_schema.required")
    if "score_reason" not in required or "candidate_profile_field_ids" not in required:
        raise ValueError("Recruitment persona output schema lacks evidence and score fields")
    if not str(output_schema.get("score_meaning") or "").strip():
        raise ValueError("Recruitment persona score meaning is required")

    return PersonaPackRegistry(
        pack_version=str(payload["pack_version"]),
        jurisdiction=jurisdiction,
        sources=sources,
        output_schema={**output_schema, "required": list(required)},
        personas=tuple(personas),
    )


def load_persona_pack_registry(version: str | None = None) -> PersonaPackRegistry:
    selected_version = version or config.RECRUITMENT_PERSONA_PACK_VERSION
    if not _VERSION_RE.fullmatch(selected_version):
        raise ValueError("Recruitment persona pack version must use v<positive integer>")
    path = _PACK_ROOT / selected_version / "personas.json"
    if not path.is_file():
        raise FileNotFoundError(f"Recruitment persona pack not found: {selected_version}")
    return _parse_registry(json.loads(path.read_text(encoding="utf-8")), selected_version)
