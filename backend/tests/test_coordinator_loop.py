"""Specification for #146: the conversational coordinator runs a tool loop.

Design: `docs/v4-146-coordinator-loop.md`.

Every test marked `_XFAIL_146` fails today, because the production symbols it
imports do not exist. They are the specification, not a regression net. The
marker is `strict=True` on purpose: the moment the loop works, an XPASS turns the
suite red and the marker has to come off. A non-strict xfail is an optional
assertion, and this repo has already paid for an optional field.

`test_scripted_deep_agent_drives_a_real_graph_today` is deliberately NOT xfail.
It guards the harness. Without it, a broken double would make every xfail above
pass for the wrong reason and nobody would know.

What the tests deliberately do NOT do: assert on a status code, assert on a reply
string I scripted myself as if it were evidence of reasoning, or accept a call
count as proof that a tool result reached the model. Where the claim is "the
agent read its own results", the assertion is on the message list the model was
handed.
"""

from __future__ import annotations

import json

import pytest

from backend.tests.scripted_deep_agent import ScriptedDeepAgent, final, submission, tool_call


_XFAIL_146 = pytest.mark.xfail(
    reason=(
        "#146: DeepAgentConversationModel, ConversationContext and the coordinator "
        "tools (read_shortlist, search_jobs) are not implemented yet"
    ),
    strict=True,
)


# ── fixtures ─────────────────────────────────────────────────────────────────


RESUME_TEXT = "Led team of 12 engineers building semiconductor yield analytics."

RESUME_DOCUMENT = {
    "schema_version": 1,
    "revision": "rev-1",
    "raw_text": RESUME_TEXT,
    "blocks": [
        {
            "id": "b1",
            "text": "Led team of 12 engineers.",
            "section_key": "experience",
            "entry_id": "e1",
        }
    ],
}


def _job(job_id: int, title: str, company: str, seniority: str = "Professional"):
    from recruitment_team.discovery import JobSnapshot, JobSource

    return JobSnapshot(
        job_id=job_id,
        title=title,
        company=company,
        location="Singapore",
        salary="$10,000 - $15,000",
        employment_type="Full Time",
        seniority=seniority,
        description=f"{title} role at {company}.",
        skills=("Python", "Semiconductor"),
        similarity_score=0.9,
        source=JobSource(
            source="MyCareersFuture",
            url=f"https://example.test/jobs/{job_id}",
            source_posting_id=f"MCF-{job_id}",
            posted_date="2026-07-03",
            closing_date="2026-08-03",
            scraped_at="2026-07-19T00:00:00Z",
            availability="current",
            snapshot_sha256="a" * 64,
        ),
    )


def _search_result(jobs):
    from recruitment_team.discovery import JobSearchResult

    return JobSearchResult(
        query="",
        jobs=tuple(jobs),
        candidate_count=len(jobs),
        visible_candidate_count=len(jobs),
        truncated=False,
        valid_empty=not jobs,
    )


class _RecordingDiscovery:
    """Wraps ScriptedDiscovery to capture the exact args the loop searched with."""

    def __init__(self, results):
        from recruitment_team.discovery import ScriptedDiscovery

        self._inner = ScriptedDiscovery(list(results))
        self.calls: list[dict] = []

    def search_jobs(self, query: str, exclude_junior: bool = False):
        self.calls.append({"query": query, "exclude_junior": exclude_junior})
        return self._inner.search_jobs(query, exclude_junior=exclude_junior)

    def get_job(self, job_id: int):
        return self._inner.get_job(job_id)

    @property
    def search_count(self) -> int:
        return len(self.calls)


def _context(discovery, *, recommendations=(), shortlisted=(), events=None, **overrides):
    from recruitment_team import ConversationContext

    kwargs = {
        "thread_id": 1,
        "trace_key": "coordinator-loop-trace",
        "candidate_profile": None,
        "role_profile": None,
        "target_job": None,
        "resume_document": RESUME_DOCUMENT,
        "latest_search_query": "",
        "recommendations": tuple(recommendations),
        "shortlisted_jobs": tuple(shortlisted),
        "preferences": (),
        "wants_experienced_roles": True,
        "discovery": discovery,
        "on_event": (events.append if events is not None else None),
    }
    kwargs.update(overrides)
    return ConversationContext(**kwargs)


def _model(agent, discovery):
    from recruitment_team import DeepAgentConversationModel

    return DeepAgentConversationModel(discovery=discovery, model_factory=lambda: agent)


def _tool_results(events, tool_name):
    """Tool return values as the graph really produced them, decoded."""
    out = []
    for item in events:
        if item.get("kind") == "tool_result" and item.get("tool_name") == tool_name:
            content = item.get("content")
            out.append(json.loads(content) if isinstance(content, str) else content)
    return out


def _rendered(request) -> str:
    """Flatten one recorded model request into searchable text."""
    return "\n".join(str(getattr(message, "content", "")) for message in request)


# ── the harness itself, guarded ──────────────────────────────────────────────


def test_scripted_deep_agent_drives_a_real_graph_today(monkeypatch):
    """The double must drive a genuine deep-agent graph, with real tool execution.

    Not xfail. If this breaks, every xfail below would start passing for reasons
    that have nothing to do with #146.
    """
    import resume_agent.models as agent_models
    from langchain_core.tools import tool

    from resume_agent.agent import create_resume_agent
    from recruitment_team.open_agent.streaming import iter_progress_events

    monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "test-key")

    executed: list[str] = []

    @tool
    def echo(text: str) -> dict:
        """Echo the supplied text back."""
        executed.append(text)
        return {"ok": True, "echoed": text}

    agent = ScriptedDeepAgent(
        responses=[tool_call("echo", {"text": "hello"}, "call-1"), final("done")]
    )
    graph = create_resume_agent(model=agent, tools=[echo], subagents=[])

    events = list(
        iter_progress_events(
            graph,
            {"messages": [{"role": "user", "content": "Say hello."}]},
            {"recursion_limit": 20},
        )
    )

    assert executed == ["hello"], "the tool must really execute, not be simulated"
    assert _tool_results(events, "echo") == [{"ok": True, "echoed": "hello"}]
    assert [item["kind"] for item in events] == ["tool_call", "tool_result", "message"]
    assert agent.consumed == 2
    # deepagents binds its own builtins alongside ours; ours has to be in there.
    assert "echo" in agent.bound_tool_names[0]
    # The tool result really came back to the model, so a scripted decision can
    # depend on it.
    assert "hello" in _rendered(agent.requests[1])


def test_scripted_deep_agent_raises_instead_of_wrapping_when_the_script_runs_out():
    """A short script must be a loud failure, never a silent replay."""
    agent = ScriptedDeepAgent(responses=[final("only one")])
    agent._generate([])
    with pytest.raises(AssertionError, match="ran out of script on call 2"):
        agent._generate([])


# ── the specification ────────────────────────────────────────────────────────


@_XFAIL_146
def test_search_then_read_then_reply_persists_the_shortlist_and_names_a_job(monkeypatch):
    """The bug in one test.

    One turn: the coordinator searches, the results come back into its own
    context, and it answers naming a job. Today the coordinator cannot search,
    and a `SearchJobs` command's results never reach it at all.
    """
    import resume_agent.models as agent_models

    from backend.tests.test_recruitment_team_module import (
        _owner_with_resume,
        _role_profiler,
        _session_factory,
    )
    from recruitment_team import RecruitmentTeam
    from recruitment_team.activity_publisher import RecordedActivityPublisher
    from recruitment_team.interface import StartThread
    from recruitment_team.telemetry import RecordedTelemetry

    monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "test-key")

    discovery = _RecordingDiscovery(
        [_search_result([_job(101, "Yield Enhancement Engineer", "Micron")])]
    )
    agent = ScriptedDeepAgent(
        responses=[
            tool_call(
                "search_jobs",
                {"query": "semiconductor yield analytics engineer", "exclude_junior": True},
                "call-1",
            ),
            tool_call("read_shortlist", {}, "call-2"),
            submission(
                "Yield Enhancement Engineer at Micron is the closest match to the "
                "yield analytics work on your resume."
            ),
            final("submitted"),
        ]
    )

    sessions = _session_factory()
    owner_id, resume_id = _owner_with_resume(sessions)
    with sessions() as db:
        team = RecruitmentTeam(
            db,
            _model(agent, discovery),
            discovery,
            _role_profiler(),
            RecordedTelemetry(),
            RecordedActivityPublisher(),
        )
        receipt = team.execute(
            owner_id,
            StartThread(
                resume_version_id=resume_id,
                message="Find me roles that use my yield analytics work.",
            ),
            idempotency_key="turn-1",
        )
        snapshot = team.snapshot(owner_id, receipt.thread_id)

    # The search really ran, through the port, with the parameter the agent chose.
    assert discovery.calls == [
        {"query": "semiconductor yield analytics engineer", "exclude_junior": True}
    ]

    # The results landed in the thread, in the shape _known_job resolves against.
    # Without this, the next ShortlistJob click is a 422, not just a stale panel.
    assert [job.job_id for job in snapshot.case_facts.recommendations] == [101]
    assert snapshot.case_facts.recommendations[0].title == "Yield Enhancement Engineer"
    assert snapshot.case_facts.latest_search_query == "semiconductor yield analytics engineer"

    # The load-bearing assertion: the posting reached the model. The title exists
    # nowhere in the transcript, the resume or the system prompt -- only in the
    # tool result. If it is in the request, the coordinator read its own results.
    assert "Micron" in _rendered(agent.requests[2])
    assert "Yield Enhancement Engineer" in _rendered(agent.requests[2])

    # And the candidate sees a reply that names it, rather than being asked to
    # paste a job description.
    assert "Micron" in snapshot.messages[-1].content
    assert "paste" not in snapshot.messages[-1].content.lower()

    # search_query records the query that really ran, not one the model requested.
    assert snapshot.case_facts.latest_search_query == discovery.calls[-1]["query"]
    assert agent.consumed == 4


@_XFAIL_146
def test_a_second_search_in_one_turn_is_chosen_after_reading_the_first_results(monkeypatch):
    """The agent decides to search again by reading its own results.

    No exclusion predicate and no ranking formula: what makes the second query
    different is that the first result set was in the model's context when it
    chose the second one.
    """
    import resume_agent.models as agent_models

    monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "test-key")

    discovery = _RecordingDiscovery(
        [
            _search_result(
                [
                    _job(201, "Graduate Trainee, Process", "HRNET Ventures", seniority="Junior"),
                    _job(202, "Intern, Data", "BOK SENG Logistics", seniority="Junior"),
                ]
            ),
            _search_result([_job(203, "Staff Yield Engineer", "NXP")]),
        ]
    )
    agent = ScriptedDeepAgent(
        responses=[
            tool_call("search_jobs", {"query": "data engineer", "exclude_junior": False}, "call-1"),
            tool_call(
                "search_jobs",
                {"query": "staff semiconductor yield engineer", "exclude_junior": True},
                "call-2",
            ),
            submission("Staff Yield Engineer at NXP fits your level; the first pass returned trainee roles."),
            final("submitted"),
        ]
    )
    events: list[dict] = []
    context = _context(discovery, events=events)

    reply = _model(agent, discovery).respond([], RESUME_TEXT, (), context)

    assert discovery.search_count == 2
    assert discovery.calls[0]["query"] != discovery.calls[1]["query"]

    # The first result set was in front of the model when it chose the second
    # query. That, and not the count, is what "read its own results" means.
    second_decision_request = _rendered(agent.requests[1])
    assert "HRNET Ventures" in second_decision_request
    assert "Graduate Trainee, Process" in second_decision_request

    # Both searches in one turn land in the thread sink, newest first, deduped.
    assert [job.job_id for result in context.search_results for job in result.jobs] == [
        201,
        202,
        203,
    ]
    assert reply.search_query == "staff semiconductor yield engineer"
    assert agent.consumed == 4


@_XFAIL_146
def test_has_repeated_call_rejects_a_materially_identical_repeat_within_a_turn(monkeypatch):
    """Guardrails limit volume, never choice.

    An identical repeat never reaches the discovery port. A materially different
    query does, so the guardrail is not quietly blocking a second search.
    """
    import resume_agent.models as agent_models

    monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "test-key")

    same = {"query": "semiconductor yield engineer", "exclude_junior": True}
    other = {"query": "process integration engineer", "exclude_junior": True}
    discovery = _RecordingDiscovery(
        [_search_result([_job(301, "Yield Engineer", "Micron")]),
         _search_result([_job(302, "Process Integration Engineer", "Avago")])]
    )
    agent = ScriptedDeepAgent(
        responses=[
            tool_call("search_jobs", dict(same), "call-1"),
            tool_call("search_jobs", dict(same), "call-2"),
            tool_call("search_jobs", dict(other), "call-3"),
            submission("Two distinct searches; the duplicate added nothing."),
            final("submitted"),
        ]
    )
    events: list[dict] = []

    _model(agent, discovery).respond([], RESUME_TEXT, (), _context(discovery, events=events))

    results = _tool_results(events, "search_jobs")
    assert len(results) == 3
    assert results[0].get("reason") != "identical_call_no_new_information"
    assert results[1]["ok"] is False
    assert results[1]["reason"] == "identical_call_no_new_information"
    assert results[2].get("reason") != "identical_call_no_new_information"

    # Only the two allowed calls reached the port. The rejected one never did.
    assert [call["query"] for call in discovery.calls] == [same["query"], other["query"]]
    assert agent.consumed == 5


@_XFAIL_146
def test_iteration_cap_returns_a_stopped_marker_and_never_raises(monkeypatch):
    """`GraphRecursionError` must not escape, and the turn must not fabricate a reply.

    HTTP 200 is not an acceptance criterion: a turn that never produced a
    submission is a 503, not a cheerful empty answer.
    """
    import config
    import resume_agent.models as agent_models

    from recruitment_team.errors import ConversationUnavailable

    monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "test-key")
    monkeypatch.setattr(config, "COORDINATOR_MAX_TOOL_ITERATIONS", 4)

    discovery = _RecordingDiscovery([])
    # repeat_last makes the agent call read_shortlist forever, which is exactly
    # the run that blows through a recursion limit without ever submitting.
    agent = ScriptedDeepAgent(
        responses=[tool_call("read_shortlist", {}, "call-loop")], repeat_last=True
    )
    model = _model(agent, discovery)
    context = _context(discovery)

    outcome = model.drive(context, [], RESUME_TEXT)

    assert outcome["stopped"] is True
    assert outcome["reason"] == "tool_iteration_cap"

    with pytest.raises(ConversationUnavailable):
        model.respond([], RESUME_TEXT, (), _context(discovery))


@_XFAIL_146
def test_ask_candidate_pauses_before_any_further_tool_runs_and_the_answer_resumes_it(monkeypatch):
    """The interrupt, not the prompt, is what stops the next tool.

    Turn 1 scripts `ask_candidate` immediately followed by `search_jobs`. If the
    pause were prompt convention, the search would run on a guess. It must not.
    Turn 2's answer resumes the same checkpointed graph and the search then runs.
    """
    import resume_agent.models as agent_models

    from backend.tests.test_recruitment_team_module import (
        _owner_with_resume,
        _role_profiler,
        _session_factory,
    )
    from recruitment_team import RecruitmentTeam
    from recruitment_team.activity_publisher import RecordedActivityPublisher
    from recruitment_team.interface import SendMessage, StartThread
    from recruitment_team.telemetry import RecordedTelemetry

    monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "test-key")

    discovery = _RecordingDiscovery(
        [_search_result([_job(401, "Staff Yield Engineer", "NXP")])]
    )
    agent = ScriptedDeepAgent(
        responses=[
            tool_call(
                "ask_candidate",
                {"questions": ["Are you open to roles outside semiconductors?"]},
                "call-ask",
            ),
            # Scripted next, and must NOT run during turn 1.
            tool_call(
                "search_jobs",
                {"query": "staff yield engineer semiconductor", "exclude_junior": True},
                "call-search",
            ),
            submission("Staff Yield Engineer at NXP keeps you in semiconductors, as you asked."),
            final("submitted"),
        ]
    )

    sessions = _session_factory()
    owner_id, resume_id = _owner_with_resume(sessions)
    with sessions() as db:
        team = RecruitmentTeam(
            db,
            _model(agent, discovery),
            discovery,
            _role_profiler(),
            RecordedTelemetry(),
            RecordedActivityPublisher(),
        )
        first = team.execute(
            owner_id,
            StartThread(resume_version_id=resume_id, message="Find me a role."),
            idempotency_key="turn-1",
        )
        paused_snapshot = team.snapshot(owner_id, first.thread_id)

    assert discovery.search_count == 0, (
        "the graph must pause before the next tool executes; a search that ran here "
        "would mean the pause is prompt convention rather than the interrupt"
    )
    assert agent.consumed == 1
    assert "Are you open to roles outside semiconductors?" in paused_snapshot.messages[-1].content
    # The pause stays invisible to the transport: setting awaiting_candidate_answer
    # would route the next message to the assessment runner's answer command.
    assert paused_snapshot.workflow_state != "awaiting_candidate_answer"
    assert paused_snapshot.case_facts.recommendations == ()

    # A separate session and module instance: the resume rides the durable
    # checkpointer, not a live in-memory graph.
    with sessions() as db:
        team = RecruitmentTeam(
            db,
            _model(agent, discovery),
            discovery,
            _role_profiler(),
            RecordedTelemetry(),
            RecordedActivityPublisher(),
        )
        team.execute(
            owner_id,
            SendMessage(
                thread_id=first.thread_id,
                message="No, keep me in semiconductors.",
            ),
            idempotency_key="turn-2",
        )
        resumed = team.snapshot(owner_id, first.thread_id)

    assert discovery.search_count == 1
    assert [job.job_id for job in resumed.case_facts.recommendations] == [401]
    assert "NXP" in resumed.messages[-1].content
    assert agent.consumed == 4


@_XFAIL_146
def test_propose_resume_edit_rejects_a_new_numeric_fact_and_a_dropped_one(monkeypatch):
    """Invariant 3 holds on the conversational path because it is the same function.

    Three proposals against `Led team of 12 engineers.`:
      1. introduces `40`     -> rejected, the number is named
      2. drops `12`          -> rejected by run_all_gates' fact_preservation gate
      3. rewords, keeps `12` -> accepted, and stays pending
    """
    import resume_agent.models as agent_models

    monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "test-key")

    discovery = _RecordingDiscovery([])
    agent = ScriptedDeepAgent(
        responses=[
            tool_call(
                "propose_resume_edit",
                {"block_id": "b1", "rewrite": "Led a team of 40 engineers."},
                "call-1",
            ),
            tool_call(
                "propose_resume_edit",
                {"block_id": "b1", "rewrite": "Led the platform engineering team."},
                "call-2",
            ),
            tool_call(
                "propose_resume_edit",
                {"block_id": "b1", "rewrite": "Led a team of 12 engineers."},
                "call-3",
            ),
            submission("Drafted one evidence-safe rewrite of your leadership bullet."),
            final("submitted"),
        ]
    )
    events: list[dict] = []
    context = _context(discovery, events=events)

    _model(agent, discovery).respond([], RESUME_TEXT, (), context)

    results = _tool_results(events, "propose_resume_edit")
    assert len(results) == 3

    assert results[0]["accepted"] is False
    assert "40" in results[0]["reason"]

    assert results[1]["accepted"] is False
    assert "fact" in results[1]["reason"].lower() or "12" in results[1]["reason"]

    assert results[2]["accepted"] is True
    assert results[2]["application_status"] == "pending_user_review"

    # Exactly one edit survived, and it is pending. No agent path writes a resume.
    assert len(context.proposed_edits) == 1
    assert context.proposed_edits[0]["status"] == "pending"
    assert context.proposed_edits[0]["rewrite"] == "Led a team of 12 engineers."
    assert agent.consumed == 5
