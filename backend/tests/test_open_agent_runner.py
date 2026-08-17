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
            "args": {"synthesis": "Corrected, evidence-grounded synthesis."},
            "id": "correction-1",
        }],
    )
    runner = OpenAgentTargetAssessmentRunner(
        model_factory=lambda: _ScriptedModel(responses=[AIMessage(content="Initial synthesis.")]),
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
    final_reply = AIMessage(content="Proposed one evidence-safe rewrite; no specialist consultation needed.")
    orchestrator_model = _ScriptedModel(responses=[propose_call, final_reply])

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


def test_runner_still_reaches_a_judged_result_when_the_iteration_cap_is_hit(monkeypatch):
    """Regression guard for the "mandatory final judge" design requirement:
    hitting the orchestrator's recursion_limit must not discard whatever
    partial progress was made. `FakeMessagesListChatModel` cycles back to its
    last scripted response forever once exhausted, so a single repeating
    tool-call response makes the orchestrator loop indefinitely -- exactly
    the kind of run that blows through a (deliberately tiny, for a fast
    deterministic test) recursion_limit instead of ever producing a final
    non-tool-call reply. The runner must still yield a terminal
    TargetAssessmentResult with the judge populated, not let
    GraphRecursionError propagate out of run()."""
    import resume_agent.models as agent_models

    monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "test-key")
    monkeypatch.setattr(config, "AGENT_MAX_TOOL_ITERATIONS", 4)

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
    assert result.judge is not None
    assert result.judge["disposition"] == "pass"


def test_runner_resume_carries_forward_specialist_runs_and_proposed_edits_from_before_the_pause(monkeypatch):
    """The pause and the resume happen on two entirely separate runner (and
    model) instances, mirroring two separate HTTP requests in production --
    proving the durable SqliteSaver checkpointer, not any shared in-memory
    object, is what makes this a real continuation."""
    import resume_agent.models as agent_models

    monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "test-key")

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
        responses=[delegate_call, submit_call, persona_final, propose_call, ask_call]
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
    assert len(paused.detail["specialist_runs"]) == 1
    assert paused.detail["specialist_runs"][0]["persona_id"] == "recruiter"
    assert len(paused.detail["proposed_edits"]) == 1
    assert paused.detail["proposed_edits"][0]["block_id"] == "b1"

    final_reply = AIMessage(
        content="Consulted the recruiter persona and proposed one rewrite; candidate confirmed the team size."
    )
    second_runner = OpenAgentTargetAssessmentRunner(
        model_factory=lambda: _ScriptedModel(responses=[final_reply]),
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
    assert len(result.specialist_runs) == 1
    assert result.specialist_runs[0]["persona_id"] == "recruiter"
    assert len(result.proposed_edits) == 1
    assert result.proposed_edits[0]["block_id"] == "b1"
    assert result.synthesis == (
        "Consulted the recruiter persona and proposed one rewrite; candidate confirmed the team size."
    )


def test_runner_resume_yields_failed_result_for_an_unknown_pause_token(monkeypatch):
    import resume_agent.models as agent_models

    monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "test-key")

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
    assert judge_calls == [], "the judge must never be invoked for a token that was never paused"


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


def test_runner_pauses_and_yields_no_result_when_ask_candidate_interrupts(monkeypatch):
    import resume_agent.models as agent_models

    monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "test-key")

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
