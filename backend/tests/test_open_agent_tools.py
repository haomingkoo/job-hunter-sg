from __future__ import annotations

from recruitment_team.assessment_contracts import TargetAssessmentRequest
from recruitment_team.open_agent.context import assessment_context
from recruitment_team.open_agent.tools import read_candidate_evidence, read_target_job


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
