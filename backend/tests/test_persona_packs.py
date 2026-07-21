from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from resume_agent.contracts import TARGET_JOB_PERSONAS
from recruitment_team.persona_packs import _parse_registry, load_persona_pack_registry


def _payload() -> dict:
    path = Path(__file__).parents[1] / "recruitment_team" / "persona_packs" / "v1" / "personas.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_persona_registry_is_versioned_cited_complete_and_bounded():
    registry = load_persona_pack_registry("v1")

    assert registry.pack_version == "recruitment-personas-v1"
    assert registry.jurisdiction == "Singapore"
    assert tuple(pack.persona_id for pack in registry.personas) == TARGET_JOB_PERSONAS
    assert len(registry.sources) == 3
    assert all(source.url.startswith("https://") for source in registry.sources)
    assert {source.publisher for source in registry.sources} == {
        "Tripartite Alliance for Fair and Progressive Employment Practices",
        "LinkedIn Talent Solutions",
    }
    for pack in registry.personas:
        assert pack.criteria
        assert pack.examples
        assert pack.counterexamples
        assert pack.source_ids
        assert pack.limitations
        assert pack.labelled_fixtures
        assert all(fixture.expected_label for fixture in pack.labelled_fixtures)


def test_persona_registry_exposes_score_and_field_level_provenance_contract():
    registry = load_persona_pack_registry("v1")

    assert "candidate_profile_field_ids" in registry.output_schema["required"]
    assert "resume_evidence_ids" in registry.output_schema["required"]
    assert "strengths" in registry.output_schema["required"]
    assert "weaknesses" in registry.output_schema["required"]
    assert "score" in registry.output_schema["required"]
    assert "score_reason" in registry.output_schema["required"]
    assert "hiring probability" in registry.output_schema["score_meaning"]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda payload: payload["personas"].pop(),
            "bounded reviewer contract",
        ),
        (
            lambda payload: payload["personas"][0].update(source_ids=["unknown"]),
            "unknown source ID",
        ),
        (
            lambda payload: payload["personas"][0].update(criteria=[]),
            "criteria must contain",
        ),
        (
            lambda payload: payload["sources"][0].update(url="http://example.test"),
            "HTTPS URLs",
        ),
        (
            lambda payload: payload.update(pack_version="recruitment-personas-v2"),
            "identity does not match",
        ),
    ],
)
def test_persona_registry_rejects_incomplete_or_untraceable_packs(mutate, message):
    payload = deepcopy(_payload())
    mutate(payload)

    with pytest.raises(ValueError, match=message):
        _parse_registry(payload, "v1")


def test_persona_registry_rejects_hidden_or_undocumented_version_names():
    with pytest.raises(ValueError, match="v<positive integer>"):
        load_persona_pack_registry("latest")
