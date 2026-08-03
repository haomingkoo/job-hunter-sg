from __future__ import annotations

import json
from types import SimpleNamespace

from recruitment_team.tool_call_guard import ToolCallGuardMiddleware


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
