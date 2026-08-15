from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

from recruitment_team.candidate_profile import CandidateProfileField
from recruitment_team.role_evidence_assessor import (
    LangChainRoleEvidenceAssessor,
    RoleEvidenceAssessmentError,
    RoleEvidenceAssessmentRequest,
    RoleEvidenceAssessmentRun,
    RoleEvidenceJudgment,
    ScriptedRoleEvidenceAssessor,
    role_evidence_attempt_limit,
)
from recruitment_team.role_success import (
    CandidateEvidenceMatch,
    ResumeEvidenceRecord,
    RoleCitation,
    RoleCriterion,
    RoleProfileRun,
    RoleSource,
    RoleSuccessProfile,
    ScriptedRoleDefinitionGenerator,
    SourceCoverage,
)


class _Model:
    def __init__(self, payloads):
        self.payloads = iter(payloads)
        self.requests = []
        self.bindings = []

    def bind_tools(self, tools, **kwargs):
        names = [tool.name for tool in tools]
        assert names in (["submit_role_evidence_assessment"], ["submit_role_evidence_correction"])
        assert kwargs["tool_choice"] == names[0]
        self.bindings.append(names[0])
        self.bound_tool = names[0]
        return self

    def invoke(self, messages):
        self.requests.append(messages)
        payload = next(self.payloads)
        if isinstance(payload, BaseException):
            raise payload
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": self.bound_tool,
                    "args": payload,
                    "id": f"assessment-{len(self.requests)}",
                    "type": "tool_call",
                }
            ],
            response_metadata={"model_name": "assessor-test-model"},
            usage_metadata={"input_tokens": 13, "output_tokens": 5, "total_tokens": 18},
        )


def _request() -> RoleEvidenceAssessmentRequest:
    source_id = "target_job:7"
    criterion = RoleCriterion(
        criterion_id="regional_rollout",
        category="scope_seniority",
        requirement_level="required",
        statement="Lead a rollout across 5 markets.",
        source_ids=(source_id,),
        source_citations=(
            RoleCitation(
                source_id=source_id,
                source_path="description",
                relevant_excerpt="Lead a rollout across 5 markets.",
            ),
        ),
    )
    block = ResumeEvidenceRecord(
        evidence_id="block-1",
        kind="bullet",
        text="Led the rollout for Singapore, preventing USD 2M in potential losses.",
        source_locator="experience[0].bullets[0]",
        section_key="experience",
    )
    source = RoleSource(
        source_id=source_id,
        source_type="target_job",
        title="Regional Operations Lead",
        url="https://example.test/jobs/7",
        publication_date="2026-07-01",
        evidence_strength="primary",
        evidence_fields=("description",),
    )
    proposed = CandidateEvidenceMatch(
        criterion_id=criterion.criterion_id,
        alignment="direct",
        resume_evidence_ids=(block.evidence_id,),
        explanation="Draft only.",
        confidence=0.9,
        confidence_basis="Draft only.",
    )
    profile_field = CandidateProfileField(
        field_id="profile-regional-rollout",
        category="demonstrated_capability",
        statement="Led the rollout for Singapore.",
        resume_evidence_ids=(block.evidence_id,),
        evidence_quotes=("Led the rollout for Singapore",),
        evidence_kind="direct",
        evidence_support_score=100,
        score_reason="Explicit action.",
    )
    return RoleEvidenceAssessmentRequest(
        (criterion,),
        (block,),
        (source,),
        (profile_field,),
        (proposed,),
    )


def _judgment(**changes):
    item = {
        "criterion_id": "regional_rollout",
        "alignment": "partial",
        "resume_evidence_ids": ["block-1"],
        "candidate_profile_field_ids": ["profile-regional-rollout"],
        "supported_strength": "The candidate led the rollout for Singapore.",
        "remaining_gap": "Leadership across 5 markets is not shown.",
        "evidence_support_score": 55,
        "score_reason": "The cited block supports rollout leadership in Singapore only.",
    }
    item.update(changes)
    return item


def _two_criterion_request() -> RoleEvidenceAssessmentRequest:
    request = _request()
    stable_criterion = RoleCriterion(
        criterion_id="monthly_forecast",
        category="responsibilities",
        requirement_level="required",
        statement="Prepare a monthly forecast.",
        source_ids=request.criteria[0].source_ids,
        source_citations=(
            RoleCitation(
                source_id="target_job:7",
                source_path="description",
                relevant_excerpt="Prepare a monthly forecast.",
            ),
        ),
    )
    stable_block = ResumeEvidenceRecord(
        evidence_id="block-2",
        kind="bullet",
        text="Prepared monthly forecasts for senior leaders.",
        source_locator="experience[0].bullets[1]",
        section_key="experience",
    )
    stable_field = CandidateProfileField(
        field_id="profile-monthly-forecast",
        category="demonstrated_capability",
        statement="Prepared monthly forecasts for senior leaders.",
        resume_evidence_ids=(stable_block.evidence_id,),
        evidence_quotes=(stable_block.text,),
        evidence_kind="direct",
        evidence_support_score=100,
        score_reason="Explicit action.",
    )
    return RoleEvidenceAssessmentRequest(
        criteria=(stable_criterion, *request.criteria),
        resume_blocks=(*request.resume_blocks, stable_block),
        role_sources=request.role_sources,
        candidate_profile_fields=(*request.candidate_profile_fields, stable_field),
    )


def _stable_judgment():
    return {
        "criterion_id": "monthly_forecast",
        "alignment": "direct",
        "resume_evidence_ids": ["block-2"],
        "candidate_profile_field_ids": ["profile-monthly-forecast"],
        "supported_strength": "  Exact stable strength.  ",
        "remaining_gap": "None",
        "evidence_support_score": 90,
        "score_reason": "Explicit monthly forecasting evidence.",
    }


def test_assessor_returns_one_validated_judgment_and_uses_xml_tool_contract():
    model = _Model([{"judgments": [_judgment()]}])

    run = LangChainRoleEvidenceAssessor(model).assess(_request())

    assert run.attempt_count == 1
    assert run.prompt_version == "role-evidence-assessor-v9"
    assert run.judgments[0].alignment == "partial"
    assert run.judgments[0].evidence_support_score == 55
    data_message = model.requests[0][1].content
    assert data_message.startswith("<role_evidence_assessment_data>")
    assert '"proposed_evidence"' in data_message
    assert '"candidate_profile_fields"' in data_message
    assert '"profile-regional-rollout"' in data_message
    assert "Draft only." in data_message


def test_assessor_retries_once_with_original_evidence_failed_output_and_exact_error():
    import config

    from recruitment_team.telemetry import RecordedTelemetry

    rejected = {"judgments": [_judgment(), _judgment()]}
    model = _Model([rejected, {"judgments": [_judgment()]}])
    telemetry = RecordedTelemetry()
    renewals = []

    with telemetry.operation("role_success.profile") as parent:
        run = LangChainRoleEvidenceAssessor(
            model,
            telemetry=telemetry,
        ).assess(_request(), before_model_call=lambda: renewals.append("renewed"))

    assert run.attempt_count == 2
    assert renewals == ["renewed"] * 4
    assert run.validation_codes == ("criterion_coverage:duplicate_ids",)
    retry = model.requests[1]
    assert retry[1].content == model.requests[0][1].content
    assert "<validation_error_data>\ncriterion_coverage:duplicate_ids" in retry[2].content
    assert "<failed_assessment_data>" in retry[2].content
    assert "regional_rollout" in retry[2].content
    attempts = [span for span in telemetry.spans if span.name == "role_evidence_assessment.model_attempt"]
    validations = [span for span in telemetry.spans if span.name == "role_evidence_assessment.validation"]
    assert [span.parent_id for span in (*attempts, *validations)] == [parent.span_id] * 4
    assert attempts[0].attributes == {
        "attempt": 1,
        "max_attempts": role_evidence_attempt_limit(len(_request().criteria)),
        "prompt_version": "role-evidence-assessor-v9",
        "configured_timeout_seconds": config.RECRUITMENT_MODEL_HTTP_TIMEOUT_SECONDS,
        "transport_retries": config.RECRUITMENT_MODEL_TRANSPORT_RETRIES,
        "correction_scope": "full",
        "model": "assessor-test-model",
        "input_tokens": 13,
        "output_tokens": 5,
        "status": "success",
        "error_type": "",
    }
    assert [span.attributes for span in validations] == [
        {
            "attempt": 1,
            "correction_scope": "full",
            "validation_code": "criterion_coverage:duplicate_ids",
            "accepted": False,
            "retry_triggered": True,
        },
        {
            "attempt": 2,
            "correction_scope": "full",
            "validation_code": "",
            "accepted": True,
            "retry_triggered": False,
        },
    ]
    assert not any("regional_rollout" in str(value) for span in telemetry.spans for value in span.attributes.values())
    assert model.bindings == [
        "submit_role_evidence_assessment",
        "submit_role_evidence_assessment",
    ]


def test_assessor_targets_one_failed_judgment_and_preserves_other_values():
    from recruitment_team.telemetry import RecordedTelemetry

    request = _two_criterion_request()
    stable = _stable_judgment()
    failed = _judgment(supported_strength='The candidate "led 5 markets".')
    corrected = _judgment(
        supported_strength="The candidate led the Singapore rollout.",
        remaining_gap="Leadership across all required markets is not shown.",
        score_reason="The cited evidence supports one-market rollout leadership.",
    )
    model = _Model(
        [
            {"judgments": [stable, failed]},
            {"judgment": corrected},
        ]
    )
    telemetry = RecordedTelemetry()

    run = LangChainRoleEvidenceAssessor(model, telemetry=telemetry).assess(request)

    assert model.bindings == [
        "submit_role_evidence_assessment",
        "submit_role_evidence_correction",
    ]
    correction_message = model.requests[1][1].content
    assert "<role_evidence_correction_data>" in correction_message
    assert "literal_quote:unsupported:'led 5 markets':regional_rollout" in correction_message
    assert '"criterion_id":"regional_rollout"' in correction_message
    assert '"criterion_id":"monthly_forecast"' not in correction_message
    assert "Exact stable strength" not in correction_message
    assert '"evidence_id":"block-1"' in correction_message
    assert '"evidence_id":"block-2"' in correction_message
    assert "Prepared monthly forecasts for senior leaders." in correction_message
    assert run.judgments[0] == RoleEvidenceJudgment(
        criterion_id=stable["criterion_id"],
        alignment=stable["alignment"],
        resume_evidence_ids=tuple(stable["resume_evidence_ids"]),
        candidate_profile_field_ids=tuple(stable["candidate_profile_field_ids"]),
        supported_strength=stable["supported_strength"],
        remaining_gap=stable["remaining_gap"],
        evidence_support_score=stable["evidence_support_score"],
        score_reason=stable["score_reason"],
    )
    assert run.judgments[1].supported_strength == corrected["supported_strength"]
    attempts = [span for span in telemetry.spans if span.name == "role_evidence_assessment.model_attempt"]
    validations = [span for span in telemetry.spans if span.name == "role_evidence_assessment.validation"]
    assert [span.attributes["correction_scope"] for span in attempts] == [
        "full",
        "single_criterion",
    ]
    assert [span.attributes["correction_scope"] for span in validations] == [
        "full",
        "single_criterion",
    ]
    assert not any(
        "Prepared monthly forecasts for senior leaders" in str(value)
        for span in telemetry.spans
        for value in span.attributes.values()
    )


def test_rejected_assessment_resumes_at_its_correction_after_timeout():
    request = _two_criterion_request()
    rejected = {
        "judgments": [
            _stable_judgment(),
            _judgment(supported_strength='The candidate "led 5 markets".'),
        ]
    }
    checkpoints = []
    interrupted_model = _Model([rejected, TimeoutError("correction timed out")])

    with pytest.raises(TimeoutError, match="correction timed out"):
        LangChainRoleEvidenceAssessor(interrupted_model).assess(
            request,
            save_checkpoint=checkpoints.append,
        )

    assert [item.previous_scope for item in checkpoints] == ["full", "single_criterion"]
    checkpoint = checkpoints[-1]
    assert checkpoint.attempt_count == 1
    assert checkpoint.previous_scope == "single_criterion"
    assert checkpoint.validation_code.startswith("literal_quote:unsupported:")

    corrected = _judgment(
        supported_strength="The candidate led the Singapore rollout.",
        remaining_gap="Leadership across all required markets is not shown.",
        score_reason="The cited evidence supports one-market rollout leadership.",
    )
    resumed_model = _Model([{"judgment": corrected}])
    run = LangChainRoleEvidenceAssessor(resumed_model).assess(request, checkpoint=checkpoint)

    assert resumed_model.bindings == ["submit_role_evidence_correction"]
    assert run.attempt_count == 2
    assert run.judgments[1].supported_strength == corrected["supported_strength"]


def test_assessor_corrects_distinct_invalid_criteria_sequentially():
    request = _two_criterion_request()
    wrong_field = _judgment(candidate_profile_field_ids=["profile-monthly-forecast"])
    unsupported_number = _stable_judgment()
    unsupported_number["score_reason"] = "The evidence covers 30 of 35 required activities."
    corrected_number = _stable_judgment()
    corrected_number["resume_evidence_ids"] *= 2
    corrected_number["candidate_profile_field_ids"] *= 2
    model = _Model(
        [
            {"judgments": [wrong_field, unsupported_number]},
            {"judgment": _judgment()},
            {"judgment": corrected_number},
        ]
    )

    run = LangChainRoleEvidenceAssessor(model).assess(request)

    assert run.attempt_count == 3
    assert run.validation_codes == (
        "candidate_profile_field_ids:evidence_mismatch",
        "numeric_claim:unsupported",
    )
    assert model.bindings == [
        "submit_role_evidence_assessment",
        "submit_role_evidence_correction",
        "submit_role_evidence_correction",
    ]
    numeric_correction = model.requests[2][1].content
    assert '"unsupported_numbers":["30","35"]' in numeric_correction
    assert '"field_id":"profile-monthly-forecast"' in numeric_correction
    assert '"field_id":"profile-regional-rollout"' not in numeric_correction
    assert '"evidence_id":"block-2"' in numeric_correction
    assert '"evidence_id":"block-1"' not in numeric_correction
    assert (
        next(item for item in run.judgments if item.criterion_id == "monthly_forecast").score_reason
        == (corrected_number["score_reason"])
    )
    monthly = next(item for item in run.judgments if item.criterion_id == "monthly_forecast")
    assert monthly.resume_evidence_ids == ("block-2",)
    assert monthly.candidate_profile_field_ids == ("profile-monthly-forecast",)


@pytest.mark.parametrize(
    ("changes", "error"),
    [
        ({"resume_evidence_ids": ["unknown"]}, "resume_evidence_ids:unknown:unknown:regional_rollout"),
        (
            {"candidate_profile_field_ids": []},
            "candidate_profile_field_ids:missing_for_positive:regional_rollout",
        ),
        (
            {"candidate_profile_field_ids": ["unknown"]},
            "candidate_profile_field_ids:unknown:unknown:regional_rollout",
        ),
        (
            {"supported_strength": 'The candidate "led 5 markets".'},
            "literal_quote:unsupported:'led 5 markets':regional_rollout",
        ),
        (
            {"score_reason": "The evidence proves USD 9M in savings."},
            "numeric_claim:unsupported:9m:regional_rollout",
        ),
    ],
)
def test_assessor_rejects_invalid_ids_quotes_and_numbers_without_fallback(changes, error, monkeypatch):
    import config

    monkeypatch.setattr(config, "ROLE_EVIDENCE_VALIDATION_ATTEMPTS", 2)
    payload = {"judgments": [_judgment(**changes)]}
    model = _Model([payload, {"judgment": _judgment(**changes)}])

    with pytest.raises(RoleEvidenceAssessmentError) as caught:
        LangChainRoleEvidenceAssessor(model).assess(_request())

    assert caught.value.validation_code == error
    assert caught.value.rejected_submission == payload
    assert len(model.requests) == 2
    assert model.bindings == [
        "submit_role_evidence_assessment",
        "submit_role_evidence_correction",
    ]


def test_assessor_rejects_resume_evidence_not_owned_by_selected_profile_field(monkeypatch):
    import config

    monkeypatch.setattr(config, "ROLE_EVIDENCE_VALIDATION_ATTEMPTS", 2)
    request = _two_criterion_request()
    regional = _judgment(candidate_profile_field_ids=["profile-monthly-forecast"])
    stable = _stable_judgment()
    model = _Model(
        [
            {"judgments": [stable, regional]},
            {"judgment": regional},
        ]
    )

    with pytest.raises(RoleEvidenceAssessmentError) as caught:
        LangChainRoleEvidenceAssessor(model).assess(request)

    assert caught.value.validation_code == ("candidate_profile_field_ids:evidence_mismatch:block-1:regional_rollout")
    assert len(model.requests) == 2
    correction_message = model.requests[1][1].content
    assert "candidate_profile_field_ids:evidence_mismatch:block-1:regional_rollout" in correction_message
    assert "remove or replace exactly those" in correction_message


def test_assessor_correction_names_the_valid_field_for_orphaned_evidence_and_can_recover():
    """A model that cited evidence via the wrong profile field is told exactly
    which field(s) actually own that evidence, and can use that to submit a
    valid correction -- proving the retry can genuinely recover, not just
    fail identically twice (the real-world failure this test guards)."""
    request = _two_criterion_request()
    unrelated_field = CandidateProfileField(
        field_id="profile-unrelated",
        category="domain",
        statement="Worked in an unrelated domain.",
        resume_evidence_ids=("block-2",),
        evidence_quotes=("unrelated domain",),
        evidence_kind="direct",
        evidence_support_score=100,
        score_reason="Explicit domain.",
    )
    request = RoleEvidenceAssessmentRequest(
        criteria=request.criteria,
        resume_blocks=request.resume_blocks,
        role_sources=request.role_sources,
        candidate_profile_fields=(*request.candidate_profile_fields, unrelated_field),
    )
    regional = _judgment(candidate_profile_field_ids=["profile-monthly-forecast"])
    stable = _stable_judgment()
    corrected = _judgment(candidate_profile_field_ids=["profile-monthly-forecast", "profile-regional-rollout"])
    model = _Model(
        [
            {"judgments": [stable, regional]},
            {"judgment": corrected},
        ]
    )

    run = LangChainRoleEvidenceAssessor(model).assess(request)

    correction_message = model.requests[1][1].content
    assert '"orphaned_evidence_valid_field_ids":{"block-1":["profile-regional-rollout"]}' in correction_message
    assert "Led the rollout for Singapore." in correction_message
    assert "Worked in an unrelated domain." not in correction_message
    assert '"source_locator":"experience[0].bullets[1]"' not in correction_message
    assert run.judgments[1].candidate_profile_field_ids == tuple(corrected["candidate_profile_field_ids"])


def test_assessor_correction_names_unsupported_numbers_for_a_computed_value():
    """A narrative stating a computed gap (e.g. "2 years short") derived from
    real grounded numbers still fails numeric_claim, since the computed value
    itself never appears verbatim -- the correction must name exactly which
    numbers to drop rather than a vague "remove or replace"."""
    failed = _judgment(score_reason="The candidate is 2 years short of the requirement.")
    corrected = _judgment(score_reason="The candidate falls short of the requirement.")
    model = _Model([{"judgments": [failed]}, {"judgment": corrected}])

    run = LangChainRoleEvidenceAssessor(model).assess(_request())

    correction_message = model.requests[1][1].content
    assert '"unsupported_numbers":["2"]' in correction_message
    assert "Describe that comparison in words instead" in correction_message
    assert run.judgments[0].score_reason == corrected["score_reason"]


def test_assessor_prompt_requires_unquoted_narrative_paraphrase():
    from recruitment_team.prompts.role_evidence_assessor import (
        ROLE_EVIDENCE_ASSESSOR_SYSTEM_PROMPT,
    )

    assert "must use unquoted paraphrase" in ROLE_EVIDENCE_ASSESSOR_SYSTEM_PROMPT
    assert "do not use quotation marks" in ROLE_EVIDENCE_ASSESSOR_SYSTEM_PROMPT


def test_assessor_accepts_escaped_ampersand_in_a_literal_quote():
    source_id = "target_job:7"
    criterion = RoleCriterion(
        criterion_id="regional_rollout",
        category="scope_seniority",
        requirement_level="required",
        statement="Lead a rollout across 5 markets.",
        source_ids=(source_id,),
        source_citations=(
            RoleCitation(
                source_id=source_id,
                source_path="description",
                relevant_excerpt="Lead a rollout across 5 markets.",
            ),
        ),
    )
    block = ResumeEvidenceRecord(
        evidence_id="block-1",
        kind="bullet",
        text="Led the rollout for Singapore & Malaysia, preventing USD 2M in losses.",
        source_locator="experience[0].bullets[0]",
        section_key="experience",
    )
    source = RoleSource(
        source_id=source_id,
        source_type="target_job",
        title="Regional Operations Lead",
        url="https://example.test/jobs/7",
        publication_date="2026-07-01",
        evidence_strength="primary",
        evidence_fields=("description",),
    )
    profile_field = CandidateProfileField(
        field_id="profile-regional-rollout",
        category="demonstrated_capability",
        statement="Led the rollout for Singapore & Malaysia.",
        resume_evidence_ids=(block.evidence_id,),
        evidence_quotes=("Led the rollout for Singapore & Malaysia",),
        evidence_kind="direct",
        evidence_support_score=100,
        score_reason="Explicit action.",
    )
    request = RoleEvidenceAssessmentRequest((criterion,), (block,), (source,), (profile_field,))
    payload = {
        "judgments": [
            _judgment(
                supported_strength='The block says "Led the rollout for Singapore &amp; Malaysia".',
            )
        ]
    }

    run = LangChainRoleEvidenceAssessor(_Model([payload])).assess(request)

    assert run.judgments[0].supported_strength.endswith('&amp; Malaysia".')


def test_tool_payload_reports_output_truncated_on_finish_reason_length():
    from recruitment_team.role_evidence_assessor import _tool_payload

    response = AIMessage(content="", tool_calls=[], response_metadata={"finish_reason": "length"})

    payload, failure = _tool_payload(response)

    assert payload is None
    assert failure == "output_truncated:length"


def test_assessor_accepts_literal_quotes_and_numbers_from_cited_evidence_or_criterion():
    payload = {
        "judgments": [
            _judgment(
                supported_strength='The block says "preventing USD 2M in potential losses".',
                remaining_gap='The role requires "5 markets"; only Singapore is shown.',
                score_reason="USD 2M is grounded in the cited block, while 5 is grounded in the role.",
            )
        ]
    }

    run = LangChainRoleEvidenceAssessor(_Model([payload])).assess(_request())

    assert run.judgments[0].supported_strength.endswith('potential losses".')


def test_deep_profile_replaces_draft_with_independent_assessment_and_metadata():
    from resume_document import create_resume_document

    from recruitment_team.assessed_role_success import EvidenceAssessedRoleSuccessProfiler
    from recruitment_team.candidate_profile import (
        CandidateEvidenceProfile,
        CandidateProfileEvidence,
    )
    from recruitment_team.discovery import JobSnapshot, JobSource

    request = _request()
    generated = RoleProfileRun(
        profile=RoleSuccessProfile(
            profile_version="definition-v1",
            target_job_id=7,
            sources=request.role_sources,
            criteria=request.criteria,
            candidate_evidence=request.proposed_evidence,
            source_coverage=SourceCoverage(True, 0, 0, "unmatched", ()),
            clarification_question=None,
        ),
        model_name="definition-model",
        attempt_count=1,
        input_tokens=100,
        output_tokens=20,
        generator_attempt_count=1,
        generator_model_name="definition-model",
    )
    resume_text = "EXPERIENCE\n- Led the rollout for Singapore, preventing USD 2M in potential losses."
    canonical_id = create_resume_document(resume_text)["blocks"][-1]["id"]
    candidate_profile = CandidateEvidenceProfile(
        profile_version="candidate-evidence-profile-v3",
        resume_document_id="resume-document",
        resume_revision="resume-revision",
        fields=(
            CandidateProfileField(
                field_id="profile-regional-rollout",
                category="demonstrated_capability",
                statement="Led the rollout for Singapore.",
                resume_evidence_ids=(canonical_id,),
                evidence_quotes=("Led the rollout for Singapore",),
                evidence_kind="direct",
                evidence_support_score=100,
                score_reason="Explicit action.",
            ),
        ),
        cited_resume_evidence=(
            CandidateProfileEvidence(
                evidence_id=canonical_id,
                kind="bullet",
                text=resume_text.splitlines()[-1],
                source_locator="experience[0].bullets[0]",
                section_key="experience",
            ),
        ),
    )
    assessed = RoleEvidenceAssessmentRun(
        judgments=(
            RoleEvidenceJudgment(
                criterion_id="regional_rollout",
                alignment="partial",
                resume_evidence_ids=(canonical_id,),
                candidate_profile_field_ids=("profile-regional-rollout",),
                supported_strength="Led the Singapore rollout.",
                remaining_gap="Leadership across 5 markets is not shown.",
                evidence_support_score=55,
                score_reason="One-market leadership is explicit.",
            ),
        ),
        prompt_version="assessor-v1",
        model_name="assessor-model",
        attempt_count=1,
        input_tokens=80,
        output_tokens=10,
    )
    target = JobSnapshot(
        job_id=7,
        title="Regional Operations Lead",
        company="Example",
        location="Singapore",
        salary="",
        employment_type="Full Time",
        seniority="Senior",
        description="Lead a rollout across 5 markets.",
        skills=(),
        similarity_score=None,
        source=JobSource("fixture", "https://example.test/jobs/7", "7", "", "", "", "open", "hash"),
    )
    profiler = EvidenceAssessedRoleSuccessProfiler(
        ScriptedRoleDefinitionGenerator([generated]),
        ScriptedRoleEvidenceAssessor([assessed]),
    )

    run = profiler.profile(
        candidate_profile,
        target,
        (),
    )

    match = run.profile.candidate_evidence[0]
    assert match.alignment == "partial"
    assert match.supported_strength == "Led the Singapore rollout."
    assert match.remaining_gap == "Leadership across 5 markets is not shown."
    assert match.evidence_support_score == 55
    assert run.profile.assessment_disposition == "pass"
    assert run.profile.evidence_assessment_model == "assessor-model"
    assert run.profile.cited_resume_evidence[0].evidence_id == canonical_id
    assert run.attempt_count == 2
    assert run.input_tokens == 180
