from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.evaluate_job_ranking as ranking_evaluation
from scripts.evaluate_job_ranking import evaluate_case, run


MANIFEST = Path(__file__).resolve().parents[1] / "evals/job-ranking-v1.json"
QUALITY_GATES = Path(__file__).resolve().parents[2] / "docs/quality-gates.md"


def test_synthetic_ranking_check_is_not_described_as_an_outcome_backtest():
    documentation = QUALITY_GATES.read_text().casefold()
    module_description = (ranking_evaluation.__doc__ or "").casefold()

    assert "synthetic semantic job-ranking regression" in documentation
    assert "synthetic semantic job-ranking regression" in module_description
    assert "backtest" not in documentation
    assert "backtest" not in module_description


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
        "relevance": 1,
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


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda manifest: manifest.update(cases=[]), "ranking manifest requires at least one case"),
        (
            lambda manifest: manifest["cases"].append(dict(manifest["cases"][0])),
            "ranking manifest case IDs must be unique",
        ),
        (
            lambda manifest: manifest["cases"][0].update(
                required_in_top_k=[101],
                forbidden_in_results=[101],
            ),
            "required and forbidden candidates overlap",
        ),
        (
            lambda manifest: [candidate.update(relevance=0) for candidate in manifest["cases"][0]["candidates"]],
            "at least one candidate must be relevant",
        ),
    ],
)
def test_ranking_gate_rejects_fail_open_manifests(tmp_path, mutate, message):
    manifest = json.loads(MANIFEST.read_text())
    mutate(manifest)
    path = tmp_path / "ranking.json"
    path.write_text(json.dumps(manifest))

    with pytest.raises(ValueError) as error:
        run(path)

    assert message in str(error.value)


def test_ranking_gate_rejects_duplicate_or_unknown_output_ids():
    case = json.loads(MANIFEST.read_text())["cases"][0]

    with pytest.raises(ValueError, match="ranked job IDs must be unique"):
        evaluate_case(case, [101, 101])
    with pytest.raises(ValueError, match="ranked results contain an unknown candidate"):
        evaluate_case(case, [999])
