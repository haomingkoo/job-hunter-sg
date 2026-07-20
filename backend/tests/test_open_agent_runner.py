# backend/tests/test_open_agent_runner.py
from __future__ import annotations

import json

import config
from langchain_core.messages import AIMessage
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel

from recruitment_team.assessment_contracts import TargetAssessmentProgress, TargetAssessmentResult
from recruitment_team.open_agent.runner import OpenAgentTargetAssessmentRunner
from recruitment_team.telemetry import RecordedTelemetry


class _ScriptedModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def _judge_call(call_id: str = "judge-call-1") -> AIMessage:
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
                "disposition": "pass",
            },
            "id": call_id,
        }],
    )


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
        trace_key="open-agent-runner-trace",
        resume_document={
            "schema_version": 1,
            "revision": "rev-1",
            "raw_text": "Led team of 12 engineers.",
            "blocks": [{"id": "b1", "text": "Led team of 12 engineers.", "section_key": "experience", "entry_id": "e1"}],
        },
    )


def test_runner_reaches_completed_via_mandatory_judge_with_zero_personas_consulted(monkeypatch):
    import resume_agent.models as agent_models

    monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "test-key")

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
    assert result.status == "completed"
    assert result.judge is not None
    assert result.judge["disposition"] == "pass"
    assert result.specialist_runs == ()
    assert result.synthesis == "No specialist consultation needed; evidence is unambiguous."


def _valid_specialist_args(persona_id: str, summary: str, score: int) -> dict:
    return {
        "persona_id": persona_id,
        "summary": summary,
        "strengths": ["Directly relevant leadership experience."],
        "weaknesses": [],
        "evidence_gaps": [],
        "criterion_ids": [],
        "candidate_profile_field_ids": [],
        "resume_evidence_ids": [],
        "score": score,
        "score_reason": "Grounded in directly supplied evidence.",
    }


def test_runner_captures_a_real_persona_submission_via_streaming(monkeypatch):
    import resume_agent.models as agent_models

    monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "test-key")

    # The runner hands its single orchestrator model to every persona subagent
    # too (create_target_persona_subagents binds one shared model), so one
    # scripted model plays both roles: the delegate call and final reply for
    # the coordinator, and the submission call and final reply for the
    # "recruiter" persona it delegates to -- in the order the graph actually
    # calls the model as execution unwinds (coordinator delegates, the
    # recruiter subgraph runs to completion, then the coordinator resumes).
    delegate_call = AIMessage(
        content="",
        tool_calls=[{
            "name": "task",
            "args": {"description": "Review as the recruiter.", "subagent_type": "recruiter"},
            "id": "call-1",
        }],
    )
    submit_call = AIMessage(
        content="",
        tool_calls=[{
            "name": "submit_target_specialist_assessment",
            "args": _valid_specialist_args("recruiter", "Strong hands-on leadership evidence.", 82),
            "id": "submit-1",
        }],
    )
    persona_final = AIMessage(content="Recruiter assessment complete.")
    coordinator_final = AIMessage(content="Consulted the recruiter persona; synthesis complete.")
    shared_model = _ScriptedModel(responses=[delegate_call, submit_call, persona_final, coordinator_final])

    judge_model = _ScriptedModel(responses=[_judge_call()])

    runner = OpenAgentTargetAssessmentRunner(
        model_factory=lambda: shared_model,
        judge_model_factory=lambda: judge_model,
        telemetry=RecordedTelemetry(),
    )

    updates = list(runner.run(_request()))
    result = next(item for item in updates if isinstance(item, TargetAssessmentResult))

    assert len(result.specialist_runs) == 1
    run = result.specialist_runs[0]
    assert run["persona_id"] == "recruiter"
    assert run["status"] == "completed"
    # These values only exist in submit_call's scripted args above -- if this
    # assertion passes, the runner read them from the real streamed
    # tool_result, not a hardcoded/paraphrased stand-in.
    assert run["submission"]["score"] == 82
    assert run["submission"]["summary"] == "Strong hands-on leadership evidence."
    assert result.synthesis == "Consulted the recruiter persona; synthesis complete."


def test_runner_rejects_a_materially_identical_repeated_search_jobs_call(monkeypatch):
    import resume_agent.models as agent_models
    import resume_agent.tools as agent_tools
    from resume_agent.agent import create_resume_agent

    from recruitment_team.open_agent import context
    from recruitment_team.open_agent.runner import guarded_search_jobs
    from recruitment_team.open_agent.streaming import iter_progress_events

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
        content="", tool_calls=[{"name": "guarded_search_jobs", "args": search_args, "id": "call-1"}]
    )
    repeat_call = AIMessage(
        content="", tool_calls=[{"name": "guarded_search_jobs", "args": search_args, "id": "call-2"}]
    )
    different_call = AIMessage(
        content="", tool_calls=[{"name": "guarded_search_jobs", "args": different_args, "id": "call-3"}]
    )
    final_reply = AIMessage(content="Done searching.")
    model = _ScriptedModel(responses=[first_call, repeat_call, different_call, final_reply])

    agent = create_resume_agent(model=model, tools=[guarded_search_jobs], subagents=[])
    run_config = {"recursion_limit": config.AGENT_MAX_TOOL_ITERATIONS}

    with context.assessment_context(_request()):
        events = list(iter_progress_events(
            agent,
            {"messages": [{"role": "user", "content": "Search for a matching role."}]},
            run_config,
        ))

    search_results = [
        e for e in events if e["kind"] == "tool_result" and e["tool_name"] == "guarded_search_jobs"
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
    assert repeat_result["reason"] == "identical_call_no_new_information"
    # A materially different query is genuinely allowed through, not blocked
    # by the guardrail just because a prior call happened.
    assert different_result.get("reason") != "identical_call_no_new_information"
    # Only the two allowed calls (first + different-args) reached the real
    # search backend; the identical repeat never did.
    assert len(real_search_calls) == 2


def test_runner_pauses_and_yields_no_result_when_ask_candidate_interrupts(monkeypatch):
    import resume_agent.models as agent_models

    monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "test-key")

    ask_call = AIMessage(
        content="",
        tool_calls=[{
            "name": "ask_candidate",
            "args": {"question": "How large was the team you led?"},
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
