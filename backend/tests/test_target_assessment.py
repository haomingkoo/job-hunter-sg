from __future__ import annotations

import json

from langchain_core.messages import AIMessage
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel

from backend.tests.fakes import five_target_persona_responses, valid_target_synthesis_args
from recruitment_team.assessment_contracts import (
    TargetAssessmentProgress,
    TargetAssessmentResult,
    target_assessment_execution_policy,
)
from recruitment_team.open_agent.runner import OpenAgentTargetAssessmentRunner
from recruitment_team.telemetry import RecordedTelemetry


class _ScriptedModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def _request():
    from backend.tests.fakes import AllowingEditEvidenceValidator
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
        edit_evidence_validator=AllowingEditEvidenceValidator(),
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
            "args": valid_target_synthesis_args(),
            "id": "correction-call-1",
        }],
    )


def test_open_agent_runner_corrects_and_rejudges_a_repairable_synthesis(monkeypatch):
    """A repairable synthesis reaches completed only after a fresh judge passes it."""
    import resume_agent.models as agent_models

    monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "test-key")

    final_reply = AIMessage(content="Synthesis produced after all specialist reviews.")
    orchestrator_model = _ScriptedModel(
        responses=five_target_persona_responses(final_reply)
    )
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
    assert result.synthesis.startswith("Strengths\n-")
    assert result.correction["attempted"] is True
    assert result.correction["status"] == "completed"
    assert result.correction["rejudge_disposition"] == "pass"
    assert result.execution_metrics["trace_key"] == "assessment-trace-key"
    assert result.execution_metrics["model_call_count"] == 3
    assert result.execution_metrics["terminal_status"] == "completed"
    assert {attempt["stage"] for attempt in result.execution_metrics["attempts"]} >= {
        "target_assessment_judge",
        "target_assessment_correction",
    }


def test_blocked_judgment_emits_a_terminal_held_back_lifecycle_event(monkeypatch):
    import resume_agent.models as agent_models

    monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "test-key")
    deleted: list[str] = []
    monkeypatch.setattr("recruitment_team.open_agent.runner.delete_checkpoint", deleted.append)
    runner = OpenAgentTargetAssessmentRunner(
        model_factory=lambda: _ScriptedModel(
            responses=five_target_persona_responses(AIMessage(content="Original synthesis."))
        ),
        judge_model_factory=lambda: _ScriptedModel(responses=[_judge_call("block")]),
        telemetry=RecordedTelemetry(),
    )

    updates = list(runner.run(_request()))
    result = next(item for item in updates if isinstance(item, TargetAssessmentResult))
    progress = [item for item in updates if isinstance(item, TargetAssessmentProgress)]

    assert result.status == "quality_blocked"
    assert len(deleted) == 1
    assert progress[-1].team_member == "quality_judge"
    assert progress[-1].status == "quality_blocked"
    assert progress[-1].detail["failure_code"] == "quality_gate_blocked"


def test_failed_rejudge_preserves_the_successful_initial_judgment(monkeypatch):
    import config
    import resume_agent.models as agent_models

    monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "test-key")
    monkeypatch.setattr(config, "AGENT_JUDGE_VALIDATION_ATTEMPTS", 2)
    judge_models = iter([
        _ScriptedModel(responses=[_judge_call("revise")]),
        _ScriptedModel(responses=[AIMessage(content="invalid"), AIMessage(content="still invalid")]),
    ])
    runner = OpenAgentTargetAssessmentRunner(
        model_factory=lambda: _ScriptedModel(
            responses=five_target_persona_responses(AIMessage(content="Original synthesis."))
        ),
        judge_model_factory=lambda: next(judge_models),
        correction_model_factory=lambda: _ScriptedModel(responses=[_correction_call()]),
        telemetry=RecordedTelemetry(),
    )

    result = next(
        item for item in runner.run(_request()) if isinstance(item, TargetAssessmentResult)
    )

    assert result.status == "failed"
    assert result.error["error_type"] == "TargetAssessmentRejudgeUnavailable"
    assert result.judge["disposition"] == "revise"


def test_failed_correction_fails_without_a_synthetic_quality_verdict(monkeypatch):
    import config
    import resume_agent.models as agent_models

    monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "test-key")
    monkeypatch.setattr(config, "RECRUITMENT_SYNTHESIS_VALIDATION_ATTEMPTS", 2)

    orchestrator_model = _ScriptedModel(
        responses=five_target_persona_responses(AIMessage(content="Original synthesis."))
    )
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

    assert result.status == "failed"
    assert result.synthesis.startswith("Strengths\n-")
    assert result.judge["disposition"] == "revise"
    assert result.correction["status"] == "failed"
    assert result.correction["attempt_count"] == 2
    assert result.error["error_type"] == "TargetAssessmentCorrectionUnavailable"
    assert result.error["failure_code"] == "attempt_budget_exhausted"


def test_invalid_judge_attempts_fail_without_fabricating_a_block_verdict(monkeypatch):
    import config
    import resume_agent.models as agent_models

    monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "test-key")
    monkeypatch.setattr(config, "AGENT_JUDGE_VALIDATION_ATTEMPTS", 2)

    orchestrator_model = _ScriptedModel(
        responses=five_target_persona_responses(AIMessage(content="Original synthesis."))
    )
    judge_model = _ScriptedModel(
        responses=[AIMessage(content="invalid"), AIMessage(content="still invalid")]
    )
    runner = OpenAgentTargetAssessmentRunner(
        model_factory=lambda: orchestrator_model,
        judge_model_factory=lambda: judge_model,
        telemetry=RecordedTelemetry(),
    )

    updates = list(runner.run(_request()))
    result = next(item for item in updates if isinstance(item, TargetAssessmentResult))
    judge_progress = [
        item
        for item in updates
        if getattr(item, "team_member", None) == "quality_judge"
    ]

    assert result.status == "failed"
    assert result.judge is None
    assert result.error["error_type"] == "TargetAssessmentJudgeUnavailable"
    assert result.error["failure_code"] == "attempt_budget_exhausted"
    assert len(judge_progress) == 4
    assert judge_progress[-1].status == "failed"
    assert not any("completed its structured review" in item.summary for item in judge_progress)
    judge_attempts = [
        attempt
        for attempt in result.execution_metrics["attempts"]
        if attempt["stage"] == "target_assessment_judge"
    ]
    assert [attempt["status"] for attempt in judge_attempts] == [
        "validation_failed",
        "validation_failed",
    ]


def test_judge_retry_receives_actionable_validation_guidance(monkeypatch):
    import copy
    import config
    import recruitment_team.open_agent.quality_gate as quality_gate_module

    monkeypatch.setattr(config, "AGENT_JUDGE_VALIDATION_ATTEMPTS", 2)
    captured = []
    responses = iter([
        _judge_call("pass").tool_calls[0]["args"] | {
            "weaknesses": ["The candidate's hiring probability is unclear."],
        },
        _judge_call("pass").tool_calls[0]["args"],
    ])

    def capture(_model, _tool, _prompt, _data_name, data, **_kwargs):
        captured.append(copy.deepcopy(data))
        return next(responses), "", 0, 0, "test"

    monkeypatch.setattr(quality_gate_module, "invoke_structured", capture)
    runner = OpenAgentTargetAssessmentRunner(model_factory=lambda: object())

    outcome = list(runner._quality_gate.review(_request(), [], "Original synthesis."))[-1]

    assert outcome.status == "completed"
    assert "previous_validation_code" not in captured[0]
    assert captured[1]["previous_validation_code"] == "judge:speculative_claim"
    assert "screening outcomes" in captured[1]["previous_validation_guidance"]


def test_execution_policy_exposes_every_behavior_control():
    policy = target_assessment_execution_policy()

    assert policy["synthesis_validation_attempts"] > 0
    assert policy["maximum_synthesis_corrections"] in {0, 1}
    assert policy["transport_retries"] >= 0
    assert policy["fallback_model"] is None
    assert policy["content_truncation"] is False
    json.dumps(policy)


def test_judge_tool_schema_puts_output_only_policy_on_narrative_fields():
    from recruitment_team.assessment_contracts import JUDGE_TOOL

    schema = JUDGE_TOOL.args_schema.model_json_schema()
    properties = schema["properties"]
    for field in ("strengths", "weaknesses", "score_reason", "confidence_reason"):
        assert "output" in properties[field]["description"].casefold()
    assert "candidate" in properties["evidence_gaps"]["description"].casefold()
    deduction = schema["$defs"]["Deduction"]["properties"]["reason"]
    assert "output quality" in deduction["description"].casefold()


def test_judge_and_correction_receive_the_evidence_their_prompts_claim(monkeypatch):
    import recruitment_team.open_agent.quality_gate as quality_gate_module

    captured = []

    def capture(_model, _tool, _prompt, data_name, data, **_kwargs):
        captured.append((data_name, data))
        if data_name == "open_agent_judge_data":
            return _judge_call("revise").tool_calls[0]["args"], "", 0, 0, "test"
        return valid_target_synthesis_args(), "", 0, 0, "test"

    monkeypatch.setattr(quality_gate_module, "invoke_structured", capture)
    runner = OpenAgentTargetAssessmentRunner(model_factory=lambda: object())
    request = _request()

    outcome = list(runner._quality_gate.review(request, [], "Original synthesis."))[-1]

    judge_data = captured[0][1]
    correction_data = captured[1][1]
    assert outcome.correction["status"] == "completed"
    assert judge_data["candidate_profile"]["fields"]
    assert judge_data["failures"] == [
        {
            "persona_id": pack.persona_id,
            "failure_type": "validation",
            "failure_code": "structured_output_invalid",
        }
        for pack in runner._registry.personas
    ]
    assert correction_data["candidate_profile"] == judge_data["candidate_profile"]
    assert "candidate_evidence" not in judge_data["role_success_profile"]
    assert "cited_resume_evidence" not in judge_data["role_success_profile"]
    assert "sources" not in judge_data["role_success_profile"]
