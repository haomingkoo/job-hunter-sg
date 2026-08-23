from __future__ import annotations

import config
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from recruitment_team.open_agent.subagents import create_target_persona_subagents
from recruitment_team.persona_packs import load_persona_pack_registry


def test_target_persona_graphs_have_an_explicit_independent_budget():
    model = FakeMessagesListChatModel(responses=[AIMessage(content="done")])

    subagents = create_target_persona_subagents(load_persona_pack_registry(), model)

    assert subagents
    assert all("runnable" in subagent for subagent in subagents)
    assert {
        subagent["runnable"].config.get("recursion_limit")
        for subagent in subagents
    } == {config.TARGET_SPECIALIST_MAX_TOOL_ITERATIONS}


def test_target_persona_prompt_explains_atomic_gap_citations():
    from recruitment_team.open_agent.subagents import target_persona_spec

    registry = load_persona_pack_registry()
    spec = target_persona_spec(
        registry.pack("recruiter"),
        str(registry.output_schema["score_meaning"]),
        object(),
    )

    assert "classify it as evidence_gap" in spec["system_prompt"]
    assert "leave both candidate citation lists empty" in spec["system_prompt"]
