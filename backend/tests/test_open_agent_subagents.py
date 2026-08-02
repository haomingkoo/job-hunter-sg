from __future__ import annotations

from recruitment_team.assessment_contracts import SPECIALIST_TOOL
from recruitment_team.open_agent.subagents import create_target_persona_subagents
from recruitment_team.persona_packs import load_persona_pack_registry


def test_creates_one_subagent_per_persona_pack_entry():
    registry = load_persona_pack_registry()
    subagents = create_target_persona_subagents(registry, model=object())

    assert len(subagents) == len(registry.personas)
    assert {sub["name"] for sub in subagents} == {pack.persona_id for pack in registry.personas}


def test_each_subagent_has_exactly_its_own_submission_tool():
    registry = load_persona_pack_registry()
    subagents = create_target_persona_subagents(registry, model=object())

    for sub in subagents:
        assert [t.name for t in sub["tools"]] == [SPECIALIST_TOOL.name]


def test_system_prompt_embeds_the_pack_s_job_scope_and_criteria():
    registry = load_persona_pack_registry()
    subagents = create_target_persona_subagents(registry, model=object())
    recruiter_pack = registry.pack("recruiter")
    recruiter_subagent = next(sub for sub in subagents if sub["name"] == "recruiter")

    assert recruiter_pack.job_scope in recruiter_subagent["system_prompt"]
    assert recruiter_pack.criteria[0] in recruiter_subagent["system_prompt"]
    assert recruiter_pack.limitations[0] in recruiter_subagent["system_prompt"]
    assert registry.output_schema["score_meaning"] in recruiter_subagent["system_prompt"]
    assert "untrusted reference data" in recruiter_subagent["system_prompt"].lower()
