from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from semantic_corpus import (
    CorpusError,
    assert_privacy_safe_report,
    load_corpus,
    privacy_safe_summary,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
SYNTHETIC_ROOT = REPO_ROOT / "backend/evals/corpora/synthetic-v1"


def test_checked_in_synthetic_corpus_loads_without_leaking_inputs():
    corpus = load_corpus(SYNTHETIC_ROOT / "manifest.json", SYNTHETIC_ROOT)
    summary = privacy_safe_summary(corpus)
    resume_text = corpus.cases[0].resume.path.read_text(encoding="utf-8")

    assert corpus.dataset_version == "synthetic-v1"
    assert [(case.case_id, case.role_family) for case in corpus.cases] == [
        ("synthetic-ai-project-lead", "ai_delivery")
    ]
    assert summary["case_count"] == 1
    assert str(SYNTHETIC_ROOT) not in json.dumps(summary)
    assert_privacy_safe_report(summary, private_values=(resume_text,))


def test_loader_rejects_hash_mismatch(tmp_path: Path):
    manifest = _write_case(tmp_path)
    (tmp_path / "resume.txt").write_text("changed", encoding="utf-8")

    with pytest.raises(CorpusError, match="SHA-256 mismatch"):
        load_corpus(manifest, tmp_path)


def test_loader_rejects_paths_outside_explicit_corpus_dir(tmp_path: Path):
    manifest = _write_case(tmp_path)
    value = json.loads(manifest.read_text(encoding="utf-8"))
    value["cases"][0]["resume"]["ref"] = "../resume.txt"
    manifest.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(CorpusError, match="stay within corpus_dir"):
        load_corpus(manifest, tmp_path)


def test_privacy_guard_rejects_private_content_and_absolute_paths(tmp_path: Path):
    private_text = "Private resume content that must not leave the runner."
    with pytest.raises(CorpusError, match="private source content"):
        assert_privacy_safe_report(
            {"result": private_text},
            private_values=(private_text,),
        )
    with pytest.raises(CorpusError, match="absolute path"):
        assert_privacy_safe_report({"artifact": str(tmp_path / "resume.pdf")})


def _write_case(root: Path) -> Path:
    files = {
        "resume": ("resume.txt", "Synthetic resume"),
        "target_job": ("target-job.json", json.dumps({"title": "Engineer"})),
        "labels": ("labels.json", json.dumps({"expected_fields": []})),
    }
    case = {"case_id": "case-1", "role_family": "engineering"}
    for name, (filename, content) in files.items():
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
    return manifest
