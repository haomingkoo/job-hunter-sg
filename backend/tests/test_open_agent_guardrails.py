from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from recruitment_team.tool_call_guard import ToolCallGuardMiddleware
import recruitment_team.tool_call_guard as tool_call_guard


def _request(name: str, args: dict, call_id: str):
    return SimpleNamespace(tool_call={"name": name, "args": args, "id": call_id})


def test_rejects_an_identical_persona_delegation_without_executing_it_twice():
    guard = ToolCallGuardMiddleware()
    calls = []
    handler = lambda request: calls.append(request) or {"ok": True}
    args = {"subagent_type": "recruiter", "description": "Review this role."}

    assert guard.wrap_tool_call(_request("task", args, "1"), handler) == {"ok": True}
    refusal = guard.wrap_tool_call(_request("task", args, "2"), handler)

    assert len(calls) == 1
    assert json.loads(refusal.content)["reason"].startswith("identical_call_no_new_information")


def test_allows_materially_different_calls():
    guard = ToolCallGuardMiddleware()
    calls = []
    handler = lambda request: calls.append(request) or {"ok": True}

    guard.wrap_tool_call(_request("search_jobs", {"query": "backend engineer"}, "1"), handler)
    guard.wrap_tool_call(_request("search_jobs", {"query": "platform engineer"}, "2"), handler)

    assert len(calls) == 2


def test_hides_a_tool_after_one_rejected_identical_call():
    guard = ToolCallGuardMiddleware()
    search_jobs = SimpleNamespace(name="search_jobs")
    ask_candidate = SimpleNamespace(name="ask_candidate")
    args = {"query": "backend engineer"}

    guard.wrap_tool_call(
        _request("search_jobs", args, "1"),
        lambda _request: {"ok": True},
    )
    guard.wrap_tool_call(
        _request("search_jobs", args, "2"),
        lambda _request: {"ok": True},
    )
    observed = []
    model_request = SimpleNamespace(
        tools=[search_jobs, ask_candidate],
        override=lambda **changes: SimpleNamespace(tools=changes["tools"]),
    )

    guard.wrap_model_call(
        model_request,
        lambda request: observed.extend(request.tools) or "done",
    )

    assert observed == [ask_candidate]


def test_initial_assessment_keeps_task_for_missing_persona_after_completed_revisit(
    monkeypatch,
):
    from recruitment_team.open_agent import context

    monkeypatch.setattr(context, "missing_required_specialists", lambda: ("ats",))
    monkeypatch.setattr(context, "completed_specialist_revisit_allowed", lambda: False)
    guard = ToolCallGuardMiddleware(enforce_fresh_specialists=True)
    task = SimpleNamespace(name="task")
    synthesis = SimpleNamespace(name="submit_target_assessment_synthesis")

    refusal = guard.wrap_tool_call(
        _request("task", {"subagent_type": "recruiter"}, "1"),
        lambda _request: {"ok": True},
    )
    observed = []
    model_request = SimpleNamespace(
        tools=[task, synthesis],
        override=lambda **changes: SimpleNamespace(tools=changes["tools"]),
    )
    guard.wrap_model_call(
        model_request,
        lambda request: observed.extend(request.tools),
    )
    remaining = guard.wrap_tool_call(
        _request("task", {"subagent_type": "ats"}, "2"),
        lambda _request: {"ok": True},
    )

    payload = json.loads(refusal.content)
    assert payload["reason"].startswith(
        "specialist_already_completed_no_new_evidence"
    )
    assert payload["missing_required_specialists"] == ["ats"]
    assert payload["next_action"] == "Delegate one of the remaining required specialists: ats."
    assert observed == [task, synthesis]
    assert remaining == {"ok": True}


def test_duplicate_task_rejection_still_allows_remaining_required_personas(monkeypatch):
    from recruitment_team.open_agent import context

    missing = ["recruiter", "ats"]
    monkeypatch.setattr(context, "missing_required_specialists", lambda: tuple(missing))
    monkeypatch.setattr(context, "completed_specialist_revisit_allowed", lambda: False)
    guard = ToolCallGuardMiddleware(enforce_fresh_specialists=True)
    calls = []
    recruiter_args = {"subagent_type": "recruiter", "description": "Review this role."}

    guard.wrap_tool_call(
        _request("task", recruiter_args, "1"),
        lambda request: calls.append(request) or {"ok": True},
    )
    duplicate = guard.wrap_tool_call(
        _request("task", recruiter_args, "2"),
        lambda request: calls.append(request) or {"ok": True},
    )
    missing.remove("recruiter")

    observed = []
    task = SimpleNamespace(name="task")
    synthesis = SimpleNamespace(name="submit_target_assessment_synthesis")
    model_request = SimpleNamespace(
        tools=[task, synthesis],
        override=lambda **changes: SimpleNamespace(tools=changes["tools"]),
    )
    guard.wrap_model_call(
        model_request,
        lambda request: observed.extend(request.tools),
    )
    remaining = guard.wrap_tool_call(
        _request("task", {"subagent_type": "ats", "description": "Review as ATS."}, "3"),
        lambda request: calls.append(request) or {"ok": True},
    )

    payload = json.loads(duplicate.content)
    assert payload["reason"].startswith("identical_call_no_new_information")
    assert payload["missing_required_specialists"] == ["recruiter", "ats"]
    assert observed == [task, synthesis]
    assert remaining == {"ok": True}
    assert len(calls) == 2


def test_resumed_assessment_allows_completed_persona_revisit(monkeypatch):
    from recruitment_team.open_agent import context

    monkeypatch.setattr(context, "missing_required_specialists", lambda: ())
    monkeypatch.setattr(context, "completed_specialist_revisit_allowed", lambda: True)
    guard = ToolCallGuardMiddleware(enforce_fresh_specialists=True)
    calls = []

    result = guard.wrap_tool_call(
        _request("task", {"subagent_type": "recruiter"}, "1"),
        lambda request: calls.append(request) or {"ok": True},
    )

    assert result == {"ok": True}
    assert len(calls) == 1


def test_removes_completed_read_once_tool_from_the_next_model_request():
    guard = ToolCallGuardMiddleware()
    read_shortlist = SimpleNamespace(name="read_shortlist")
    search_jobs = SimpleNamespace(name="search_jobs")
    guard.wrap_tool_call(
        _request("read_shortlist", {}, "1"),
        lambda _request: {"ok": True},
    )
    observed = []
    model_request = SimpleNamespace(
        tools=[read_shortlist, search_jobs],
        override=lambda **changes: SimpleNamespace(tools=changes["tools"]),
    )

    guard.wrap_model_call(
        model_request,
        lambda request: observed.extend(request.tools) or "done",
    )

    assert observed == [search_jobs]


def test_hides_preferences_only_after_an_accepted_batch():
    guard = ToolCallGuardMiddleware()
    preferences = SimpleNamespace(name="record_preferences")
    search_jobs = SimpleNamespace(name="search_jobs")
    model_request = SimpleNamespace(
        tools=[preferences, search_jobs],
        override=lambda **changes: SimpleNamespace(tools=changes["tools"]),
    )

    guard.wrap_tool_call(
        _request("record_preferences", {"updates": []}, "1"),
        lambda _request: {"accepted": False},
    )
    before_acceptance = []
    guard.wrap_model_call(
        model_request,
        lambda request: before_acceptance.extend(request.tools),
    )
    guard.wrap_tool_call(
        _request("record_preferences", {"updates": [{"field": "location"}]}, "2"),
        lambda _request: {"accepted": True},
    )
    after_acceptance = []
    guard.wrap_model_call(
        model_request,
        lambda request: after_acceptance.extend(request.tools),
    )

    assert before_acceptance == [preferences, search_jobs]
    assert after_acceptance == [search_jobs]


def test_allows_same_synthesis_after_specialists_change_runtime_state():
    guard = ToolCallGuardMiddleware()
    calls = []
    args = {"claims": [{"statement": "Grounded claim"}]}

    guard.wrap_tool_call(
        _request("submit_target_assessment_synthesis", args, "1"),
        lambda request: calls.append(request) or {"ok": False, "retry": True},
    )
    guard.wrap_tool_call(
        _request("submit_target_assessment_synthesis", args, "2"),
        lambda request: calls.append(request) or {"ok": True, "accepted": True},
    )

    assert len(calls) == 2


def test_rejects_tools_outside_the_explicit_workflow_allowlist():
    guard = ToolCallGuardMiddleware(allowed_tools={"read_target_job", "task"})
    calls = []

    refusal = guard.wrap_tool_call(
        _request("read_file", {"file_path": "/tmp/irrelevant"}, "1"),
        lambda request: calls.append(request) or {"ok": True},
    )

    assert calls == []
    assert json.loads(refusal.content) == {
        "ok": False,
        "failure_type": "validation",
        "reason": "tool_not_available_for_this_workflow",
        "retry": False,
    }


def test_rejects_parallel_identical_calls_before_both_handlers_start():
    """LangGraph executes calls from one model message on worker threads."""
    guard = ToolCallGuardMiddleware()
    barrier = threading.Barrier(2)
    calls = []

    def invoke(call_id):
        barrier.wait()
        return guard.wrap_tool_call(
            _request("search_jobs", {"query": "platform engineer"}, call_id),
            lambda request: calls.append(request) or {"ok": True},
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(invoke, ("1", "2")))

    assert len(calls) == 1
    decoded = [
        json.loads(result.content) if hasattr(result, "content") else result
        for result in results
    ]
    assert sum(item.get("ok") is True for item in decoded) == 1
    assert sum(item.get("retry") is False for item in decoded) == 1


def test_bounds_concurrent_specialist_delegations(monkeypatch):
    specialist_limit = 2
    monkeypatch.setattr(
        tool_call_guard,
        "_specialist_slots",
        threading.BoundedSemaphore(specialist_limit),
    )
    guard = ToolCallGuardMiddleware()
    active = 0
    peak = 0
    lock = threading.Lock()

    def handler(_request):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.02)
        with lock:
            active -= 1
        return {"ok": True}

    def delegate(index):
        return guard.wrap_tool_call(
            _request("task", {"subagent_type": f"persona-{index}"}, str(index)),
            handler,
        )

    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(delegate, range(5)))

    assert peak == specialist_limit
    assert results == [{"ok": True}] * 5
