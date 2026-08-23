from __future__ import annotations

import json
from types import SimpleNamespace

import config
import pytest
from backend.tests.fakes import (
    five_target_persona_responses as _five_persona_responses,
    target_synthesis_call,
    valid_target_synthesis_args,
    valid_target_specialist_args as _valid_specialist_args,
)
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from pydantic import Field

from recruitment_team.assessment_contracts import (
    TargetAssessmentProgress,
    TargetAssessmentResult,
    public_specialist_validation_code,
)
from recruitment_team.open_agent.runner import (
    OpenAgentTargetAssessmentRunner,
    _agent_attempt_limit,
    _delete_terminal_checkpoint,
    _require_pending_specialist_delegation,
    _target_execution_metrics,
)
from recruitment_team.telemetry import RecordedTelemetry


class _ScriptedModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


class _OpenAIToolCapturingModel(_ScriptedModel):
    exposed_tool_names: set[str] = Field(default_factory=set)

    def _get_ls_params(self, *args, **kwargs):
        return {"ls_provider": "openai"}

    def bind_tools(self, tools, **kwargs):
        self.exposed_tool_names.update(tool.name for tool in tools)
        return self


def test_attempt_limit_matches_the_graph_that_owns_the_model_step():
    assert _agent_attempt_limit("coordinator") == config.TARGET_ASSESSMENT_MAX_TOOL_ITERATIONS
    assert _agent_attempt_limit("ats") == config.TARGET_SPECIALIST_MAX_TOOL_ITERATIONS


def test_semantic_validation_code_keeps_category_without_rejected_content():
    code = public_specialist_validation_code(
        "specialist:skeptic:summary:unsupported_numeric_claim:314159_years"
    )

    assert code == "unsupported_numeric_claim"
    assert "314159" not in code


def test_missing_specialists_narrow_the_coordinator_to_delegation(monkeypatch):
    monkeypatch.setattr(
        "recruitment_team.open_agent.runner.context.missing_required_specialists",
        lambda: ("ats", "technical"),
    )
    tools = [SimpleNamespace(name="task"), SimpleNamespace(name="submit_target_assessment_synthesis")]
    observed = []
    request = SimpleNamespace(
        tools=tools,
        override=lambda **changes: SimpleNamespace(**changes),
    )

    _require_pending_specialist_delegation.wrap_model_call(
        request,
        lambda updated: observed.append(updated) or AIMessage(content="done"),
    )

    assert [tool.name for tool in observed[0].tools] == ["task"]
    assert observed[0].tool_choice == {
        "type": "function",
        "function": {"name": "task"},
    }


def test_completed_specialists_restore_the_full_coordinator_tool_set(monkeypatch):
    monkeypatch.setattr(
        "recruitment_team.open_agent.runner.context.missing_required_specialists",
        lambda: (),
    )
    request = SimpleNamespace(tools=[SimpleNamespace(name="task")])

    observed = []
    _require_pending_specialist_delegation.wrap_model_call(
        request,
        lambda unchanged: observed.append(unchanged) or AIMessage(content="done"),
    )

    assert observed == [request]


def test_target_metrics_include_nested_resume_edit_validator_attempt(monkeypatch):
    monkeypatch.setattr(
        "recruitment_team.open_agent.runner.current_transport_metrics",
        lambda: {
            "transport_call_count": 2,
            "transport_input_tokens": 33,
            "transport_output_tokens": 13,
            "transport_latency_ms": 42.5,
            "transport_models": ["coordinator-model", "evidence-model"],
            "transport_by_role": {
                "coordinator": {
                    "call_count": 1,
                    "attempt_count": 1,
                    "retry_count": 0,
                    "error_count": 0,
                    "input_tokens": 20,
                    "output_tokens": 8,
                    "latency_ms": 30.0,
                    "models": ["coordinator-model"],
                },
                "resume_edit_evidence": {
                    "call_count": 1,
                    "attempt_count": 1,
                    "retry_count": 0,
                    "error_count": 0,
                    "input_tokens": 13,
                    "output_tokens": 5,
                    "latency_ms": 12.5,
                    "models": ["evidence-model"],
                },
            },
            "nested_model_attempts": [{
                "attempt_id": "resume_edit_evidence:validator-call-1",
                "stage": "resume_edit_evidence",
                "team_member": "resume_edit_evidence",
                "model": "evidence-model",
                "input_tokens": 13,
                "output_tokens": 5,
                "attempt_count": 1,
                "status": "success",
            }],
        },
    )

    metrics = _target_execution_metrics(
        _request(),
        [{
            "attempt_id": "coordinator-call-1",
            "model": "coordinator-model",
            "input_tokens": 20,
            "output_tokens": 8,
        }],
        (),
        10,
        "completed",
    )

    assert metrics["model_call_count"] == 2
    assert metrics["input_tokens"] == 33
    assert metrics["output_tokens"] == 13
    assert metrics["models"] == ["coordinator-model", "evidence-model"]
    assert metrics["transport_latency_ms"] == 42.5
    assert metrics["transport_by_role"]["coordinator"]["input_tokens"] == 20
    assert metrics["transport_by_role"]["resume_edit_evidence"]["models"] == [
        "evidence-model"
    ]
    assert [attempt["attempt_id"] for attempt in metrics["attempts"]] == [
        "coordinator-call-1",
        "resume_edit_evidence:validator-call-1",
    ]
    assert "nested_model_attempts" not in metrics


def _judge_call(call_id: str = "judge-call-1", disposition: str = "pass") -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{
            "name": "submit_target_assessment_judgment",
            "args": {
                "strengths": ["Clear, unambiguous evidence."],
                "weaknesses": [],
                "deductions": [],
                "evidence_gaps": [],
                "rubric_scores": {
                    "evidence_grounding": 90, "role_coverage": 85,
                    "decision_usefulness": 85, "fairness_and_boundaries": 100,
                },
                "score": 88,
                "score_reason": "Grounded in directly supplied evidence.",
                "confidence": 85,
                "confidence_reason": "No ambiguity in the source evidence.",
                "disposition": disposition,
            },
            "id": call_id,
        }],
    )


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
        trace_key="open-agent-runner-trace",
        edit_evidence_validator=AllowingEditEvidenceValidator(),
        resume_document={
            "schema_version": 1,
            "revision": "rev-1",
            "raw_text": "Led team of 12 engineers.",
            "blocks": [{"id": "b1", "text": "Led team of 12 engineers.", "section_key": "experience", "entry_id": "e1"}],
        },
    )


def test_target_runtime_exposes_only_declared_domain_tools_and_named_personas():
    model = _OpenAIToolCapturingModel(responses=[AIMessage(content="Done.")])
    runner = OpenAgentTargetAssessmentRunner(
        model_factory=lambda: model,
        telemetry=RecordedTelemetry(),
    )
    graph = runner._build_agent(model)
    graph.invoke(
        {"messages": [{"role": "user", "content": "Assess the role."}]},
        config={"configurable": {"thread_id": "tool-inventory-test"}},
    )

    assert model.exposed_tool_names == {
        "ask_candidate",
        "propose_resume_edit",
        "read_candidate_evidence",
        "read_target_job",
        "submit_target_assessment_synthesis",
        "task",
    }
    assert not {
        "write_todos",
        "ls",
        "read_file",
        "write_file",
        "edit_file",
        "glob",
        "grep",
        "execute",
    } & model.exposed_tool_names


def test_accepted_specialist_report_reaches_the_next_coordinator_model_request(monkeypatch):
    import resume_agent.models as agent_models

    monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "test-key")
    requests: list[list] = []

    class CapturingModel(_ScriptedModel):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            requests.append(list(messages))
            return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    coordinator_model = CapturingModel(
        responses=_five_persona_responses(
            None,
            target_synthesis_call("report-propagation-synthesis"),
        )
    )
    runner = OpenAgentTargetAssessmentRunner(
        model_factory=lambda: coordinator_model,
        judge_model_factory=lambda: _ScriptedModel(responses=[_judge_call()]),
        telemetry=RecordedTelemetry(),
    )

    updates = list(runner.run(_request()))
    result = next(item for item in updates if isinstance(item, TargetAssessmentResult))
    task_results = [
        message
        for model_request in requests
        for message in model_request
        if isinstance(message, ToolMessage) and message.name == "task"
    ]

    assert result.status == "completed"
    assert any(
        "recruiter found grounded delivery evidence" in str(message.content)
        and "<accepted_specialist_report_data>" in str(message.content)
        for message in task_results
    )

def test_terminal_checkpoint_cleanup_failure_emits_content_free_telemetry(monkeypatch):
    def fail_cleanup(_thread_id):
        raise OSError("checkpoint store unavailable")

    monkeypatch.setattr("recruitment_team.open_agent.runner.delete_checkpoint", fail_cleanup)
    telemetry = RecordedTelemetry()

    _delete_terminal_checkpoint(
        {"configurable": {"thread_id": "private-checkpoint-token"}},
        telemetry,
    )

    assert len(telemetry.spans) == 1
    span = telemetry.spans[0]
    assert span.name == "checkpoint_cleanup"
    assert span.status == "error"
    assert span.error_type == "OSError"
    assert span.attributes == {
        "workflow": "target_assessment",
        "outcome": "failed",
    }
    assert "private-checkpoint-token" not in str(span.attributes)


def test_runner_fails_before_judge_with_zero_personas_consulted(monkeypatch):
    import resume_agent.models as agent_models

    monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "test-key")
    deleted: list[str] = []
    monkeypatch.setattr("recruitment_team.open_agent.runner.delete_checkpoint", deleted.append)

    final_reply = AIMessage(content="No specialist consultation needed; evidence is unambiguous.")
    orchestrator_model = _ScriptedModel(responses=[final_reply])

    judge_model = _ScriptedModel(responses=[_judge_call()])

    runner = OpenAgentTargetAssessmentRunner(
        model_factory=lambda: orchestrator_model,
        judge_model_factory=lambda: judge_model,
        telemetry=RecordedTelemetry(),
    )

    updates = list(runner.run(_request()))
    progress = [item for item in updates if isinstance(item, TargetAssessmentProgress)]
    result = next(item for item in updates if isinstance(item, TargetAssessmentResult))

    assert progress[0].team_member == "coordinator" and progress[0].status == "running"
    assert result.status == "failed"
    assert result.judge is None
    assert result.error["failure_code"] == "structured_output_invalid"
    assert result.specialist_runs == ()
    assert "specialist:recruiter:missing" in result.error["validation_codes"]
    assert len(deleted) == 1


def test_runner_stops_after_synthesis_validation_budget(monkeypatch):
    import resume_agent.models as agent_models

    monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "test-key")

    def invalid_synthesis(call_id: str, years: int) -> AIMessage:
        args = valid_target_synthesis_args()
        args["claims"][0]["statement"] = f"Built the platform over {years} years."
        return AIMessage(
            content="",
            tool_calls=[{
                "name": "submit_target_assessment_synthesis",
                "args": args,
                "id": call_id,
            }],
        )

    runner = OpenAgentTargetAssessmentRunner(
        model_factory=lambda: _ScriptedModel(
            responses=_five_persona_responses(
                None,
                invalid_synthesis("invalid-synthesis-1", 12),
                invalid_synthesis("invalid-synthesis-2", 13),
            )
        ),
        judge_model_factory=lambda: _ScriptedModel(responses=[_judge_call()]),
        telemetry=RecordedTelemetry(),
    )

    updates = list(runner.run(_request()))
    result = next(item for item in updates if isinstance(item, TargetAssessmentResult))

    assert result.status == "failed"
    assert result.judge is None
    assert result.error["failure_code"] == "attempt_budget_exhausted"
    assert result.error["validation_codes"] == [
        "synthesis:claim:0:unsupported_numeric_claim:13_years"
    ]


def test_runner_corrects_a_fixable_synthesis_inside_the_same_graph(monkeypatch):
    import resume_agent.models as agent_models

    monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "test-key")
    invalid_args = valid_target_synthesis_args()
    invalid_args["claims"][0]["statement"] = "Built the platform over 12 years."
    invalid = AIMessage(
        content="",
        tool_calls=[{
            "name": "submit_target_assessment_synthesis",
            "args": invalid_args,
            "id": "invalid-synthesis-before-correction",
        }],
    )
    runner = OpenAgentTargetAssessmentRunner(
        model_factory=lambda: _ScriptedModel(
            responses=_five_persona_responses(
                None,
                invalid,
                target_synthesis_call("corrected-synthesis"),
            )
        ),
        judge_model_factory=lambda: _ScriptedModel(responses=[_judge_call()]),
        telemetry=RecordedTelemetry(),
    )

    result = next(
        item
        for item in runner.run(_request())
        if isinstance(item, TargetAssessmentResult)
    )

    assert result.status == "completed"
    assert result.judge is not None
    assert result.judge["disposition"] == "pass"


def test_sequential_judge_correction_and_rejudge_renew_a_controlled_clock(monkeypatch):
    import resume_agent.models as agent_models

    monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "test-key")
    clock = {"seconds": 0}

    class AdvancingModel(_ScriptedModel):
        def invoke(self, *args, **kwargs):
            clock["seconds"] += 9
            return super().invoke(*args, **kwargs)

    judge_responses = iter((
        _judge_call("judge-revise", disposition="revise"),
        _judge_call("judge-pass", disposition="pass"),
    ))
    correction = AIMessage(
        content="",
        tool_calls=[{
            "name": "submit_corrected_target_assessment",
            "args": valid_target_synthesis_args(),
            "id": "correction-1",
        }],
    )
    runner = OpenAgentTargetAssessmentRunner(
        model_factory=lambda: _ScriptedModel(
            responses=_five_persona_responses(AIMessage(content="Initial synthesis."))
        ),
        judge_model_factory=lambda: AdvancingModel(responses=[next(judge_responses)]),
        correction_model_factory=lambda: AdvancingModel(responses=[correction]),
        telemetry=RecordedTelemetry(),
    )
    renewals = []
    last_renewal = {"seconds": 0}

    def renew_lease():
        assert clock["seconds"] - last_renewal["seconds"] < 10
        renewals.append(clock["seconds"])
        last_renewal["seconds"] = clock["seconds"]

    result = next(
        item
        for item in runner.run(_request(), renew_lease=renew_lease)
        if isinstance(item, TargetAssessmentResult)
    )

    assert result.status == "completed"
    assert result.correction["attempted"] is True
    assert clock["seconds"] == 27
    assert {9, 18, 27} <= set(renewals)


def test_specialist_contract_rejects_unknown_and_unlinked_provenance():
    from recruitment_team.assessment_contracts import validate_specialist_runs
    from resume_agent.contracts import TARGET_JOB_PERSONAS

    runs = [
        {
            "persona_id": persona_id,
            "status": "completed",
            "submission": _valid_specialist_args(persona_id, "Grounded review.", 80),
        }
        for persona_id in TARGET_JOB_PERSONAS
    ]
    runs[0]["submission"] = {
        **runs[0]["submission"],
        "findings": [{
            **runs[0]["submission"]["findings"][0],
            "criterion_ids": ["invented-criterion"],
            "resume_evidence_ids": ["invented-evidence"],
        }],
    }

    failures = validate_specialist_runs(_request(), runs, TARGET_JOB_PERSONAS)

    assert "specialist:recruiter:finding:0:unknown_criterion_citation" in failures
    assert "specialist:recruiter:finding:0:unlinked_resume_citation" in failures


def test_specialist_contract_rejects_protected_status_in_scoring():
    from recruitment_team.assessment_contracts import validate_specialist_runs

    submission = _valid_specialist_args("recruiter", "Grounded review.", 80)
    submission.update({
        "weaknesses": ["The candidate is not a Singapore Permanent Resident."],
        "score_reason": "Residency status reduced the fit score.",
    })
    runs = [{
        "persona_id": "recruiter",
        "status": "completed",
        "submission": submission,
    }]

    failures = validate_specialist_runs(_request(), runs, ("recruiter",))

    assert "specialist:recruiter:protected_status" in failures


def test_specialist_contract_rejects_tenure_calculated_from_dates():
    from recruitment_team.assessment_contracts import validate_specialist_runs

    submission = _valid_specialist_args("skeptic", "Only about 3 years of experience.", 20)
    runs = [{
        "persona_id": "skeptic",
        "status": "completed",
        "submission": submission,
    }]

    failures = validate_specialist_runs(_request(), runs, ("skeptic",))

    assert "specialist:skeptic:summary:unsupported_numeric_claim:3_years" in failures


@pytest.mark.parametrize("score_reason", ["Evidence support is 80%.", "Evidence support is 80/100."])
def test_specialist_contract_allows_its_own_score_in_the_score_reason(score_reason):
    from recruitment_team.assessment_contracts import validate_specialist_runs

    submission = _valid_specialist_args("ats", "Grounded review.", 80)
    submission["score_reason"] = score_reason
    runs = [{"persona_id": "ats", "status": "completed", "submission": submission}]

    assert validate_specialist_runs(_request(), runs, ("ats",)) == ()


def test_specialist_contract_does_not_exempt_the_score_from_the_summary():
    from recruitment_team.assessment_contracts import validate_specialist_runs

    submission = _valid_specialist_args("ats", "The candidate is an 80% match.", 80)
    runs = [{"persona_id": "ats", "status": "completed", "submission": submission}]

    failures = validate_specialist_runs(_request(), runs, ("ats",))

    assert "specialist:ats:summary:unsupported_numeric_claim:80%" in failures


@pytest.mark.parametrize(
    "claim",
    [
        "The candidate fails the first screen.",
        "This resume is unparseable for the target role.",
        "The candidate will not pass automated screening.",
        "There is insufficient evidence to support a first-screen pass.",
    ],
)
def test_specialist_contract_rejects_unobserved_screening_outcomes(claim):
    from recruitment_team.assessment_contracts import validate_specialist_runs

    submission = _valid_specialist_args("ats", claim, 20)
    runs = [{"persona_id": "ats", "status": "completed", "submission": submission}]

    failures = validate_specialist_runs(_request(), runs, ("ats",))

    assert "specialist:ats:speculative_claim" in failures


def test_specialist_contract_validates_each_finding_against_its_own_citations():
    from recruitment_team.assessment_contracts import validate_specialist_runs

    submission = _valid_specialist_args("recruiter", "Grounded review.", 80)
    submission["findings"].append({
        "kind": "strength",
        "statement": "Another claimed strength.",
        "criterion_ids": ["design_agent_systems"],
        "candidate_profile_field_ids": ["demonstrated_agent_platform"],
        "resume_evidence_ids": ["evidence-from-another-field"],
    })
    submission["findings"].append({
        "kind": "weakness",
        "statement": "A weakness without candidate-profile support.",
        "criterion_ids": ["design_agent_systems"],
        "candidate_profile_field_ids": [],
        "resume_evidence_ids": [],
    })
    runs = [{"persona_id": "recruiter", "status": "completed", "submission": submission}]

    failures = validate_specialist_runs(_request(), runs, ("recruiter",))

    assert "specialist:recruiter:finding:1:unlinked_resume_citation" in failures
    assert "specialist:recruiter:finding:2:missing_profile_citations" in failures


def test_specialist_contract_allows_model_chosen_revisit_after_full_coverage():
    from recruitment_team.assessment_contracts import validate_specialist_runs
    from resume_agent.contracts import TARGET_JOB_PERSONAS

    runs = [
        {
            "persona_id": persona_id,
            "status": "completed",
            "submission": _valid_specialist_args(persona_id, "Grounded review.", 80),
        }
        for persona_id in TARGET_JOB_PERSONAS
    ]
    runs.append({
        "persona_id": "recruiter",
        "status": "completed",
        "submission": _valid_specialist_args(
            "recruiter",
            "Revisited after the coordinator found new evidence.",
            82,
        ),
    })

    assert validate_specialist_runs(_request(), runs, TARGET_JOB_PERSONAS) == ()


def test_persona_submission_tool_binds_identity_and_rejects_bad_citations():
    from recruitment_team.open_agent import context
    from recruitment_team.open_agent.subagents import target_persona_spec
    from recruitment_team.assessment_contracts import SPECIALIST_TOOL
    from recruitment_team.persona_packs import load_persona_pack_registry

    registry = load_persona_pack_registry()
    spec = target_persona_spec(
        registry.pack("recruiter"),
        str(registry.output_schema["score_meaning"]),
        object(),
    )
    submission_tool = next(tool for tool in spec["tools"] if tool.name == SPECIALIST_TOOL.name)
    invalid = {
        **_valid_specialist_args("skeptic", "Wrong persona and invented citations.", 70),
        "findings": [{
            "kind": "strength",
            "statement": "Invented finding.",
            "criterion_ids": ["invented-criterion"],
            "candidate_profile_field_ids": ["invented-profile-field"],
            "resume_evidence_ids": ["invented-evidence"],
        }],
    }

    with context.assessment_context(_request()):
        rejected = submission_tool.invoke(invalid)
        accepted = submission_tool.invoke(
            _valid_specialist_args("recruiter", "Grounded recruiter review.", 80)
        )

    assert rejected["ok"] is False
    assert rejected["accepted"] is False
    assert rejected["retry"] is True
    assert rejected["attempt_count"] == 1
    assert rejected["attempt_limit"] == config.AGENT_PERSONA_VALIDATION_ATTEMPTS
    assert rejected["expected_persona_id"] == "recruiter"
    assert rejected["validation_codes"] == [
        "specialist:recruiter:finding:0:unknown_criterion_citation",
        "specialist:recruiter:finding:0:unknown_profile_citation",
        "specialist:recruiter:finding:0:unlinked_resume_citation",
    ]
    assert rejected["allowed_profile_evidence"] == {
        "demonstrated_agent_platform": ["b_test"]
    }
    assert rejected["validation_guidance"] == (
        "Replace invented criterion IDs with IDs from allowed_criterion_ids."
    )
    assert accepted["ok"] is True
    assert accepted["accepted"] is True
    assert accepted["attempt_count"] == 2
    assert accepted["submission"]["persona_id"] == "recruiter"


def test_persona_submission_tool_completes_canonical_profile_citation_owner():
    from recruitment_team.open_agent import context
    from recruitment_team.open_agent.subagents import target_persona_spec
    from recruitment_team.assessment_contracts import SPECIALIST_TOOL
    from recruitment_team.persona_packs import load_persona_pack_registry

    registry = load_persona_pack_registry()
    spec = target_persona_spec(
        registry.pack("ats"),
        str(registry.output_schema["score_meaning"]),
        object(),
    )
    submission_tool = next(tool for tool in spec["tools"] if tool.name == SPECIALIST_TOOL.name)
    submission = _valid_specialist_args("ats", "Grounded ATS review.", 80)
    submission["findings"][0]["candidate_profile_field_ids"] = []

    with context.assessment_context(_request()):
        accepted = submission_tool.invoke(submission)

    assert accepted["accepted"] is True
    assert accepted["citation_repair_count"] == 1
    assert accepted["submission"]["findings"][0]["candidate_profile_field_ids"] == [
        "demonstrated_agent_platform"
    ]


def test_missing_profile_guidance_names_the_exact_evidence_gap_repair():
    from recruitment_team.assessment_contracts import SpecialistSubmission
    from recruitment_team.open_agent.subagents import _specialist_validation_guidance

    submission = SpecialistSubmission.model_validate(
        _valid_specialist_args("ats", "Grounded ATS review.", 80)
    )
    finding = submission.findings[0]
    finding.candidate_profile_field_ids = []
    finding.resume_evidence_ids = []

    guidance = _specialist_validation_guidance(
        "specialist:ats:finding:0:missing_profile_citations",
        submission,
    )

    assert "findings[0]" in guidance
    assert "kind to 'evidence_gap'" in guidance
    assert "rather than a candidate weakness" in guidance


def test_runner_stops_when_a_specialist_exhausts_its_correction_budget(monkeypatch):
    import resume_agent.models as agent_models

    monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "test-key")
    monkeypatch.setattr(config, "AGENT_PERSONA_VALIDATION_ATTEMPTS", 2)
    invalid = _valid_specialist_args("recruiter", "Invented criterion review.", 70)
    invalid["findings"][0]["criterion_ids"] = ["invented-criterion"]
    responses = [
        AIMessage(content="", tool_calls=[{
            "name": "task",
            "args": {
                "description": "Run the recruiter review.",
                "subagent_type": "recruiter",
            },
            "id": "delegate-recruiter",
        }]),
        AIMessage(content="", tool_calls=[{
            "name": "submit_target_specialist_assessment",
            "args": invalid,
            "id": "invalid-recruiter-1",
        }]),
        AIMessage(content="", tool_calls=[{
            "name": "submit_target_specialist_assessment",
            "args": invalid,
            "id": "invalid-recruiter-2",
        }]),
    ]
    runner = OpenAgentTargetAssessmentRunner(
        model_factory=lambda: _ScriptedModel(responses=responses),
        judge_model_factory=lambda: _ScriptedModel(responses=[_judge_call()]),
        telemetry=RecordedTelemetry(),
    )

    updates = list(runner.run(_request()))
    result = next(item for item in updates if isinstance(item, TargetAssessmentResult))

    assert result.status == "failed"
    assert result.error["failure_code"] == "specialist_attempt_budget_exhausted"
    assert result.error["validation_codes"][0] == (
        "specialist:recruiter:finding:0:unknown_criterion_citation"
    )
    assert result.execution_metrics["semantic_outcomes"] == [
        {
            "outcome_id": "invalid-recruiter-1",
            "role": "recruiter",
            "stage": "specialist_submission",
            "accepted": False,
            "submission_attempt": 1,
            "validation_code": "unknown_criterion_citation",
        },
        {
            "outcome_id": "invalid-recruiter-2",
            "role": "recruiter",
            "stage": "specialist_submission",
            "accepted": False,
            "submission_attempt": 2,
            "validation_code": "unknown_criterion_citation",
        },
    ]
    assert result.execution_metrics["semantic_by_role"]["recruiter"] == {
        "submission_count": 2,
        "accepted_count": 0,
        "rejected_count": 2,
        "correction_attempt_count": 1,
    }
    assert "Invented criterion review." not in json.dumps(result.execution_metrics)
    assert all(
        attempt["status"] == "generated"
        for attempt in result.execution_metrics["attempts"]
        if attempt.get("stage") == "target_assessment"
    )
    failure = next(
        item
        for item in updates
        if isinstance(item, TargetAssessmentProgress)
        and item.team_member == "specialist_team"
        and item.status == "failed"
    )
    assert failure.detail["attempt_limit"] == config.AGENT_PERSONA_VALIDATION_ATTEMPTS
    assert not any(
        isinstance(item, TargetAssessmentProgress) and item.team_member == "judge"
        for item in updates
    )


def test_judge_retries_structured_validation_with_the_configured_budget(monkeypatch):
    import resume_agent.models as agent_models

    monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "test-key")
    invalid = AIMessage(content="I forgot to use the required judgment tool.")
    model = _ScriptedModel(responses=[invalid, _judge_call()])
    runner = OpenAgentTargetAssessmentRunner(
        model_factory=lambda: model,
        judge_model_factory=lambda: model,
        telemetry=RecordedTelemetry(),
    )

    outcome = list(runner._quality_gate.review(_request(), [], "Grounded synthesis."))[-1]
    judge = outcome.judge

    assert judge["disposition"] == "pass"
    assert judge["attempt_count"] == config.AGENT_JUDGE_VALIDATION_ATTEMPTS == 2


def test_judge_retries_candidate_scoring_claim_and_exposes_validation_code(monkeypatch):
    import resume_agent.models as agent_models

    monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "test-key")
    invalid_args = _judge_call("invalid-judge").tool_calls[0]["args"]
    invalid_args["weaknesses"] = ["The synthesis should quantify 0% alignment on core skills."]
    model = _ScriptedModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[{
                    "name": "submit_target_assessment_judgment",
                    "args": invalid_args,
                    "id": "invalid-judge",
                }],
            ),
            _judge_call("corrected-judge"),
        ]
    )
    runner = OpenAgentTargetAssessmentRunner(
        model_factory=lambda: model,
        judge_model_factory=lambda: model,
        telemetry=RecordedTelemetry(),
    )

    updates = list(runner._quality_gate.review(_request(), [], "Grounded synthesis."))
    outcome = updates[-1]

    assert outcome.judge["attempt_count"] == 2
    assert outcome.attempts[0]["validation_code"] == "judge:candidate_scoring_claim"


def test_runner_captures_a_real_persona_submission_via_streaming(monkeypatch):
    import resume_agent.models as agent_models

    monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "test-key")

    # The runner hands its single orchestrator model to every persona subagent
    # too (create_target_persona_subagents binds one shared model), so one
    # scripted model plays both roles: the delegate call and final reply for
    # the coordinator, and the submission call and final reply for the
    # persona it delegates to -- in the order the graph actually calls the
    # model as execution unwinds (coordinator delegates, the persona subgraph
    # runs to completion, then the coordinator resumes).
    coordinator_final = AIMessage(content="Consulted all five personas; synthesis complete.")
    shared_model = _ScriptedModel(responses=_five_persona_responses(coordinator_final))

    judge_model = _ScriptedModel(responses=[_judge_call()])

    runner = OpenAgentTargetAssessmentRunner(
        model_factory=lambda: shared_model,
        judge_model_factory=lambda: judge_model,
        telemetry=RecordedTelemetry(),
    )

    updates = list(runner.run(_request()))
    result = next(item for item in updates if isinstance(item, TargetAssessmentResult))

    assert len(result.specialist_runs) == 5
    run = result.specialist_runs[0]
    assert run["persona_id"] == "recruiter"
    assert run["status"] == "completed"
    # These values only exist in submit_call's scripted args above -- if this
    # assertion passes, the runner read them from the real streamed
    # tool_result, not a hardcoded/paraphrased stand-in.
    assert run["submission"]["score"] == 81
    assert run["submission"]["summary"] == "recruiter found grounded delivery evidence."
    assert result.synthesis.startswith("Strengths\n-")
    assert result.synthesis_claims
    assert result.synthesis_claims[0]["criterion_ids"] == ["design_agent_systems"]
    specialist_completions = [
        item
        for item in updates
        if isinstance(item, TargetAssessmentProgress)
        and item.summary.endswith("submitted its assessment.")
    ]
    assert len(specialist_completions) == 5
    assert all(item.detail["tool_call_id"] for item in specialist_completions)
    assert len(result.execution_metrics["semantic_outcomes"]) == 5
    assert all(
        outcome["accepted"] is True
        and outcome["validation_code"] == ""
        and "submission" not in outcome
        for outcome in result.execution_metrics["semantic_outcomes"]
    )
    assert result.execution_metrics["semantic_by_role"]["recruiter"] == {
        "submission_count": 1,
        "accepted_count": 1,
        "rejected_count": 0,
        "correction_attempt_count": 0,
    }
    assert shared_model.i == len(shared_model.responses) - 1


def test_runner_carries_an_accepted_proposed_edit_out_on_the_result(monkeypatch):
    import resume_agent.models as agent_models

    monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "test-key")

    propose_call = AIMessage(
        content="",
        tool_calls=[{
            "name": "propose_resume_edit",
            "args": {"block_id": "b1", "rewrite": "Led a team of 12 engineers."},
            "id": "call-1",
        }],
    )
    final_reply = AIMessage(content="All five specialists reviewed; proposed one evidence-safe rewrite.")
    orchestrator_model = _ScriptedModel(
        responses=_five_persona_responses(final_reply, propose_call)
    )

    judge_model = _ScriptedModel(responses=[_judge_call()])

    runner = OpenAgentTargetAssessmentRunner(
        model_factory=lambda: orchestrator_model,
        judge_model_factory=lambda: judge_model,
        telemetry=RecordedTelemetry(),
    )

    updates = list(runner.run(_request()))
    result = next(item for item in updates if isinstance(item, TargetAssessmentResult))

    assert len(result.proposed_edits) == 1
    edit = result.proposed_edits[0]
    # These values only exist in propose_call's scripted args above -- if this
    # assertion passes, the runner read them from the real tool acceptance,
    # not a hardcoded/paraphrased stand-in.
    assert edit["block_id"] == "b1"
    assert edit["rewrite"] == "Led a team of 12 engineers."
    assert edit["original"] == "Led team of 12 engineers."
    assert edit["document_revision"] == "rev-1"


def test_runner_rejects_a_materially_identical_repeated_search_jobs_call(monkeypatch):
    import resume_agent.models as agent_models
    import resume_agent.tools as agent_tools
    from resume_agent.agent import create_resume_agent

    from recruitment_team.open_agent import context
    from recruitment_team.open_agent.streaming import iter_progress_events
    from recruitment_team.tool_call_guard import ToolCallGuardMiddleware

    monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "test-key")

    class FakeDb:
        def close(self):
            return None

    real_search_calls: list[dict] = []

    def _spy_find_similar_jobs(*_args, **_kwargs):
        real_search_calls.append({})
        return []

    monkeypatch.setattr(agent_tools, "SessionLocal", lambda: FakeDb())
    monkeypatch.setattr(agent_tools, "encode_text", lambda _query: [0.1, 0.2])
    monkeypatch.setattr(agent_tools, "find_similar_jobs", _spy_find_similar_jobs)

    search_args = {"query": "backend engineer", "n": None, "detail": False}
    different_args = {"query": "platform engineer", "n": None, "detail": False}
    first_call = AIMessage(
        content="", tool_calls=[{"name": "search_jobs", "args": search_args, "id": "call-1"}]
    )
    repeat_call = AIMessage(
        content="", tool_calls=[{"name": "search_jobs", "args": search_args, "id": "call-2"}]
    )
    different_call = AIMessage(
        content="", tool_calls=[{"name": "search_jobs", "args": different_args, "id": "call-3"}]
    )
    final_reply = AIMessage(content="Done searching.")
    model = _ScriptedModel(responses=[first_call, repeat_call, different_call, final_reply])

    agent = create_resume_agent(
        model=model,
        tools=[agent_tools.search_jobs],
        subagents=[],
        middleware=[ToolCallGuardMiddleware()],
    )
    run_config = {"recursion_limit": config.AGENT_MAX_TOOL_ITERATIONS}

    with context.assessment_context(_request()):
        events = list(iter_progress_events(
            agent,
            {"messages": [{"role": "user", "content": "Search for a matching role."}]},
            run_config,
        ))

    search_results = [
        e for e in events if e["kind"] == "tool_result" and e["tool_name"] == "search_jobs"
    ]
    assert len(search_results) == 3

    def _content(event):
        raw = event["content"]
        return json.loads(raw) if isinstance(raw, str) else raw

    first_result = _content(search_results[0])
    repeat_result = _content(search_results[1])
    different_result = _content(search_results[2])

    assert first_result.get("reason") != "identical_call_no_new_information"
    assert repeat_result["ok"] is False
    assert repeat_result["reason"].startswith("identical_call_no_new_information")
    # A materially different query is genuinely allowed through, not blocked
    # by the guardrail just because a prior call happened.
    assert different_result.get("reason") != "identical_call_no_new_information"
    # Only the two allowed calls (first + different-args) reached the real
    # search backend; the identical repeat never did.
    assert len(real_search_calls) == 2


def test_runner_fails_closed_when_the_iteration_cap_is_hit(monkeypatch):
    """A partial loop may be retained for diagnosis, but it cannot be judged as success."""
    import resume_agent.models as agent_models

    monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "test-key")
    monkeypatch.setattr(config, "TARGET_ASSESSMENT_MAX_TOOL_ITERATIONS", 4)

    def fail_cleanup(_token):
        raise OSError("checkpoint store unavailable")

    monkeypatch.setattr(
        "recruitment_team.open_agent.runner.delete_checkpoint",
        fail_cleanup,
    )

    read_call = AIMessage(
        content="",
        tool_calls=[{"name": "read_target_job", "args": {}, "id": "call-loop"}],
    )
    orchestrator_model = _ScriptedModel(responses=[read_call])

    judge_model = _ScriptedModel(responses=[_judge_call()])

    runner = OpenAgentTargetAssessmentRunner(
        model_factory=lambda: orchestrator_model,
        judge_model_factory=lambda: judge_model,
        telemetry=RecordedTelemetry(),
    )

    updates = list(runner.run(_request()))

    results = [item for item in updates if isinstance(item, TargetAssessmentResult)]
    assert len(results) == 1, "the run must still reach exactly one terminal result, not raise"
    result = results[0]
    assert result.status == "failed"
    assert result.judge is None
    assert result.error["failure_code"] == "attempt_budget_exhausted"
    assert result.checkpoint_cleanup_token


def test_recursion_limit_diagnostic_preserves_the_nested_budget():
    from langgraph.errors import GraphRecursionError
    from recruitment_team.open_agent.runner import _recursion_limit_from_error

    error = GraphRecursionError("Recursion limit of 28 reached without a stop condition")

    assert _recursion_limit_from_error(error) == 28


def test_runner_resume_carries_forward_specialist_runs_and_proposed_edits_from_before_the_pause(monkeypatch):
    """The pause and the resume happen on two entirely separate runner (and
    model) instances, mirroring two separate HTTP requests in production --
    proving the durable SqliteSaver checkpointer, not any shared in-memory
    object, is what makes this a real continuation."""
    import resume_agent.models as agent_models

    monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "test-key")

    propose_call = AIMessage(
        content="",
        tool_calls=[{
            "name": "propose_resume_edit",
            "args": {"block_id": "b1", "rewrite": "Led a team of 12 engineers."},
            "id": "call-2",
        }],
    )
    ask_call = AIMessage(
        content="",
        tool_calls=[{
            "name": "ask_candidate",
            "args": {"questions": ["How large was the team you led?"]},
            "id": "call-3",
        }],
    )
    orchestrator_model = _ScriptedModel(
        responses=_five_persona_responses(None, propose_call, ask_call)
    )

    first_runner = OpenAgentTargetAssessmentRunner(
        model_factory=lambda: orchestrator_model,
        judge_model_factory=lambda: _ScriptedModel(responses=[_judge_call()]),
        telemetry=RecordedTelemetry(),
    )
    updates = list(first_runner.run(_request()))
    paused = next(
        item for item in updates if isinstance(item, TargetAssessmentProgress) and item.status == "paused"
    )
    pause_token = paused.detail["pause_token"]
    assert pause_token
    assert len(paused.detail["specialist_runs"]) == 5
    assert paused.detail["specialist_runs"][0]["persona_id"] == "recruiter"
    assert len(paused.detail["proposed_edits"]) == 1
    assert paused.detail["proposed_edits"][0]["block_id"] == "b1"

    final_reply = AIMessage(
        content="Consulted all five personas and proposed one rewrite; candidate confirmed the team size."
    )
    second_runner = OpenAgentTargetAssessmentRunner(
        model_factory=lambda: _ScriptedModel(
            responses=[target_synthesis_call("resumed-synthesis"), final_reply]
        ),
        judge_model_factory=lambda: _ScriptedModel(responses=[_judge_call(call_id="judge-call-2")]),
        telemetry=RecordedTelemetry(),
    )
    resumed = list(second_runner.resume(
        pause_token,
        "Led a team of 12 engineers.",
        _request(),
        list(paused.detail["specialist_runs"]),
        paused.detail["synthesis"],
        list(paused.detail["proposed_edits"]),
    ))
    result = next(item for item in resumed if isinstance(item, TargetAssessmentResult))
    assert result.status == "completed"
    assert len(result.specialist_runs) == 5
    assert result.specialist_runs[0]["persona_id"] == "recruiter"
    assert len(result.proposed_edits) == 1
    assert result.proposed_edits[0]["block_id"] == "b1"
    assert result.synthesis.startswith("Strengths\n-")


def test_invalid_specialist_is_not_carried_across_pause_and_can_be_corrected_after_resume(
    monkeypatch,
):
    """A semantic tool rejection must not become durable specialist state.

    The coordinator remains free to revisit that persona after the candidate
    answers, and only the corrected, context-grounded submission is accepted.
    """
    import resume_agent.models as agent_models
    from resume_agent.contracts import TARGET_JOB_PERSONAS

    monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "test-key")

    first_responses: list[AIMessage] = []
    for index, persona_id in enumerate(TARGET_JOB_PERSONAS, start=1):
        first_responses.append(
            AIMessage(
                content="",
                tool_calls=[{
                    "name": "task",
                    "args": {
                        "description": f"Review as {persona_id} before the candidate question.",
                        "subagent_type": persona_id,
                    },
                    "id": f"pre-pause-delegate-{index}",
                }],
            )
        )
        submission = _valid_specialist_args(
            persona_id,
            f"{persona_id} review before pause.",
            80,
        )
        if persona_id == "recruiter":
            submission["findings"][0]["criterion_ids"] = ["invented-criterion"]
        first_responses.append(
            AIMessage(
                content="",
                tool_calls=[{
                    "name": "submit_target_specialist_assessment",
                    "args": submission,
                    "id": f"pre-pause-submit-{index}",
                }],
            )
        )
        if persona_id == "recruiter":
            first_responses.append(
                AIMessage(content="Recruiter report was rejected; returning without a report.")
            )
    first_responses.append(
        AIMessage(
            content="",
            tool_calls=[{
                "name": "ask_candidate",
                "args": {"questions": ["Can you clarify your recruiting evidence?"]},
                "id": "specialist-contract-question",
            }],
        )
    )

    first_runner = OpenAgentTargetAssessmentRunner(
        model_factory=lambda: _ScriptedModel(responses=first_responses),
        judge_model_factory=lambda: _ScriptedModel(responses=[_judge_call()]),
        telemetry=RecordedTelemetry(),
    )
    first_updates = list(first_runner.run(_request()))
    paused = next(
        item
        for item in first_updates
        if isinstance(item, TargetAssessmentProgress) and item.status == "paused"
    )

    assert {run["persona_id"] for run in paused.detail["specialist_runs"]} == (
        set(TARGET_JOB_PERSONAS) - {"recruiter"}
    )
    rejection = next(
        item
        for item in first_updates
        if isinstance(item, TargetAssessmentProgress)
        and item.team_member == "recruiter"
        and item.detail.get("tool_name") == "submit_target_specialist_assessment"
    )
    assert rejection.status == "running"

    revisit = AIMessage(
        content="",
        tool_calls=[{
            "name": "task",
            "args": {
                "description": "Revisit recruiter with the candidate's new answer.",
                "subagent_type": "recruiter",
            },
            "id": "post-pause-delegate-recruiter",
        }],
    )
    corrected = AIMessage(
        content="",
        tool_calls=[{
            "name": "submit_target_specialist_assessment",
            "args": _valid_specialist_args(
                "recruiter", "Corrected recruiter review after candidate answer.", 82
            ),
            "id": "post-pause-submit-recruiter",
        }],
    )
    final_reply = AIMessage(content="All five grounded persona reports are complete.")
    second_runner = OpenAgentTargetAssessmentRunner(
        model_factory=lambda: _ScriptedModel(
            responses=[revisit, corrected, target_synthesis_call("corrected-synthesis"), final_reply]
        ),
        judge_model_factory=lambda: _ScriptedModel(responses=[_judge_call("post-pause-judge")]),
        telemetry=RecordedTelemetry(),
    )
    resumed = list(
        second_runner.resume(
            paused.detail["pause_token"],
            "I led recruiting calibration with hiring managers.",
            _request(),
            list(paused.detail["specialist_runs"]),
            paused.detail["synthesis"],
            list(paused.detail["proposed_edits"]),
            ask_candidate_call_id=paused.detail["ask_candidate_call_id"],
        )
    )
    result = next(item for item in resumed if isinstance(item, TargetAssessmentResult))

    assert result.status == "completed"
    assert len(result.specialist_runs) == len(TARGET_JOB_PERSONAS)
    recruiter_runs = [
        run for run in result.specialist_runs if run["persona_id"] == "recruiter"
    ]
    assert len(recruiter_runs) == 1
    assert recruiter_runs[0]["submission"]["score"] == 82


def test_runner_resume_yields_failed_result_for_an_unknown_pause_token(monkeypatch):
    import resume_agent.models as agent_models

    monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "test-key")
    deleted: list[str] = []
    monkeypatch.setattr("recruitment_team.open_agent.runner.delete_checkpoint", deleted.append)

    judge_calls: list[int] = []

    def _judge_model_factory():
        judge_calls.append(1)
        return _ScriptedModel(responses=[_judge_call()])

    runner = OpenAgentTargetAssessmentRunner(
        model_factory=lambda: _ScriptedModel(responses=[AIMessage(content="unused")]),
        judge_model_factory=_judge_model_factory,
        telemetry=RecordedTelemetry(),
    )

    updates = list(runner.resume("token-nobody-ever-paused-on", "some answer", _request(), [], "", []))

    assert len(updates) == 1
    result = updates[0]
    assert isinstance(result, TargetAssessmentResult)
    assert result.status == "failed"
    assert result.error["error_type"] == "PauseTokenNotFound"
    assert deleted == ["token-nobody-ever-paused-on"]
    assert judge_calls == [], "the judge must never be invoked for a token that was never paused"


def test_runner_resume_fails_closed_when_checkpoint_state_cannot_be_read(monkeypatch):
    class BrokenCheckpointAgent:
        def get_state(self, _run_config):
            raise RuntimeError("database unavailable")

    runner = OpenAgentTargetAssessmentRunner(
        model_factory=lambda: _ScriptedModel(responses=[]),
        telemetry=RecordedTelemetry(),
    )
    monkeypatch.setattr(runner, "_build_agent", lambda _model: BrokenCheckpointAgent())

    updates = list(
        runner.resume(
            "durable-pause-token",
            "Candidate answer",
            _request(),
            [],
            "",
            [],
        )
    )

    progress = next(item for item in updates if isinstance(item, TargetAssessmentProgress))
    result = next(item for item in updates if isinstance(item, TargetAssessmentResult))
    assert progress.status == "failed"
    assert progress.detail["failure_code"] == "checkpoint_state_unavailable"
    assert progress.detail["failure_type"] == "transient"
    assert progress.detail["retryable"] is True
    assert progress.detail["recovery_action"] == "retry_same_run"
    assert result.status == "failed"
    assert result.error["failure_code"] == "checkpoint_state_unavailable"
    assert result.error["failure_type"] == "transient"
    assert result.error["retryable"] is True
    assert result.error["recovery_action"] == "retry_same_run"


def test_post_stream_checkpoint_read_failure_preserves_resumable_checkpoint(monkeypatch):
    deleted: list[str] = []

    class FailsOnSecondRead:
        reads = 0

        def get_state(self, _run_config):
            self.reads += 1
            if self.reads == 1:
                return SimpleNamespace(interrupts=(object(),), values={"messages": []})
            raise RuntimeError("checkpoint database temporarily unavailable")

    runner = OpenAgentTargetAssessmentRunner(
        model_factory=lambda: _ScriptedModel(responses=[]),
        telemetry=RecordedTelemetry(),
    )
    monkeypatch.setattr(runner, "_build_agent", lambda _model: FailsOnSecondRead())
    monkeypatch.setattr("recruitment_team.open_agent.runner.iter_progress_events", lambda *_a, **_k: iter(()))
    monkeypatch.setattr("recruitment_team.open_agent.runner.delete_checkpoint", deleted.append)

    updates = list(runner.resume("durable-pause-token", "Answer", _request(), [], "", []))

    result = next(item for item in updates if isinstance(item, TargetAssessmentResult))
    assert result.error["recovery_action"] == "retry_same_run"
    assert result.execution_metrics["checkpoint_hit_count"] == 1
    assert deleted == []


def test_unexpected_stream_exception_cleans_up_unresumable_checkpoint(monkeypatch):
    deleted: list[str] = []

    def broken_stream(*_args, **_kwargs):
        raise RuntimeError("provider stream failed")
        yield  # pragma: no cover - make this a generator

    runner = OpenAgentTargetAssessmentRunner(
        model_factory=lambda: _ScriptedModel(responses=[]),
        telemetry=RecordedTelemetry(),
    )
    monkeypatch.setattr(runner, "_build_agent", lambda _model: object())
    monkeypatch.setattr("recruitment_team.open_agent.runner.iter_progress_events", broken_stream)
    monkeypatch.setattr("recruitment_team.open_agent.runner.delete_checkpoint", deleted.append)

    with pytest.raises(RuntimeError, match="provider stream failed"):
        list(runner.run(_request()))

    assert len(deleted) == 1


def test_resumed_stream_exception_preserves_checkpoint_for_service_retry(monkeypatch):
    deleted: list[str] = []

    class PausedAgent:
        def get_state(self, _run_config):
            return SimpleNamespace(interrupts=(object(),), values={"messages": []})

    def broken_stream(*_args, **_kwargs):
        raise TimeoutError("provider timed out after resume")
        yield  # pragma: no cover - make this a generator

    runner = OpenAgentTargetAssessmentRunner(
        model_factory=lambda: _ScriptedModel(responses=[]),
        telemetry=RecordedTelemetry(),
    )
    monkeypatch.setattr(runner, "_build_agent", lambda _model: PausedAgent())
    monkeypatch.setattr("recruitment_team.open_agent.runner.iter_progress_events", broken_stream)
    monkeypatch.setattr("recruitment_team.open_agent.runner.delete_checkpoint", deleted.append)

    with pytest.raises(TimeoutError, match="provider timed out"):
        list(runner.resume("durable-pause-token", "Answer", _request(), [], "", []))

    assert deleted == []


def test_resume_suppresses_the_replayed_ask_candidate_call_and_reports_a_genuine_second_pause(monkeypatch):
    """Regression guard for a real bug an adversarial review found: resuming
    past an interrupted ask_candidate call replays that same AIMessage as a
    fresh node update (LangChain's HumanInTheLoopMiddleware.after_model
    returns the original AIMessage, tool_calls intact, for a "respond"
    decision), which iter_progress_events can't tell apart from a genuine new
    decision -- so without ask_candidate_call_id/skip_tool_call_ids wired
    through, every resume double-counts the already-answered question as a
    second paused event. This proves resuming into a SECOND, real
    ask_candidate call yields exactly one paused event (the new one), not
    two."""
    import resume_agent.models as agent_models

    monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "test-key")

    first_ask = AIMessage(
        content="",
        tool_calls=[{"name": "ask_candidate", "args": {"questions": ["Q1"]}, "id": "call-q1"}],
    )
    first_runner = OpenAgentTargetAssessmentRunner(
        model_factory=lambda: _ScriptedModel(responses=[first_ask]),
        judge_model_factory=lambda: _ScriptedModel(responses=[_judge_call()]),
        telemetry=RecordedTelemetry(),
    )
    updates = list(first_runner.run(_request()))
    first_paused = next(
        item for item in updates if isinstance(item, TargetAssessmentProgress) and item.status == "paused"
    )
    pause_token = first_paused.detail["pause_token"]
    first_call_id = first_paused.detail["ask_candidate_call_id"]
    assert first_call_id == "call-q1"

    second_ask = AIMessage(
        content="",
        tool_calls=[{"name": "ask_candidate", "args": {"questions": ["Q2"]}, "id": "call-q2"}],
    )
    judge_calls: list[int] = []

    def _judge_model_factory():
        judge_calls.append(1)
        return _ScriptedModel(responses=[_judge_call(call_id="judge-call-2")])

    second_runner = OpenAgentTargetAssessmentRunner(
        model_factory=lambda: _ScriptedModel(responses=[second_ask]),
        judge_model_factory=_judge_model_factory,
        telemetry=RecordedTelemetry(),
    )
    resumed = list(second_runner.resume(
        pause_token,
        "Answer to Q1.",
        _request(),
        [],
        "",
        [],
        ask_candidate_call_id=first_call_id,
    ))

    paused_events = [
        item for item in resumed if isinstance(item, TargetAssessmentProgress) and item.status == "paused"
    ]
    assert len(paused_events) == 1, (
        "expected exactly one paused event (the genuine second question), not a phantom "
        "duplicate of the first, already-answered one"
    )
    assert paused_events[0].detail["question"] == "Q2"
    assert paused_events[0].detail["ask_candidate_call_id"] == "call-q2"
    assert not [item for item in resumed if isinstance(item, TargetAssessmentResult)]
    assert judge_calls == [], "the judge must never run while a second question is still pending"


def test_question_limit_resume_consumes_forced_finish_state_before_judging(monkeypatch):
    import resume_agent.models as agent_models

    monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "test-key")
    monkeypatch.setattr(config, "OPEN_AGENT_MAX_CANDIDATE_QUESTION_ROUNDS", 1)

    first_ask = AIMessage(
        content="",
        tool_calls=[{"name": "ask_candidate", "args": {"questions": ["Q1"]}, "id": "limit-q1"}],
    )
    first_runner = OpenAgentTargetAssessmentRunner(
        model_factory=lambda: _ScriptedModel(responses=_five_persona_responses(None, first_ask)),
        judge_model_factory=lambda: _ScriptedModel(responses=[_judge_call()]),
        telemetry=RecordedTelemetry(),
    )
    first_updates = list(first_runner.run(_request()))
    first_pause = next(
        item
        for item in first_updates
        if isinstance(item, TargetAssessmentProgress) and item.status == "paused"
    )

    second_ask = AIMessage(
        content="",
        tool_calls=[{"name": "ask_candidate", "args": {"questions": ["Q2"]}, "id": "limit-q2"}],
    )
    forced_synthesis = target_synthesis_call("forced-finish-synthesis")
    forced_final = AIMessage(content="Finished after the question budget was exhausted.")
    second_runner = OpenAgentTargetAssessmentRunner(
        model_factory=lambda: _ScriptedModel(responses=[second_ask, forced_synthesis, forced_final]),
        judge_model_factory=lambda: _ScriptedModel(responses=[_judge_call(call_id="limit-judge")]),
        telemetry=RecordedTelemetry(),
    )

    resumed = list(second_runner.resume(
        first_pause.detail["pause_token"],
        "Answer to Q1.",
        _request(),
        list(first_pause.detail["specialist_runs"]),
        first_pause.detail["synthesis"],
        list(first_pause.detail["proposed_edits"]),
        ask_candidate_call_id=first_pause.detail["ask_candidate_call_id"],
    ))

    result = next(item for item in resumed if isinstance(item, TargetAssessmentResult))
    assert result.status == "completed"
    assert result.synthesis.startswith("Strengths\n-")
    assert len(result.specialist_runs) == 5
    assert not [
        item
        for item in resumed
        if isinstance(item, TargetAssessmentProgress) and item.status == "paused"
    ]


def test_runner_pauses_and_yields_no_result_when_ask_candidate_interrupts(monkeypatch):
    import resume_agent.models as agent_models

    monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "test-key")
    deleted: list[str] = []
    monkeypatch.setattr("recruitment_team.open_agent.runner.delete_checkpoint", deleted.append)

    ask_call = AIMessage(
        content="",
        tool_calls=[{
            "name": "ask_candidate",
            "args": {"questions": ["How large was the team you led?"]},
            "id": "call-1",
        }],
    )
    orchestrator_model = _ScriptedModel(responses=[ask_call])

    judge_calls: list[int] = []

    def _judge_model_factory():
        # Must never be invoked while the run is paused waiting on the
        # candidate -- counted, not raised, so a bug here surfaces as a
        # clean assertion failure below instead of an unrelated crash.
        judge_calls.append(1)
        return _ScriptedModel(responses=[_judge_call()])

    runner = OpenAgentTargetAssessmentRunner(
        model_factory=lambda: orchestrator_model,
        judge_model_factory=_judge_model_factory,
        telemetry=RecordedTelemetry(),
    )

    updates = list(runner.run(_request()))

    results = [item for item in updates if isinstance(item, TargetAssessmentResult)]
    assert results == [], "a paused run must not yield a terminal TargetAssessmentResult"
    assert judge_calls == [], "the judge must never be invoked while the run is waiting on the candidate"

    paused = [item for item in updates if isinstance(item, TargetAssessmentProgress) and item.status == "paused"]
    assert len(paused) == 1, "exactly one paused progress event must be yielded"
    assert paused[0].team_member == "coordinator"
    assert paused[0].detail["question"] == "How large was the team you led?"
    assert deleted == [], "a yielded pause must retain the only resumable checkpoint"


def test_runner_never_surfaces_a_protected_status_question(monkeypatch):
    import resume_agent.models as agent_models

    monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "test-key")
    ask_call = AIMessage(
        content="",
        tool_calls=[{
            "name": "ask_candidate",
            "args": {"questions": ["Are you a Singaporean or Singapore Permanent Resident?"]},
            "id": "protected-question",
        }],
    )
    runner = OpenAgentTargetAssessmentRunner(
        model_factory=lambda: _ScriptedModel(responses=[ask_call]),
        judge_model_factory=lambda: _ScriptedModel(responses=[_judge_call()]),
        telemetry=RecordedTelemetry(),
    )

    updates = list(runner.run(_request()))

    assert not [
        item
        for item in updates
        if isinstance(item, TargetAssessmentProgress) and item.status == "paused"
    ]
    result = next(item for item in updates if isinstance(item, TargetAssessmentResult))
    assert result.status == "failed"
    assert result.error["failure_code"] == "protected_candidate_question"
    assert result.error["validation_codes"] == ["candidate_question:protected_status"]


def test_checkpoint_serializer_explicitly_allows_conversation_reply():
    import warnings

    from recruitment_team.conversation_model import ConversationReply, PreferenceUpdatePayload
    from recruitment_team.open_agent.runner import _CHECKPOINTER

    reply = ConversationReply(
        reply="Platform roles only.",
        preference_updates=[
            PreferenceUpdatePayload(
                field="role",
                value="AI platform engineer",
                evidence_quote="Platform roles only.",
            )
        ],
    )

    encoded = _CHECKPOINTER.serde.dumps_typed(reply)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        restored = _CHECKPOINTER.serde.loads_typed(encoded)

    assert restored == reply
