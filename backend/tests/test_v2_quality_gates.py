from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_v2_quality_gate_docs_cover_required_controls():
    text = (ROOT / "docs" / "v2-quality-gates.md").read_text()

    for phrase in [
        "one runnable check",
        "RUN_LIVE_SEALION=1",
        "tool-choice smoke",
        "search_jobs",
        "RUN_LIVE_MCP=1",
        "source_url",
        "source_type",
        "retrieved_at",
        "confidence",
        "candidate evidence",
        "market research",
        "UI smoke",
    ]:
        assert phrase in text


def test_v2_pr_template_captures_test_and_skip_status():
    text = (ROOT / ".github" / "pull_request_template.md").read_text()

    for phrase in [
        "Acceptance check",
        "Normal tests",
        "Live SEA-LION smoke",
        "Live MCP smoke",
        "UI smoke path",
        "Known skipped checks",
    ]:
        assert phrase in text


def test_v2_harness_points_to_existing_fake_agent_and_ui_smokes():
    agent_tests = (ROOT / "backend" / "tests" / "test_resume_agent.py").read_text()
    live_tests = (ROOT / "backend" / "tests" / "test_resume_agent_live.py").read_text()
    tracker_tests = (ROOT / "frontend" / "src" / "components" / "__tests__" / "TrackerTab.workspace.test.jsx").read_text()

    assert "FakeAgent" in agent_tests
    assert "RUN_LIVE_SEALION" in live_tests
    assert "search_jobs" in live_tests
    assert "opens a workspace detail view" in tracker_tests
    assert "groups tracked applications by status in board view" in tracker_tests
