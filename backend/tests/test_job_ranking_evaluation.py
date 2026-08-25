from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.evaluate_job_ranking import evaluate_case, run


MANIFEST = Path(__file__).resolve().parents[1] / "evals/job-ranking-v1.json"


def test_ranking_manifest_has_valid_privacy_safe_expectations():
    manifest = json.loads(MANIFEST.read_text())

    assert manifest["dataset_version"] == "job-ranking-v1"
    assert len(manifest["cases"]) >= 3
    for case in manifest["cases"]:
        perfect = [
            candidate["id"]
            for candidate in sorted(
                case["candidates"],
                key=lambda candidate: candidate["relevance"],
                reverse=True,
            )
            if candidate["id"] not in case["forbidden_in_results"]
        ]
        assert evaluate_case(case, perfect)["passed"] is True


def test_ranking_gate_fails_a_hard_company_constraint_violation():
    case = json.loads(MANIFEST.read_text())["cases"][1]

    report = evaluate_case(case, [204, 201, 202, 203])

    assert report["passed"] is False
    assert {item["type"] for item in report["violations"]} == {"forbidden_present"}


def test_ranking_run_rejects_a_manifest_with_the_wrong_model_identity(tmp_path):
    manifest = json.loads(MANIFEST.read_text())
    manifest["model_revision"] = "not-the-runtime-revision"
    path = tmp_path / "ranking.json"
    path.write_text(json.dumps(manifest))

    with pytest.raises(ValueError) as error:
        run(path)

    assert str(error.value) == "ranking manifest model identity does not match the runtime encoder"


def test_ranking_run_reports_an_empty_eligible_set_as_a_failed_case(tmp_path):
    manifest = json.loads(MANIFEST.read_text())
    case = manifest["cases"][0]
    case["candidates"] = [{
        "id": 1,
        "title": "Recruiter",
        "company": "Asia Search Pte Ltd",
        "description": "Recruitment role.",
        "skills": [],
        "relevance": 0,
    }]
    case["required_in_top_k"] = []
    case["forbidden_in_results"] = []
    case["pairwise_preferences"] = []
    manifest["cases"] = [case]
    path = tmp_path / "ranking.json"
    path.write_text(json.dumps(manifest))

    report = run(path)

    assert report["passed"] is False
    assert report["cases"][0]["violations"] == [{"type": "no_eligible_candidates"}]
