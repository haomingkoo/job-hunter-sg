from __future__ import annotations

from dataclasses import asdict, replace

import pytest
from langchain_core.messages import AIMessage

from resume_document import create_resume_document
from recruitment_team.candidate_profile import (
    CandidateEvidenceProfile,
    CandidateProfileEvidence,
    CandidateProfileField,
    CandidateProfileRun,
    CandidateProfileValidationError,
    _build_profile,
)
from recruitment_team.candidate_profile_review import (
    GloballyReviewedCandidateProfiler,
    _SemanticMergeSubmission,
    _apply_evidence_disposition,
    _evaluation_input,
    _global_review_input,
    _semantic_merge_input,
    _validate_evaluation,
    _validate_global_merge,
)
from recruitment_team.execution_metrics import merge_execution_event
from recruitment_team.prompts import CANDIDATE_PROFILE_REVIEW_VERSION
from recruitment_team.telemetry import RecordedTelemetry


def _document():
    return create_resume_document(
        "SUMMARY\nReduced close from 8 days to 5 days.\n"
        "EXPERIENCE\nOperations Analyst | 2020 - 2024\n"
        "- Reduced close from 8 days to 5 days while preserving audit controls."
    )


def _local_run(document):
    summary = next(
        block for block in document["blocks"] if block["section_key"] == "summary" and "Reduced" in block["text"]
    )
    experience = next(block for block in document["blocks"] if block["kind"] == "bullet")
    fields = (
        CandidateProfileField(
            field_id="summary_result",
            category="outcome",
            statement="Reduced close from 8 days to 5 days.",
            resume_evidence_ids=(summary["id"],),
            evidence_quotes=(summary["text"],),
            evidence_kind="direct",
            evidence_support_score=100,
            score_reason="The summary states the realized result.",
        ),
        CandidateProfileField(
            field_id="experience_result",
            category="outcome",
            statement="Reduced close from 8 days to 5 days, preserving audit controls.",
            resume_evidence_ids=(experience["id"],),
            evidence_quotes=(experience["text"],),
            evidence_kind="direct",
            evidence_support_score=100,
            score_reason="The experience bullet states the realized result and qualifier.",
        ),
    )
    evidence = tuple(
        CandidateProfileEvidence(
            evidence_id=block["id"],
            kind=block["kind"],
            text=block["text"],
            source_locator=str((block.get("source") or {}).get("locator") or ""),
            section_key=block["section_key"],
        )
        for block in (summary, experience)
    )
    return CandidateProfileRun(
        profile=CandidateEvidenceProfile(
            profile_version="candidate-evidence-profile-v3",
            resume_document_id=document["document_id"],
            resume_revision=document["revision"],
            fields=fields,
            cited_resume_evidence=evidence,
        ),
        model_name="extractor-model",
        attempt_count=2,
        scope_count=2,
        model_call_count=2,
        checkpoint_id="a" * 64,
    )


def _merged_payload(run):
    first, second = run.profile.fields
    return {
        "decisions": [
            {
                "source_field_numbers": [1, 2],
                "category": "outcome",
                "statement": second.statement,
                "evidence_kind": "direct",
                "evidence_support_score": 100,
                "score_reason": "Both cited blocks directly state the same realized result.",
            }
        ]
    }


def _evaluation_payload(_field_id, _evidence):
    return {
        "supported_field_refs": ["field_1"],
        "field_evaluations": [],
        "strengths": ["Repeated evidence is represented once with complete provenance."],
        "weaknesses": [],
        "score": 100,
        "score_reason": "The profile is concise, supported, and role-neutral.",
        "result": "pass",
    }


class _Extractor:
    def __init__(self, run):
        self.run = run

    def profile(self, _document):
        return self.run


class _Model:
    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.calls = []
        self.tool_name = ""

    def bind_tools(self, tools, **kwargs):
        self.tool_name = tools[0].name
        assert kwargs["tool_choice"] == self.tool_name
        return self

    def invoke(self, messages):
        self.calls.append((self.tool_name, messages))
        output = next(self.outputs)
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": self.tool_name,
                    "args": output,
                    "id": f"review-{len(self.calls)}",
                    "type": "tool_call",
                }
            ],
            response_metadata={"model_name": "review-model"},
            usage_metadata={"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
        )


class _Store:
    def __init__(self):
        self.saved = {}
        self.feedback = {}
        self.metrics = {}

    def load(self, _checkpoint_id):
        return dict(self.saved)

    def save(self, _checkpoint_id, scope_id, payload):
        self.saved[scope_id] = payload

    def load_retry_feedback(self, _checkpoint_id, scope_id):
        return self.feedback.get(scope_id)

    def save_retry_feedback(self, _checkpoint_id, scope_id, feedback):
        self.feedback[scope_id] = feedback

    def clear_retry_feedback(self, _checkpoint_id, scope_id):
        self.feedback.pop(scope_id, None)

    def record_execution_event(self, checkpoint_id, event):
        self.metrics = merge_execution_event(
            self.metrics,
            {**event, "logical_run_id": checkpoint_id},
        )

    def execution_metrics(self, _checkpoint_id):
        return dict(self.metrics)


def test_global_merge_and_one_independent_evaluation_reduce_repetition_with_provenance():
    document = _document()
    local = _local_run(document)
    merged = _merged_payload(local)
    blocks = {block["id"]: block for block in document["blocks"]}
    accepted, failure = _validate_global_merge(merged, local.profile, blocks)
    assert failure == ""
    reviewed = _build_profile(document, accepted["fields"])
    semantic_submission = {"reviewed_field_numbers": [1, 2], **merged}
    model = _Model(
        [
            semantic_submission,
            {"decisions": []},
            _evaluation_payload(
                reviewed.fields[0].field_id,
                reviewed.cited_resume_evidence,
            ),
        ]
    )
    store = _Store()
    telemetry = RecordedTelemetry()
    progress = []

    result = GloballyReviewedCandidateProfiler(
        _Extractor(local),
        model,
        checkpoint_store=store,
        telemetry=telemetry,
        progress_publisher=progress.append,
    ).profile(document)

    assert len(result.profile.fields) == 1
    assert set(result.profile.fields[0].resume_evidence_ids) == {
        item.evidence_id for item in local.profile.cited_resume_evidence
    }
    assert result.evaluation["result"] == "pass"
    assert result.evaluation["field_evaluations"][0]["field_id"] == result.profile.fields[0].field_id
    assert [name for name, _messages in model.calls] == [
        "submit_globally_merged_candidate_profile",
        "submit_globally_merged_candidate_profile",
        "submit_candidate_profile_evaluation",
    ]
    assert result.model_call_count == 3
    assert all(attempt.get("attempt_id") for attempt in store.metrics["attempts"])
    assert len({attempt["attempt_id"] for attempt in store.metrics["attempts"]}) == 3
    assert result.scope_count == 5
    model_spans = [span for span in telemetry.spans if span.name == "candidate_profile_review.model_attempt"]
    validation_spans = [span for span in telemetry.spans if span.name == "candidate_profile_review.validation"]
    assert len(model_spans) == 3
    assert len(validation_spans) == 3
    assert all(span.attributes["review_version"] == CANDIDATE_PROFILE_REVIEW_VERSION for span in model_spans)
    assert all(span.attributes["accepted"] is True for span in validation_spans)
    assert "Reduced close" not in repr([span.attributes for span in telemetry.spans])
    assert [
        (
            item.transition,
            item.scope_id,
            item.scope_count,
            item.completed_scope_count,
        )
        for item in progress
    ] == [
        ("start", "__global_semantic_merge__", 5, 2),
        ("checkpoint", "__global_semantic_merge__", 5, 2),
        ("completion", "__global_semantic_merge__", 5, 3),
        ("start", "__global_correction__", 5, 3),
        ("checkpoint", "__global_correction__", 5, 3),
        ("completion", "__global_correction__", 5, 4),
        ("start", "__independent_evaluation__", 5, 4),
        ("checkpoint", "__independent_evaluation__", 5, 4),
        ("completion", "__independent_evaluation__", 5, 5),
    ]


def test_global_validator_reports_reused_field_numbers():
    document = _document()
    run = _local_run(document)
    blocks = {block["id"]: block for block in document["blocks"]}
    payload = _merged_payload(run)
    payload["decisions"].append(
        {
            **payload["decisions"][0],
            "source_field_numbers": [2],
        }
    )
    payload["decisions"].append(
        {
            **payload["decisions"][0],
            "source_field_numbers": [1],
        }
    )

    accepted, failure = _validate_global_merge(payload, run.profile, blocks)

    assert accepted is None
    assert failure == "global_merge:source_field_reused(numbers=1,2)"


def test_semantic_merge_preserves_ambiguous_overlaps_without_discarding_review():
    document = _document()
    run = _local_run(document)
    blocks = {block["id"]: block for block in document["blocks"]}
    payload = _merged_payload(run)
    payload["decisions"].append({**payload["decisions"][0], "source_field_numbers": [1, 2]})

    accepted, warning = _validate_global_merge(
        payload,
        run.profile,
        blocks,
        merge_only=True,
    )

    assert accepted is not None
    assert len(accepted["fields"]) == 2
    assert warning == "global_merge:ambiguous_overlaps_preserved(numbers=1,2)"


def test_global_validator_reports_the_valid_field_number_range():
    document = _document()
    run = _local_run(document)
    blocks = {block["id"]: block for block in document["blocks"]}
    payload = _merged_payload(run)
    payload["decisions"][0]["source_field_numbers"] = [99]

    accepted, failure = _validate_global_merge(payload, run.profile, blocks)

    assert accepted is None
    assert failure == ("global_merge:unknown_source_field(valid=1..2;out_of_range=99)")


def test_global_review_input_sends_every_field_without_repeating_evidence_text():
    document = _document()
    local = _local_run(document)
    blocks = {block["id"]: block for block in document["blocks"]}

    payload, required_correction_refs = _global_review_input(
        local.profile,
        blocks,
    )

    assert [field["field_number"] for field in payload["fields"]] == [1, 2]
    assert [field["source_sections"] for field in payload["fields"]] == [
        ["summary"],
        ["experience"],
    ]
    assert all("evidence_quotes" not in field for field in payload["fields"])
    assert payload["co_citation_groups"] == []
    assert payload["exact_statement_groups"] == []
    assert payload["correction_evidence"] == {}
    assert required_correction_refs == set()


def test_global_review_highlights_structural_repetition_without_filtering_fields():
    document = _document()
    local = _local_run(document)
    first = local.profile.fields[0]
    profile = replace(
        local.profile,
        fields=(first, replace(first, field_id="repeated_summary_result")),
    )
    blocks = {block["id"]: block for block in document["blocks"]}

    payload, required_correction_refs = _global_review_input(profile, blocks)

    assert [field["field_number"] for field in payload["fields"]] == [1, 2]
    assert payload["co_citation_groups"] == [[1, 2]]
    assert payload["exact_statement_groups"] == [[1, 2]]
    assert required_correction_refs == set()

    merge_input, required_merge_groups = _semantic_merge_input(profile, blocks)
    assert merge_input["exact_statement_groups"] == [[1, 2]]
    assert merge_input["required_exact_groups"] == [[1, 2]]
    assert required_merge_groups == ((1, 2),)


def test_exact_wording_with_different_provenance_is_not_a_forced_merge():
    document = _document()
    local = _local_run(document)
    first, second = local.profile.fields
    profile = replace(
        local.profile,
        fields=(first, replace(second, statement=first.statement)),
    )
    blocks = {block["id"]: block for block in document["blocks"]}

    merge_input, required_merge_groups = _semantic_merge_input(profile, blocks)

    assert merge_input["exact_statement_groups"] == [[1, 2]]
    assert merge_input["required_exact_groups"] == []
    assert required_merge_groups == ()


def test_semantic_merge_requires_exact_statement_groups():
    document = _document()
    local = _local_run(document)
    first = local.profile.fields[0]
    profile = replace(
        local.profile,
        fields=(first, replace(first, field_id="repeated_summary_result")),
    )
    blocks = {block["id"]: block for block in document["blocks"]}

    accepted, failure = _validate_global_merge(
        {"decisions": []},
        profile,
        blocks,
        required_merge_groups=((1, 2),),
        merge_only=True,
    )

    assert accepted is None
    assert failure == "global_merge:missing_exact_groups(1,2)"


def test_global_merge_rejects_temporary_field_reference_in_persisted_reason():
    document = _document()
    local = _local_run(document)
    payload = _merged_payload(local)
    payload["decisions"][0]["score_reason"] = "Merged field 2 into field 1 because their statements overlap."
    blocks = {block["id"]: block for block in document["blocks"]}

    accepted, failure = _validate_global_merge(payload, local.profile, blocks)

    assert accepted is None
    assert failure == "global_merge:temporary_field_reference_in_score_reason"


def test_semantic_merge_schema_requires_at_least_two_source_fields():
    decision_schema = _SemanticMergeSubmission.model_json_schema()["$defs"]["_SemanticMergeDecision"]

    assert decision_schema["properties"]["source_field_numbers"]["minItems"] == 2


def test_semantic_merge_requires_a_complete_review_receipt():
    document = _document()
    local = _local_run(document)
    payload = {"reviewed_field_numbers": [1], **_merged_payload(local)}
    blocks = {block["id"]: block for block in document["blocks"]}

    accepted, failure = _validate_global_merge(
        payload,
        local.profile,
        blocks,
        merge_only=True,
        require_complete_review=True,
    )

    assert accepted is None
    assert failure == "global_merge:review_coverage_mismatch(missing=2;unexpected=none)"


def test_review_checkpoints_make_replay_zero_call():
    document = _document()
    local = _local_run(document)
    merged = _merged_payload(local)
    blocks = {block["id"]: block for block in document["blocks"]}
    accepted, failure = _validate_global_merge(merged, local.profile, blocks)
    assert failure == ""
    reviewed = _build_profile(document, accepted["fields"])
    _evaluation_data, field_refs = _evaluation_input(reviewed)
    accepted_evaluation, failure = _validate_evaluation(
        _evaluation_payload(
            reviewed.fields[0].field_id,
            reviewed.cited_resume_evidence,
        ),
        field_refs,
    )
    assert failure == ""
    store = _Store()
    store.saved = {
        "__global_semantic_merge__": accepted,
        "__global_correction__": accepted,
        "__independent_evaluation__": accepted_evaluation,
    }
    model = _Model([])

    result = GloballyReviewedCandidateProfiler(
        _Extractor(local),
        model,
        checkpoint_store=store,
    ).profile(document)
    replayed = GloballyReviewedCandidateProfiler(
        _Extractor(local),
        model,
        checkpoint_store=store,
    ).profile(document)

    assert model.calls == []
    assert result.checkpoint_hit_count == 3
    assert replayed.checkpoint_hit_count == 6
    assert result.evaluation["result"] == "pass"


def test_evaluation_expands_explicit_supported_refs_to_complete_field_rows():
    document = _document()
    profile = _local_run(document).profile
    _payload, field_refs = _evaluation_input(profile)
    raw = {
        "supported_field_refs": list(field_refs),
        "field_evaluations": [],
        "strengths": ["Every field has exact citation support."],
        "weaknesses": [],
        "score": 100,
        "score_reason": "The independent review marked every field fully supported.",
        "result": "pass",
    }

    accepted, failure = _validate_evaluation(raw, field_refs)

    assert failure == ""
    assert [row["field_id"] for row in accepted["field_evaluations"]] == [field.field_id for field in profile.fields]
    assert all(row["label"] == "supported" for row in accepted["field_evaluations"])


def test_evaluation_result_must_match_categorical_field_disposition():
    profile = _local_run(_document()).profile
    _payload, field_refs = _evaluation_input(profile)
    raw = {
        "supported_field_refs": ["field_1"],
        "field_evaluations": [
            {
                "field_ref": "field_2",
                "strengths": ["The field preserves part of the source."],
                "weaknesses": ["The statement overstates the source."],
                "score": 99,
                "score_reason": "The categorical label, not this score, controls disposition.",
                "label": "partially_supported",
                "cited_evidence_ids": list(profile.fields[1].resume_evidence_ids),
            }
        ],
        "strengths": ["One field is fully supported."],
        "weaknesses": ["One field requires revision."],
        "score": 99,
        "score_reason": "Aggregate scores do not override field labels.",
        "result": "pass",
    }

    accepted, failure = _validate_evaluation(raw, field_refs)

    assert accepted is None
    assert failure == "evaluation:result_disposition_mismatch(expected=revise;observed=pass)"


def test_detailed_supported_label_cannot_bypass_supported_field_refs_contract():
    profile = _local_run(_document()).profile
    _payload, field_refs = _evaluation_input(profile)
    raw = {
        "supported_field_refs": ["field_2"],
        "field_evaluations": [
            {
                "field_ref": "field_1",
                "strengths": ["Some wording is grounded."],
                "weaknesses": ["The diagnostic still identifies a material weakness."],
                "score": 100,
                "score_reason": "A numeric score cannot grant supported disposition.",
                "label": "supported",
                "cited_evidence_ids": list(profile.fields[0].resume_evidence_ids),
            }
        ],
        "strengths": ["One field is contractually supported."],
        "weaknesses": ["One field used the wrong disposition bucket."],
        "score": 100,
        "score_reason": "Only supported_field_refs admits a field.",
        "result": "pass",
    }

    accepted, failure = _validate_evaluation(raw, field_refs)

    assert accepted is None
    assert failure == (
        "evaluation:summary_result:supported_requires_supported_field_ref"
    )


def test_revise_retains_only_supported_fields_and_keeps_rejected_diagnostics():
    profile = _local_run(_document()).profile
    evaluation = {
        "result": "revise",
        "field_evaluations": [
            {
                "field_id": profile.fields[0].field_id,
                "label": "supported",
                "disposition_source": "supported_field_refs",
            },
            {
                "field_id": profile.fields[1].field_id,
                "label": "partially_supported",
                "disposition_source": "field_evaluation",
                "weaknesses": ["The qualifier needs revision."],
            },
        ],
    }

    retained, diagnostic = _apply_evidence_disposition(profile, evaluation)

    assert [field.field_id for field in retained.fields] == [profile.fields[0].field_id]
    assert {item.evidence_id for item in retained.cited_resume_evidence} == set(
        profile.fields[0].resume_evidence_ids
    )
    assert diagnostic["field_evaluations"] == evaluation["field_evaluations"]
    assert diagnostic["evidence_disposition"] == {
        "policy": "fully_supported_fields_only",
        "action": "publish_supported_subset",
        "supported_field_ids": [profile.fields[0].field_id],
        "rejected_field_ids": [profile.fields[1].field_id],
    }


def test_block_with_no_supported_fields_fails_closed_and_preserves_evaluation_scope():
    document = _document()
    local = _local_run(document)
    merged = _merged_payload(local)
    blocks = {block["id"]: block for block in document["blocks"]}
    accepted, failure = _validate_global_merge(merged, local.profile, blocks)
    assert failure == ""
    reviewed = _build_profile(document, accepted["fields"])
    blocked_evaluation = _evaluation_payload(
        reviewed.fields[0].field_id,
        reviewed.cited_resume_evidence,
    )
    blocked_evaluation["supported_field_refs"] = []
    blocked_evaluation["field_evaluations"] = [
        {
            "field_ref": "field_1",
            "strengths": ["The canonical statement is concise."],
            "weaknesses": ["The canonical statement is not fully supported."],
            "score": 100,
            "score_reason": "The unsupported label controls despite the score.",
            "label": "unsupported",
            "cited_evidence_ids": [
                item.evidence_id for item in reviewed.cited_resume_evidence
            ],
        }
    ]
    blocked_evaluation["result"] = "block"
    model = _Model(
        [
            {"reviewed_field_numbers": [1, 2], **merged},
            {"decisions": []},
            blocked_evaluation,
        ]
    )
    store = _Store()

    with pytest.raises(CandidateProfileValidationError) as error:
        GloballyReviewedCandidateProfiler(
            _Extractor(local),
            model,
            checkpoint_store=store,
        ).profile(document)

    assert error.value.validation_code == "evaluation:no_supported_fields"
    assert error.value.rejected_submission["result"] == "block"
    assert error.value.rejected_submission["evidence_disposition"]["action"] == (
        "block_no_supported_evidence"
    )
    assert store.saved["__independent_evaluation__"]["result"] == "block"


def test_evaluation_rejects_a_noncanonical_field_citation():
    profile = _local_run(_document()).profile
    _payload, field_refs = _evaluation_input(profile)
    raw = {
        "supported_field_refs": ["field_2"],
        "field_evaluations": [
            {
                "field_ref": "field_1",
                "strengths": ["The statement is concise."],
                "weaknesses": ["Its citation is not canonical."],
                "score": 50,
                "score_reason": "The evidence reference is invalid.",
                "label": "partially_supported",
                "cited_evidence_ids": ["unknown_evidence"],
            }
        ],
        "strengths": ["The profile is structured."],
        "weaknesses": ["One field has invalid provenance."],
        "score": 50,
        "score_reason": "One citation cannot be resolved.",
        "result": "revise",
    }

    accepted, failure = _validate_evaluation(raw, field_refs)

    assert accepted is None
    assert failure.endswith(":noncanonical_evidence_id")


def test_evaluation_names_every_missing_field_reference():
    profile = _local_run(_document()).profile
    _payload, field_refs = _evaluation_input(profile)
    raw = {
        "supported_field_refs": ["field_1"],
        "field_evaluations": [],
        "strengths": ["One field is supported."],
        "weaknesses": ["The review omitted a field."],
        "score": 50,
        "score_reason": "Coverage is incomplete.",
        "result": "revise",
    }

    accepted, failure = _validate_evaluation(raw, field_refs)

    assert accepted is None
    assert failure == "evaluation:field_coverage_mismatch(missing=field_2;unexpected=none)"


def test_global_validator_rejects_role_identity_as_skill_and_direct_inference():
    document = create_resume_document("EXPERIENCE\nOperations Manager | 2020 - 2024")
    heading = next(block for block in document["blocks"] if block["kind"] == "entry_heading")
    profile = CandidateEvidenceProfile(
        profile_version="candidate-evidence-profile-v3",
        resume_document_id=document["document_id"],
        resume_revision=document["revision"],
        fields=(
            CandidateProfileField(
                field_id="role",
                category="chronology",
                statement=heading["text"],
                resume_evidence_ids=(heading["id"],),
                evidence_quotes=(heading["text"],),
                evidence_kind="direct",
                evidence_support_score=100,
                score_reason="The title and dates are explicit.",
            ),
        ),
        cited_resume_evidence=(),
    )
    blocks = {block["id"]: block for block in document["blocks"]}
    payload = {
        "decisions": [
            {
                "source_field_numbers": [1],
                "category": "stated_skill",
                "statement": "Operations management is likely demonstrated.",
                "score_reason": "The role title suggests this skill.",
                "evidence_kind": "direct",
                "evidence_support_score": 100,
            }
        ]
    }

    accepted, failure = _validate_global_merge(payload, profile, blocks)

    assert accepted is None
    assert "role_identity_is_not_skill" in failure
    assert "direct_evidence_admits_inference" in failure


def _single_field_validation(text, *, category):
    document = create_resume_document(f"EXPERIENCE\n{text}")
    block = next(block for block in document["blocks"] if block["text"] == text)
    field = CandidateProfileField(
        field_id="field",
        category=category,
        statement=block["text"],
        resume_evidence_ids=(block["id"],),
        evidence_quotes=(block["text"],),
        evidence_kind="direct",
        evidence_support_score=100,
        score_reason="The cited resume text states this directly.",
    )
    profile = CandidateEvidenceProfile(
        profile_version="candidate-evidence-profile-v3",
        resume_document_id=document["document_id"],
        resume_revision=document["revision"],
        fields=(field,),
        cited_resume_evidence=(),
    )
    blocks = {item["id"]: item for item in document["blocks"]}
    decision = asdict(field)
    decision.pop("field_id")
    decision.pop("resume_evidence_ids")
    decision.pop("evidence_quotes")
    decision["source_field_numbers"] = [1]
    decision["score_reason"] = "The global review confirmed the cited resume text."
    return _validate_global_merge({"decisions": [decision]}, profile, blocks)


def test_global_validator_requires_time_evidence_for_chronology():
    accepted, failure = _single_field_validation(
        "Led manufacturing operations across four regions.",
        category="chronology",
    )

    assert accepted is None
    assert failure == "field:field:chronology_without_time_evidence"


def test_global_validator_accepts_duration_as_time_evidence():
    accepted, failure = _single_field_validation(
        "Has 8 years of manufacturing transformation experience.",
        category="chronology",
    )

    assert accepted is not None
    assert failure == ""


def test_global_validator_requires_a_realized_result_for_outcomes():
    accepted, failure = _single_field_validation(
        "Responsible for operational excellence and audit controls.",
        category="outcome",
    )

    assert accepted is None
    assert failure == "field:field:outcome_without_realized_result"


def test_global_validator_preserves_realized_prevention_with_potential_qualifier():
    accepted, failure = _single_field_validation(
        "Prevented potential losses through a risk-scoring system.",
        category="outcome",
    )

    assert accepted is not None
    assert failure == ""


def test_global_validator_classifies_awards_as_credentials():
    accepted, failure = _single_field_validation(
        "Received the President's Award for manufacturing excellence.",
        category="outcome",
    )

    assert accepted is None
    assert "award_misclassified" in failure
