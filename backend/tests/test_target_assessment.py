from __future__ import annotations

import json

from langchain_core.messages import AIMessage

from recruitment_team.target_assessment import (
    NativeTargetAssessmentRunner,
    TargetAssessmentProgress,
    TargetAssessmentRequest,
    TargetAssessmentResult,
    target_assessment_execution_policy,
)
from recruitment_team.telemetry import RecordedTelemetry


def _request():
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


class _BoundModel:
    def __init__(self):
        self.tool_name = ""

    def bind_tools(self, tools, tool_choice):
        self.tool_name = tool_choice
        return self

    def invoke(self, messages):
        body = str(messages[-1].content)
        if self.tool_name == "submit_target_specialist_assessment":
            persona_id = next(
                persona
                for persona in ("recruiter", "hiring_manager", "ats", "skeptic", "market_researcher")
                if f'&quot;persona_id&quot;:&quot;{persona}&quot;' in body
                or f'"persona_id":"{persona}"' in body
            )
            args = {
                "persona_id": persona_id,
                "summary": "The supplied evidence directly supports the target criterion.",
                "strengths": ["The candidate demonstrates an agent platform outcome."],
                "weaknesses": [],
                "evidence_gaps": [],
                "criterion_ids": ["design_agent_systems"],
                "candidate_profile_field_ids": ["demonstrated_agent_platform"],
                "resume_evidence_ids": ["b_test"],
                "score": 90,
                "score_reason": "The cited field directly supports the cited role criterion.",
            }
        elif self.tool_name == "submit_target_assessment_synthesis":
            args = {
                "summary": "The target has direct evidence support with explicit provenance.",
                "strengths": ["Agent-system delivery is directly supported."],
                "weaknesses": [],
                "evidence_gaps": [],
                "next_steps": ["Validate the outcome and ownership in interview."],
                "coverage_notes": [],
                "criterion_ids": ["design_agent_systems"],
                "candidate_profile_field_ids": ["demonstrated_agent_platform"],
                "resume_evidence_ids": ["b_test"],
            }
        else:
            args = {
                "strengths": ["Every substantive conclusion has supplied provenance."],
                "weaknesses": [],
                "deductions": [],
                "evidence_gaps": [],
                "rubric_scores": {
                    "evidence_grounding": 95,
                    "role_coverage": 90,
                    "decision_usefulness": 90,
                    "fairness_and_boundaries": 100,
                },
                "score": 94,
                "score_reason": "The output is grounded, useful, and preserves boundaries.",
                "confidence": 90,
                "confidence_reason": "All specialist submissions and source IDs were available.",
                "disposition": "pass",
            }
        return AIMessage(
            content="",
            tool_calls=[{"name": self.tool_name, "args": args, "id": "call-1"}],
            usage_metadata={"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
            response_metadata={"model_name": "scripted-native-v3"},
        )


def test_native_runner_executes_five_specialists_synthesis_and_fresh_judge(monkeypatch):
    import config

    monkeypatch.setattr(config, "RECRUITMENT_SPECIALIST_MAX_CONCURRENCY", 1)
    telemetry = RecordedTelemetry()
    runner = NativeTargetAssessmentRunner(model_factory=_BoundModel, telemetry=telemetry)

    updates = list(runner.run(_request()))

    progress = [item for item in updates if isinstance(item, TargetAssessmentProgress)]
    result = next(item for item in updates if isinstance(item, TargetAssessmentResult))
    assert [item.team_member for item in progress[1:6]] == [
        "recruiter",
        "hiring_manager",
        "ats",
        "skeptic",
        "market_researcher",
    ]
    assert result.status == "completed"
    assert len(result.specialist_runs) == 5
    assert all(run["status"] == "completed" for run in result.specialist_runs)
    assert result.judge["disposition"] == "pass"
    assert result.judge["strengths"]
    assert result.judge["score_reason"]
    assert "## Strengths" in result.synthesis
    assert result.execution_policy["raw_resume_passed_to_assessment"] is False
    assert result.execution_policy["content_truncation"] is False
    assert [span.name for span in telemetry.spans].count(
        "target_assessment.specialist_attempt"
    ) == 5
    assert [span.name for span in telemetry.spans].count("target_assessment.synthesis") == 1
    assert [span.name for span in telemetry.spans].count("target_assessment.judge_attempt") == 1
    assert all(span.attributes.get("input_tokens") == 100 for span in telemetry.spans)


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
