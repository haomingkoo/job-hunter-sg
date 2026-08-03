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
