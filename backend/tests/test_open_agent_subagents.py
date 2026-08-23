from __future__ import annotations

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage

from recruitment_team.assessment_contracts import SPECIALIST_TOOL
from recruitment_team.open_agent.subagents import (
    create_target_persona_subagents,
    target_persona_spec,
)
from recruitment_team.open_agent.context import assessment_context
from recruitment_team.persona_packs import load_persona_pack_registry


def test_creates_one_subagent_per_persona_pack_entry():
    registry = load_persona_pack_registry()
    model = FakeMessagesListChatModel(responses=[AIMessage(content="done")])
    subagents = create_target_persona_subagents(registry, model=model)

    assert len(subagents) == len(registry.personas)
    assert {sub["name"] for sub in subagents} == {pack.persona_id for pack in registry.personas}


def test_precompiled_subagents_keep_the_models_transport_observer():
    registry = load_persona_pack_registry()
    callback = BaseCallbackHandler()
    model = FakeMessagesListChatModel(
        responses=[AIMessage(content="done")],
        callbacks=[callback],
    )

    subagents = create_target_persona_subagents(registry, model=model)

    assert all(sub["runnable"].config["callbacks"] == [callback] for sub in subagents)


def test_each_subagent_receives_frozen_evidence_and_has_its_own_submission_tool():
    registry = load_persona_pack_registry()
    specs = [
        target_persona_spec(pack, str(registry.output_schema["score_meaning"]), object())
        for pack in registry.personas
    ]

    for sub in specs:
        assert [t.name for t in sub["tools"]] == [SPECIALIST_TOOL.name]


def test_system_prompt_embeds_the_pack_s_job_scope_and_criteria():
    registry = load_persona_pack_registry()
    recruiter_pack = registry.pack("recruiter")
    recruiter_subagent = target_persona_spec(
        recruiter_pack,
        str(registry.output_schema["score_meaning"]),
        object(),
    )

    assert recruiter_pack.job_scope in recruiter_subagent["system_prompt"]
    assert recruiter_pack.criteria[0] in recruiter_subagent["system_prompt"]
    assert recruiter_pack.limitations[0] in recruiter_subagent["system_prompt"]
    assert registry.output_schema["score_meaning"] in recruiter_subagent["system_prompt"]
    assert "runtime attaches one frozen assessment-evidence packet" in recruiter_subagent["system_prompt"]
    assert "untrusted reference data" in recruiter_subagent["system_prompt"].lower()


def test_specialist_first_turn_gets_exact_evidence_ids_without_a_read_round_trip():
    from backend.tests.test_target_assessment import _request

    registry = load_persona_pack_registry()
    spec = target_persona_spec(
        registry.pack("recruiter"),
        str(registry.output_schema["score_meaning"]),
        object(),
    )
    evidence_middleware = spec["middleware"][0]

    with assessment_context(_request()):
        update = evidence_middleware.before_model(
            {"messages": [HumanMessage(content="Review this role.")]},
            None,
        )

    message = update["messages"][0]
    assert message.name == "assessment_evidence"
    assert '"criterion_id":"design_agent_systems"' in message.content
    assert '"field_id":"demonstrated_agent_platform"' in message.content
    assert '"resume_evidence_ids":["b_test"]' in message.content
