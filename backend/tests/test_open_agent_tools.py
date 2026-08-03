from __future__ import annotations

from dataclasses import replace

from backend.tests.fakes import AllowingEditEvidenceValidator
from recruitment_team.assessment_contracts import TargetAssessmentRequest
from recruitment_team.open_agent.context import assessment_context
from recruitment_team.open_agent.tools import (
    ask_candidate,
    propose_resume_edit,
    read_candidate_evidence,
    read_target_job,
)
from recruitment_team.resume_edit_evidence import ResumeEditEvidenceResult


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
        edit_evidence_validator=AllowingEditEvidenceValidator(),
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


def test_propose_resume_edit_rejects_semantically_unsupported_scope():
    class _RejectingValidator:
        def validate(self, request):
            return ResumeEditEvidenceResult(
                supported=False,
                unsupported_claims=("coached production teams on performance management",),
                reason="Mentoring engineers does not establish production-team management.",
            )

    request = replace(
        _request(resume_document=_document()),
        edit_evidence_validator=_RejectingValidator(),
    )
    with assessment_context(request):
        result = propose_resume_edit.invoke({
            "block_id": "b1",
            "rewrite": (
                "Led team of 12 engineers saving $3M; coached production teams "
                "on performance management."
            ),
        })

    assert result["accepted"] is False
    assert result["failure_code"] == "unsupported_claims"
    assert "performance management" in result["reason"]
    assert "Remove the unsupported claims" in result["reason"]


def test_propose_resume_edit_resolves_profile_field_evidence_ids():
    class _RecordingValidator:
        def __init__(self):
            self.request = None

        def validate(self, request):
            self.request = request
            return ResumeEditEvidenceResult(supported=True, reason="Supported.")

    validator = _RecordingValidator()
    request = replace(
        _request(resume_document=_document()),
        edit_evidence_validator=validator,
    )
    field = request.candidate_profile.fields[0]
    with assessment_context(request):
        result = propose_resume_edit.invoke({
            "block_id": "b1",
            "rewrite": "Directed team of 12 engineers saving $3M.",
            "candidate_evidence_ids": [field.field_id],
        })

    assert result["accepted"] is True
    assert field.statement in validator.request.supporting_evidence


def test_ask_candidate_carries_every_question_in_one_pause():
    """One call, many questions: each pause costs the candidate a full wait."""
    result = ask_candidate.invoke(
        {"questions": ["How large was the team you led?", "Which storage did you operate?"]}
    )
    assert result["questions"] == [
        "How large was the team you led?",
        "Which storage did you operate?",
    ]
    assert result["ok"] is True


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


def test_several_questions_render_as_one_numbered_message():
    """The pause surfaces one message however many gaps the agent found."""
    from recruitment_team.open_agent.streaming import format_questions

    assert format_questions({"questions": ["Only one?"]}) == "Only one?"
    assert format_questions({"questions": ["First?", "Second?"]}) == "1. First?\n2. Second?"
    assert format_questions({"questions": []}) == ""
    # A model that sends a bare string instead of a list must still surface.
    assert format_questions({"questions": "Bare string?"}) == "Bare string?"


def test_question_rounds_are_counted_from_the_graph_state():
    """The cap has to read real history; nothing else bounds ask_candidate."""
    from recruitment_team.open_agent.runner import _ask_rounds_so_far

    class _Msg:
        def __init__(self, calls):
            self.tool_calls = calls

    class _State:
        def __init__(self, messages):
            self.values = {"messages": messages}

    class _Agent:
        def __init__(self, messages):
            self._messages = messages

        def get_state(self, _config):
            return _State(self._messages)

    messages = [
        _Msg([{"name": "ask_candidate", "args": {}}]),
        _Msg([{"name": "read_target_job", "args": {}}]),
        _Msg([{"name": "ask_candidate", "args": {}}]),
    ]

    assert _ask_rounds_so_far(_Agent(messages), {}) == 2
    assert _ask_rounds_so_far(_Agent([]), {}) == 0


def test_counting_rounds_never_breaks_a_resume():
    """A state read failure must not take down the run it is guarding."""
    from recruitment_team.open_agent.runner import _ask_rounds_so_far

    class _Broken:
        def get_state(self, _config):
            raise RuntimeError("checkpointer unavailable")

    assert _ask_rounds_so_far(_Broken(), {}) == 0
