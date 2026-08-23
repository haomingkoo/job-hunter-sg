from __future__ import annotations

from dataclasses import replace

import pytest

from backend.tests.fakes import AllowingEditEvidenceValidator
from recruitment_team.assessment_contracts import (
    JudgeSubmission,
    TARGET_SYNTHESIS_MAX_CITATIONS_PER_KIND,
    TARGET_SYNTHESIS_MAX_CLAIMS,
    TARGET_SYNTHESIS_MAX_STATEMENT_CHARS,
    TargetAssessmentRequest,
    validate_judge_submission,
)
from recruitment_team.open_agent import context as open_agent_context
from recruitment_team.open_agent.context import assessment_context
from recruitment_team.open_agent.tools import (
    ask_candidate,
    propose_resume_edit,
    read_candidate_evidence,
    read_target_job,
    submit_target_assessment_synthesis,
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


def _judge_submission(*, weakness: str = "") -> JudgeSubmission:
    return JudgeSubmission(
        strengths=["The synthesis stays close to the cited evidence."],
        weaknesses=[weakness] if weakness else [],
        deductions=[],
        evidence_gaps=[],
        rubric_scores={
            "evidence_grounding": 90,
            "role_coverage": 90,
            "decision_usefulness": 90,
            "fairness_and_boundaries": 90,
        },
        score=90,
        score_reason="This score measures output quality.",
        confidence=90,
        confidence_reason="The supplied records are sufficient to review the output.",
        disposition="pass",
    )


@pytest.mark.parametrize(
    ("weakness", "failure"),
    [
        ("The synthesis should quantify 0% alignment.", "judge:candidate_scoring_claim"),
        ("The candidate's hiring probability is unclear.", "judge:speculative_claim"),
        ("The candidate will pass the first screening.", "judge:speculative_claim"),
        ("The candidate's citizenship is not discussed.", "judge:protected_status"),
    ],
)
def test_judge_contract_rejects_candidate_screening_claims(weakness, failure):
    assert failure in validate_judge_submission(_judge_submission(weakness=weakness))


def test_judge_contract_accepts_output_quality_language():
    assert validate_judge_submission(_judge_submission()) == ()
    assert validate_judge_submission(_judge_submission(
        weakness="The synthesis avoids predicting whether the candidate will pass screening.",
    )) == ()
    assert validate_judge_submission(_judge_submission(
        weakness="The synthesis avoids hiring-probability and competitive-candidate claims.",
    )) == ()


def test_synthesis_tool_schema_bounds_provider_output_size():
    schema = submit_target_assessment_synthesis.args_schema.model_json_schema()
    claims = schema["properties"]["claims"]
    claim = schema["$defs"]["SynthesisClaim"]["properties"]

    assert claims["maxItems"] == TARGET_SYNTHESIS_MAX_CLAIMS
    assert claim["statement"]["maxLength"] == TARGET_SYNTHESIS_MAX_STATEMENT_CHARS
    for field_name in (
        "criterion_ids",
        "candidate_profile_field_ids",
        "resume_evidence_ids",
        "candidate_evidence_ids",
    ):
        assert claim[field_name]["maxItems"] == TARGET_SYNTHESIS_MAX_CITATIONS_PER_KIND


def test_read_candidate_evidence_returns_current_request_fields():
    request = _request()
    with assessment_context(request):
        result = read_candidate_evidence.invoke({})
    assert result["ok"] is True
    assert result["fields"]
    assert "score_reason" not in result["fields"][0]
    assert "resume_document_id" not in result


def test_read_target_job_returns_current_role_profile_and_job():
    request = _request()
    with assessment_context(request):
        result = read_target_job.invoke({})
    assert result["ok"] is True
    assert result["target_job"]["title"] or result["target_job"]
    assert result["role_profile"]["criteria"]
    assert "candidate_evidence" not in result["role_profile"]
    assert "cited_resume_evidence" not in result["role_profile"]
    assert "sources" not in result["role_profile"]


def test_read_target_job_excludes_protected_preferences_from_model_copy():
    request = _request()
    request = replace(
        request,
        target_job=replace(
            request.target_job,
            description=(
                "Design resilient banking systems. Singapore citizens or permanent "
                "residents preferred. Must be authorised to work in Singapore."
            ),
        ),
    )

    with assessment_context(request):
        result = read_target_job.invoke({})

    description = result["target_job"]["description"]
    assert "citizen" not in description.casefold()
    assert "permanent resident" not in description.casefold()
    assert "authorised to work" in description.casefold()


def test_target_synthesis_accepts_only_evidence_linked_claims():
    request = _request()
    with assessment_context(request):
        result = submit_target_assessment_synthesis.invoke({
            "claims": [{
                "kind": "strength",
                "statement": "Built a production agent platform with traced model and tool calls.",
                "criterion_ids": ["design_agent_systems"],
                "candidate_profile_field_ids": ["demonstrated_agent_platform"],
                "resume_evidence_ids": ["b_test"],
                "candidate_evidence_ids": [],
            }]
        })
        rendered = open_agent_context.submitted_synthesis()

    assert result == {"ok": True, "accepted": True, "claim_count": 1}
    assert rendered == (
        "Strengths\n- Built a production agent platform with traced model and tool calls."
    )


def test_target_synthesis_waits_for_every_runtime_required_specialist():
    request = _request()
    with assessment_context(
        request,
        required_specialist_ids=("recruiter", "ats"),
        initial_specialist_ids=("recruiter",),
    ):
        result = submit_target_assessment_synthesis.invoke({
            "claims": [{
                "kind": "next_step",
                "statement": "Prepare an example about designing agent systems.",
                "criterion_ids": ["design_agent_systems"],
                "candidate_profile_field_ids": [],
                "resume_evidence_ids": [],
                "candidate_evidence_ids": [],
            }]
        })

    assert result["accepted"] is False
    assert result["failure_code"] == "required_specialists_missing"
    assert result["missing_specialists"] == ["ats"]


def test_target_synthesis_allows_non_factual_step_counts():
    request = _request()
    with assessment_context(request):
        result = submit_target_assessment_synthesis.invoke({
            "claims": [{
                "kind": "next_step",
                "statement": "Prepare 3 examples about designing agent systems.",
                "criterion_ids": ["design_agent_systems"],
                "candidate_profile_field_ids": [],
                "resume_evidence_ids": [],
                "candidate_evidence_ids": [],
            }]
        })

    assert result["accepted"] is True


def test_target_synthesis_accepts_equivalent_supported_duration_wording():
    request = _request()
    criteria = tuple(
        replace(
            criterion,
            statement="At least 5 years designing agent systems.",
        )
        if criterion.criterion_id == "design_agent_systems"
        else criterion
        for criterion in request.role_profile.criteria
    )
    request = replace(
        request,
        role_profile=replace(request.role_profile, criteria=criteria),
    )

    with assessment_context(request):
        result = submit_target_assessment_synthesis.invoke({
            "claims": [{
                "kind": "gap",
                "statement": "Evidence does not establish 5+ years designing agent systems.",
                "criterion_ids": ["design_agent_systems"],
                "candidate_profile_field_ids": [],
                "resume_evidence_ids": [],
                "candidate_evidence_ids": [],
            }]
        })

    assert result["accepted"] is True


@pytest.mark.parametrize(
    ("statement", "validation_code"),
    [
        ("Built the platform over 12 years.", "synthesis:claim:0:unsupported_numeric_claim:12_years"),
        ("The resume is suspiciously thin for this role.", "synthesis:claim:0:speculative_claim"),
        ("This is a strong market with excellent hiring prospects.", "synthesis:claim:0:speculative_claim"),
    ],
)
def test_target_synthesis_rejects_unsupported_math_and_speculation(
    statement,
    validation_code,
):
    request = _request()
    with assessment_context(request):
        result = submit_target_assessment_synthesis.invoke({
            "claims": [{
                "kind": "strength",
                "statement": statement,
                "criterion_ids": ["design_agent_systems"],
                "candidate_profile_field_ids": ["demonstrated_agent_platform"],
                "resume_evidence_ids": ["b_test"],
                "candidate_evidence_ids": [],
            }]
        })
        rendered = open_agent_context.submitted_synthesis()

    assert result["ok"] is False
    assert validation_code in result["validation_codes"]
    assert rendered == ""


def test_target_synthesis_stops_after_its_validation_budget():
    request = _request()
    payload = {
        "claims": [{
            "kind": "strength",
            "statement": "Built the platform over 12 years.",
            "criterion_ids": ["design_agent_systems"],
            "candidate_profile_field_ids": ["demonstrated_agent_platform"],
            "resume_evidence_ids": ["b_test"],
            "candidate_evidence_ids": [],
        }]
    }

    with assessment_context(request):
        first = submit_target_assessment_synthesis.invoke(payload)
        terminal = submit_target_assessment_synthesis.invoke(payload)

    assert first["attempt"] == 1 and first["retry"] is True
    assert terminal["attempt"] == 2 and terminal["retry"] is False
    assert "budget exhausted" in terminal["reason"].casefold()


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


def test_ask_candidate_rejects_protected_status_but_allows_work_authorisation():
    rejected = ask_candidate.invoke(
        {"questions": ["Are you a Singaporean or Singapore Permanent Resident?"]}
    )
    allowed = ask_candidate.invoke(
        {"questions": ["Are you authorised to work in Singapore without employer sponsorship?"]}
    )

    assert rejected["ok"] is False
    assert rejected["retry"] is False
    assert allowed == {
        "ok": True,
        "questions": ["Are you authorised to work in Singapore without employer sponsorship?"],
    }


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
    # Interrupt middleware sees tool arguments before schema validation. Never
    # expose a model-produced container literally when its shape drifts.
    assert format_questions({"questions": [{"question": "Nested?"}]}) == "Nested?"
    assert format_questions({"questions": '["First?", {"question": "Second?"}]'}) == (
        "1. First?\n2. Second?"
    )
    assert format_questions({
        "questions": '["First?"], "": ["Second?"], "": "Third?"]',
    }) == "1. First?\n2. Second?\n3. Third?"


def test_question_rounds_are_counted_from_the_graph_state():
    """The cap has to read real history; nothing else bounds ask_candidate."""
    from recruitment_team.open_agent.runner import _ask_rounds_so_far, _checkpoint_state

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

    assert _ask_rounds_so_far(_checkpoint_state(_Agent(messages), {})) == 2
    assert _ask_rounds_so_far(_checkpoint_state(_Agent([]), {})) == 0


def test_counting_rounds_fails_closed_when_checkpoint_state_is_unavailable():
    """A broken checkpoint cannot silently reset the candidate-question budget."""
    from recruitment_team.open_agent.runner import CheckpointStateUnavailable, _checkpoint_state

    class _Broken:
        def get_state(self, _config):
            raise RuntimeError("checkpointer unavailable")

    with pytest.raises(CheckpointStateUnavailable):
        _checkpoint_state(_Broken(), {})
