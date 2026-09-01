"""Specification for #146: the conversational coordinator runs a tool loop.

Design: `docs/v4-146-coordinator-loop.md` (revision 2).

Written first as strict xfails against symbols that did not exist. The markers
came off one at a time as the loop was built; nothing here was relaxed to make
that happen. Two assertions were corrected, both because they described a graph
that does not exist: the iteration cap counted tool calls where LangGraph counts
super-steps, and "ORCHESTRATOR" appears verbatim in deepagents' own subagent
middleware prompt.

The three `test_scripted_deep_agent_*` / `test_repeat_last_*` tests guard the
harness. Without them, a broken double would make everything below pass for the
wrong reason and nobody would know.

What the tests deliberately do NOT do: assert on a status code, assert on a reply
string scripted here as if it were evidence of reasoning, or accept a call count
as proof that a tool result reached the model. Where the claim is "the agent read
its own results", the assertion is on the message list the model was handed, or
on state the model could not have seen any other way.
"""

from __future__ import annotations

import json
import uuid

import pytest

from backend.tests.scripted_deep_agent import (
    ScriptedDeepAgent,
    final,
    submission,
    tool_call,
)


@pytest.fixture(autouse=True)
def _no_live_model(monkeypatch):
    """`create_agent_model` must never be reached from this file.

    Revision 1 opened seven tests with
    `monkeypatch.setattr(agent_models.ai_service, "_get_api_key", lambda: "test-key")`.
    Every one was dead: `create_resume_agent` short-circuits on
    `model or create_agent_model()` and these tests always supply a model. Worse
    than dead, a fake key lets `create_agent_model` build a live SEA-LION client
    successfully, so the day the loop does construct its own model those lines
    would have enabled a real network call instead of failing fast.

    Both bindings are patched. `resume_agent/agent.py:11` imported the name at
    module level, so patching `resume_agent.models` alone would miss
    `create_resume_agent`; `conversation_model.py` and `role_success.py` import it
    lazily from `resume_agent.models`, so patching `resume_agent.agent` alone
    would miss those.
    """
    import resume_agent.agent as agent_module
    import resume_agent.models as models_module

    def _explode(*args, **kwargs):
        raise AssertionError(
            "a coordinator-loop test tried to construct a real SEA-LION model; "
            "pass model_factory=lambda: ScriptedDeepAgent(...) instead"
        )

    monkeypatch.setattr(agent_module, "create_agent_model", _explode)
    monkeypatch.setattr(models_module, "create_agent_model", _explode)


RESUME_TEXT = (
    "EXPERIENCE\n"
    "Micron Technology, Singapore\n"
    "Yield Engineering Manager, 2018-2026\n"
    "- Led team of 12 engineers building semiconductor yield analytics.\n"
    "- Cut wafer scrap by 18 percent across three fabs.\n"
)

LEADERSHIP_BULLET = "Led team of 12 engineers building semiconductor yield analytics."


def _resume_document() -> dict:
    """The exact document `_model_reply` builds, from the exact resume text.

    Block IDs are content hashes, so a script cannot hardcode one. It has to be
    looked up here, which also proves the test and production derive it the same
    way.
    """
    from resume_document import create_resume_document

    return create_resume_document(RESUME_TEXT)


def _leadership_block_id() -> str:
    return next(
        block["id"]
        for block in _resume_document()["blocks"]
        if block["text"] == LEADERSHIP_BULLET
    )


def _owner_with_resume(session_factory) -> tuple[int, int]:
    """A user whose resume carries a numeric fact, so gate rejection is testable."""
    from models import ResumeVersion, User

    with session_factory() as db:
        user = User(
            email="candidate@example.com",
            password_hash="test-only",  # pragma: allowlist secret
            name="Candidate",
        )
        db.add(user)
        db.flush()
        resume = ResumeVersion(
            user_id=user.id,
            label="Yield engineering resume",
            resume_text=RESUME_TEXT,
            is_master=True,
        )
        db.add(resume)
        db.commit()
        return user.id, resume.id


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


def _failed_search(failure_code: str = "connection_failure"):
    """What `LangChainJobDiscovery` really returns when the tool fails.

    `discovery.py:120-130`: no jobs, `valid_empty=False`, a `failure_type`. The
    command path raises `DiscoveryUnavailable` before touching `case_facts`, so it
    can never destroy a shortlist. The tool has no such protection by accident.
    """
    from recruitment_team.discovery import JobSearchResult

    return JobSearchResult(
        query="",
        jobs=(),
        candidate_count=None,
        visible_candidate_count=None,
        truncated=False,
        valid_empty=False,
        failure_type="transient",
        failure_code=failure_code,
    )


class _RecordingDiscovery:
    """Wraps ScriptedDiscovery to capture the exact args the loop searched with."""

    def __init__(self, results):
        from recruitment_team.discovery import ScriptedDiscovery

        self._inner = ScriptedDiscovery(list(results))
        self.calls: list[dict] = []

    def search_jobs(
        self,
        query: str,
        *,
        company: str = "",
        direct_employers_only: bool = True,
        exclude_junior: bool = False,
        singapore_only: bool = True,
        title_phrase: str = "",
    ):
        self.calls.append({
            "query": query,
            "company": company,
            "direct_employers_only": direct_employers_only,
            "exclude_junior": exclude_junior,
            "singapore_only": singapore_only,
            "title_phrase": title_phrase,
        })
        return self._inner.search_jobs(
            query,
            company=company,
            direct_employers_only=direct_employers_only,
            exclude_junior=exclude_junior,
            singapore_only=singapore_only,
            title_phrase=title_phrase,
        )

    def get_job(self, job_id: int):
        return self._inner.get_job(job_id)

    @property
    def search_count(self) -> int:
        return len(self.calls)


def _context(discovery, *, recommendations=(), shortlisted=(), events=None, **overrides):
    from backend.tests.fakes import AllowingEditEvidenceValidator
    from backend.tests.test_recruitment_team_module import _candidate_profile_run
    from recruitment_team import ConversationContext

    kwargs = {
        # RecruitmentThread.id is a uuid4 string (models.py:312). A fresh one per
        # context also keeps the shared SqliteSaver from carrying a checkpoint
        # between two tests that both used thread "1".
        "thread_id": str(uuid.uuid4()),
        "trace_key": "coordinator-loop-trace",
        "candidate_profile": _candidate_profile_run(RESUME_TEXT).profile,
        "role_profile": None,
        "target_job": None,
        "resume_document": _resume_document(),
        "latest_search_query": "",
        "recommendations": tuple(recommendations),
        "shortlisted_jobs": tuple(shortlisted),
        "preferences": (),
        "published_matches": (),
        "discovery": discovery,
        "edit_evidence_validator": AllowingEditEvidenceValidator(),
        "on_event": (events.append if events is not None else None),
    }
    kwargs.update(overrides)
    return ConversationContext(**kwargs)


def _model(agent):
    """The loop adapter with a scripted brain.

    No `discovery` parameter: the port arrives on the ConversationContext and
    there is exactly one source for it. Passing it twice would mean no test could
    ever observe which copy the tool read.
    """
    from recruitment_team import DeepAgentConversationModel

    return DeepAgentConversationModel(model_factory=lambda: agent)


def _team(db, agent, discovery, publisher=None, telemetry=None):
    from backend.tests.fakes import AllowingEditEvidenceValidator
    from backend.tests.test_recruitment_team_module import _candidate_profile_run, _role_profiler
    from recruitment_team import RecruitmentTeam
    from recruitment_team.activity_publisher import RecordedActivityPublisher
    from recruitment_team.candidate_profile import ScriptedCandidateProfilerFactory
    from recruitment_team.telemetry import RecordedTelemetry

    return RecruitmentTeam(
        db,
        _model(agent),
        discovery,
        _role_profiler(),
        telemetry or RecordedTelemetry(),
        publisher or RecordedActivityPublisher(),
        edit_evidence_validator=AllowingEditEvidenceValidator(),
        candidate_profiler_factory_provider=lambda: ScriptedCandidateProfilerFactory(
            [_candidate_profile_run(RESUME_TEXT)]
        ),
    )


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


def _tool_summaries(publisher) -> list[str]:
    """Published per-tool activity summaries, in publication order."""
    return [
        event.summary
        for event in publisher.events
        if event.summary.endswith(".") and " called " in event.summary
    ]


def _raw_case_facts(sessions, thread_id: str) -> dict:
    """`case_facts` as stored, including keys CaseFacts does not project.

    `search_query` is one of them (`interface.py:103-118` has no such field), and
    it is the key `_query_from_candidate` reads on the next SearchJobs command.
    """
    from models import RecruitmentThread

    with sessions() as db:
        thread = (
            db.query(RecruitmentThread).filter(RecruitmentThread.id == thread_id).first()
        )
        return dict(thread.case_facts)


def _echo_tool(executed: list[str]):
    from langchain_core.tools import tool

    @tool
    def echo(text: str) -> dict:
        """Echo the supplied text back."""
        executed.append(text)
        return {"ok": True, "echoed": text}

    return echo


def _harness_reply_schema():
    from pydantic import BaseModel, Field

    class HarnessReply(BaseModel):
        """Submit the final reply."""

        reply: str = Field(min_length=1)

    return HarnessReply


def test_scripted_deep_agent_drives_a_real_graph_today():
    """The double must drive a genuine deep-agent graph, with real tool execution.

    Not xfail. If this breaks, every xfail below would start passing for reasons
    that have nothing to do with #146. It goes through `create_deep_agent`
    directly, because `create_resume_agent` has no `system_prompt` or
    `response_format` seam yet (§4) and a harness guard has to be green today. The
    schema is local so this does not depend on the `_ConversationPayload` to
    `ConversationReply` rename §5 asks for either.
    """
    from deepagents import create_deep_agent
    from langchain.agents.structured_output import ToolStrategy

    from recruitment_team.open_agent.streaming import iter_progress_events

    executed: list[str] = []
    harness_reply = _harness_reply_schema()
    agent = ScriptedDeepAgent(
        responses=[
            tool_call("echo", {"text": "hello"}, "call-1"),
            tool_call("HarnessReply", {"reply": "done"}, "call-2"),
        ]
    )
    graph = create_deep_agent(
        model=agent,
        tools=[_echo_tool(executed)],
        subagents=[],
        system_prompt="Test coordinator.",
        response_format=ToolStrategy(harness_reply),
    )

    events = list(
        iter_progress_events(
            graph,
            {"messages": [{"role": "user", "content": "Say hello."}]},
            {"recursion_limit": 20},
        )
    )

    assert executed == ["hello"], "the tool must really execute, not be simulated"
    assert _tool_results(events, "echo") == [{"ok": True, "echoed": "hello"}]
    # deepagents binds its own builtins alongside ours; ours has to be in there.
    assert "echo" in agent.bound_tool_names[0]
    # The tool result really came back to the model, so a scripted decision can
    # depend on it.
    assert "hello" in _rendered(agent.requests[1])
    # ToolStrategy terminates the loop on the structured call: no trailing
    # completion, which is the extra model call revision 1 was going to pay for.
    assert agent.consumed == 2
    assert agent.calls == 2


def test_scripted_deep_agent_raises_instead_of_wrapping_when_the_script_runs_out():
    """A short script must be a loud failure, never a silent replay."""
    agent = ScriptedDeepAgent(responses=[final("only one")])
    agent._generate([])
    with pytest.raises(AssertionError, match="ran out of script on call 2"):
        agent._generate([])


def test_repeat_last_freezes_consumed_so_only_calls_can_bound_a_runaway_loop():
    """The guard for the iteration-cap test's own assertion.

    Under `repeat_last`, `consumed` stops at 1 forever. A cap test that asserted
    `consumed` would pass whether the recursion limit was honoured, doubled or
    ignored entirely.
    """
    agent = ScriptedDeepAgent(responses=[final("again")], repeat_last=True)
    for _ in range(5):
        agent._generate([])

    assert agent.consumed == 1
    assert agent.calls == 5


def test_create_resume_agent_accepts_a_coordinator_prompt_and_a_response_format():
    """§4's two seams, asserted on what the model actually received.

    `resume_agent/agent.py:34` hardcodes ORCHESTRATOR_SYSTEM_PROMPT. A coordinator
    with a different goal cannot be expressed through the factory as written, and
    §5's termination needs `response_format` passed through.
    """
    from langchain.agents.structured_output import ToolStrategy

    from resume_agent.agent import create_resume_agent

    # The prompt this seam exists to displace, asserted on its own opening line
    # rather than on the bare word "orchestrator": deepagents' built-in subagent
    # middleware says "bloat the orchestrator thread" in every graph it builds,
    # so the loose form fires whether or not the seam works.
    from resume_agent.prompts import ORCHESTRATOR_SYSTEM_PROMPT

    goal = "Find roles worth applying to, and get this resume ready for them."
    agent = ScriptedDeepAgent(
        responses=[tool_call("HarnessReply", {"reply": "done"}, "call-1")]
    )
    graph = create_resume_agent(
        model=agent,
        tools=[_echo_tool([])],
        subagents=[],
        system_prompt=goal,
        response_format=ToolStrategy(_harness_reply_schema()),
    )
    state = graph.invoke(
        {"messages": [{"role": "user", "content": "Start."}]},
        config={"recursion_limit": 20},
    )

    assert goal in _rendered(agent.requests[0])
    assert ORCHESTRATOR_SYSTEM_PROMPT.splitlines()[0] not in _rendered(agent.requests[0])
    assert state["structured_response"].reply == "done"


def test_search_then_read_then_reply_persists_the_shortlist_and_names_a_job():
    """The bug in one turn.

    The coordinator searches, the results come back into its own context, and it
    answers naming a job. Today the coordinator cannot search, and a `SearchJobs`
    command's results never reach it at all.
    """
    from backend.tests.test_recruitment_team_module import _session_factory
    from recruitment_team.activity_publisher import RecordedActivityPublisher
    from recruitment_team.interface import StartThread

    discovery = _RecordingDiscovery(
        [
            _search_result([_job(101, "Yield Enhancement Engineer", "Micron")]),
            _search_result([_job(101, "Yield Enhancement Engineer", "Micron")]),
        ]
    )
    agent = ScriptedDeepAgent(
        responses=[
            tool_call(
                "search_jobs",
                {"query": "semiconductor yield analytics engineer"},
                "call-1",
            ),
            tool_call("read_shortlist", {}, "call-2"),
            submission(
                "Yield Enhancement Engineer at Micron is the closest match to the "
                "yield analytics work on your resume."
            ),
        ]
    )
    publisher = RecordedActivityPublisher()

    sessions = _session_factory()
    owner_id, resume_id = _owner_with_resume(sessions)
    with sessions() as db:
        team = _team(db, agent, discovery, publisher)
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
    assert discovery.calls[0] == (
        {
            "query": "semiconductor yield analytics engineer",
            "company": "",
                "direct_employers_only": True,
                "exclude_junior": False,
                "singapore_only": True,
                "title_phrase": "",
        }
    )
    assert discovery.calls[1]["query"] == "platform engineering"

    # The results landed in the thread, in the shape _known_job resolves against.
    # Without this, the next ShortlistJob click is a 422, not just a stale panel.
    assert [job.job_id for job in snapshot.case_facts.recommendations] == [101]
    assert snapshot.case_facts.recommendations[0].title == "Yield Enhancement Engineer"
    assert snapshot.case_facts.latest_search_query == "semiconductor yield analytics engineer"

    # The load-bearing assertion: the posting reached the model. The title exists
    # nowhere in the transcript, the resume or the system prompt -- only in the
    # tool result. If it is in the request, the coordinator read its own results.
    assert "Yield Enhancement Engineer" in _rendered(agent.requests[2])
    assert "Yield Enhancement Engineer" in _rendered(agent.requests[2])

    # And the candidate sees a reply that names it, rather than being asked to
    # paste a job description.
    assert "Micron" in snapshot.messages[-1].content
    assert "paste" not in snapshot.messages[-1].content.lower()

    # Acceptance criterion 4 is "visible in the activity stream", so the stream is
    # asserted rather than assumed.
    assert _tool_summaries(publisher) == [
        "coordinator called search_jobs.",
        "coordinator called read_shortlist.",
    ]
    sequences = [event.sequence for event in publisher.events]
    assert sequences == sorted(sequences) and len(set(sequences)) == len(sequences)
    search_call = next(
        event
        for event in publisher.events
        if event.attributes.get("tool_name") == "search_jobs"
        and event.attributes.get("stage") == "call"
    )
    search_result = next(
        event
        for event in publisher.events
        if event.attributes.get("tool_name") == "search_jobs"
        and event.attributes.get("stage") == "result"
    )
    assert search_call.attributes == {
        "tool_name": "search_jobs",
        "stage": "call",
        "operation_id": "call-1",
    }
    assert search_call.parent_id == receipt.run_id
    assert search_result.parent_id == search_call.attributes["operation_id"] == "call-1"
    assert search_result.attributes["result_count"] == 1
    assert search_result.duration_ms is not None
    assert search_result.duration_ms >= 0
    completed = next(
        event
        for event in reversed(publisher.events)
        if event.event_type == "run" and event.status == "completed"
    )
    assert completed.parent_id == receipt.run_id
    assert completed.attributes["model"] == "coordinator-deep-agent"
    assert completed.duration_ms is not None

    assert agent.calls == 3


def test_a_shortlist_the_model_never_saw_reaches_the_next_conversational_turn():
    """The headline #146 scenario, with its recorded before-state.

    The candidate clicks Search (the deterministic command path, which never calls
    the conversation model), then asks a question one turn later. Nothing about
    those postings is anywhere in the model's transcript, so naming one proves
    `read_shortlist` was read rather than remembered.

    Before-state 2026-08-01: "I cannot ... I do not have access to the 7 job
    postings mentioned in the previous turn."
    """
    from backend.tests.test_recruitment_team_module import _session_factory
    from recruitment_team.interface import SearchJobs, SendMessage, StartThread

    discovery = _RecordingDiscovery(
        [
            _search_result(
                [
                    _job(101, "Yield Enhancement Engineer", "Micron"),
                    _job(102, "Process Integration Engineer", "GlobalFoundries"),
                ]
            )
        ]
    )
    agent = ScriptedDeepAgent(
        responses=[
            # Turn 1: a plain reply, no tools.
            submission("Tell me which fabs you have worked with."),
            # Turn 2: the only way to learn what the button found.
            tool_call("read_shortlist", {}, "call-read"),
            submission(
                "Your leadership bullet already matches Yield Enhancement Engineer "
                "at Micron, so I would lead with it.",
            ),
        ]
    )

    sessions = _session_factory()
    owner_id, resume_id = _owner_with_resume(sessions)
    with sessions() as db:
        team = _team(db, agent, discovery)
        receipt = team.execute(
            owner_id,
            StartThread(resume_version_id=resume_id, message="Hello, I run yield analytics."),
            idempotency_key="turn-1",
        )
        thread_id = receipt.thread_id
        team.execute(
            owner_id,
            SearchJobs(thread_id=thread_id, query="semiconductor yield analytics"),
            idempotency_key="button-search",
        )
        team.execute(
            owner_id,
            SendMessage(
                thread_id=thread_id,
                message="Improve my resume for these roles. I want to stay in Singapore.",
            ),
            idempotency_key="turn-2",
        )
        snapshot = team.snapshot(owner_id, thread_id)

    # Turn 2 did not search. The one search on record is the button's.
    assert discovery.search_count == 1

    # requests[1] is turn 2's first decision, taken before read_shortlist returned.
    # It replays turn 1 from the checkpoint plus the compact thread_state block,
    # and neither contains a posting. "Yield Enhancement Engineer" is the posting
    # title and appears nowhere in RESUME_TEXT, which says "Yield Engineering
    # Manager" -- so it isolates the posting from the resume the agent is given
    # on a thread with no candidate profile. If it leaks in here, thread_state is
    # carrying the shortlist and read_shortlist is decorative.
    assert "Yield Enhancement Engineer" not in _rendered(agent.requests[1])
    assert "Yield Enhancement Engineer" not in _rendered(agent.requests[1])

    # requests[2] is the decision taken after it read the shortlist.
    assert "Yield Enhancement Engineer" in _rendered(agent.requests[2])
    assert "GlobalFoundries" in _rendered(agent.requests[2])

    assert "Micron" in snapshot.messages[-1].content
    assert "paste" not in snapshot.messages[-1].content.lower()

    assert snapshot.case_facts.preferences == ()

    assert agent.calls == 3


def test_one_search_per_turn_uses_the_first_result_and_then_replies():
    """A changed query cannot turn one user request into repeated searches."""
    from backend.tests.test_recruitment_team_module import _session_factory
    from recruitment_team.interface import StartThread

    discovery = _RecordingDiscovery(
        [
            _search_result(
                [
                    _job(201, "Graduate Trainee, Process", "HRNET Ventures", seniority="Junior"),
                    _job(202, "Intern, Data", "BOK SENG Logistics", seniority="Junior"),
                ]
            ),
            _search_result(
                [
                    _job(201, "Graduate Trainee, Process", "HRNET Ventures", seniority="Junior"),
                    _job(202, "Intern, Data", "BOK SENG Logistics", seniority="Junior"),
                ]
            ),
        ]
    )
    agent = ScriptedDeepAgent(
        responses=[
            tool_call("search_jobs", {"query": "data engineer"}, "call-1"),
            tool_call(
                "search_jobs",
                {"query": "staff semiconductor yield engineer"},
                "call-2",
            ),
            submission(
                "That search returned only junior roles, so I did not publish a senior match."
            ),
        ]
    )

    sessions = _session_factory()
    owner_id, resume_id = _owner_with_resume(sessions)
    with sessions() as db:
        team = _team(db, agent, discovery)
        receipt = team.execute(
            owner_id,
            StartThread(resume_version_id=resume_id, message="Find me a senior role."),
            idempotency_key="turn-1",
        )
        snapshot = team.snapshot(owner_id, receipt.thread_id)

    assert discovery.search_count == 2

    # The first result set was in front of the model when it chose the second
    # query. That, and not the count, is what "read its own results" means.
    second_decision_request = _rendered(agent.requests[1])
    assert "HRNET Ventures" in second_decision_request
    assert "Graduate Trainee, Process" in second_decision_request

    assert [job.job_id for job in snapshot.case_facts.recommendations] == [201, 202]
    assert snapshot.case_facts.latest_search_query == "data engineer"
    assert agent.calls == 3


def test_coordinator_search_guard_rejects_a_changed_second_query():
    """One logical search is a turn boundary, not an argument fingerprint."""
    first = {"query": "semiconductor yield engineer"}
    second = {"query": "process integration engineer"}
    discovery = _RecordingDiscovery(
        [
            _search_result([_job(301, "Yield Engineer", "Micron")]),
            _search_result([_job(301, "Yield Engineer", "Micron")]),
        ]
    )
    agent = ScriptedDeepAgent(
        responses=[
            tool_call("search_jobs", dict(first), "call-1"),
            tool_call("search_jobs", dict(second), "call-2"),
            submission("The first current search is ready to review."),
        ]
    )
    events: list[dict] = []

    _model(agent).respond([], RESUME_TEXT, (), _context(discovery, events=events))

    results = _tool_results(events, "search_jobs")
    assert len(results) == 2
    assert results[0].get("reason") != "tool_already_used_this_turn"
    assert results[1]["ok"] is False
    assert results[1]["reason"].startswith("tool_already_used_this_turn")
    assert "finish the reply" in results[1]["reason"]

    # Only the first logical search reached the port. JobRecommender performs
    # the explicit query plus its bounded profile query inside that one call.
    assert [call["query"] for call in discovery.calls] == [
        first["query"],
        "platform engineering",
    ]
    assert agent.calls == 3


def test_a_search_that_returns_nothing_leaves_the_existing_shortlist_alone():
    """An empty search must not empty the panel and 422 the next click.

    Revision 1 replaced `recommendations` whenever the sink was non-empty, so one
    valid-empty result silently destroyed the previous turn's matches. The command
    path never had this failure mode: it raises before touching `case_facts`.
    """
    from backend.tests.test_recruitment_team_module import _session_factory
    from recruitment_team.interface import SearchJobs, SendMessage, ShortlistJob, StartThread

    discovery = _RecordingDiscovery(
        [
            _search_result(
                [
                    _job(501, "Yield Enhancement Engineer", "Micron"),
                    _job(502, "Process Integration Engineer", "GlobalFoundries"),
                ]
            ),
            _search_result([]),
            _search_result([]),
        ]
    )
    agent = ScriptedDeepAgent(
        responses=[
            submission("Tell me more about the fabs you have run."),
            tool_call(
                "search_jobs",
                {"query": "quantum photonics architect"},
                "call-empty",
            ),
            submission("Nothing current matched that; the earlier matches still stand."),
        ]
    )

    sessions = _session_factory()
    owner_id, resume_id = _owner_with_resume(sessions)
    with sessions() as db:
        team = _team(db, agent, discovery)
        receipt = team.execute(
            owner_id,
            StartThread(resume_version_id=resume_id, message="Hello."),
            idempotency_key="turn-1",
        )
        thread_id = receipt.thread_id
        team.execute(
            owner_id,
            SearchJobs(thread_id=thread_id, query="semiconductor yield analytics"),
            idempotency_key="button-search",
        )
        team.execute(
            owner_id,
            SendMessage(thread_id=thread_id, message="What about quantum photonics?"),
            idempotency_key="turn-2",
        )
        snapshot = team.snapshot(owner_id, thread_id)
        # The real consequence of a wiped shortlist is a 422 here, not a stale panel.
        team.execute(
            owner_id,
            ShortlistJob(thread_id=thread_id, job_id=501),
            idempotency_key="shortlist-501",
        )

    assert [job.job_id for job in snapshot.case_facts.recommendations] == [501, 502]
    assert snapshot.case_facts.latest_search_query == "semiconductor yield analytics"
    # The agent was told the search was fine and simply matched nothing.
    assert "valid_empty" in _rendered(agent.requests[2])


def test_a_failed_search_is_surfaced_to_the_agent_and_leaves_the_shortlist_alone():
    """A source failure fails closed and preserves the last verified shortlist."""
    from backend.tests.test_recruitment_team_module import _session_factory
    from recruitment_team.errors import ConversationUnavailable
    from recruitment_team.interface import SearchJobs, SendMessage, StartThread

    discovery = _RecordingDiscovery(
        [
            _search_result([_job(601, "Yield Enhancement Engineer", "Micron")]),
            _failed_search(),
        ]
    )
    agent = ScriptedDeepAgent(
        responses=[
            submission("Hello, tell me what you are aiming for."),
            tool_call(
                "search_jobs",
                {"query": "staff yield engineer"},
                "call-fail",
            ),
            submission("The job source did not answer just now; your earlier matches stand."),
        ]
    )

    sessions = _session_factory()
    owner_id, resume_id = _owner_with_resume(sessions)
    with sessions() as db:
        team = _team(db, agent, discovery)
        receipt = team.execute(
            owner_id,
            StartThread(resume_version_id=resume_id, message="Hello."),
            idempotency_key="turn-1",
        )
        thread_id = receipt.thread_id
        team.execute(
            owner_id,
            SearchJobs(thread_id=thread_id, query="semiconductor yield analytics"),
            idempotency_key="button-search",
        )
        with pytest.raises(ConversationUnavailable) as error:
            team.execute(
                owner_id,
                SendMessage(thread_id=thread_id, message="Try a staff-level search."),
                idempotency_key="turn-2",
            )
        snapshot = team.snapshot(owner_id, thread_id)

    assert error.value.failure_type == "transient"
    assert error.value.failure_code == "connection_failure"
    assert error.value.detail == {
        "validation_code": "search_result_unavailable",
        "tool_name": "search_jobs",
    }
    assert [job.job_id for job in snapshot.case_facts.recommendations] == [601]
    assert snapshot.case_facts.latest_search_query == "semiconductor yield analytics"
    assert "connection_failure" in _rendered(agent.requests[2])


def test_search_query_records_the_query_that_ran_not_the_one_the_model_asked_for():
    """`search_query` becomes an observation instead of a request.

    The scripted submission deliberately asks for a different query than the one
    the tool executed. Revision 1's assertion compared `ScriptedDiscovery`'s
    echoed query against itself and could not fail.

    Two keys, two meanings: `search_query` is what ran, and is what
    `_query_from_candidate` reads on the next SearchJobs command;
    `latest_search_query` is the query behind the list currently in
    `recommendations`.
    """
    from backend.tests.test_recruitment_team_module import _session_factory
    from recruitment_team.interface import StartThread

    executed = "staff semiconductor yield engineer"
    discovery = _RecordingDiscovery([
        _search_result([_job(701, "Staff Yield Engineer", "NXP")]),
        _search_result([_job(701, "Staff Yield Engineer", "NXP")]),
    ])
    agent = ScriptedDeepAgent(
        responses=[
            tool_call("search_jobs", {"query": executed}, "call-1"),
            submission("Staff Yield Engineer at NXP is the strongest current match."),
        ]
    )

    sessions = _session_factory()
    owner_id, resume_id = _owner_with_resume(sessions)
    with sessions() as db:
        team = _team(db, agent, discovery)
        receipt = team.execute(
            owner_id,
            StartThread(resume_version_id=resume_id, message="Find me a staff role."),
            idempotency_key="turn-1",
        )
        thread_id = receipt.thread_id

    facts = _raw_case_facts(sessions, thread_id)
    assert facts["search_query"] == executed
    assert facts["latest_search_query"] == executed
    assert facts["search_query"] == executed


def test_iteration_cap_fails_the_turn_instead_of_raising_or_fabricating_a_reply(monkeypatch):
    """`GraphRecursionError` must not escape, and the turn must not invent an answer.

    HTTP 200 is not an acceptance criterion: a turn that never produced a
    submission is a 503, not a cheerful empty answer. The bound on `calls` is what
    makes this test able to fail -- `repeat_last` pins `consumed` at 1 whether the
    recursion limit is honoured or ignored.

    13 rather than 4, and an exact count rather than a range. The constant is a
    LangGraph recursion_limit, which counts super-steps: measured against this
    graph, a turn costs 5 steps plus 4 per tool call. At 4 even a no-tool turn
    caps, so the opening turn never completed and the range 2..4 described a
    graph that does not exist. 13 is the smallest value that lets two tool calls
    plus a submission through, and a runaway makes exactly four model calls
    before it trips.
    """
    import config

    from backend.tests.test_recruitment_team_module import _session_factory
    from models import RecruitmentMessage
    from recruitment_team.activity_publisher import RecordedActivityPublisher
    from recruitment_team.errors import ConversationUnavailable
    from recruitment_team.interface import SendMessage, StartThread

    monkeypatch.setattr(config, "COORDINATOR_MAX_TOOL_ITERATIONS", 13)

    discovery = _RecordingDiscovery([])
    opening = ScriptedDeepAgent(responses=[submission("Hello, what are you aiming for?")])
    # repeat_last makes the agent call read_shortlist forever, which is exactly
    # the run that blows through a recursion limit without ever submitting.
    looping = ScriptedDeepAgent(
        responses=[tool_call("read_shortlist", {}, "call-loop")], repeat_last=True
    )
    publisher = RecordedActivityPublisher()

    sessions = _session_factory()
    owner_id, resume_id = _owner_with_resume(sessions)
    with sessions() as db:
        receipt = _team(db, opening, discovery).execute(
            owner_id,
            StartThread(resume_version_id=resume_id, message="Hello."),
            idempotency_key="turn-1",
        )
        thread_id = receipt.thread_id

    with sessions() as db:
        team = _team(db, looping, discovery, publisher)
        with pytest.raises(ConversationUnavailable) as error:
            team.execute(
                owner_id,
                SendMessage(thread_id=thread_id, message="Keep going."),
                idempotency_key="turn-2",
            )

    assert error.value.failure_type == "business"
    assert error.value.failure_code == "attempt_budget_exhausted"

    # The cap was really honoured. Without this bound the test passes whether the
    # limit is 13, 45 or ignored: `repeat_last` never runs out of script.
    # 6, not 4: dropping TodoListMiddleware removed a layer from every super-step,
    # so the same recursion limit buys more real tool calls.
    assert looping.calls == 6

    failed = [event for event in publisher.events if event.status == "failed"]
    assert len(failed) == 1
    assert failed[0].detail["failure_type"] == "business"
    assert failed[0].detail["failure_code"] == "attempt_budget_exhausted"
    assert failed[0].parent_id == failed[0].run_id
    assert failed[0].attributes == {
        "error_type": "ConversationUnavailable",
        "command_type": "send_message",
        "attempt_count": 1,
        "attempt_limit": 2,
        "attempted_stage": "send_message",
        "failure_type": "business",
        "failure_code": "attempt_budget_exhausted",
        "retryable": False,
        "recovery_action": "start_new_logical_run",
    }
    assert failed[0].duration_ms is not None

    with sessions() as db:
        roles = [row.role for row in db.query(RecruitmentMessage).all()]
    assert roles == ["user", "assistant", "user"], (
        "the capped turn wrote its user message and then nothing: no fabricated reply"
    )


def test_repeated_rejected_tool_results_fail_before_the_global_iteration_cap(monkeypatch):
    """A model ignoring retry=false cannot burn the whole coordinator budget."""
    import config

    from backend.tests.test_recruitment_team_module import _session_factory
    from models import RecruitmentMessage
    from recruitment_team.activity_publisher import RecordedActivityPublisher
    from recruitment_team.errors import ConversationUnavailable
    from recruitment_team.interface import StartThread

    monkeypatch.setattr(config, "COORDINATOR_MAX_CONSECUTIVE_TOOL_REJECTIONS", 2)
    quote = "I led a platform migration."
    repeated_call = {"unsupported": True}
    agent = ScriptedDeepAgent(
        responses=[
            tool_call("unsupported_tool", repeated_call, "reject-1"),
            tool_call("unsupported_tool", repeated_call, "reject-2"),
            tool_call("unsupported_tool", repeated_call, "reject-3"),
            submission("This unreachable reply must not be fabricated as success."),
        ]
    )
    publisher = RecordedActivityPublisher()
    sessions = _session_factory()
    owner_id, resume_id = _owner_with_resume(sessions)

    with sessions() as db:
        with pytest.raises(ConversationUnavailable) as error:
            _team(db, agent, _RecordingDiscovery([]), publisher).execute(
                owner_id,
                StartThread(resume_version_id=resume_id, message=quote),
                idempotency_key="rejected-tool-loop",
            )

    assert error.value.failure_code == "attempt_budget_exhausted"
    assert agent.calls == 3
    assert agent.consumed == 3
    assert "retry" in _rendered(agent.requests[2])
    assert not any(
        event.event_type == "run" and event.status == "completed"
        for event in publisher.events
    )
    with sessions() as db:
        assert [row.role for row in db.query(RecruitmentMessage).all()] == ["user"]


def test_productive_looking_tool_churn_stops_before_the_eight_call_failure_shape():
    """Bound useful-looking churn, not only exact duplicates and recursion.

    Production run e3cba09d made eight provider calls, repeatedly searched and
    wrote state, consumed 368k input tokens, then failed its structured reply.
    Materially different arguments evade the identical-call guard, so this is
    the acceptance boundary that run exposed: stop the turn before call seven
    and classify it as exhausted work, not a late structured-output surprise.
    """
    from recruitment_team.errors import ConversationUnavailable

    searches = (
        "finance platform business analyst",
        "senior finance systems analyst",
        "finance transformation business analyst",
        "management reporting platform analyst",
    )
    agent = ScriptedDeepAgent(
        responses=[
            tool_call("search_jobs", {"query": searches[0]}, "search-1"),
            tool_call("search_jobs", {"query": searches[1]}, "search-2"),
            tool_call(
                "write_plan",
                {"steps": [{"step": "Review finance roles", "status": "in_progress"}]},
                "plan-1",
            ),
            tool_call("search_jobs", {"query": searches[2]}, "search-3"),
            tool_call(
                "write_plan",
                {"steps": [{"step": "Compare finance roles", "status": "in_progress"}]},
                "plan-2",
            ),
            tool_call("search_jobs", {"query": searches[3]}, "search-4"),
            tool_call(
                "write_plan",
                {"steps": [{"step": "Explain the shortlist", "status": "in_progress"}]},
                "plan-3",
            ),
            final("I found the strongest finance roles but did not submit the required reply."),
        ]
    )
    one_result = _search_result([_job(801, "Finance Platform Business Analyst", "DBS")])
    discovery = _RecordingDiscovery([one_result] * 8)
    events: list[dict] = []

    with pytest.raises(ConversationUnavailable) as error:
        _model(agent).respond([], RESUME_TEXT, (), _context(discovery, events=events))

    assert error.value.failure_code == "attempt_budget_exhausted"
    assert agent.calls <= 6
    assert len(_tool_results(events, "search_jobs")) <= 3
    assert len(_tool_results(events, "write_plan")) <= 2


def test_rejected_shortlist_is_one_shot_and_the_coordinator_still_replies():
    """A bad ranking draft must not recreate production's five-write loop."""
    job = _job(802, "Finance Platform Business Analyst", "DBS")
    agent = ScriptedDeepAgent(
        responses=[
            tool_call(
                "search_jobs",
                {"query": "finance platform business analyst"},
                "search-1",
            ),
            tool_call(
                "write_shortlist",
                {
                    "matches": [
                        {
                            "job_id": 802,
                            "matched": [
                                {
                                    "statement": "Finance platform experience",
                                    "resume_quote": "not an exact resume quote",
                                }
                            ],
                            "stretch": [],
                            "missing": [],
                            "level_fit": "aligned",
                            "pay_position": "near_peer_median",
                        }
                    ]
                },
                "shortlist-1",
            ),
            submission(
                "I found a current DBS finance-platform role, but no ranked card passed "
                "the exact-evidence gate."
            ),
        ]
    )
    discovery = _RecordingDiscovery([_search_result([job]), _search_result([job])])
    events: list[dict] = []

    reply = _model(agent).respond([], RESUME_TEXT, (), _context(discovery, events=events))

    assert reply.reply_mode == "structured"
    assert "DBS" in reply.content
    assert agent.calls == 3
    assert len(_tool_results(events, "write_shortlist")) == 1
    assert agent.bound_tool_names[-1] == ["ConversationReply"]


def test_parallel_search_calls_execute_only_one_logical_search():
    """Sibling calls cannot race past the one-search-per-turn boundary."""
    from langchain_core.messages import AIMessage

    job = _job(803, "Finance Systems Analyst", "OCBC")
    agent = ScriptedDeepAgent(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "search_jobs",
                        "args": {"query": "finance systems analyst"},
                        "id": "search-1",
                    },
                    {
                        "name": "search_jobs",
                        "args": {"query": "finance transformation analyst"},
                        "id": "search-2",
                    },
                ],
            ),
            submission("I found one current finance-systems role at OCBC."),
        ]
    )
    result = _search_result([job])
    discovery = _RecordingDiscovery([result, result])
    events: list[dict] = []
    context = _context(discovery, events=events)

    reply = _model(agent).respond([], RESUME_TEXT, (), context)

    assert "OCBC" in reply.content
    assert len(context.search_results) == 1
    assert len(_tool_results(events, "search_jobs")) == 2
    assert agent.calls == 2


def test_conversation_unavailable_maps_to_503():
    """`_raise_http_error` matches by explicit type and ends in a bare `raise`.

    A new `*Unavailable` that nobody adds to the isinstance tuple is a 500.
    """
    from fastapi import HTTPException

    from recruitment_team.errors import ConversationUnavailable
    from recruitment_team.http_routes import _raise_http_error
    from recruitment_team.recovery import classify_failure

    with pytest.raises(HTTPException) as error:
        _raise_http_error(
            ConversationUnavailable(
                "coordinator loop hit its tool iteration cap",
                decision=classify_failure("attempt_budget_exhausted"),
            )
        )

    assert error.value.status_code == 503


def test_terminal_coordinator_cleanup_failure_is_returned_as_durable_debt(monkeypatch):
    monkeypatch.setattr(
        "recruitment_team.coordinator.model._delete_terminal_checkpoint",
        lambda _run_config: False,
    )
    reply = _model(ScriptedDeepAgent(responses=[submission("Ready.")])).respond(
        [],
        RESUME_TEXT,
        (),
        _context(_RecordingDiscovery([])),
    )

    assert reply.pause_token == ""
    assert reply.checkpoint_cleanup_token.startswith("coordinator-")


def test_failed_coordinator_turn_carries_cleanup_debt_without_exposing_it(monkeypatch):
    from recruitment_team.errors import ConversationUnavailable

    monkeypatch.setattr(
        "recruitment_team.coordinator.model._delete_terminal_checkpoint",
        lambda _run_config: False,
    )
    agent = ScriptedDeepAgent(
        responses=[
            tool_call(
                "ask_candidate",
                {"questions": ["Are you a Singapore citizen or permanent resident?"]},
                "protected-question",
            )
        ]
    )

    with pytest.raises(ConversationUnavailable) as caught:
        _model(agent).respond([], RESUME_TEXT, (), _context(_RecordingDiscovery([])))

    cleanup_token = caught.value.checkpoint_cleanup_token
    assert cleanup_token.startswith("coordinator-")
    assert cleanup_token not in str(caught.value)


def test_ask_candidate_pauses_before_any_further_tool_runs_and_the_answer_resumes_it(
    monkeypatch,
):
    """The interrupt, not the prompt, is what stops the next tool.

    Turn 1 scripts `ask_candidate` immediately followed by `search_jobs`. If the
    pause were prompt convention, the search would run on a guess. It must not.
    Turn 2's answer resumes the same checkpointed graph and the search then runs.
    """
    from backend.tests.test_recruitment_team_module import _session_factory
    from recruitment_team.activity_publisher import RecordedActivityPublisher
    from recruitment_team.interface import SendMessage, StartThread

    deleted_checkpoints: list[str] = []
    monkeypatch.setattr(
        "recruitment_team.coordinator.model._delete_terminal_checkpoint",
        lambda run_config: deleted_checkpoints.append(
            run_config["configurable"]["thread_id"]
        ) or True,
    )

    discovery = _RecordingDiscovery([
        _search_result([_job(401, "Staff Yield Engineer", "NXP")]),
        _search_result([_job(401, "Staff Yield Engineer", "NXP")]),
    ])
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
                {"query": "staff yield engineer semiconductor"},
                "call-search",
            ),
            submission("Staff Yield Engineer at NXP keeps you in semiconductors, as you asked."),
        ]
    )
    first_publisher = RecordedActivityPublisher()
    second_publisher = RecordedActivityPublisher()

    sessions = _session_factory()
    owner_id, resume_id = _owner_with_resume(sessions)
    with sessions() as db:
        team = _team(db, agent, discovery, first_publisher)
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
    assert agent.calls == 1
    assert "Are you open to roles outside semiconductors?" in paused_snapshot.messages[-1].content
    # The pause stays invisible to the transport: setting awaiting_candidate_answer
    # would route the next message to the assessment runner's answer command.
    assert paused_snapshot.workflow_state != "awaiting_candidate_answer"
    assert paused_snapshot.case_facts.recommendations == ()
    assert _tool_summaries(first_publisher) == ["coordinator called ask_candidate."]
    assert deleted_checkpoints == [], "a paused graph must remain resumable"

    # A separate session and module instance: the resume rides the durable
    # checkpointer, not a live in-memory graph.
    with sessions() as db:
        team = _team(db, agent, discovery, second_publisher)
        team.execute(
            owner_id,
            SendMessage(
                thread_id=first.thread_id,
                message="No, keep me in semiconductors.",
            ),
            idempotency_key="turn-2",
        )
        resumed = team.snapshot(owner_id, first.thread_id)

    assert discovery.search_count == 2
    assert [job.job_id for job in resumed.case_facts.recommendations] == [401]
    assert "NXP" in resumed.messages[-1].content
    assert agent.calls == 3

    # Every assertion above is also satisfied by a turn 2 that ignored the pause
    # and started a brand new graph, because the script would play out
    # identically either way. This one is not. A resumed turn delivers the answer
    # as the ask_candidate tool's own result and seeds no new message; a restart
    # would have ended this request with a HumanMessage carrying a fresh
    # thread-state block.
    answer_delivery = agent.requests[1][-1]
    assert type(answer_delivery).__name__ == "ToolMessage"
    assert "No, keep me in semiconductors." in str(answer_delivery.content)

    # Resuming replays the interrupted AIMessage with its tool_calls intact
    # (streaming.py:44-50). Without skip_tool_call_ids the candidate sees the same
    # question published twice.
    assert _tool_summaries(second_publisher) == ["coordinator called search_jobs."]
    assert len(deleted_checkpoints) == 1
    assert deleted_checkpoints[0].startswith(f"coordinator-{first.thread_id}-")


def test_conversational_coordinator_rejects_protected_question_after_interrupt(
    monkeypatch,
):
    from backend.tests.test_recruitment_team_module import _session_factory
    from recruitment_team.errors import ConversationUnavailable
    from recruitment_team.interface import StartThread

    deleted_checkpoints: list[str] = []
    monkeypatch.setattr(
        "recruitment_team.coordinator.model._delete_terminal_checkpoint",
        lambda run_config: deleted_checkpoints.append(
            run_config["configurable"]["thread_id"]
        ) or True,
    )
    agent = ScriptedDeepAgent(
        responses=[
            tool_call(
                "ask_candidate",
                {"questions": ["Are you a Singapore citizen or permanent resident?"]},
                "protected-question",
            ),
        ]
    )
    sessions = _session_factory()
    owner_id, resume_id = _owner_with_resume(sessions)

    with sessions() as db:
        team = _team(db, agent, _RecordingDiscovery([]))
        with pytest.raises(ConversationUnavailable) as caught:
            team.execute(
                owner_id,
                StartThread(resume_version_id=resume_id, message="Help me choose."),
                idempotency_key="protected-question",
            )

    assert caught.value.failure_type == "safety"
    assert caught.value.failure_code == "protected_candidate_question"
    assert caught.value.retryable is False
    assert len(deleted_checkpoints) == 1


def test_conversational_coordinator_allows_work_authorisation_question(monkeypatch):
    from backend.tests.test_recruitment_team_module import _session_factory
    from recruitment_team.interface import StartThread

    deleted_checkpoints: list[str] = []
    monkeypatch.setattr(
        "recruitment_team.coordinator.model._delete_terminal_checkpoint",
        lambda run_config: deleted_checkpoints.append(
            run_config["configurable"]["thread_id"]
        ) or True,
    )
    agent = ScriptedDeepAgent(
        responses=[
            tool_call(
                "ask_candidate",
                {"questions": ["Are you authorised to work in Singapore?"]},
                "work-authorisation-question",
            ),
        ]
    )
    sessions = _session_factory()
    owner_id, resume_id = _owner_with_resume(sessions)

    with sessions() as db:
        team = _team(db, agent, _RecordingDiscovery([]))
        started = team.execute(
            owner_id,
            StartThread(resume_version_id=resume_id, message="Help me choose."),
            idempotency_key="work-authorisation-question",
        )
        snapshot = team.snapshot(owner_id, started.thread_id)

    assert "authorised to work" in snapshot.messages[-1].content
    assert deleted_checkpoints == []


def test_candidate_question_limit_fails_instead_of_pausing_forever(monkeypatch):
    import config

    from backend.tests.test_recruitment_team_module import _session_factory
    from recruitment_team.errors import ConversationUnavailable
    from recruitment_team.interface import SendMessage, StartThread

    monkeypatch.setattr(config, "OPEN_AGENT_MAX_CANDIDATE_QUESTION_ROUNDS", 1)
    agent = ScriptedDeepAgent(
        responses=[
            tool_call("ask_candidate", {"questions": ["First question?"]}, "call-ask-1"),
            tool_call("ask_candidate", {"questions": ["Second question?"]}, "call-ask-2"),
        ]
    )
    sessions = _session_factory()
    owner_id, resume_id = _owner_with_resume(sessions)

    with sessions() as db:
        team = _team(db, agent, _RecordingDiscovery([]))
        first = team.execute(
            owner_id,
            StartThread(resume_version_id=resume_id, message="Help me choose."),
            idempotency_key="question-cap-1",  # gitleaks:allow - deterministic test key
        )
        with pytest.raises(ConversationUnavailable) as caught:
            team.execute(
                owner_id,
                SendMessage(thread_id=first.thread_id, message="My answer."),
                idempotency_key="question-cap-2",  # gitleaks:allow - deterministic test key
            )

    assert caught.value.failure_code == "attempt_budget_exhausted"
    assert agent.calls == 2


def test_a_proposed_edit_reaches_the_pending_table_and_the_rejections_reach_the_model():
    """Invariant 3 and invariant 5 hold on the conversational path.

    Three proposals against the real leadership bullet:
      1. introduces `40`     -> rejected, the number is named
      2. drops `12`          -> rejected by run_all_gates' fact_preservation gate
      3. rewords, keeps `12` -> accepted, and stays pending

    Asserted through `team.proposed_edits`, which is what a candidate can retrieve
    and what proves the sink was drained into `ProposedResumeEdit`. Asserting on
    the context's own list would pass with the drain deleted.
    """
    from backend.tests.test_recruitment_team_module import _session_factory
    from recruitment_team.interface import StartThread

    block_id = _leadership_block_id()
    accepted_rewrite = "Led a team of 12 engineers delivering semiconductor yield analytics."
    discovery = _RecordingDiscovery([])
    agent = ScriptedDeepAgent(
        responses=[
            tool_call(
                "propose_resume_edit",
                {
                    "block_id": block_id,
                    "rewrite": "Led a team of 40 engineers building semiconductor yield analytics.",
                },
                "call-1",
            ),
            tool_call(
                "propose_resume_edit",
                {"block_id": block_id, "rewrite": "Led the platform engineering team."},
                "call-2",
            ),
            tool_call(
                "propose_resume_edit",
                {"block_id": block_id, "rewrite": accepted_rewrite},
                "call-3",
            ),
            submission(
                "The tighter wording foregrounds leadership while preserving the original scope.",
            ),
        ]
    )

    sessions = _session_factory()
    owner_id, resume_id = _owner_with_resume(sessions)
    with sessions() as db:
        team = _team(db, agent, discovery)
        receipt = team.execute(
            owner_id,
            StartThread(
                resume_version_id=resume_id,
                message="Sharpen my leadership bullet.",
            ),
            idempotency_key="turn-1",
        )
        pending = team.proposed_edits(owner_id, receipt.thread_id)
        snapshot = team.snapshot(owner_id, receipt.thread_id)

    # Exactly one edit survived, it is retrievable, and it is pending. No agent
    # path writes a resume.
    assert len(pending) == 1
    assert pending[0]["status"] == "pending"
    assert pending[0]["applicable"] is True
    assert pending[0]["original"] == LEADERSHIP_BULLET
    assert pending[0]["rewrite"] == accepted_rewrite
    assert snapshot.messages[-1].content == (
        "1 evidence-supported resume edit is pending below for your approval.\n\n"
        "The tighter wording foregrounds leadership while preserving the original scope."
    )

    # Both rejections came back to the model with a reason it could act on.
    assert "40" in _rendered(agent.requests[1])
    assert "Missing facts from original: 12" in _rendered(agent.requests[2])
    assert agent.calls == 4


def test_edit_turn_renders_actual_results_and_labels_uncertainty():
    block_id = _leadership_block_id()
    agent = ScriptedDeepAgent(
        responses=[
            tool_call(
                "propose_resume_edit",
                {
                    "block_id": block_id,
                    "rewrite": "Led a team of 40 engineers building semiconductor yield analytics.",
                },
                "call-edit",
            ),
            submission(
                "Three edits are pending.",
                assumptions=["The role may include formal people management"],
                missing_information=["Direct-report count"],
                follow_up_question="How many direct reports did you manage?",
            ),
        ]
    )

    reply = _model(agent).respond(
        [],
        RESUME_TEXT,
        (),
        _context(_RecordingDiscovery([])),
    )

    assert "No resume edit became pending." in reply.content
    assert "Three edits" not in reply.content
    assert "Assumptions, not resume claims" in reply.content
    assert "Missing or unverified: Direct-report count." in reply.content
    assert reply.content.endswith("How many direct reports did you manage?")


def test_get_conversation_model_returns_the_loop_adapter():
    """The one-line wiring change, guarded.

    Every existing reference to `get_conversation_model` in the suite replaces the
    callable, and every test above injects the adapter by hand. Without this the
    loop can be built, the suite can go green, and `http_routes.py:91` can keep
    returning the single-shot adapter with no signal at all.
    """
    from recruitment_team import DeepAgentConversationModel
    from recruitment_team.http_routes import get_conversation_model
    from recruitment_team.telemetry import RecordedTelemetry

    assert isinstance(
        get_conversation_model(telemetry=RecordedTelemetry()),
        DeepAgentConversationModel,
    )


def test_a_transport_turn_reaches_the_loop_without_overriding_the_dependency(monkeypatch):
    """End to end through FastAPI with the real DI graph for the conversation model.

    `get_conversation_model` is deliberately NOT overridden. Only the model factory
    is patched, at the seam `create_resume_agent` uses. If the HTTP dependency no
    longer returns the tool-using coordinator, the scripted structured-output call
    is never consumed and this fails.

    `get_role_success_profiler` is overridden because it eagerly constructs a live
    SEA-LION client (`role_success.py:354-360`). That is unrelated to the wiring
    under test.
    """
    from fastapi.testclient import TestClient

    import main
    import resume_agent.agent as agent_module
    from auth import get_current_user
    from backend.tests.test_recruitment_team_module import (
        _candidate_profile_run,
        _role_profiler,
        _session_factory,
    )
    from database import get_db
    from recruitment_team.candidate_profile import ScriptedCandidateProfilerFactory
    from recruitment_team.http_routes import (
        get_candidate_profiler_factory_provider,
        get_job_discovery,
        get_role_success_profiler,
    )

    discovery = _RecordingDiscovery(
        [
            _search_result([_job(801, "Yield Enhancement Engineer", "Micron")]),
            _search_result([_job(801, "Yield Enhancement Engineer", "Micron")]),
        ]
    )
    agent = ScriptedDeepAgent(
        responses=[
            tool_call(
                "search_jobs",
                {"query": "semiconductor yield analytics"},
                "call-1",
            ),
            submission("Yield Enhancement Engineer at Micron is your closest current match."),
        ]
    )

    sessions = _session_factory()
    owner_id, resume_id = _owner_with_resume(sessions)

    def override_db():
        with sessions() as db:
            yield db

    # Both bindings, for the reason the guard fixture documents: the coordinator
    # imports create_agent_model lazily from resume_agent.models, so patching
    # resume_agent.agent alone leaves the real factory reachable.
    import resume_agent.models as models_module

    monkeypatch.setattr(agent_module, "create_agent_model", lambda *a, **kw: agent)
    monkeypatch.setattr(models_module, "create_agent_model", lambda *a, **kw: agent)
    main.app.dependency_overrides[get_db] = override_db
    main.app.dependency_overrides[get_current_user] = lambda: type(
        "AuthenticatedUser",
        (),
        {"id": owner_id},
    )()
    main.app.dependency_overrides[get_job_discovery] = lambda: discovery
    main.app.dependency_overrides[get_role_success_profiler] = lambda: _role_profiler()
    main.app.dependency_overrides[get_candidate_profiler_factory_provider] = (
            lambda: lambda: ScriptedCandidateProfilerFactory([_candidate_profile_run(RESUME_TEXT)])
        )
    try:
        client = TestClient(main.app)
        started = client.post(
            "/api/recruitment-team/threads",
            json={
                "resume_version_id": resume_id,
                "message": "Find me yield analytics roles.",
                "idempotency_key": "http-coordinator-loop",
            },
        )
        assert started.status_code == 201
        thread_id = started.json()["thread_id"]
        state = client.get(f"/api/recruitment-team/threads/{thread_id}")
        assert state.status_code == 200
        body = state.json()
    finally:
        for dependency in (
            get_db,
            get_current_user,
            get_job_discovery,
            get_role_success_profiler,
            get_candidate_profiler_factory_provider,
        ):
            main.app.dependency_overrides.pop(dependency, None)

    assert discovery.search_count == 2
    assert [job["job_id"] for job in body["case_facts"]["recommendations"]] == [801]
    assert "Micron" in body["messages"][-1]["content"]
    assert agent.calls == 2


def test_the_coordinator_binds_only_the_tools_it_needs():
    """create_deep_agent's base stack cannot be declined, so we do not use it.

    Measured on 2026-08-02: create_deep_agent bound ten tools for one real one --
    edit_file, execute, glob, grep, ls, read_file, write_file and task ride along
    whether or not they mean anything, and its `middleware` argument only appends.
    Nine irrelevant tools compete for a mid-size model's attention on every turn.
    """
    from langchain_openai import ChatOpenAI

    from recruitment_team.coordinator.model import DeepAgentConversationModel
    from recruitment_team.prompts import COORDINATOR_SYSTEM_PROMPT

    model = DeepAgentConversationModel(
        model_factory=lambda: ChatOpenAI(model="x", api_key="ph", base_url="http://localhost:1")
    )

    discovery = _RecordingDiscovery([])
    without_target = _bound_tool_names(model._build_agent(_context(discovery)))
    bound = _bound_tool_names(
        model._build_agent(
            _context(
                discovery,
                candidate_profile=object(),
                target_job=_job(901, "Platform Architect", "ACME"),
            )
        )
    )

    assert bound == {
        "ask_candidate",
        "propose_resume_edit",
        "read_candidate_evidence",
        "read_shortlist",
        "read_target_job",
        "search_jobs",
        "write_plan",
        "write_shortlist",
    }
    assert without_target == bound - {"read_target_job"}
    # Deepagents' write_todos is deliberately absent. Live on 2026-08-02 the model wrote the
    # same three-item list eleven times and died on the iteration cap, ignoring an
    # actionable refusal, a prompt rule and a hard guard. The scoped write_plan
    # tool returns an explicit receipt and has a candidate-visible persistence seam.
    assert "write_todos" not in bound
    for inherited in ("execute", "edit_file", "write_file", "glob", "grep", "ls", "task"):
        assert inherited not in bound
    normalized_prompt = " ".join(COORDINATOR_SYSTEM_PROMPT.split()).casefold()
    assert "which tools are useful" in normalized_prompt
    assert "which tools and specialists are useful" not in normalized_prompt
    assert "delegate" not in normalized_prompt


def test_the_coordinator_model_is_built_explicitly(monkeypatch):
    """Handing model=None to the factory inherits a 60s timeout and no retries.

    Every other recruitment path passes 300s and 2 retries. The loop makes up to
    a dozen calls a turn, so it is the last surface that should get a fifth of
    the time and no retry.
    """
    import config
    import resume_agent.models as models_module

    from recruitment_team.coordinator.model import DeepAgentConversationModel

    captured: dict = {}
    monkeypatch.setattr(
        models_module,
        "create_agent_model",
        lambda *args, **kwargs: captured.update(kwargs) or object(),
    )

    DeepAgentConversationModel()._build_model()

    assert captured["timeout"] == config.RECRUITMENT_MODEL_HTTP_TIMEOUT_SECONDS
    assert captured["max_retries"] == config.RECRUITMENT_MODEL_TRANSPORT_RETRIES
    assert captured["model"] == config.COORDINATOR_MODEL
    assert captured["max_completion_tokens"] == config.RECRUITMENT_CONVERSATION_MAX_TOKENS


def _bound_tool_names(graph) -> set[str]:
    for node in graph.nodes.values():
        for attribute in ("tools_by_name", "_tools_by_name"):
            found = getattr(node, attribute, None) or getattr(
                getattr(node, "bound", None), attribute, None
            )
            if found:
                return set(found)
    raise AssertionError("no tool node found on the compiled graph")


def test_a_turn_reports_the_prompt_that_actually_ran():
    """A trace stamping a constant cannot tell you which prompt produced a turn.

    The coordinator reports its own version instead of a generic fallback.
    """
    from recruitment_team.prompts import COORDINATOR_PROMPT_VERSION

    discovery = _RecordingDiscovery([_search_result([])])
    agent = ScriptedDeepAgent(responses=[submission("Noted.")])

    reply = _model(agent).respond([], "", (), _context(discovery))

    assert COORDINATOR_PROMPT_VERSION == "recruitment-coordinator-loop-v22"
    assert reply.prompt_version == COORDINATOR_PROMPT_VERSION


def test_a_thread_with_no_profile_fails_before_building_the_coordinator():
    """A coordinator turn cannot bypass the reviewed evidence-profile gate."""
    agent = ScriptedDeepAgent(responses=[submission("Noted.")])

    with pytest.raises(
        RuntimeError,
        match="coordinator requires a current candidate evidence profile",
    ):
        _model(agent).respond(
            [],
            RESUME_TEXT,
            (),
            _context(_RecordingDiscovery([]), candidate_profile=None),
        )

    assert agent.calls == 0


def test_the_resume_is_withheld_when_a_reviewed_profile_exists():
    """The coordinator receives citable profile evidence, not raw resume text."""
    discovery = _RecordingDiscovery([_search_result([])])
    agent = ScriptedDeepAgent(responses=[submission("Noted.")])

    _model(agent).respond([], RESUME_TEXT, (), _context(discovery))

    assert "Yield Engineering Manager" not in _rendered(agent.requests[0])


def test_model_context_keeps_recent_dialogue_and_uses_durable_state_for_older_turns(monkeypatch):
    from types import SimpleNamespace

    import config

    monkeypatch.setattr(config, "RECRUITMENT_MODEL_HISTORY_TURNS", 1)
    model = _model(ScriptedDeepAgent(responses=[]))
    context = _context(_RecordingDiscovery([]))
    messages = [
        SimpleNamespace(role="user", content="old user detail"),
        SimpleNamespace(role="assistant", content="old assistant reply"),
        SimpleNamespace(role="user", content="recent user detail"),
        SimpleNamespace(role="assistant", content="recent assistant reply"),
        SimpleNamespace(role="user", content="current request"),
    ]

    payload = model._new_turn_payload(context, messages, ())
    rendered = _rendered(payload["messages"])

    assert "old user detail" not in rendered
    assert "old assistant reply" not in rendered
    assert "recent user detail" in rendered
    assert "recent assistant reply" in rendered
    assert "current request" in rendered


def test_a_turn_that_skips_structured_submission_fails_visibly():
    """Free prose is not a hidden success path around the reply contract."""
    from recruitment_team.errors import ConversationUnavailable

    agent = ScriptedDeepAgent(
        responses=[final("I can help you compare semiconductor leadership roles.")]
    )

    with pytest.raises(ConversationUnavailable) as error:
        _model(agent).respond([], RESUME_TEXT, (), _context(_RecordingDiscovery([])))

    assert error.value.failure_type == "validation"
    assert error.value.failure_code == "structured_output_invalid"


def test_an_unsubmitted_reply_cut_off_mid_sentence_is_rejected():
    """Never turn model truncation into a successful candidate-facing message."""
    from recruitment_team.errors import ConversationUnavailable

    agent = ScriptedDeepAgent(
        responses=[final("The strongest fit is operations leadership because your manager")]
    )

    with pytest.raises(ConversationUnavailable) as error:
        _model(agent).respond([], RESUME_TEXT, (), _context(_RecordingDiscovery([])))

    assert error.value.failure_type == "validation"
    assert error.value.failure_code == "structured_output_invalid"


def test_unsubmitted_prose_cannot_claim_a_search_that_never_ran():
    from recruitment_team.errors import ConversationUnavailable

    agent = ScriptedDeepAgent(
        responses=[final("I searched the market and found three matching roles.")]
    )

    with pytest.raises(ConversationUnavailable) as error:
        _model(agent).respond([], RESUME_TEXT, (), _context(_RecordingDiscovery([])))

    assert error.value.failure_type == "validation"
    assert error.value.failure_code == "structured_output_invalid"


def test_failed_search_cannot_be_reported_as_found_matches():
    from recruitment_team.errors import ConversationUnavailable

    agent = ScriptedDeepAgent(responses=[
        tool_call("search_jobs", {"query": "quality manager"}, "call-failed-search"),
        final("I found five matching roles for you."),
    ])

    with pytest.raises(ConversationUnavailable) as error:
        _model(agent).respond(
            [],
            RESUME_TEXT,
            (),
            _context(_RecordingDiscovery([_failed_search()])),
        )

    assert error.value.failure_type == "transient"
    assert error.value.failure_code == "connection_failure"
    assert error.value.detail == {
        "validation_code": "search_result_unavailable",
        "tool_name": "search_jobs",
    }


@pytest.mark.parametrize(
    "claim",
    (
        "There are five matching roles available.",
        "Five relevant jobs are ready for review.",
        "I have five suitable opportunities for you.",
        "Here are five strong fits to review.",
        "Your search produced several suitable openings.",
        "The corpus contains five relevant vacancies.",
        "We have five matching positions available.",
    ),
)
def test_failed_search_rejects_paraphrased_positive_result_claims(claim):
    from recruitment_team.errors import ConversationUnavailable

    agent = ScriptedDeepAgent(responses=[
        tool_call("search_jobs", {"query": "quality manager"}, "call-failed-search"),
        submission(claim),
    ])

    with pytest.raises(ConversationUnavailable) as error:
        _model(agent).respond(
            [],
            RESUME_TEXT,
            (),
            _context(_RecordingDiscovery([_failed_search()])),
        )

    assert error.value.failure_code == "connection_failure"
    assert error.value.detail["validation_code"] == "search_result_unavailable"
    assert error.value.detail["tool_name"] == "search_jobs"


def test_unverified_search_claim_failure_is_durable_and_content_free():
    from backend.tests.test_recruitment_team_module import _session_factory
    from models import RecruitmentRun
    from recruitment_team.errors import ConversationUnavailable
    from recruitment_team.interface import StartThread

    sessions = _session_factory()
    owner_id, resume_id = _owner_with_resume(sessions)
    agent = ScriptedDeepAgent(responses=[final("There are five matching roles available.")])
    with sessions() as db:
        team = _team(db, agent, _RecordingDiscovery([]))
        with pytest.raises(ConversationUnavailable):
            team.execute(
                owner_id,
                StartThread(resume_version_id=resume_id, message="Find roles for me."),
                idempotency_key="unverified-search-claim",
            )
        run = db.query(RecruitmentRun).one()
        terminal = run.result["terminal_error"]
        failed_event = next(
            event
            for event in team.events(owner_id, run.thread_id, after_sequence=0)
            if event.event_type == "run" and event.status == "failed"
        )

    assert terminal["validation_code"] == "unverified_tool_claim"
    assert terminal["tool_name"] == "search_jobs"
    assert failed_event.detail["validation_code"] == "unverified_tool_claim"
    assert failed_event.detail["tool_name"] == "search_jobs"
    assert "five matching roles" not in str(terminal).lower()


def test_conversation_reply_schema_requires_a_complete_sentence():
    """ToolStrategy uses this validation error to ask the model to repair its reply."""
    from pydantic import ValidationError
    from recruitment_team.conversation_model import ConversationReply

    with pytest.raises(ValidationError, match="complete sentence"):
        ConversationReply(reply="The strongest fit is operations leadership because")

    assert ConversationReply(reply='Target the manufacturing manager role.').reply.endswith(".")


def test_structured_output_repairs_an_incomplete_reply_before_completion():
    """Exercise ToolStrategy's retry, not only direct schema construction."""
    agent = ScriptedDeepAgent(
        responses=[
            submission("The strongest fit is operations leadership because"),
            submission("The strongest fit is operations leadership."),
        ]
    )

    reply = _model(agent).respond([], RESUME_TEXT, (), _context(_RecordingDiscovery([])))

    assert reply.content == "The strongest fit is operations leadership."
    assert reply.reply_mode == "structured"
    assert agent.calls == 2


def test_paragraphing_preserves_model_supplied_markdown():
    from recruitment_team.conversation_model import paragraph_reply

    markdown = "Opening.\n\n- First role\n- Second role"

    assert paragraph_reply(markdown) == markdown


def test_a_turn_that_produces_no_text_at_all_still_fails():
    """The fallback is the model's own answer, never a manufactured one.

    An empty final message carries nothing to deliver, so the turn is a 503 and
    the candidate is told the truth rather than shown a blank reply.
    """
    from backend.tests.test_recruitment_team_module import _session_factory
    from recruitment_team.errors import ConversationUnavailable
    from recruitment_team.interface import StartThread

    agent = ScriptedDeepAgent(responses=[final("   ")])

    sessions = _session_factory()
    owner_id, resume_id = _owner_with_resume(sessions)
    with sessions() as db:
        team = _team(db, agent, _RecordingDiscovery([]))
        with pytest.raises(ConversationUnavailable) as error:
            team.execute(
                owner_id,
                StartThread(resume_version_id=resume_id, message="What should I target?"),
                idempotency_key="turn-1",
            )

    assert error.value.failure_type == "validation"
    assert error.value.failure_code == "structured_output_invalid"
