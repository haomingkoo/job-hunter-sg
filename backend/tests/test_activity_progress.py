"""What the candidate is allowed to read off the activity panel.

`describe_progress` is the single place both agent loops turn a raw stream event
into an activity row, so this is where the never-leak-reasoning invariant is
enforced for that surface: a query the model wrote and counts derived here go
out, a tool's raw return value and a model's plain message do not.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

from langchain_core.messages import AIMessage

from recruitment_team.open_agent.streaming import describe_progress, rejected_tool_result
from recruitment_team.activity_events import public_detail, to_activity_event, trace_attributes

from backend.tests.test_open_agent_runner import _ScriptedModel


def _call(tool_name: str, args: dict | None = None, team_member: str = "coordinator") -> dict:
    return {
        "kind": "tool_call",
        "team_member": team_member,
        "tool_name": tool_name,
        "args": args or {},
        "id": "call-1",
    }


def _result(tool_name: str, content, team_member: str = "coordinator") -> dict:
    return {
        "kind": "tool_result",
        "team_member": team_member,
        "tool_name": tool_name,
        "content": content,
        "id": "call-1",
    }


def test_nonretryable_failed_tool_result_is_a_mechanical_rejection():
    assert (
        rejected_tool_result(
            _result(
                "search_jobs",
                {"ok": False, "retryable": False, "failure_code": "index_unavailable"},
            )
        )
        is True
    )
    assert (
        rejected_tool_result(
            _result(
                "search_jobs",
                {"ok": False, "retryable": True, "failure_code": "transport_timeout"},
            )
        )
        is False
    )


def test_a_tool_call_keeps_the_summary_shape_the_panel_parses():
    summary, detail = describe_progress(_call("read_shortlist"))

    assert summary == "coordinator called read_shortlist."
    assert detail["tool_name"] == "read_shortlist"
    assert detail["stage"] == "call"


def test_a_persona_is_named_as_the_member_that_ran_the_tool():
    summary, _ = describe_progress(_call("read_target_job", team_member="ats"))

    assert summary == "ats called read_target_job."


def test_a_search_call_never_exposes_the_query_it_ran():
    _, detail = describe_progress(_call("search_jobs", {"query": "semiconductor yield analytics engineer"}))

    assert "query" not in detail


def test_a_search_call_exposes_constraints_without_company_text():
    _, detail = describe_progress(
        _call(
            "search_jobs",
            {
                "query": "quality transformation",
                "company": "Micron",
                "direct_employers_only": True,
            },
        )
    )

    assert detail["company_filter_applied"] is True
    assert detail["direct_employers_only"] is True
    assert "company" not in detail


def test_a_call_with_no_query_carries_none():
    _, detail = describe_progress(_call("propose_resume_edit", {"block_id": "b1", "rewrite": "x"}))

    assert "query" not in detail


def test_an_unbounded_query_never_reaches_the_panel():
    _, detail = describe_progress(_call("search_jobs", {"query": "yield " * 200}))

    assert "query" not in detail


def test_trace_attributes_never_persist_query_text_even_when_it_looks_safe():
    safe = trace_attributes(
        _call("search_jobs", {"query": "yield " * 100, "exclude_junior": True}),
        {"tool_name": "search_jobs", "stage": "call"},
    )
    private = trace_attributes(
        _call("search_jobs", {"query": "roles for person@example.com"}),
        {"tool_name": "search_jobs", "stage": "call"},
    )

    assert "query" not in safe
    assert "query_redacted" not in safe
    assert "query" not in private
    assert "query_redacted" not in private


def test_activity_operation_ids_are_not_mislabeled_as_trace_spans():
    attributes = trace_attributes(
        _call("search_jobs"),
        {"tool_name": "search_jobs", "stage": "call"},
    )

    assert attributes["operation_id"] == "call-1"
    assert "span_id" not in attributes


def test_legacy_span_attribute_projects_to_the_operation_contract():
    projected = to_activity_event(SimpleNamespace(
        sequence=1,
        run_id="run-1",
        event_type="conversation",
        status="running",
        team_member="coordinator",
        attempt=1,
        trace_key="trace-1",
        summary="coordinator called search_jobs.",
        detail={},
        parent_id="run-1",
        duration_ms=None,
        attributes={"span_id": "legacy-call-1"},
        created_at=datetime.now(timezone.utc),
    ))

    assert projected.attributes["span_id"] == "legacy-call-1"
    assert projected.attributes["operation_id"] == "legacy-call-1"


def test_a_coordinator_search_result_reports_how_many_postings_came_back():
    summary, detail = describe_progress(
        _result("search_jobs", json.dumps({"ok": True, "jobs": [{"job_id": 1}, {"job_id": 2}]}))
    )

    assert summary == "coordinator finished search_jobs."
    assert detail == {
        "tool_name": "search_jobs",
        "stage": "result",
        "outcome": "2 matching postings",
        "tool_call_id": "call-1",
        "result_count": 2,
    }


def test_a_search_result_exposes_safe_candidate_funnel_counts():
    _, detail = describe_progress(
        _result(
            "search_jobs",
            {
                "ok": True,
                "jobs": [{"job_id": 1}],
                "candidate_count": 7,
                "eligible_candidate_count": 63,
                "visible_candidate_count": 7,
                "truncated": True,
            },
        )
    )

    assert detail["result_count"] == 1
    assert detail["candidate_count"] == 7
    assert detail["eligible_candidate_count"] == 63
    assert detail["visible_candidate_count"] == 7
    assert detail["truncated"] is True


def test_the_assessment_search_result_shape_reports_the_same_count():
    """`agent_tool_contract.search_jobs_result` reports `results` and a count."""
    _, detail = describe_progress(_result("search_jobs", {"ok": True, "count": 1, "results": [{"id": 7}]}))

    assert detail["outcome"] == "1 matching posting"


def test_an_empty_search_says_so_rather_than_saying_nothing():
    _, detail = describe_progress(_result("search_jobs", {"ok": True, "jobs": []}))

    assert detail["outcome"] == "0 matching postings"


def test_a_rejected_repeat_search_reports_why_nothing_came_back():
    _, detail = describe_progress(
        _result(
            "search_jobs",
            {"ok": False, "failure_type": "validation", "reason": "identical_call_no_new_information"},
        )
    )

    assert detail["outcome"] == "tool completed without an accepted result"


def test_a_failed_search_reports_the_failure_type_when_there_is_no_reason():
    _, detail = describe_progress(_result("search_jobs", {"ok": False, "failure_type": "timeout"}))

    assert detail["outcome"] == "tool completed without an accepted result"
    assert detail["failure_type"] == "timeout"


def test_a_failed_tool_result_keeps_only_safe_recovery_metadata():
    _, detail = describe_progress(
        _result(
            "search_jobs",
            {
                "ok": False,
                "failure_type": "validation",
                "failure_code": "structured_output_invalid",
                "retryable": True,
                "recovery_action": "retry_tool",
                "validation_code": "jobs:missing",
                "raw_output": "private model content",
            },
        )
    )

    assert detail["failure_code"] == "structured_output_invalid"
    assert detail["retryable"] is True
    assert detail["recovery_action"] == "retry_tool"
    assert detail["validation_code"] == "jobs:missing"
    assert "raw_output" not in detail


def test_read_shortlist_reports_both_lists_rather_than_half_the_truth():
    _, detail = describe_progress(
        _result(
            "read_shortlist",
            {"ok": True, "recommendations": [{}, {}, {}], "shortlisted_jobs": [{}]},
        )
    )

    assert detail["outcome"] == "3 found earlier, 1 shortlisted"


def test_an_accepted_edit_says_it_is_still_pending():
    _, detail = describe_progress(
        _result("propose_resume_edit", {"accepted": True, "application_status": "pending_user_review"})
    )

    assert detail["outcome"] == "one resume edit drafted, waiting on your approval"


def test_a_published_shortlist_is_not_misreported_as_a_resume_edit():
    _, detail = describe_progress(_result("write_shortlist", {"accepted": True, "published_job_ids": [12, 34]}))

    assert detail["outcome"] == "2 roles ranked with resume evidence"


def test_a_plan_update_reports_the_visible_artifact_size():
    _, detail = describe_progress(_result("write_plan", {"accepted": True, "recorded": 3, "changed": True}))

    assert detail["outcome"] == "plan updated with 3 steps"


def test_a_rejected_edit_reports_the_gate_that_rejected_it():
    _, detail = describe_progress(
        _result("propose_resume_edit", {"accepted": False, "reason": "Unsupported numeric facts: 40"})
    )

    assert detail["outcome"] == "no resume edit passed the evidence gate"


def test_an_unbounded_rejection_reason_is_not_exposed():
    _, detail = describe_progress(_result("propose_resume_edit", {"accepted": False, "reason": "gate failed. " * 50}))

    assert detail["outcome"] == "no resume edit passed the evidence gate"
    assert "gate failed" not in detail["outcome"]


def test_a_model_message_produces_no_activity_row():
    """Invariant 9. A plain model message is reasoning, not a conclusion."""
    assert (
        describe_progress({"kind": "message", "team_member": "coordinator", "content": "Let me think about this."})
        is None
    )


def test_a_model_attempt_produces_metadata_only_activity():
    summary, detail = describe_progress(
        {
            "kind": "model_attempt",
            "team_member": "recruiter",
            "id": "model-step-1",
            "model": "provider-model",
            "input_tokens": 123,
            "output_tokens": 45,
            "content": "private model output",
        }
    )

    assert summary == "recruiter completed a model step."
    assert detail == {"stage": "model", "model_attempt_id": "model-step-1"}
    assert "provider-model" not in json.dumps(detail)
    assert "123" not in json.dumps(detail)
    assert "private model output" not in json.dumps(detail)


def test_durable_activity_metadata_drops_pause_and_model_content():
    public = public_detail(
        {
            "stage": "paused",
            "question": "What confidential project did you lead?",
            "answer": "The confidential answer",
            "pause_token": "checkpoint-capability-token",
            "specialist_runs": [{"summary": "private finding"}],
            "synthesis": "private synthesis",
            "proposed_edits": [{"rewrite": "private resume text"}],
            "input_tokens": 123,
            "output_tokens": 45,
            "question_count": 1,
        },
    )

    assert public == {"stage": "paused", "question_count": 1}


def test_every_tool_result_produces_a_content_free_completion_row():
    for content in ({"ok": True, "target_job": {"title": "X"}}, "not json at all", None):
        summary, detail = describe_progress(_result("read_target_job", content))
        assert summary == "coordinator finished read_target_job."
        assert detail["outcome"] == "tool completed"
        assert "title" not in json.dumps(detail)


def test_no_posting_text_travels_through_a_result_row():
    """Counts, not content. Scraped job text is untrusted and stays out."""
    _, detail = describe_progress(
        _result(
            "search_jobs",
            {
                "ok": True,
                "jobs": [
                    {
                        "job_id": 1,
                        "title": "Yield Enhancement Engineer",
                        "company": "Micron",
                        "description": "Own wafer yield across three fabs.",
                    }
                ],
            },
        )
    )

    rendered = json.dumps(detail)
    assert "Micron" not in rendered
    assert "Yield Enhancement Engineer" not in rendered
    assert "wafer" not in rendered


def test_the_search_graph_streams_the_count_that_came_back(monkeypatch):
    """End to end through the real graph, not through describe_progress directly.

    Before this, the runner published `{"tool_name": ...}` and dropped every
    tool result that was not a persona submission, so a candidate watching a
    search could see only that "searching" happened.
    """
    import resume_agent.models as agent_models
    import resume_agent.tools as agent_tools
    from resume_agent.agent import create_resume_agent
    from recruitment_team.open_agent.streaming import iter_progress_events
    from recruitment_team.tool_call_guard import ToolCallGuardMiddleware

    monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "test-key")

    class FakeDb:
        def close(self):
            return None

    monkeypatch.setattr(agent_tools, "SessionLocal", lambda: FakeDb())
    monkeypatch.setattr(agent_tools, "encode_text", lambda _query: [0.1, 0.2])
    monkeypatch.setattr(agent_tools, "find_similar_jobs", lambda *_a, **_k: [])

    search = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "search_jobs",
                "args": {
                    "query": "semiconductor yield analytics engineer",
                    "n": None,
                    "detail": False,
                    # This test isolates event streaming; its FakeDb deliberately
                    # has no query interface for eligibility filtering.
                    "singapore_only": False,
                },
                "id": "call-1",
            }
        ],
    )
    graph = create_resume_agent(
        model=_ScriptedModel(responses=[search, AIMessage(content="Done.")]),
        tools=[agent_tools.search_jobs],
        subagents=[],
        middleware=[ToolCallGuardMiddleware()],
    )

    events = list(
        iter_progress_events(
            graph,
            {"messages": [{"role": "user", "content": "Find matching roles."}]},
            {"recursion_limit": 12},
        )
    )
    progress = [row for event in events if (row := describe_progress(event)) is not None]
    by_stage = {detail.get("stage"): (summary, detail) for summary, detail in progress}

    assert by_stage["call"][0] == "coordinator called search_jobs."
    assert "query" not in by_stage["call"][1]
    assert by_stage["result"][1]["outcome"] == "0 matching postings"


class _ToolStepModel:
    """A conversation model that reports tool steps the way the loop will.

    The loop itself is #146's other half. What this asserts is the half
    `RecruitmentTeam` owns: that it hands the turn a sink at all, and that each
    step reaching that sink becomes a committed, published activity event.
    """

    def __init__(self, steps: list[dict], reply: str):
        self._steps = steps
        self._reply = reply
        self.call_count = 0

    def respond(self, messages, resume_text, current_preferences=(), context=None):
        from recruitment_team.conversation_model import ModelReply

        self.call_count += 1
        assert context is not None, "the turn ran without a conversation context"
        assert context.on_event is not None, (
            "the turn ran with no activity sink, so no tool step could ever be published"
        )
        for step in self._steps:
            context.on_event(step)
        return ModelReply(content=self._reply, model_name="scripted-loop")


def test_a_conversational_turn_publishes_one_activity_row_per_tool_step():
    from recruitment_team import RecruitmentTeam
    from recruitment_team.activity_publisher import RecordedActivityPublisher
    from recruitment_team.interface import StartThread
    from recruitment_team.telemetry import RecordedTelemetry

    from backend.tests.test_recruitment_team_module import (
        _candidate_profile_run,
        _discovery,
        _owner_with_resume,
        _role_profiler,
        _session_factory,
    )

    model = _ToolStepModel(
        steps=[
            _call("search_jobs", {"query": "semiconductor yield analytics engineer"}),
            _result("search_jobs", {"ok": True, "jobs": [{"job_id": 101}, {"job_id": 102}]}),
            _call("read_shortlist"),
            _result("read_shortlist", {"ok": True, "recommendations": [{}, {}], "shortlisted_jobs": []}),
            # Reasoning. It must not become a row.
            {"kind": "message", "team_member": "coordinator", "content": "Now let me weigh these."},
        ],
        reply="Yield Enhancement Engineer at Micron is the closest match.",
    )
    publisher = RecordedActivityPublisher()

    sessions = _session_factory()
    owner_id, resume_id = _owner_with_resume(sessions)
    with sessions() as db:
        from recruitment_team.candidate_profile import ScriptedCandidateProfilerFactory

        team = RecruitmentTeam(
            db,
            model,
            _discovery(),
            _role_profiler(),
            RecordedTelemetry(),
            publisher,
            candidate_profiler_factory_provider=lambda: ScriptedCandidateProfilerFactory(
                [_candidate_profile_run()]
            ),
        )
        receipt = team.execute(
            owner_id,
            StartThread(resume_version_id=resume_id, message="Find me yield roles."),
            idempotency_key="turn-1",
        )

    # A fresh session, so this reads what the turn really committed rather than
    # what is still pending in the session that wrote it.
    with sessions() as db:
        stored = RecruitmentTeam(db, model, _discovery(), _role_profiler(), RecordedTelemetry(), publisher).events(
            owner_id, receipt.thread_id, after_sequence=0
        )

    steps = [
        event
        for event in publisher.events
        if event.event_type == "conversation" and event.detail.get("tool_name")
    ]
    assert [event.summary for event in steps] == [
        "coordinator called search_jobs.",
        "coordinator finished search_jobs.",
        "coordinator called read_shortlist.",
        "coordinator finished read_shortlist.",
    ]
    assert "query" not in steps[0].detail
    assert steps[1].detail["outcome"] == "2 matching postings"
    assert steps[3].detail["outcome"] == "2 found earlier, 0 shortlisted"

    # buildRoster sorts on sequence, so a duplicate or a gap reorders the trail.
    sequences = [event.sequence for event in publisher.events]
    assert sequences == sorted(sequences)
    assert len(set(sequences)) == len(sequences)

    # Between the run's own two events, not after the turn finished.
    run_events = [event for event in publisher.events if event.event_type == "run"]
    assert run_events[0].sequence < steps[0].sequence < run_events[-1].sequence

    # The rows outlive the session that wrote them, so reopening the thread
    # replays the same trail the live stream showed.
    assert [
        event.summary
        for event in stored
        if event.event_type == "conversation" and event.detail.get("tool_name")
    ] == [
        event.summary for event in steps
    ]

    assert "Now let me weigh these." not in " ".join(event.summary for event in publisher.events)
