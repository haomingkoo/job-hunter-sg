from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import job_ranking_release_evaluation as release_evaluation
from job_ranking_release_evaluation import (
    ReleaseEvaluationError,
    prepare_blinded_pool,
    score_release,
)


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, sort_keys=True) + "\n")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _artifacts(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    corpus_path = tmp_path / "corpus.jsonl"
    jobs = [
        {
            "key": "source:micron",
            "title": "Manufacturing Manager",
            "company": "Micron Technology",
            "location": "Central",
            "seniority": "Manager",
            "salary": "$10,000",
            "skills": ["yield", "quality"],
            "description": "Leads semiconductor manufacturing and quality improvement.",
        },
        {
            "key": "source:agency",
            "title": "Junior Recruiter",
            "company": "Agency Pte Ltd",
            "location": "Central",
            "seniority": "Entry Level",
            "salary": "$3,000",
            "skills": [],
            "description": "Recruits manufacturing workers.",
        },
    ]
    corpus_path.write_text("".join(json.dumps(job) + "\n" for job in jobs))
    protocol_path = tmp_path / "protocol.json"
    released_sha = "a" * 40
    protocol = {
        "protocol_version": "test-v1",
        "released_commit": released_sha,
        "corpus": {"sha256": _sha256(corpus_path), "job_count": 2},
        "encoder": {"frozen_matrix_sha256": "m" * 64},
        "evaluation_harness": {
            "capture_sha256": "h" * 64,
            "pool_and_scoring_sha256": _sha256(
                Path(release_evaluation.__file__)
            ),
        },
        "candidate_profile": {"experience": "Semiconductor quality manager"},
        "judging": {"raters": 3},
        "cases": [
            {
                "case_id": "heldout-explicit-micron",
                "query": "semiconductor quality manager",
                "company": "Micron",
                "direct_employers_only": True,
                "exclude_junior": True,
                "singapore_only": True,
                "title_phrase": "manager",
                "top_k": 2,
            }
        ],
    }
    _write_json(protocol_path, protocol)
    receipt_common = {
        "protocol_sha256": _sha256(protocol_path),
        "harness_sha256": "h" * 64,
        "corpus_sha256": _sha256(corpus_path),
        "matrix_sha256": "m" * 64,
    }
    released_path = tmp_path / "released.json"
    _write_json(released_path, {
        **receipt_common,
        "implementation_sha": released_sha,
        "policy": "released",
        "cases": [{
            "case_id": "heldout-explicit-micron",
            "ranked": [
                {"job_key": "source:agency", "score": 0.9},
                {"job_key": "source:micron", "score": 0.8},
            ],
        }],
    })
    candidate_path = tmp_path / "candidate.json"
    _write_json(candidate_path, {
        **receipt_common,
        "implementation_sha": "b" * 40,
        "policy": "candidate",
        "cases": [{
            "case_id": "heldout-explicit-micron",
            "ranked": [{"job_key": "source:micron", "score": 0.8}],
        }],
    })
    return protocol_path, corpus_path, released_path, candidate_path


def test_prepare_pool_hides_arms_ranks_and_job_keys(tmp_path: Path) -> None:
    protocol, corpus, released, candidate = _artifacts(tmp_path)

    pool, mapping = prepare_blinded_pool(protocol, corpus, released, candidate)

    serialized_pool = json.dumps(pool)
    assert "source:micron" not in serialized_pool
    assert "source:agency" not in serialized_pool
    assert "released_ranked" not in serialized_pool
    assert "candidate_ranked" not in serialized_pool
    assert len(pool["cases"][0]["items"]) == 2
    assert len(mapping["cases"][0]["items"]) == 2


def test_score_release_uses_median_majority_and_precommitted_gates(
    tmp_path: Path,
) -> None:
    protocol, corpus, released, candidate = _artifacts(tmp_path)
    pool, mapping = prepare_blinded_pool(protocol, corpus, released, candidate)
    pool_path = tmp_path / "pool.json"
    mapping_path = tmp_path / "mapping.json"
    _write_json(pool_path, pool)
    _write_json(mapping_path, mapping)
    pool_hash = _sha256(pool_path)
    items = {
        item["company"]: item["item_id"] for item in pool["cases"][0]["items"]
    }
    judgment_paths = []
    for index in range(3):
        judgment = {
            "rater": f"judge-{index + 1}",
            "protocol_sha256": pool["protocol_sha256"],
            "pool_sha256": pool_hash,
            "cases": [{
                "case_id": "heldout-explicit-micron",
                "items": [
                    {
                        "item_id": items["Micron Technology"],
                        "relevance": 3 if index < 2 else 2,
                        "eligible": True,
                        "seniority_fit": True,
                    },
                    {
                        "item_id": items["Agency Pte Ltd"],
                        "relevance": 0,
                        "eligible": False,
                        "seniority_fit": False,
                    },
                ],
            }],
        }
        path = tmp_path / f"judge-{index + 1}.json"
        _write_json(path, judgment)
        judgment_paths.append(path)

    report = score_release(protocol, pool_path, mapping_path, judgment_paths)

    assert report["promotion_passed"] is True
    assert report["cases"][0]["candidate"]["ndcg_at_k"] == 1.0
    assert report["cases"][0]["released"]["ndcg_at_k"] < 1.0
    assert report["disagreement_count"] == 1


def test_score_release_rejects_incomplete_judgment(tmp_path: Path) -> None:
    protocol, corpus, released, candidate = _artifacts(tmp_path)
    pool, mapping = prepare_blinded_pool(protocol, corpus, released, candidate)
    pool_path = tmp_path / "pool.json"
    mapping_path = tmp_path / "mapping.json"
    _write_json(pool_path, pool)
    _write_json(mapping_path, mapping)
    judgment_paths = []
    for index in range(3):
        path = tmp_path / f"judge-{index + 1}.json"
        _write_json(path, {
            "rater": f"judge-{index + 1}",
            "protocol_sha256": pool["protocol_sha256"],
            "pool_sha256": _sha256(pool_path),
            "cases": [],
        })
        judgment_paths.append(path)

    with pytest.raises(ReleaseEvaluationError, match="did not judge every"):
        score_release(protocol, pool_path, mapping_path, judgment_paths)
