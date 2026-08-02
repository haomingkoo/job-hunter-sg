from __future__ import annotations

import json

from langchain_core.messages import AIMessage
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel

from recruitment_team.assessment_contracts import (
    TargetAssessmentResult,
    target_assessment_execution_policy,
)
from recruitment_team.open_agent.runner import OpenAgentTargetAssessmentRunner
from recruitment_team.telemetry import RecordedTelemetry


class _ScriptedModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def _request():
    from recruitment_team.assessment_contracts import TargetAssessmentRequest
    from backend.tests.test_recruitment_team_module import (
        _candidate_profile_run,
        _job_snapshot,
        _role_profile_run,
    )

    return TargetAssessmentRequest(
        candidate_profile=_candidate_profile_run().profile,
        role_profile=_role_profile_run().profile,
        target_job=_job_snapshot(),
        trace_key="assessment-trace-key",
    )


def _judge_call(disposition: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{
            "name": "submit_target_assessment_judgment",
            "args": {
                "strengths": [],
                "weaknesses": ["The synthesis overstates evidence not cited by any specialist."],
                "deductions": [{
                    "rubric": "evidence_grounding",
                    "reason": "Unsupported claim in the synthesis.",
                    "points": 30,
                }],
                "evidence_gaps": ["No specialist consulted to verify the claim."],
                "rubric_scores": {
                    "evidence_grounding": 40,
                    "role_coverage": 60,
                    "decision_usefulness": 50,
                    "fairness_and_boundaries": 90,
                },
                "score": 55,
                "score_reason": "Grounding is too weak to publish.",
                "confidence": 80,
                "confidence_reason": "The gap is clear from the supplied evidence.",
                "disposition": disposition,
            },
            "id": "judge-call-1",
        }],
    )


def _correction_call() -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{
            "name": "submit_corrected_target_assessment",
            "args": {
                "synthesis": "Corrected synthesis that reports the evidence gap without overstating it."
            },
            "id": "correction-call-1",
        }],
    )


def test_open_agent_runner_corrects_and_rejudges_a_repairable_synthesis(monkeypatch):
    """NativeTargetAssessmentRunner guaranteed a fixed set of five specialists
    run under threaded concurrency; that guarantee is architecture-specific
    and does not carry over -- the open-agent orchestrator decides which
    personas to consult, and test_open_agent_runner.py already covers zero-
    and one-persona consultation. What must still hold regardless of who ran
    the specialists is the one behavior this test used to exercise alongside
    that fixed cardinality: a fresh independent judge gates whether the run
    reaches "completed", and rejects it otherwise. Ported here rather than
    dropped."""
    import resume_agent.models as agent_models

    monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "test-key")

    final_reply = AIMessage(content="Synthesis produced without further specialist consultation.")
    orchestrator_model = _ScriptedModel(responses=[final_reply])
    judge_models = iter([
        _ScriptedModel(responses=[_judge_call("revise")]),
        _ScriptedModel(responses=[_judge_call("pass")]),
    ])
    correction_model = _ScriptedModel(responses=[_correction_call()])

    runner = OpenAgentTargetAssessmentRunner(
        model_factory=lambda: orchestrator_model,
        judge_model_factory=lambda: next(judge_models),
        correction_model_factory=lambda: correction_model,
        telemetry=RecordedTelemetry(),
    )

    updates = list(runner.run(_request()))
    result = next(item for item in updates if isinstance(item, TargetAssessmentResult))

    assert result.status == "completed"
    assert result.judge["disposition"] == "pass"
    assert result.judge["score"] == 55
    assert result.synthesis.startswith("Corrected synthesis")
    assert result.correction["attempted"] is True
    assert result.correction["status"] == "completed"
    assert result.correction["rejudge_disposition"] == "pass"


def test_failed_correction_stays_quality_blocked_without_a_second_judge(monkeypatch):
    import config
    import resume_agent.models as agent_models

    monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "test-key")
    monkeypatch.setattr(config, "RECRUITMENT_SYNTHESIS_VALIDATION_ATTEMPTS", 2)

    orchestrator_model = _ScriptedModel(responses=[AIMessage(content="Original synthesis.")])
    judge_model = _ScriptedModel(responses=[_judge_call("revise")])
    correction_model = _ScriptedModel(
        responses=[AIMessage(content="not a tool call"), AIMessage(content="still not a tool call")]
    )
    runner = OpenAgentTargetAssessmentRunner(
        model_factory=lambda: orchestrator_model,
        judge_model_factory=lambda: judge_model,
        correction_model_factory=lambda: correction_model,
        telemetry=RecordedTelemetry(),
    )

    result = next(
        item for item in runner.run(_request()) if isinstance(item, TargetAssessmentResult)
    )

    assert result.status == "quality_blocked"
    assert result.synthesis == "Original synthesis."
    assert result.judge["disposition"] == "revise"
    assert result.correction["status"] == "failed"
    assert result.correction["attempt_count"] == 2


def test_execution_policy_exposes_every_behavior_control():
    policy = target_assessment_execution_policy()

    assert policy["specialist_validation_attempts"] > 0
    assert policy["specialist_max_concurrency"] > 0
    assert policy["synthesis_validation_attempts"] > 0
    assert policy["judge_validation_attempts"] > 0
    assert policy["maximum_synthesis_corrections"] in {0, 1}
    assert policy["transport_retries"] >= 0
    assert policy["fallback_model"] is None
    assert policy["content_truncation"] is False
    json.dumps(policy)


def test_judge_and_correction_receive_the_evidence_their_prompts_claim(monkeypatch):
    import recruitment_team.open_agent.runner as runner_module

    captured = []

    def capture(_model, _tool, _prompt, data_name, data, **_kwargs):
        captured.append((data_name, data))
        if data_name == "open_agent_judge_data":
            return _judge_call("revise").tool_calls[0]["args"], "", 0, 0, "test"
        return {"synthesis": "Corrected synthesis."}, "", 0, 0, "test"

    monkeypatch.setattr(runner_module, "invoke_structured", capture)
    runner = OpenAgentTargetAssessmentRunner(model_factory=lambda: object())
    request = _request()

    judge = runner._run_judge(object(), request, [], "Original synthesis.")
    runner._correct_synthesis(object(), request, [], "Original synthesis.", judge)

    judge_data = captured[0][1]
    correction_data = captured[1][1]
    assert judge_data["candidate_profile"]["fields"]
    assert judge_data["failures"] == [
        {"persona_id": pack.persona_id, "failure_type": "no_submission"}
        for pack in runner._registry.personas
    ]
    assert correction_data["candidate_profile"] == judge_data["candidate_profile"]
