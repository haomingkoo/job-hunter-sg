from __future__ import annotations

import json
from types import SimpleNamespace


def test_live_prompt_receipt_binds_revision_prompt_fixture_tools_and_result(
    tmp_path,
    monkeypatch,
):
    from backend.tests import test_resume_agent_live as live_eval

    monkeypatch.setattr(live_eval, "LIVE_PROMPT_EVAL_RECEIPT_DIR", tmp_path)
    discovery = SimpleNamespace(
        fixture=[{
            "job_id": 41,
            "title": "Semiconductor Quality Manager",
            "description": "Synthetic fixture text.",
        }],
        events=[{
            "kind": "tool_call",
            "tool_name": "search_jobs",
            "args": {"query": "semiconductor quality", "direct_employers_only": True},
        }],
        calls=[{"query": "semiconductor quality", "direct_employers_only": True}],
    )
    context = SimpleNamespace(
        thread_id="receipt-test-thread",
        drafted_matches=[{"job_id": 41}],
        drafted_preferences=[],
        proposed_edits=[],
    )
    telemetry = SimpleNamespace(spans=[])
    reply = SimpleNamespace(content="Source-backed synthetic match.")

    live_eval._write_prompt_eval_receipt(
        scenario="receipt-contract",
        repeat=0,
        revision="a" * 40,
        fixture={"message": "Find a role", "job_ids": [41]},
        discovery=discovery,
        context=context,
        telemetry=telemetry,
        reply=reply,
        invariants={"published_expected_job": True},
    )

    receipt = json.loads(next(tmp_path.glob("*.json")).read_text())
    assert receipt["receipt_version"] == "live-prompt-eval-receipt-v1"
    assert receipt["evaluation_kind"] == "live_provider_prompt_evaluation_not_outcome_backtest"
    assert receipt["implementation_sha"] == "a" * 40
    assert receipt["worktree_clean"] is True
    assert receipt["fixture_sha256"]
    assert receipt["prompt_sha256"]
    assert receipt["test_sha256"]
    assert receipt["model_parameters"]["temperature"] == 0.0
    assert receipt["tool_calls"] == [{
        "name": "search_jobs",
        "args": {"query": "semiconductor quality", "direct_employers_only": True},
    }]
    assert receipt["published_job_ids"] == [41]
    assert receipt["passed"] is True
    assert receipt["error_type"] == ""


def test_live_prompt_failure_receipt_is_retained_without_a_reply(tmp_path, monkeypatch):
    from backend.tests import test_resume_agent_live as live_eval

    monkeypatch.setattr(live_eval, "LIVE_PROMPT_EVAL_RECEIPT_DIR", tmp_path)
    discovery = SimpleNamespace(fixture=[], events=[], calls=[])
    context = SimpleNamespace(
        thread_id="failed-receipt-thread",
        drafted_matches=[],
        drafted_preferences=[],
        proposed_edits=[],
    )

    live_eval._write_prompt_eval_receipt(
        scenario="provider-failure",
        repeat=0,
        revision="b" * 40,
        fixture={"message": "Find roles"},
        discovery=discovery,
        context=context,
        telemetry=SimpleNamespace(spans=[]),
        error=TimeoutError("synthetic timeout"),
        invariants={"provider_turn_completed": False},
    )

    receipt = json.loads(next(tmp_path.glob("*.json")).read_text())
    assert receipt["passed"] is False
    assert receipt["error_type"] == "TimeoutError"
    assert receipt["reply_sha256"] == ""
