from __future__ import annotations

from recruitment_team.assessment_contracts import TargetAssessmentRequest
from recruitment_team.open_agent.context import assessment_context
from recruitment_team.open_agent.tools import (
    propose_resume_edit,
    read_candidate_evidence,
    read_target_job,
)


def _request(resume_document=None):
    from backend.tests.test_recruitment_team_module import (
        _candidate_profile_run,
        _job_snapshot,
        _role_profile_run,
    )

    return TargetAssessmentRequest(
        candidate_profile=_candidate_profile_run().profile,
        role_profile=_role_profile_run().profile,
        target_job=_job_snapshot(),
        trace_key="open-agent-trace-key",
        resume_document=resume_document,
    )


def test_read_candidate_evidence_returns_current_request_fields():
    request = _request()
    with assessment_context(request):
        result = read_candidate_evidence.invoke({})
    assert result["ok"] is True
    assert result["fields"]


def test_read_target_job_returns_current_role_profile_and_job():
    request = _request()
    with assessment_context(request):
        result = read_target_job.invoke({})
    assert result["ok"] is True
    assert result["target_job"]["title"] or result["target_job"]
    assert result["role_profile"]["criteria"]


def test_tools_fail_closed_outside_an_active_context():
    result = read_candidate_evidence.invoke({})
    assert result["ok"] is False
    assert result["failure_type"] == "business"


def _document():
    return {
        "schema_version": 1,
        "revision": "rev-1",
        "raw_text": "Led team of 12 engineers saving $3M.",
        "blocks": [
            {
                "id": "b1",
                "text": "Led team of 12 engineers saving $3M.",
                "section_key": "experience",
                "entry_id": "e1",
            }
        ],
    }


def test_propose_resume_edit_accepts_a_grounded_in_place_rewrite():
    request = _request(resume_document=_document())
    with assessment_context(request):
        result = propose_resume_edit.invoke(
            {"block_id": "b1", "rewrite": "Directed team of 12 engineers saving $3M."}
        )
    assert result["accepted"] is True
    assert result["application_status"] == "pending_user_review"


def test_propose_resume_edit_rejects_new_numeric_facts():
    request = _request(resume_document=_document())
    with assessment_context(request):
        result = propose_resume_edit.invoke(
            {"block_id": "b1", "rewrite": "Led team of 25 engineers saving $3M."}
        )
    assert result["accepted"] is False
    assert "25" in result["reason"]


def test_propose_resume_edit_rejects_multi_block_rewrite():
    request = _request(resume_document=_document())
    with assessment_context(request):
        result = propose_resume_edit.invoke(
            {"block_id": "b1", "rewrite": "Line one.\nLine two."}
        )
    assert result["accepted"] is False


def test_propose_resume_edit_rejects_unknown_block():
    request = _request(resume_document=_document())
    with assessment_context(request):
        result = propose_resume_edit.invoke(
            {"block_id": "does-not-exist", "rewrite": "Anything."}
        )
    assert result["accepted"] is False


def test_propose_resume_edit_rejects_via_validation_gates_with_no_new_numbers():
    # No new numeric facts here (12 and $3M are preserved), so this exercises
    # run_all_gates (hallucination gate) as a check independent of the
    # numeric-fact layer.
    request = _request(resume_document=_document())
    with assessment_context(request):
        result = propose_resume_edit.invoke(
            {
                "block_id": "b1",
                "rewrite": (
                    "Led team of 12 engineers saving $3M using Python, Docker, "
                    "Kubernetes, and Terraform."
                ),
            }
        )
    assert result["accepted"] is False
    assert "25" not in (result.get("reason") or "")


def test_propose_resume_edit_stops_at_the_cap(monkeypatch):
    import config

    monkeypatch.setattr(config, "OPEN_AGENT_MAX_PROPOSED_EDITS", 1)
    request = _request(resume_document=_document())
    with assessment_context(request):
        first = propose_resume_edit.invoke(
            {"block_id": "b1", "rewrite": "Directed team of 12 engineers saving $3M."}
        )
        second = propose_resume_edit.invoke(
            {"block_id": "b1", "rewrite": "Managed team of 12 engineers saving $3M."}
        )
    assert first["accepted"] is True
    assert second["accepted"] is False
    assert second["checkpoint_required"] is True
