"""What the candidate is allowed to read off the activity panel.

`describe_progress` is the single place both agent loops turn a raw stream event
into an activity row, so this is where the never-leak-reasoning invariant is
enforced for that surface: a query the model wrote and counts derived here go
out, a tool's raw return value and a model's plain message do not.
"""

from __future__ import annotations

import json

import config
from langchain_core.messages import AIMessage

from recruitment_team.assessment_contracts import TargetAssessmentProgress
from recruitment_team.open_agent.runner import OpenAgentTargetAssessmentRunner
from recruitment_team.open_agent.streaming import MAX_ACTIVITY_TEXT_CHARS, describe_progress
from recruitment_team.telemetry import RecordedTelemetry

from backend.tests.test_open_agent_runner import _ScriptedModel, _judge_call, _request


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
    }


# ── which tool ran ───────────────────────────────────────────────────────────


def test_a_tool_call_keeps_the_summary_shape_the_panel_parses():
    summary, detail = describe_progress(_call("read_shortlist"))

    assert summary == "coordinator called read_shortlist."
    assert detail["tool_name"] == "read_shortlist"
    assert detail["stage"] == "call"


def test_a_persona_is_named_as_the_member_that_ran_the_tool():
    summary, _ = describe_progress(_call("read_target_job", team_member="ats"))

    assert summary == "ats called read_target_job."


# ── what it looked for ───────────────────────────────────────────────────────


def test_a_search_call_carries_the_query_it_ran():
    _, detail = describe_progress(
        _call("search_jobs", {"query": "semiconductor yield analytics engineer"})
    )

    assert detail["query"] == "semiconductor yield analytics engineer"


def test_a_call_with_no_query_carries_none():
    _, detail = describe_progress(_call("propose_resume_edit", {"block_id": "b1", "rewrite": "x"}))

    assert "query" not in detail


def test_an_unbounded_query_is_clipped_before_it_reaches_the_panel():
    _, detail = describe_progress(_call("search_jobs", {"query": "yield " * 200}))

    assert len(detail["query"]) <= MAX_ACTIVITY_TEXT_CHARS


# ── what came back ───────────────────────────────────────────────────────────


def test_a_coordinator_search_result_reports_how_many_postings_came_back():
    summary, detail = describe_progress(
        _result("search_jobs", json.dumps({"ok": True, "jobs": [{"job_id": 1}, {"job_id": 2}]}))
    )

    assert summary == "coordinator finished search_jobs."
    assert detail == {"tool_name": "search_jobs", "stage": "result", "outcome": "2 matching postings"}


def test_the_assessment_search_result_shape_reports_the_same_count():
    """`agent_tool_contract.search_jobs_result` reports `results` and a count."""
    _, detail = describe_progress(
        _result("guarded_search_jobs", {"ok": True, "count": 1, "results": [{"id": 7}]})
    )

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

    assert detail["outcome"] == "nothing returned (identical call no new information)"


def test_a_failed_search_reports_the_failure_type_when_there_is_no_reason():
    _, detail = describe_progress(_result("search_jobs", {"ok": False, "failure_type": "timeout"}))

    assert detail["outcome"] == "nothing returned (timeout)"


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


def test_a_rejected_edit_reports_the_gate_that_rejected_it():
    _, detail = describe_progress(
        _result("propose_resume_edit", {"accepted": False, "reason": "Unsupported numeric facts: 40"})
    )

    assert detail["outcome"] == "no edit drafted (Unsupported numeric facts: 40)"


def test_an_unbounded_rejection_reason_is_clipped():
    _, detail = describe_progress(
        _result("propose_resume_edit", {"accepted": False, "reason": "gate failed. " * 50})
    )

    assert len(detail["outcome"]) <= MAX_ACTIVITY_TEXT_CHARS


# ── what never reaches the panel ─────────────────────────────────────────────


def test_a_model_message_produces_no_activity_row():
    """Invariant 9. A plain model message is reasoning, not a conclusion."""
    assert describe_progress(
        {"kind": "message", "team_member": "coordinator", "content": "Let me think about this."}
    ) is None


def test_a_result_with_nothing_countable_produces_no_row_rather_than_an_empty_one():
    assert describe_progress(_result("read_target_job", {"ok": True, "target_job": {"title": "X"}})) is None
    assert describe_progress(_result("some_tool", "not json at all")) is None
    assert describe_progress(_result("some_tool", None)) is None


def test_no_posting_text_travels_through_a_result_row():
    """Counts, not content. Scraped job text is untrusted and stays out."""
    _, detail = describe_progress(
        _result(
            "search_jobs",
            {
                "ok": True,
                "jobs": [
                    {"job_id": 1, "title": "Yield Enhancement Engineer", "company": "Micron",
                     "description": "Own wafer yield across three fabs."}
                ],
            },
        )
    )

    rendered = json.dumps(detail)
    assert "Micron" not in rendered
    assert "Yield Enhancement Engineer" not in rendered
    assert "wafer" not in rendered


# ── the runner really publishes them ─────────────────────────────────────────


def test_the_runner_streams_the_query_it_searched_for_and_the_count_that_came_back(monkeypatch):
    """End to end through the real graph, not through describe_progress directly.

    Before this, the runner published `{"tool_name": ...}` and dropped every
    tool result that was not a persona submission, so a candidate watching a
    search could see only that "searching" happened.
    """
    import resume_agent.models as agent_models
    import resume_agent.tools as agent_tools

    monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "test-key")
    monkeypatch.setattr(config, "AGENT_MAX_TOOL_ITERATIONS", 6)

    class FakeDb:
        def close(self):
            return None

    monkeypatch.setattr(agent_tools, "SessionLocal", lambda: FakeDb())
    monkeypatch.setattr(agent_tools, "encode_text", lambda _query: [0.1, 0.2])
    monkeypatch.setattr(agent_tools, "find_similar_jobs", lambda *_a, **_k: [])

    search = AIMessage(
        content="",
        tool_calls=[{
            "name": "guarded_search_jobs",
            "args": {"query": "semiconductor yield analytics engineer", "n": None, "detail": False},
            "id": "call-1",
        }],
    )
    runner = OpenAgentTargetAssessmentRunner(
        model_factory=lambda: _ScriptedModel(responses=[search, AIMessage(content="Done.")]),
        judge_model_factory=lambda: _ScriptedModel(responses=[_judge_call()]),
        telemetry=RecordedTelemetry(),
    )

    progress = [
        item for item in runner.run(_request()) if isinstance(item, TargetAssessmentProgress)
    ]
    by_stage = {item.detail.get("stage"): item for item in progress if item.detail.get("tool_name")}

    assert by_stage["call"].summary == "coordinator called guarded_search_jobs."
    assert by_stage["call"].detail["query"] == "semiconductor yield analytics engineer"
    assert by_stage["result"].detail["outcome"] == "0 matching postings"
    assert by_stage["result"].status == "running", (
        "a mid-run tool result must not mark the coordinator row as reported"
    )


# ── the conversational turn publishes them ───────────────────────────────────


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
        team = RecruitmentTeam(
            db, model, _discovery(), _role_profiler(), RecordedTelemetry(), publisher
        )
        receipt = team.execute(
            owner_id,
            StartThread(resume_version_id=resume_id, message="Find me yield roles."),
            idempotency_key="turn-1",
        )

    # A fresh session, so this reads what the turn really committed rather than
    # what is still pending in the session that wrote it.
    with sessions() as db:
        stored = RecruitmentTeam(
            db, model, _discovery(), _role_profiler(), RecordedTelemetry(), publisher
        ).events(owner_id, receipt.thread_id, after_sequence=0)

    steps = [event for event in publisher.events if event.event_type == "conversation"]
    assert [event.summary for event in steps] == [
        "coordinator called search_jobs.",
        "coordinator finished search_jobs.",
        "coordinator called read_shortlist.",
        "coordinator finished read_shortlist.",
    ]
    assert steps[0].detail["query"] == "semiconductor yield analytics engineer"
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
    assert [event.summary for event in stored if event.event_type == "conversation"] == [
        event.summary for event in steps
    ]

    assert "Now let me weigh these." not in " ".join(event.summary for event in publisher.events)
