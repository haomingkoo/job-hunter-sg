"""The coordinator's thread-facing tools, and what they change about the thread.

Stream 2 of #146. `docs/v4-146-coordinator-loop.md` §2, §3.

Two claims are under test and they are not the same claim:

1. The tools can see this thread. `read_shortlist` returns postings the model
   never saw, and `search_jobs` runs a query the candidate never typed.
2. What they find survives the turn. This is the one that matters. An agent that
   searches while `case_facts["recommendations"]` stays empty has not fixed
   #146, it has moved it: the panel goes stale and, worse, `_known_job`
   (recruitment_team.py) resolves a job_id only against recommendations plus the
   shortlist, so the candidate's next Shortlist click on a job the agent found is
   a 422.

So every persistence test drives `RecruitmentTeam.execute` and asserts on the
thread that comes back out, never on the context object the test built itself.
One of them clicks Shortlist afterwards, because that is the failure a stale
list actually causes.

The conversation-model double here really invokes the tools. It is not the
deep-agent loop -- that is the other stream's adapter -- but a double that
returned a canned ModelReply would assert nothing about whether a tool can reach
this thread or whether the drain runs.
"""

from __future__ import annotations

import pytest

from backend.tests.test_recruitment_team_module import (
    _owner_with_resume,
    _role_profiler,
    _session_factory,
)


RESUME_HINT = "semiconductor yield analytics"


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
        description=f"{title} at {company}. Owns defect density and yield ramp.",
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


def _search_result(jobs, query: str = ""):
    from recruitment_team.discovery import JobSearchResult

    return JobSearchResult(
        query=query,
        jobs=tuple(jobs),
        candidate_count=len(jobs),
        visible_candidate_count=len(jobs),
        truncated=False,
        valid_empty=not jobs,
    )


def _failed_search(failure_type: str = "unavailable"):
    """What LangChainJobDiscovery really returns on a source failure.

    No jobs, `valid_empty=False`, a `failure_type` (discovery.py:120-130).
    """
    from recruitment_team.discovery import JobSearchResult

    return JobSearchResult(
        query="",
        jobs=(),
        candidate_count=None,
        visible_candidate_count=None,
        truncated=False,
        valid_empty=False,
        failure_type=failure_type,
        retryable=True,
    )


class _RecordingDiscovery:
    """Captures the exact args a tool searched with, and never invents a result."""

    def __init__(self, results):
        self._results = list(results)
        self.calls: list[dict] = []

    def search_jobs(self, query: str, exclude_junior: bool = False):
        from recruitment_team.discovery import JobSearchResult

        self.calls.append({"query": query, "exclude_junior": exclude_junior})
        assert self._results, "the loop searched more times than the test scripted"
        result = self._results.pop(0)
        return JobSearchResult(
            query=query,
            **{key: value for key, value in result.__dict__.items() if key != "query"},
        )

    def get_job(self, job_id: int):
        return None

    @property
    def search_count(self) -> int:
        return len(self.calls)


class _ToolCallingConversationModel:
    """A ConversationModel that really invokes the coordinator's tools.

    `turns` is one list of `(tool, args)` per turn. Results are kept so a test
    can assert on what the tool returned to the model rather than on a call
    count.
    """

    def __init__(self, turns, *, reply: str = "Here is what I found.", search_query: str = ""):
        self._turns = list(turns)
        self._reply = reply
        self._search_query = search_query
        self.results: list[list] = []
        self.contexts: list = []
        self.call_count = 0

    def respond(self, messages, resume_text, current_preferences=(), context=None):
        from recruitment_team.conversation_model import ModelReply

        self.call_count += 1
        self.contexts.append(context)
        calls = self._turns.pop(0) if self._turns else []
        # Invoked with no argument for the context: the tools read it off the
        # ContextVars RecruitmentTeam set around this call, which is the only
        # way they can reach it from inside a deep-agent graph.
        self.results.append([tool.invoke(dict(args)) for tool, args in calls])
        return ModelReply(
            content=self._reply,
            model_name="tool-calling-double",
            search_query=self._search_query,
        )


def _team(db, model, discovery):
    from recruitment_team import RecruitmentTeam
    from recruitment_team.activity_publisher import RecordedActivityPublisher
    from recruitment_team.telemetry import RecordedTelemetry

    return RecruitmentTeam(
        db,
        model,
        discovery,
        _role_profiler(),
        RecordedTelemetry(),
        RecordedActivityPublisher(),
    )


def _context(discovery, *, recommendations=(), shortlisted=(), **overrides):
    from recruitment_team import ConversationContext

    kwargs = {
        "thread_id": "1f0d0a0e-0000-4000-8000-00000000abcd",
        "trace_key": "coordinator-tools-trace",
        "candidate_profile": None,
        "role_profile": None,
        "target_job": None,
        "resume_document": {"blocks": []},
        "latest_search_query": "",
        "recommendations": tuple(recommendations),
        "shortlisted_jobs": tuple(shortlisted),
        "preferences": (),
        "wants_experienced_roles": True,
        "discovery": discovery,
    }
    kwargs.update(overrides)
    return ConversationContext(**kwargs)


def _raw_case_facts(sessions, thread_id: str) -> dict:
    """case_facts as stored, including keys CaseFacts does not project.

    `search_query` is one of them, and it is the key `_query_from_candidate`
    reads on the next SearchJobs command.
    """
    from models import RecruitmentThread

    with sessions() as db:
        thread = (
            db.query(RecruitmentThread).filter(RecruitmentThread.id == thread_id).first()
        )
        return dict(thread.case_facts)


# ── read_shortlist ───────────────────────────────────────────────────────────


def test_read_shortlist_returns_the_postings_with_enough_to_reason_about():
    """Naming a job is not the whole bug.

    The reply that prompted #146 asked the candidate to paste a job description.
    An agent that can see only a title still has to ask, so the description and
    skills have to come back too.
    """
    from recruitment_team.open_agent.context import assessment_context
    from recruitment_team.open_agent.tools import read_shortlist

    context = _context(
        _RecordingDiscovery([]),
        recommendations=[_job(101, "Yield Enhancement Engineer", "Micron")],
        shortlisted=[_job(102, "Process Integration Engineer", "GlobalFoundries")],
        latest_search_query=RESUME_HINT,
    )

    with assessment_context(context, initial_edits=context.proposed_edits):
        result = read_shortlist.invoke({})

    assert result["ok"] is True
    assert result["latest_search_query"] == RESUME_HINT
    assert [job["job_id"] for job in result["recommendations"]] == [101]
    assert result["recommendations"][0]["title"] == "Yield Enhancement Engineer"
    assert result["recommendations"][0]["company"] == "Micron"
    assert result["recommendations"][0]["salary"] == "$10,000 - $15,000"
    assert result["recommendations"][0]["seniority"] == "Professional"
    assert "defect density" in result["recommendations"][0]["description"]
    assert result["recommendations"][0]["skills"] == ["Python", "Semiconductor"]
    assert [job["company"] for job in result["shortlisted_jobs"]] == ["GlobalFoundries"]
    assert result["selected_target_job_id"] is None
    assert result["candidate_profile_available"] is False


def test_read_shortlist_shows_a_search_run_earlier_in_the_same_turn():
    """The agent has to see what it just found, not what the turn started with.

    Reading `context.recommendations` directly would show the agent a list one
    search out of date, and would let the panel disagree with what the agent was
    shown. Both go through `merged_recommendations` for that reason.
    """
    from recruitment_team.open_agent.context import assessment_context
    from recruitment_team.open_agent.tools import read_shortlist, search_jobs

    discovery = _RecordingDiscovery([_search_result([_job(202, "Staff Yield Engineer", "NXP")])])
    context = _context(
        discovery,
        recommendations=[_job(201, "Yield Enhancement Engineer", "Micron")],
        latest_search_query="stale query",
    )

    with assessment_context(context, initial_edits=context.proposed_edits):
        before = read_shortlist.invoke({})
        search_jobs.invoke({"query": "staff yield engineer", "exclude_junior": True})
        after = read_shortlist.invoke({})

    assert [job["job_id"] for job in before["recommendations"]] == [201]
    assert before["latest_search_query"] == "stale query"
    assert [job["job_id"] for job in after["recommendations"]] == [202]
    assert after["latest_search_query"] == "staff yield engineer"


def test_read_shortlist_reports_a_selected_target_and_an_available_profile():
    from recruitment_team.open_agent.context import assessment_context
    from recruitment_team.open_agent.tools import read_shortlist

    from backend.tests.test_recruitment_team_module import _candidate_profile_run

    target = _job(303, "Staff Yield Engineer", "NXP")
    context = _context(
        _RecordingDiscovery([]),
        recommendations=[target],
        target_job=target,
        candidate_profile=_candidate_profile_run().profile,
    )

    with assessment_context(context, initial_edits=context.proposed_edits):
        result = read_shortlist.invoke({})

    assert result["selected_target_job_id"] == 303
    assert result["candidate_profile_available"] is True


def test_read_shortlist_outside_a_conversation_is_loud_rather_than_empty():
    """An empty shortlist that is really a wiring bug reads exactly like a thread
    that has found nothing. It must not."""
    from recruitment_team.open_agent.tools import read_shortlist

    result = read_shortlist.invoke({})

    assert result["ok"] is False
    assert "recommendations" not in result


def test_read_shortlist_refuses_an_assessment_context():
    """The two shapes share one ContextVar, so the wrong one must not read as empty."""
    from backend.tests.test_recruitment_team_module import (
        _candidate_profile_run,
        _role_profile_run,
    )
    from recruitment_team.assessment_contracts import TargetAssessmentRequest
    from recruitment_team.open_agent.context import assessment_context
    from recruitment_team.open_agent.tools import read_shortlist

    request = TargetAssessmentRequest(
        candidate_profile=_candidate_profile_run().profile,
        role_profile=_role_profile_run().profile,
        target_job=_job(404, "Staff Yield Engineer", "NXP"),
        trace_key="assessment",
    )

    with assessment_context(request):
        result = read_shortlist.invoke({})

    assert result["ok"] is False
    assert "recommendations" not in result


# ── the shared tools on a conversation context ───────────────────────────────


def test_read_target_job_and_read_candidate_evidence_say_what_is_missing():
    """A conversation turn has neither, so both must explain rather than crash.

    They dereference `request.target_job` and `request.candidate_profile`
    directly on the assessment path; on this path both are None.
    """
    from recruitment_team.open_agent.context import assessment_context
    from recruitment_team.open_agent.tools import read_candidate_evidence, read_target_job

    context = _context(_RecordingDiscovery([]))

    with assessment_context(context, initial_edits=context.proposed_edits):
        target = read_target_job.invoke({})
        evidence = read_candidate_evidence.invoke({})

    assert target["ok"] is False
    assert "read_shortlist" in target["reason"]
    assert evidence["ok"] is False
    # Not just what is missing: what to do instead, and not to retry. The
    # coordinator called this twelve times against a profile-less thread on
    # 2026-08-02 because the refusal named a gap without naming an alternative.
    assert "evidence profile" in evidence["reason"]
    # Name the block the resume is actually in, and say the IDs are in it. The
    # refusal used to point at thread_state, which never carries the resume.
    assert "resume block" in evidence["reason"]
    assert "propose_resume_edit" in evidence["reason"]
    assert evidence["retry"] is False


# ── search_jobs ──────────────────────────────────────────────────────────────


def test_search_jobs_goes_through_the_port_with_the_args_the_agent_chose():
    from recruitment_team.open_agent.context import assessment_context
    from recruitment_team.open_agent.tools import search_jobs

    discovery = _RecordingDiscovery([_search_result([_job(201, "Staff Yield Engineer", "NXP")])])
    context = _context(discovery)

    with assessment_context(context, initial_edits=context.proposed_edits):
        result = search_jobs.invoke({"query": "staff yield engineer", "exclude_junior": False})

    # exclude_junior is the agent's call, not a heuristic applied behind it.
    assert discovery.calls == [{"query": "staff yield engineer", "exclude_junior": False}]
    assert result["ok"] is True
    assert result["valid_empty"] is False
    assert [job["company"] for job in result["jobs"]] == ["NXP"]
    assert len(context.search_results) == 1


def test_search_jobs_requires_exclude_junior_so_the_model_cannot_decline_to_choose():
    """An optional field is a request. `search_query` was optional, merged,
    deployed and never once populated."""
    from recruitment_team.open_agent.tools import search_jobs

    assert set(search_jobs.args_schema.model_json_schema()["required"]) == {
        "query",
        "exclude_junior",
    }


def test_an_identical_repeat_never_reaches_the_port_and_a_different_query_does():
    """Guardrails limit volume, never choice."""
    from recruitment_team.open_agent.context import assessment_context
    from recruitment_team.open_agent.tools import search_jobs

    same = {"query": "semiconductor yield engineer", "exclude_junior": True}
    other = {"query": "process integration engineer", "exclude_junior": True}
    discovery = _RecordingDiscovery(
        [
            _search_result([_job(301, "Yield Engineer", "Micron")]),
            _search_result([_job(302, "Process Integration Engineer", "Avago")]),
        ]
    )
    context = _context(discovery)

    with assessment_context(context, initial_edits=context.proposed_edits):
        first = search_jobs.invoke(dict(same))
        repeat = search_jobs.invoke(dict(same))
        different = search_jobs.invoke(dict(other))

    assert first["ok"] is True
    assert repeat["ok"] is False
    assert repeat["reason"] == "identical_call_no_new_information"
    assert different["ok"] is True
    assert [call["query"] for call in discovery.calls] == [same["query"], other["query"]]
    # The rejected call produced no result, so it cannot reach the thread either.
    assert len(context.search_results) == 2


def test_a_source_failure_is_returned_to_the_agent_rather_than_raised():
    """A failure mid-turn is information the agent can act on.

    The command path raises DiscoveryUnavailable, which is right for a button
    press and wrong for an agent that could search again with different terms.
    """
    from recruitment_team.open_agent.context import assessment_context
    from recruitment_team.open_agent.tools import search_jobs

    context = _context(_RecordingDiscovery([_failed_search("unavailable")]))

    with assessment_context(context, initial_edits=context.proposed_edits):
        result = search_jobs.invoke({"query": "staff yield engineer", "exclude_junior": True})

    assert result["ok"] is False
    assert result["failure_type"] == "unavailable"
    assert result["retryable"] is True
    assert len(context.search_results) == 1


def test_a_valid_empty_search_is_reported_as_nothing_matched_not_as_a_failure():
    from recruitment_team.open_agent.context import assessment_context
    from recruitment_team.open_agent.tools import search_jobs

    context = _context(_RecordingDiscovery([_search_result([])]))

    with assessment_context(context, initial_edits=context.proposed_edits):
        result = search_jobs.invoke({"query": "quantum photonics architect", "exclude_junior": True})

    assert result["ok"] is True
    assert result["valid_empty"] is True
    assert result["jobs"] == []


def test_search_jobs_outside_a_conversation_never_touches_the_port():
    from recruitment_team.open_agent.tools import search_jobs

    result = search_jobs.invoke({"query": "anything", "exclude_junior": True})

    assert result["ok"] is False
    assert result["failure_type"] == "business"


# ── the crux: what the tools find has to survive the turn ────────────────────


def test_a_search_run_inside_a_turn_reaches_the_thread_and_survives_a_shortlist_click():
    """The whole point of stream 2.

    A search the candidate never asked for, run inside `respond()`, has to land
    in `case_facts["recommendations"]` in the shape `_known_job` resolves
    against. The Shortlist call at the end is the real consequence of getting
    this wrong: not a stale panel, a 422.
    """
    from recruitment_team.interface import ShortlistJob, StartThread
    from recruitment_team.open_agent.tools import search_jobs

    discovery = _RecordingDiscovery(
        [_search_result([_job(501, "Yield Enhancement Engineer", "Micron")])]
    )
    model = _ToolCallingConversationModel(
        [[(search_jobs, {"query": "semiconductor yield analytics", "exclude_junior": True})]],
        reply="Yield Enhancement Engineer at Micron is your closest current match.",
    )

    sessions = _session_factory()
    owner_id, resume_id = _owner_with_resume(sessions)
    with sessions() as db:
        team = _team(db, model, discovery)
        receipt = team.execute(
            owner_id,
            StartThread(resume_version_id=resume_id, message="Find me yield analytics roles."),
            idempotency_key="turn-1",
        )
        snapshot = team.snapshot(owner_id, receipt.thread_id)
        shortlisted = team.execute(
            owner_id,
            ShortlistJob(thread_id=receipt.thread_id, job_id=501),
            idempotency_key="shortlist-501",
        )

    assert discovery.calls == [
        {"query": "semiconductor yield analytics", "exclude_junior": True}
    ]
    assert [job.job_id for job in snapshot.case_facts.recommendations] == [501]
    assert snapshot.case_facts.recommendations[0].company == "Micron"
    assert snapshot.case_facts.latest_search_query == "semiconductor yield analytics"
    assert shortlisted.status == "completed"

    with sessions() as db:
        team = _team(db, model, discovery)
        after = team.snapshot(owner_id, receipt.thread_id)
    assert [job.job_id for job in after.case_facts.shortlisted_jobs] == [501]


def test_a_shortlist_the_model_never_saw_is_readable_on_the_next_turn():
    """The headline #146 scenario, minus the loop.

    The Search button never calls the conversation model, so nothing about those
    postings is in the transcript. If `read_shortlist` returns them on a later
    turn, the coordinator can stop asking for a pasted job description.
    """
    from recruitment_team.interface import SearchJobs, SendMessage, StartThread
    from recruitment_team.open_agent.tools import read_shortlist

    discovery = _RecordingDiscovery(
        [
            _search_result(
                [
                    _job(601, "Yield Enhancement Engineer", "Micron"),
                    _job(602, "Process Integration Engineer", "GlobalFoundries"),
                ]
            )
        ]
    )
    model = _ToolCallingConversationModel([[], [(read_shortlist, {})]])

    sessions = _session_factory()
    owner_id, resume_id = _owner_with_resume(sessions)
    with sessions() as db:
        team = _team(db, model, discovery)
        receipt = team.execute(
            owner_id,
            StartThread(resume_version_id=resume_id, message="Hello, I run yield analytics."),
            idempotency_key="turn-1",
        )
        team.execute(
            owner_id,
            SearchJobs(thread_id=receipt.thread_id, query=RESUME_HINT),
            idempotency_key="button-search",
        )
        team.execute(
            owner_id,
            SendMessage(thread_id=receipt.thread_id, message="Improve my resume for these roles."),
            idempotency_key="turn-2",
        )

    # Turn 2's tool call, not turn 1's: the button ran between them.
    shortlist = model.results[1][0]
    assert [job["company"] for job in shortlist["recommendations"]] == [
        "Micron",
        "GlobalFoundries",
    ]
    assert shortlist["latest_search_query"] == RESUME_HINT
    # The conversation model was called twice; the button did not call it.
    assert model.call_count == 2
    assert discovery.search_count == 1


def test_two_searches_in_one_turn_merge_newest_first_and_dedupe_by_job_id():
    from recruitment_team.interface import StartThread
    from recruitment_team.open_agent.tools import search_jobs

    discovery = _RecordingDiscovery(
        [
            _search_result(
                [
                    _job(701, "Graduate Trainee, Process", "HRNET", seniority="Junior"),
                    _job(702, "Intern, Data", "BOK SENG", seniority="Junior"),
                ]
            ),
            _search_result(
                [
                    _job(703, "Staff Yield Engineer", "NXP"),
                    _job(701, "Graduate Trainee, Process", "HRNET", seniority="Junior"),
                ]
            ),
        ]
    )
    model = _ToolCallingConversationModel(
        [
            [
                (search_jobs, {"query": "data engineer", "exclude_junior": False}),
                (
                    search_jobs,
                    {"query": "staff semiconductor yield engineer", "exclude_junior": True},
                ),
            ]
        ]
    )

    sessions = _session_factory()
    owner_id, resume_id = _owner_with_resume(sessions)
    with sessions() as db:
        team = _team(db, model, discovery)
        receipt = team.execute(
            owner_id,
            StartThread(resume_version_id=resume_id, message="Find me a senior role."),
            idempotency_key="turn-1",
        )
        snapshot = team.snapshot(owner_id, receipt.thread_id)

    assert [job.job_id for job in snapshot.case_facts.recommendations] == [703, 701, 702]
    assert snapshot.case_facts.latest_search_query == "staff semiconductor yield engineer"


def test_a_search_that_returns_nothing_leaves_the_existing_shortlist_alone():
    """One fruitless query must not empty a good list.

    The command path cannot cause this: it raises before it touches case_facts.
    Replacing `recommendations` whenever the sink is non-empty would, and the
    next Shortlist click would then be a 422.
    """
    from recruitment_team.interface import SearchJobs, SendMessage, ShortlistJob, StartThread
    from recruitment_team.open_agent.tools import search_jobs

    discovery = _RecordingDiscovery(
        [
            _search_result(
                [
                    _job(801, "Yield Enhancement Engineer", "Micron"),
                    _job(802, "Process Integration Engineer", "GlobalFoundries"),
                ]
            ),
            _search_result([]),
        ]
    )
    model = _ToolCallingConversationModel(
        [[], [(search_jobs, {"query": "quantum photonics architect", "exclude_junior": True})]]
    )

    sessions = _session_factory()
    owner_id, resume_id = _owner_with_resume(sessions)
    with sessions() as db:
        team = _team(db, model, discovery)
        receipt = team.execute(
            owner_id,
            StartThread(resume_version_id=resume_id, message="Hello."),
            idempotency_key="turn-1",
        )
        team.execute(
            owner_id,
            SearchJobs(thread_id=receipt.thread_id, query=RESUME_HINT),
            idempotency_key="button-search",
        )
        team.execute(
            owner_id,
            SendMessage(thread_id=receipt.thread_id, message="What about quantum photonics?"),
            idempotency_key="turn-2",
        )
        snapshot = team.snapshot(owner_id, receipt.thread_id)
        shortlisted = team.execute(
            owner_id,
            ShortlistJob(thread_id=receipt.thread_id, job_id=801),
            idempotency_key="shortlist-801",
        )

    assert [job.job_id for job in snapshot.case_facts.recommendations] == [801, 802]
    assert snapshot.case_facts.latest_search_query == RESUME_HINT
    assert shortlisted.status == "completed"
    # The query that ran is still recorded, so the next SearchJobs command sees it.
    assert _raw_case_facts(sessions, receipt.thread_id)["search_query"] == (
        "quantum photonics architect"
    )


def test_a_failed_search_leaves_the_existing_shortlist_alone():
    from recruitment_team.interface import SearchJobs, SendMessage, StartThread
    from recruitment_team.open_agent.tools import search_jobs

    discovery = _RecordingDiscovery(
        [
            _search_result([_job(901, "Yield Enhancement Engineer", "Micron")]),
            _failed_search("unavailable"),
        ]
    )
    model = _ToolCallingConversationModel(
        [[], [(search_jobs, {"query": "staff yield engineer", "exclude_junior": True})]]
    )

    sessions = _session_factory()
    owner_id, resume_id = _owner_with_resume(sessions)
    with sessions() as db:
        team = _team(db, model, discovery)
        receipt = team.execute(
            owner_id,
            StartThread(resume_version_id=resume_id, message="Hello."),
            idempotency_key="turn-1",
        )
        team.execute(
            owner_id,
            SearchJobs(thread_id=receipt.thread_id, query=RESUME_HINT),
            idempotency_key="button-search",
        )
        team.execute(
            owner_id,
            SendMessage(thread_id=receipt.thread_id, message="Try a staff-level search."),
            idempotency_key="turn-2",
        )
        snapshot = team.snapshot(owner_id, receipt.thread_id)

    assert [job.job_id for job in snapshot.case_facts.recommendations] == [901]
    assert snapshot.case_facts.latest_search_query == RESUME_HINT
    # The failure reached the agent rather than ending the turn.
    assert model.results[1][0]["failure_type"] == "unavailable"


def test_search_query_records_the_query_that_ran_not_the_one_the_model_asked_for():
    """`search_query` becomes an observation.

    The model's scripted wish is deliberately different from what the tool
    executed, so a tautological comparison cannot pass this.
    """
    from recruitment_team.interface import StartThread
    from recruitment_team.open_agent.tools import search_jobs

    executed = "staff semiconductor yield engineer"
    discovery = _RecordingDiscovery([_search_result([_job(1001, "Staff Yield Engineer", "NXP")])])
    model = _ToolCallingConversationModel(
        [[(search_jobs, {"query": executed, "exclude_junior": True})]],
        search_query="remote product manager",
    )

    sessions = _session_factory()
    owner_id, resume_id = _owner_with_resume(sessions)
    with sessions() as db:
        team = _team(db, model, discovery)
        receipt = team.execute(
            owner_id,
            StartThread(resume_version_id=resume_id, message="Find me a staff role."),
            idempotency_key="turn-1",
        )

    facts = _raw_case_facts(sessions, receipt.thread_id)
    assert facts["search_query"] == executed
    assert facts["latest_search_query"] == executed


def test_a_turn_that_ran_no_search_leaves_every_search_key_untouched():
    """The drain must be inert on an ordinary chat turn.

    Every existing conversation test runs through ScriptedConversationModel, so a
    drain that fired unconditionally would wipe a shortlist on the next hello.
    """
    from recruitment_team import ScriptedConversationModel
    from recruitment_team.interface import SearchJobs, SendMessage, StartThread

    discovery = _RecordingDiscovery([_search_result([_job(1101, "Yield Engineer", "Micron")])])
    model = ScriptedConversationModel(["Hello.", "Tell me more about the fabs you have run."])

    sessions = _session_factory()
    owner_id, resume_id = _owner_with_resume(sessions)
    with sessions() as db:
        team = _team(db, model, discovery)
        receipt = team.execute(
            owner_id,
            StartThread(resume_version_id=resume_id, message="Hello."),
            idempotency_key="turn-1",
        )
        team.execute(
            owner_id,
            SearchJobs(thread_id=receipt.thread_id, query=RESUME_HINT),
            idempotency_key="button-search",
        )
        team.execute(
            owner_id,
            SendMessage(thread_id=receipt.thread_id, message="I ran three fabs."),
            idempotency_key="turn-2",
        )
        snapshot = team.snapshot(owner_id, receipt.thread_id)

    assert [job.job_id for job in snapshot.case_facts.recommendations] == [1101]
    assert snapshot.case_facts.latest_search_query == RESUME_HINT


def test_a_rewrite_drafted_in_a_turn_reaches_the_pending_table_and_stays_pending():
    """`propose_resume_edit` is reachable from a chat turn, so its answer has to
    be true.

    The tool tells the model `pending_user_review`. Asserted through
    `team.proposed_edits`, which is what a candidate can retrieve: asserting on
    the context's own list would pass with the drain deleted. Invariant 5 holds
    because it is the same tool -- the rewrite is offered, never applied.
    """
    from recruitment_team.interface import StartThread
    from recruitment_team.open_agent.tools import propose_resume_edit

    from resume_document import create_resume_document

    sessions = _session_factory()
    owner_id, resume_id = _owner_with_resume(sessions)
    with sessions() as db:
        from models import ResumeVersion

        resume_text = db.query(ResumeVersion).filter(ResumeVersion.id == resume_id).one().resume_text
    block = create_resume_document(resume_text)["blocks"][0]

    rewrite = f"{block['text'].rstrip('.')} across the platform."
    model = _ToolCallingConversationModel(
        [[(propose_resume_edit, {"block_id": block["id"], "rewrite": rewrite})]],
        reply="Drafted one evidence-safe rewrite.",
    )

    with sessions() as db:
        team = _team(db, model, _RecordingDiscovery([]))
        receipt = team.execute(
            owner_id,
            StartThread(resume_version_id=resume_id, message="Sharpen my first bullet."),
            idempotency_key="turn-1",
        )
        pending = team.proposed_edits(owner_id, receipt.thread_id)

    assert model.results[0][0]["accepted"] is True
    assert len(pending) == 1
    assert pending[0]["status"] == "pending"
    assert pending[0]["applicable"] is True
    assert pending[0]["original"] == block["text"]
    assert pending[0]["rewrite"] == rewrite

    # The resume itself is untouched: no agent path writes one.
    with sessions() as db:
        from models import ResumeVersion

        stored = db.query(ResumeVersion).filter(ResumeVersion.id == resume_id).one()
        assert stored.resume_text == resume_text


def test_an_unknown_block_refusal_names_the_blocks_the_agent_may_edit():
    """Found live on 2026-08-02, in a browser, on the exact sentence #146 exists
    to make work: "Improve my resume for these roles."

    Block IDs are opaque hashes (`b_87156122e7ce1066fa93`). Nothing the agent can
    read contains one until a study has run, so on a profile-less thread it
    guesses, is told only "Unknown resume block.", guesses again, then repeats
    the identical call until the turn dies on the iteration cap. That turn is a
    503, and it is every candidate's second message.

    The refusal has to carry the IDs. Same lesson as read_candidate_evidence:
    a refusal a model cannot act on is a refusal it will retry.
    """
    from recruitment_team.open_agent.context import assessment_context
    from recruitment_team.open_agent.tools import propose_resume_edit

    from resume_document import create_resume_document

    document = create_resume_document(
        "HAOMING KOO\n\nEXPERIENCE\n\nLed the yield ramp for four fabs.\n"
    )
    context = _context(_RecordingDiscovery([]), resume_document=document)

    with assessment_context(context, initial_edits=context.proposed_edits):
        answer = propose_resume_edit.invoke(
            {"block_id": "experience-bullet-1", "rewrite": "Led the yield ramp."}
        )

    assert answer["accepted"] is False
    known = [block["id"] for block in document["blocks"]]
    assert answer["known_block_ids"] == known
    # Every id, not a sample: a truncated list is a refusal the agent can still
    # only guess against, which is the bug.
    assert all(block_id in answer["reason"] for block_id in known)


def test_a_profile_less_turn_shows_the_agent_the_ids_it_must_cite():
    """The turn payload, not the tool. Fixing only the refusal would still cost a
    wasted call and a wasted step on every first edit.

    Before the study runs, the resume reaches the agent as raw text, and raw text
    has no block IDs in it. So the same payload that carries the resume has to
    carry the IDs that make it citable.
    """
    from recruitment_team.coordinator.model import DeepAgentConversationModel
    from recruitment_team.interface import Message

    from resume_document import create_resume_document

    resume_text = "HAOMING KOO\n\nEXPERIENCE\n\nLed the yield ramp for four fabs.\n"
    document = create_resume_document(resume_text)
    context = _context(_RecordingDiscovery([]), resume_document=document)

    from datetime import datetime

    payload = DeepAgentConversationModel()._new_turn_payload(
        context,
        [
            Message(
                message_id=1,
                role="user",
                content="Improve my resume for these roles.",
                run_id="run-1",
                created_at=datetime(2026, 8, 2, 21, 15),
            )
        ],
        (),
        resume_text,
    )

    turn = payload["messages"][-1].content
    for block in document["blocks"]:
        assert block["id"] in turn
        assert block["text"] in turn


def test_a_rejected_turn_persists_no_search_it_ran():
    """A turn that fails validation must not leave half of itself behind.

    The drain runs after preference validation for this reason: an invalid
    evidence quote raises before any search reaches case_facts.
    """
    from recruitment_team.conversation_model import ModelReply, PreferenceUpdate
    from recruitment_team.errors import InvalidCommand
    from recruitment_team.interface import StartThread
    from recruitment_team.open_agent.tools import search_jobs

    class _BadQuoteModel(_ToolCallingConversationModel):
        def respond(self, messages, resume_text, current_preferences=(), context=None):
            super().respond(messages, resume_text, current_preferences, context)
            return ModelReply(
                content="Noted.",
                model_name="tool-calling-double",
                preference_updates=(
                    PreferenceUpdate(
                        field="salary",
                        value="$15,000",
                        evidence_quote="I need at least fifteen thousand",
                    ),
                ),
            )

    discovery = _RecordingDiscovery([_search_result([_job(1201, "Yield Engineer", "Micron")])])
    model = _BadQuoteModel(
        [[(search_jobs, {"query": "yield engineer", "exclude_junior": True})]]
    )

    sessions = _session_factory()
    owner_id, resume_id = _owner_with_resume(sessions)
    with sessions() as db:
        team = _team(db, model, discovery)
        with pytest.raises(InvalidCommand) as error:
            team.execute(
                owner_id,
                StartThread(resume_version_id=resume_id, message="Find me a yield role."),
                idempotency_key="turn-1",
            )

    assert "evidence_quote" in str(error.value)
    assert discovery.search_count == 1, "the tool did run; the turn is what failed"

    from models import RecruitmentThread

    with sessions() as db:
        thread = db.query(RecruitmentThread).one()
        assert not thread.case_facts.get("recommendations")
        assert not thread.case_facts.get("search_query")
