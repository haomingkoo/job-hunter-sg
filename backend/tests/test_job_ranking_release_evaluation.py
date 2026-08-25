from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
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


def test_release_v4_protocol_is_bound_to_canonical_harnesses_and_baseline() -> None:
    backend = Path(__file__).resolve().parents[1]
    protocol = json.loads((backend / "evals/job-ranking-release-v4.protocol.json").read_text())

    assert protocol["evaluation_harness"]["capture_sha256"] == _sha256(backend / "scripts/capture_job_ranking_arm.py")
    assert protocol["evaluation_harness"]["pool_and_scoring_sha256"] == _sha256(
        backend / "job_ranking_release_evaluation.py"
    )
    assert protocol["released_commit"] == "6a76ab3878126bf8a3b9dce51263bf270d8ffdba"
    assert protocol["work_location_classifier"]["version"] == "work-location-scope-v1"
    assert protocol["employer_relationship_classifier"]["version"] == "employer-relationship-v1"
    assert protocol["corpus"]["employer_relationship_receipt"] == {
        "direct": 1192,
        "unknown": 48634,
        "intermediary": 31205,
        "released_default_eligible": 49826,
        "candidate_default_eligible": 49826,
        "nonempty_agency": 1192,
        "nonempty_ssic_code": 0,
    }
    purpose = protocol["purpose"].casefold()
    assert "arm-blinded" in purpose
    assert "release evaluation" in purpose
    assert "backtest" not in purpose
    assert "regression" not in purpose


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
            "pool_and_scoring_sha256": _sha256(Path(release_evaluation.__file__)),
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
    _write_json(
        released_path,
        {
            **receipt_common,
            "implementation_sha": released_sha,
            "policy": "released",
            "cases": [
                {
                    "case_id": "heldout-explicit-micron",
                    "ranked": [
                        {"job_key": "source:agency", "score": 0.9},
                        {"job_key": "source:micron", "score": 0.8},
                    ],
                }
            ],
        },
    )
    candidate_path = tmp_path / "candidate.json"
    _write_json(
        candidate_path,
        {
            **receipt_common,
            "implementation_sha": "b" * 40,
            "policy": "candidate",
            "cases": [
                {
                    "case_id": "heldout-explicit-micron",
                    "ranked": [{"job_key": "source:micron", "score": 0.8}],
                }
            ],
        },
    )
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


def test_company_gate_uses_normalized_whole_words() -> None:
    assert release_evaluation._company_name_matches("Micron Semiconductor Asia Pte Ltd", "Micron")
    assert not release_evaluation._company_name_matches("Ecomicron Labs", "Micron")


def test_literal_title_and_company_constraints_are_mechanical() -> None:
    case = {"company": "Micron", "title_phrase": "manager"}
    assert release_evaluation._mechanical_ineligibility_reasons(
        case,
        {"company": "Micron Semiconductor", "title": "Manufacturing Manager"},
    ) == []
    assert release_evaluation._mechanical_ineligibility_reasons(
        case,
        {"company": "Micron Semiconductor", "title": "Manufacturing Director"},
    ) == ["title_phrase_mismatch"]
    assert release_evaluation._mechanical_ineligibility_reasons(
        case,
        {"company": "Ecomicron Labs", "title": "Manufacturing Director"},
    ) == ["company_phrase_mismatch", "title_phrase_mismatch"]


def test_candidate_capture_exercises_direct_unknown_and_structured_intermediary_policy(monkeypatch):
    from scripts import capture_job_ranking_arm as capture

    root = Path(__file__).resolve().parents[2]
    modules = capture._implementation_modules(root)
    monkeypatch.setattr(modules["embedding_service"], "encode_text", lambda _query: np.array([1.0, 0.0]))
    jobs = [
        {
            "key": "mcf:unknown",
            "title": "Quality Manager",
            "company": "Micron Semiconductor",
            "location": "Central",
            "source": "MyCareersFuture",
            "description": "Lead quality systems.",
        },
        {
            "key": "careers-gov:direct",
            "title": "Quality Manager",
            "company": "Singapore Public Service",
            "agency": "Agency for Science, Technology and Research",
            "location": "Singapore",
            "source": "Careers@Gov",
            "description": "Lead quality systems.",
        },
        {
            "key": "mcf:ssic-78",
            "title": "Quality Manager",
            "company": "Example Services",
            "location": "Central",
            "source": "MyCareersFuture",
            "company_ssic_code": "78104",
            "company_ssic_source": "mcf_posted_company",
            "description": "Lead quality systems.",
        },
    ]
    matrix = np.array([[1.0, 0.0], [1.0, 0.0], [1.0, 0.0]], dtype=np.float32)
    case = {
        "case_id": "structured-employer-policy",
        "query": "quality manager",
        "direct_employers_only": True,
        "singapore_only": True,
        "exclude_junior": False,
        "title_phrase": "manager",
        "top_k": 3,
    }

    released = capture._rank_case(case, jobs, matrix, policy="released", modules=modules)
    candidate = capture._rank_case(case, jobs, matrix, policy="candidate", modules=modules)

    assert [item["job_key"] for item in released] == [
        "mcf:unknown",
        "careers-gov:direct",
        "mcf:ssic-78",
    ]
    assert [item["job_key"] for item in candidate] == [
        "careers-gov:direct",
        "mcf:unknown",
    ]


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
    items = {item["company"]: item["item_id"] for item in pool["cases"][0]["items"]}
    judgment_paths = []
    for index in range(3):
        judgment = {
            "rater": f"judge-{index + 1}",
            "protocol_sha256": pool["protocol_sha256"],
            "pool_sha256": pool_hash,
            "cases": [
                {
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
                            "eligible": True,
                            "seniority_fit": False,
                        },
                    ],
                }
            ],
        }
        path = tmp_path / f"judge-{index + 1}.json"
        _write_json(path, judgment)
        judgment_paths.append(path)

    report = score_release(
        protocol,
        corpus,
        released,
        candidate,
        pool_path,
        mapping_path,
        judgment_paths,
    )

    assert report["promotion_passed"] is True
    assert report["cases"][0]["candidate"]["ndcg_at_k"] == 1.0
    assert report["cases"][0]["released"]["ndcg_at_k"] < 1.0
    assert report["disagreement_count"] == 1
    assert len(report["mechanical_constraint_overrides"]) == 1
    assert report["cases"][0]["released"]["hard_constraint_violations"] == [
        items["Agency Pte Ltd"]
    ]


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
        _write_json(
            path,
            {
                "rater": f"judge-{index + 1}",
                "protocol_sha256": pool["protocol_sha256"],
                "pool_sha256": _sha256(pool_path),
                "cases": [],
            },
        )
        judgment_paths.append(path)

    with pytest.raises(ReleaseEvaluationError, match="did not judge every"):
        score_release(
            protocol,
            corpus,
            released,
            candidate,
            pool_path,
            mapping_path,
            judgment_paths,
        )


def test_score_release_rejects_mapping_tampering(tmp_path: Path) -> None:
    protocol, corpus, released, candidate = _artifacts(tmp_path)
    pool, mapping = prepare_blinded_pool(protocol, corpus, released, candidate)
    pool_path = tmp_path / "pool.json"
    mapping_path = tmp_path / "mapping.json"
    _write_json(pool_path, pool)
    mapping["cases"][0]["candidate_ranked"] = mapping["cases"][0]["released_ranked"]
    _write_json(mapping_path, mapping)

    with pytest.raises(ReleaseEvaluationError, match="bound receipts"):
        score_release(
            protocol,
            corpus,
            released,
            candidate,
            pool_path,
            mapping_path,
            [],
        )
