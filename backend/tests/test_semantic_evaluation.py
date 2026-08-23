from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from evals.semantic_label_gate import (
    SemanticLabelGateError,
    validate_labelled_corpus,
)
from semantic_corpus import load_corpus


REPO_ROOT = Path(__file__).resolve().parents[2]
SYNTHETIC_ROOT = REPO_ROOT / "backend/evals/corpora/synthetic-v1"


def test_checked_in_corpus_has_nonzero_labelled_regression_coverage():
    corpus = load_corpus(SYNTHETIC_ROOT / "manifest.json", SYNTHETIC_ROOT)

    report = validate_labelled_corpus(
        corpus,
        minimum_labelled_cases=1,
        minimum_labels=2,
    )

    assert report == {
        "dataset_version": "synthetic-v1",
        "case_count": 1,
        "labelled_case_count": 1,
        "label_count": 2,
        "label_versions": ["v1"],
        "coverage_gate": "pass",
    }


def test_label_gate_fails_closed_for_zero_labels(tmp_path: Path):
    corpus = _corpus(tmp_path, {"label_version": "v1", "expected_fields": []})

    with pytest.raises(SemanticLabelGateError, match="labelled case count 0"):
        validate_labelled_corpus(corpus)


def test_label_gate_rejects_incomplete_label_contract(tmp_path: Path):
    corpus = _corpus(tmp_path, {
        "label_version": "v1",
        "expected_fields": [{"field_path": "evidence.role", "expected": "direct"}],
    })

    with pytest.raises(SemanticLabelGateError, match="boolean required"):
        validate_labelled_corpus(corpus)


def _corpus(root: Path, labels: dict):
    artifacts = {
        "resume": ("resume.txt", "Synthetic resume"),
        "target_job": ("target-job.json", json.dumps({"title": "Engineer"})),
        "labels": ("labels.json", json.dumps(labels)),
    }
    case: dict[str, Any] = {"case_id": "case-1", "role_family": "engineering"}
    for name, (filename, content) in artifacts.items():
        (root / filename).write_text(content, encoding="utf-8")
        case[name] = {
            "ref": filename,
            "sha256": hashlib.sha256(content.encode()).hexdigest(),
        }
    manifest = root / "manifest.json"
    manifest.write_text(json.dumps({
        "dataset_version": "test-v1",
        "cases": [case],
    }), encoding="utf-8")
    return load_corpus(manifest, root)
