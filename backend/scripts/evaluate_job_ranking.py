"""Run the versioned, privacy-safe semantic job-ranking backtest."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np

from embedding_service import (
    EMBEDDING_MODEL_NAME,
    EMBEDDING_MODEL_REVISION,
    build_job_embed_text,
    encode_text,
    encode_texts,
    rank_embedding_matrix,
)
from employer_filter import company_name_matches, is_recruitment_employer


DEFAULT_MANIFEST = Path(__file__).resolve().parents[1] / "evals/job-ranking-v1.json"


def _ndcg(relevances: list[int], ideal_relevances: list[int]) -> float:
    dcg = sum((2**value - 1) / math.log2(index + 2) for index, value in enumerate(relevances))
    ideal_dcg = sum(
        (2**value - 1) / math.log2(index + 2)
        for index, value in enumerate(ideal_relevances)
    )
    return dcg / ideal_dcg if ideal_dcg else 1.0


def _validate_case(case: dict) -> None:
    candidates = case.get("candidates") or []
    ids = [candidate.get("id") for candidate in candidates]
    if not case.get("case_id") or not str(case.get("query") or "").strip():
        raise ValueError("each ranking case needs case_id and query")
    if not candidates or len(ids) != len(set(ids)) or any(not isinstance(job_id, int) for job_id in ids):
        raise ValueError(f"{case['case_id']}: candidates need unique integer IDs")
    if not isinstance(case.get("top_k"), int) or case["top_k"] <= 0:
        raise ValueError(f"{case['case_id']}: top_k must be a positive integer")
    if any(
        not isinstance(candidate.get("relevance"), int) or candidate["relevance"] < 0
        for candidate in candidates
    ):
        raise ValueError(f"{case['case_id']}: relevance must be a nonnegative integer")
    if not any(candidate["relevance"] > 0 for candidate in candidates):
        raise ValueError(f"{case['case_id']}: at least one candidate must be relevant")
    if any(len(pair) != 2 for pair in case.get("pairwise_preferences") or []):
        raise ValueError(f"{case['case_id']}: pairwise preferences need two job IDs")
    known = set(ids)
    referenced = set(case.get("required_in_top_k") or []) | set(case.get("forbidden_in_results") or [])
    referenced.update(job_id for pair in case.get("pairwise_preferences") or [] for job_id in pair)
    if not referenced <= known:
        raise ValueError(f"{case['case_id']}: expectation references an unknown candidate")
    overlap = set(case.get("required_in_top_k") or []) & set(
        case.get("forbidden_in_results") or []
    )
    if overlap:
        raise ValueError(f"{case['case_id']}: required and forbidden candidates overlap")


def evaluate_case(case: dict, ranked_ids: list[int]) -> dict:
    """Evaluate human-authored invariants and report NDCG without a magic threshold."""
    _validate_case(case)
    known_ids = {candidate["id"] for candidate in case["candidates"]}
    if len(ranked_ids) != len(set(ranked_ids)):
        raise ValueError(f"{case['case_id']}: ranked job IDs must be unique")
    if not set(ranked_ids) <= known_ids:
        raise ValueError(f"{case['case_id']}: ranked results contain an unknown candidate")
    top_k = int(case["top_k"])
    ranked = ranked_ids[:top_k]
    positions = {job_id: index for index, job_id in enumerate(ranked)}
    required = set(case.get("required_in_top_k") or [])
    forbidden = set(case.get("forbidden_in_results") or [])
    violations = []
    missing = sorted(required - set(ranked))
    if missing:
        violations.append({"type": "required_missing", "job_ids": missing})
    present_forbidden = sorted(forbidden & set(ranked))
    if present_forbidden:
        violations.append({"type": "forbidden_present", "job_ids": present_forbidden})
    for preferred, lower in case.get("pairwise_preferences") or []:
        if preferred not in positions or (
            lower in positions and positions[preferred] >= positions[lower]
        ):
            violations.append({"type": "pairwise_failed", "preferred": preferred, "lower": lower})

    relevance = {candidate["id"]: int(candidate["relevance"]) for candidate in case["candidates"]}
    observed = [relevance[job_id] for job_id in ranked]
    eligible_relevance = [
        relevance[candidate["id"]]
        for candidate in case["candidates"]
        if candidate["id"] not in forbidden
    ]
    ideal = sorted(eligible_relevance, reverse=True)[:top_k]
    padded_observed = observed + [0] * max(0, len(ideal) - len(observed))
    return {
        "case_id": case["case_id"],
        "passed": not violations,
        "ranked_job_ids": ranked,
        "ndcg_at_k": round(_ndcg(padded_observed[: len(ideal)], ideal), 4),
        "violations": violations,
    }


def run(manifest_path: Path) -> dict:
    raw = manifest_path.read_bytes()
    manifest = json.loads(raw)
    if (
        manifest.get("model") != EMBEDDING_MODEL_NAME
        or manifest.get("model_revision") != EMBEDDING_MODEL_REVISION
    ):
        raise ValueError("ranking manifest model identity does not match the runtime encoder")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("ranking manifest requires at least one case")
    case_ids = [case.get("case_id") for case in cases if isinstance(case, dict)]
    if len(case_ids) != len(cases) or len(case_ids) != len(set(case_ids)):
        raise ValueError("ranking manifest case IDs must be unique")
    reports = []
    for case in cases:
        eligible = [
            candidate
            for candidate in case["candidates"]
            if (
                not case.get("direct_employers_only")
                or not is_recruitment_employer(candidate["company"], description=candidate["description"])
            )
            and (
                not case.get("company")
                or company_name_matches(candidate["company"], case["company"])
            )
        ]
        if not eligible:
            report = evaluate_case(case, [])
            report["passed"] = False
            report["violations"].append({"type": "no_eligible_candidates"})
            reports.append(report)
            continue
        query_vector = encode_text(case["query"])
        vectors = encode_texts([
            build_job_embed_text(job["title"], job["description"], job.get("skills"))
            for job in eligible
        ])
        ranked = rank_embedding_matrix(
            query_vector,
            [job["id"] for job in eligible],
            np.array(vectors, dtype=np.float32),
            int(case["top_k"]),
        )
        reports.append(evaluate_case(case, [job_id for job_id, _score in ranked]))
    return {
        "dataset_version": manifest["dataset_version"],
        "manifest_sha256": hashlib.sha256(raw).hexdigest(),
        "model": manifest["model"],
        "model_revision": manifest["model_revision"],
        "passed": all(report["passed"] for report in reports),
        "cases": reports,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()
    report = run(args.manifest.resolve())
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
