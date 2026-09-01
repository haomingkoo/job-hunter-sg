from __future__ import annotations

import json
from dataclasses import asdict

import pytest

from resume_document import create_resume_document
from recruitment_team.candidate_profile import (
    CandidateEvidenceProfile,
    CANDIDATE_PROFILE_RECEIPT_VERSION,
    CandidateProfileField,
    CandidateProfileRun,
    CandidateProfileValidationError,
    DETERMINISTIC_PROFILE_IMPLEMENTATION,
)


def _factory(profiler_type):
    class Factory:
        def create(self, checkpoint_store):
            return profiler_type(checkpoint_store=checkpoint_store)

    return Factory


def _parsed_resume():
    document = create_resume_document(
        "EXPERIENCE\n- Reduced close from 8 days to 5 days.",
        source_format="pdf",
        filename="resume.pdf",
    )
    return {
        "text": document["raw_text"],
        "document": document,
        "filename": "resume.pdf",
        "file_type": "pdf",
        "word_count": 10,
        "line_count": 2,
        "page_estimate": 1,
        "parse_quality": {"quality": "good"},
        "content_warnings": [],
    }


def test_candidate_profile_canary_writes_complete_profile_and_compact_summary(
    monkeypatch,
    tmp_path,
    capsys,
):
    from resume_document import SCHEMA_VERSION
    from scripts import validate_candidate_profile_local as script

    parsed = _parsed_resume()
    long_statement = "Resume-sourced detail " + "x" * 20_000
    block = parsed["document"]["blocks"][-1]

    class FakeProfiler:
        def __init__(self, *, checkpoint_store):
            assert checkpoint_store.path is None

        def profile(self, document):
            assert document["raw_text"] == parsed["text"]
            return CandidateProfileRun(
                profile=CandidateEvidenceProfile(
                    profile_version="candidate-evidence-profile-v3",
                    resume_document_id=document["document_id"],
                    resume_revision=document["revision"],
                    fields=(
                        CandidateProfileField(
                            field_id="outcome_close_cycle",
                            category="outcome",
                            statement=long_statement,
                            resume_evidence_ids=(block["id"],),
                            evidence_quotes=(block["text"],),
                            evidence_kind="direct",
                            evidence_support_score=100,
                            score_reason="Directly stated.",
                        ),
                    ),
                    cited_resume_evidence=(),
                ),
                model_name="canary-test-model",
                attempt_count=1,
                input_tokens=13,
                output_tokens=5,
            )

    monkeypatch.setattr(script, "parse_resume_isolated", lambda *_args: parsed)
    monkeypatch.setattr(script, "DeterministicCandidateProfilerFactory", _factory(FakeProfiler))
    resume_path = tmp_path / "resume.pdf"
    output_path = tmp_path / "report.json"
    resume_path.write_bytes(b"%PDF-test")

    result = script.main(
        [
            "--resume-pdf",
            str(resume_path),
            "--output",
            str(output_path),
        ]
    )

    report = json.loads(output_path.read_text())
    summary = capsys.readouterr().out.strip()
    assert result == 0
    assert report["profile"]["fields"][0]["statement"] == long_statement
    assert report["execution_policy"] == {
        "prompt_version": "candidate-evidence-profile-v4",
        "implementation": "deterministic_exact_extract_v1",
        "field_cap": 48,
        "decomposition_version": "extractive-whole-document-v6",
        "resume_document_schema_version": SCHEMA_VERSION,
        "checkpoint_enabled": False,
    }
    assert json.loads(summary) == {
        "status": "completed",
        "output": str(output_path),
        "fields": 1,
        "model_calls": 0,
    }
    assert long_statement not in summary


def test_candidate_profile_canary_preserves_complete_validation_error(
    monkeypatch,
    tmp_path,
    capsys,
):
    from scripts import validate_candidate_profile_local as script

    parsed = _parsed_resume()
    rejected = {"content": "rejected " + "y" * 20_000, "tool_calls": []}

    class FailingProfiler:
        def __init__(self, *, checkpoint_store):
            pass

        def profile(self, _document):
            raise CandidateProfileValidationError(
                "tool_call:required_exactly_one",
                rejected,
                attempt_count=2,
                model_name="canary-test-model",
                input_tokens=26,
                output_tokens=10,
                validation_codes=("schema_validation", "tool_call:required_exactly_one"),
            )

    monkeypatch.setattr(script, "parse_resume_isolated", lambda *_args: parsed)
    monkeypatch.setattr(script, "DeterministicCandidateProfilerFactory", _factory(FailingProfiler))
    resume_path = tmp_path / "resume.pdf"
    output_path = tmp_path / "failure.json"
    resume_path.write_bytes(b"%PDF-test")

    result = script.main(
        [
            "--resume-pdf",
            str(resume_path),
            "--output",
            str(output_path),
        ]
    )

    report = json.loads(output_path.read_text())
    summary = capsys.readouterr().out.strip()
    assert result == 1
    assert report["error"]["rejected_submission"] == rejected
    assert report["error"]["validation_codes"] == [
        "schema_validation",
        "tool_call:required_exactly_one",
    ]
    assert rejected["content"] not in summary


def test_json_checkpoint_store_fails_on_identity_mismatch(tmp_path):
    from scripts.validate_candidate_profile_local import JsonCandidateProfileCheckpointStore

    execution_policy = {"prompt_version": "test-v1", "transport_retries": 0}
    store = JsonCandidateProfileCheckpointStore(tmp_path / "checkpoint.json", execution_policy)
    payload = {"fields": []}
    store.save("identity-a", "summary_01", payload)

    assert store.load("identity-a") == {"summary_01": payload}
    assert json.loads((tmp_path / "checkpoint.json").read_text())["execution_policy"] == execution_policy
    with pytest.raises(ValueError, match="identity does not match"):
        store.load("identity-b")


def test_recruitment_canary_imports_only_matching_completed_profile_report(tmp_path):
    from scripts.validate_recruitment_team_local import _candidate_profile_run_from_report
    from recruitment_team.candidate_profile import candidate_profile_execution_policy

    document = create_resume_document("EXPERIENCE\n- Built a validated workflow.")
    block = document["blocks"][-1]
    profile = CandidateEvidenceProfile(
        profile_version="candidate-evidence-profile-v3",
        resume_document_id=document["document_id"],
        resume_revision=document["revision"],
        fields=(
            CandidateProfileField(
                field_id="capability_id",
                category="demonstrated_capability",
                statement="Built a validated workflow.",
                resume_evidence_ids=(block["id"],),
                evidence_quotes=(block["text"],),
                evidence_kind="direct",
                evidence_support_score=100,
                score_reason="Directly stated.",
            ),
        ),
        cited_resume_evidence=(),
    )
    report_path = tmp_path / "profile.json"
    report_path.write_text(
        json.dumps(
            {
                "status": "completed",
                "execution_policy": {
                    **candidate_profile_execution_policy(),
                    "checkpoint_enabled": True,
                },
                "run": {
                    "model_name": "model-a",
                    "checkpoint_id": "checkpoint-a",
                    "scope_count": 1,
                },
                "profile": asdict(profile),
                "evaluation": {
                    "receipt_version": CANDIDATE_PROFILE_RECEIPT_VERSION,
                    "implementation": DETERMINISTIC_PROFILE_IMPLEMENTATION,
                    "field_count": 1,
                    "result": "pass",
                    "evidence_disposition": {
                        "policy": DETERMINISTIC_PROFILE_IMPLEMENTATION,
                        "action": "publish_exact_profile",
                        "supported_field_ids": ["capability_id"],
                        "rejected_field_ids": [],
                    },
                },
            }
        )
    )

    imported = _candidate_profile_run_from_report(str(report_path), document)

    assert imported.profile == profile
    assert imported.model_name == "model-a"
    assert imported.checkpoint_id == "checkpoint-a"
    assert imported.evaluation["result"] == "pass"

    with pytest.raises(ValueError, match="does not belong"):
        _candidate_profile_run_from_report(
            str(report_path),
            create_resume_document("EXPERIENCE\n- Different resume."),
        )
