from __future__ import annotations

from dataclasses import replace

import pytest
from langchain_core.messages import AIMessage

from recruitment_team.candidate_profile import (
    CandidateEvidenceProfile,
    CandidateProfileEvidence,
    CandidateProfileField,
)
from recruitment_team.candidate_profile_evaluator import (
    CandidateProfileEvaluationError,
    CandidateProfileEvaluationTransportError,
    LangChainCandidateProfileEvaluator,
    _evaluation_groups,
)


class _Model:
    model_name = "candidate-profile-evaluator-test-model"

    def __init__(self, payloads):
        self._payloads = iter(payloads)
        self.requests = []
        self.bindings = []

    def bind_tools(self, tools, **kwargs):
        assert len(tools) == 1
        self.bound_tool = tools[0].name
        assert self.bound_tool in {
            "submit_candidate_profile_field_evaluations",
            "submit_candidate_profile_evaluation_integration",
        }
        assert kwargs["tool_choice"] == self.bound_tool
        self.bindings.append(self.bound_tool)
        return self

    def invoke(self, messages):
        self.requests.append(messages)
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": self.bound_tool,
                    "args": next(self._payloads),
                    "id": f"evaluation-{len(self.requests)}",
                    "type": "tool_call",
                }
            ],
            response_metadata={"model_name": self.model_name},
            usage_metadata={"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
        )


def _profile() -> CandidateEvidenceProfile:
    evidence = CandidateProfileEvidence(
        evidence_id="block-1",
        kind="bullet",
        text="Reduced close from 8 days to 5 days.",
        source_locator="experience[0].bullets[0]",
        section_key="experience",
    )
    return CandidateEvidenceProfile(
        profile_version="candidate-evidence-profile-v3",
        resume_document_id="resume-document",
        resume_revision="resume-revision",
        fields=(
            CandidateProfileField(
                field_id="outcome-close-cycle",
                category="outcome",
                statement="Reduced close from 8 days to 5 days.",
                resume_evidence_ids=(evidence.evidence_id,),
                evidence_quotes=(evidence.text,),
                evidence_kind="direct",
                evidence_support_score=100,
                score_reason="The complete outcome is explicit.",
            ),
        ),
        cited_resume_evidence=(evidence,),
    )


def _field_submission(**field_changes):
    field = {
        "field_id": "outcome-close-cycle",
        "label": "supported",
        "strengths": ["The action and both cycle-time values are preserved."],
        "weaknesses": [],
        "evidence_ids": ["block-1"],
        "score": 100,
        "score_reason": "The statement is fully and explicitly supported.",
    }
    field.update(field_changes)
    return {"field_evaluations": [field]}


def _integration(**changes):
    payload = {
        "duplicate_overrides": [],
        "strengths": ["Every field has canonical evidence."],
        "weaknesses": [],
        "score": 100,
        "score_reason": "The only field preserves its source exactly.",
    }
    payload.update(changes)
    return payload


def test_evaluator_returns_field_strength_weakness_score_reason_and_citations():
    from recruitment_team.telemetry import RecordedTelemetry

    model = _Model([_field_submission(), _integration()])
    telemetry = RecordedTelemetry()

    run = LangChainCandidateProfileEvaluator(model, telemetry=telemetry).evaluate(_profile())

    field = run.evaluation.field_evaluations[0]
    assert field.field_id == "outcome-close-cycle"
    assert field.strengths == ("The action and both cycle-time values are preserved.",)
    assert field.weaknesses == ()
    assert field.score == 100
    assert field.score_reason == "The statement is fully and explicitly supported."
    assert field.evidence_ids == ("block-1",)
    assert run.evaluation.score == 100
    assert run.attempt_count == 2
    assert run.model_call_count == 2
    assert run.group_count == 1
    assert run.input_tokens == 40
    assert run.output_tokens == 20
    assert "<candidate_profile_evaluation_group>" in model.requests[0][1].content
    assert "<candidate_profile_evaluation_integration>" in model.requests[1][1].content
    assert not any("Reduced close" in str(value) for span in telemetry.spans for value in span.attributes.values())


def test_evaluator_retries_with_original_profile_failed_output_and_validation_code():
    from recruitment_team.telemetry import RecordedTelemetry

    rejected = _field_submission(evidence_ids=["unknown"])
    model = _Model([rejected, _field_submission(), _integration()])
    telemetry = RecordedTelemetry()

    run = LangChainCandidateProfileEvaluator(model, telemetry=telemetry).evaluate(_profile())

    assert run.attempt_count == 3
    assert run.validation_codes == ("group:1:field:outcome-close-cycle:noncanonical_evidence_id",)
    correction = model.requests[1][-1].content
    assert model.requests[1][1].content == model.requests[0][1].content
    assert "field:outcome-close-cycle:noncanonical_evidence_id" in correction
    assert "failed_candidate_profile_evaluation" in correction
    spans = [span for span in telemetry.spans if span.name.endswith("validation")]
    assert [span.attributes["retry_triggered"] for span in spans] == [True, False, False]


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (
            {"field_evaluations": []},
            "field_coverage:mismatch",
        ),
        (
            _field_submission(field_id="unknown"),
            "field_coverage:mismatch",
        ),
        (
            _field_submission(evidence_ids=["unknown"]),
            "field:outcome-close-cycle:noncanonical_evidence_id",
        ),
    ],
)
def test_evaluator_fails_closed_after_rejected_correction(payload, code):
    model = _Model([payload, payload])

    with pytest.raises(CandidateProfileEvaluationError) as caught:
        LangChainCandidateProfileEvaluator(model).evaluate(_profile())

    assert caught.value.validation_code == code


def test_evidence_connected_grouping_is_semantic_and_transitive():
    profile = _profile()
    first = profile.fields[0]
    bridge = CandidateProfileField(
        field_id="bridge",
        category="demonstrated_capability",
        statement="Bridge statement.",
        resume_evidence_ids=("block-1", "block-2"),
        evidence_quotes=("Bridge",),
        evidence_kind="direct",
        evidence_support_score=80,
        score_reason="Combined evidence.",
    )
    connected = CandidateProfileField(
        field_id="connected",
        category="domain",
        statement="Connected statement.",
        resume_evidence_ids=("block-2",),
        evidence_quotes=("Connected",),
        evidence_kind="direct",
        evidence_support_score=80,
        score_reason="Direct evidence.",
    )
    separate = CandidateProfileField(
        field_id="separate",
        category="credential",
        statement="Separate statement.",
        resume_evidence_ids=("block-3",),
        evidence_quotes=("Separate",),
        evidence_kind="direct",
        evidence_support_score=80,
        score_reason="Direct evidence.",
    )
    grouped = replace(profile, fields=(first, separate, connected, bridge))

    groups = _evaluation_groups(grouped)

    assert [[field.field_id for field in group] for group in groups] == [
        ["outcome-close-cycle", "bridge", "connected"],
        ["separate"],
    ]


def test_cross_profile_integration_can_mark_a_cross_group_duplicate():
    profile = _profile()
    second_evidence = CandidateProfileEvidence(
        evidence_id="block-2",
        kind="bullet",
        text="Shortened the monthly close cycle.",
        source_locator="summary[0]",
        section_key="summary",
    )
    second_field = CandidateProfileField(
        field_id="duplicate-close-cycle",
        category="outcome",
        statement="Shortened the monthly close cycle.",
        resume_evidence_ids=(second_evidence.evidence_id,),
        evidence_quotes=(second_evidence.text,),
        evidence_kind="direct",
        evidence_support_score=90,
        score_reason="Explicit but overlaps another field.",
    )
    profile = replace(
        profile,
        fields=(*profile.fields, second_field),
        cited_resume_evidence=(*profile.cited_resume_evidence, second_evidence),
    )
    second_submission = {
        "field_evaluations": [
            {
                "field_id": second_field.field_id,
                "label": "supported",
                "strengths": ["The source states a shorter close cycle."],
                "weaknesses": [],
                "evidence_ids": [second_evidence.evidence_id],
                "score": 90,
                "score_reason": "The local statement is explicit.",
            }
        ]
    }
    integration = _integration(
        duplicate_overrides=[
            {
                "field_id": second_field.field_id,
                "duplicate_of_field_id": "outcome-close-cycle",
                "weakness": "It repeats the same close-cycle outcome at lower specificity.",
                "score": 65,
                "score_reason": "Locally supported but redundant across the profile.",
            }
        ],
        weaknesses=["One outcome is duplicated across evidence groups."],
        score=82,
        score_reason="Strong provenance with one cross-group duplication.",
    )
    model = _Model([_field_submission(), second_submission, integration])

    run = LangChainCandidateProfileEvaluator(model).evaluate(profile)

    duplicate = run.evaluation.field_evaluations[1]
    assert run.group_count == 2
    assert run.model_call_count == 3
    assert duplicate.label == "duplicated"
    assert duplicate.score == 65
    assert duplicate.weaknesses == ("It repeats the same close-cycle outcome at lower specificity.",)


def test_evaluator_propagates_transport_failure_with_stage_and_no_hidden_retry():
    from recruitment_team.telemetry import RecordedTelemetry

    class FailingModel(_Model):
        def __init__(self):
            super().__init__([])

        def invoke(self, messages):
            self.requests.append(messages)
            raise TimeoutError("provider timeout")

    telemetry = RecordedTelemetry()

    with pytest.raises(CandidateProfileEvaluationTransportError) as caught:
        LangChainCandidateProfileEvaluator(FailingModel(), telemetry=telemetry).evaluate(_profile())

    assert caught.value.stage == "local_field_evaluation"
    assert caught.value.attempt == 1
    assert caught.value.cause_type == "TimeoutError"
    attempts = [span for span in telemetry.spans if span.name == "candidate_profile_evaluation.model_attempt"]
    assert len(attempts) == 1
    assert attempts[0].attributes["status"] == "error"
    assert attempts[0].attributes["transport_retries"] == 0


def test_evaluator_prompt_has_rubric_examples_but_no_expected_benchmark_score():
    import re

    from recruitment_team.prompts.candidate_profile_evaluator import (
        CANDIDATE_PROFILE_EVALUATOR_SYSTEM_PROMPT,
    )

    assert "Few-shot boundaries" in CANDIDATE_PROFILE_EVALUATOR_SYSTEM_PROMPT
    assert "strengths" in CANDIDATE_PROFILE_EVALUATOR_SYSTEM_PROMPT
    assert "weaknesses" in CANDIDATE_PROFILE_EVALUATOR_SYSTEM_PROMPT
    assert "score_reason" in CANDIDATE_PROFILE_EVALUATOR_SYSTEM_PROMPT
    normalized = re.sub(r"\s+", " ", CANDIDATE_PROFILE_EVALUATOR_SYSTEM_PROMPT)
    assert "do not compare it with an embedded expected score" in normalized
    assert "pass threshold" not in CANDIDATE_PROFILE_EVALUATOR_SYSTEM_PROMPT.casefold()
