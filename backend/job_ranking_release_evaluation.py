"""Prepare and score one arm-blinded released-versus-candidate evaluation."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from statistics import median
from typing import Any


class ReleaseEvaluationError(ValueError):
    """The release evaluation artifacts are incomplete or inconsistent."""


def _sha256_file(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReleaseEvaluationError(f"{label} must be readable JSON") from error
    if not isinstance(value, dict):
        raise ReleaseEvaluationError(f"{label} must be a JSON object")
    return value


def _load_corpus(path: Path, expected_hash: str, expected_count: int) -> dict[str, dict]:
    if _sha256_file(path) != expected_hash:
        raise ReleaseEvaluationError("corpus SHA-256 mismatch")
    jobs: dict[str, dict] = {}
    try:
        with path.open(encoding="utf-8") as lines:
            for line in lines:
                if not line.strip():
                    continue
                job = json.loads(line)
                key = str(job.get("key") or "")
                if not key or key in jobs:
                    raise ReleaseEvaluationError("corpus job keys must be unique")
                jobs[key] = job
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReleaseEvaluationError("corpus must be readable JSONL") from error
    if len(jobs) != expected_count:
        raise ReleaseEvaluationError("corpus job count mismatch")
    return jobs


def _validate_receipts(
    protocol: dict[str, Any],
    protocol_hash: str,
    released: dict[str, Any],
    candidate: dict[str, Any],
) -> None:
    corpus = protocol["corpus"]
    matrix_hash = protocol["encoder"]["frozen_matrix_sha256"]
    for label, receipt, policy in (
        ("released", released, "released"),
        ("candidate", candidate, "candidate"),
    ):
        if receipt.get("policy") != policy:
            raise ReleaseEvaluationError(f"{label} receipt has the wrong policy")
        if receipt.get("protocol_sha256") != protocol_hash:
            raise ReleaseEvaluationError(f"{label} receipt has the wrong protocol")
        if receipt.get("corpus_sha256") != corpus["sha256"]:
            raise ReleaseEvaluationError(f"{label} receipt has the wrong corpus")
        if receipt.get("matrix_sha256") != matrix_hash:
            raise ReleaseEvaluationError(f"{label} receipt has the wrong matrix")
    if released.get("implementation_sha") != protocol["released_commit"]:
        raise ReleaseEvaluationError("released receipt has the wrong implementation")
    if candidate.get("implementation_sha") == protocol["released_commit"]:
        raise ReleaseEvaluationError("candidate must use a different implementation")
    if released.get("harness_sha256") != candidate.get("harness_sha256"):
        raise ReleaseEvaluationError("ranking arms used different capture harnesses")
    expected_cases = [case["case_id"] for case in protocol["cases"]]
    for label, receipt in (("released", released), ("candidate", candidate)):
        observed = [case.get("case_id") for case in receipt.get("cases", [])]
        if observed != expected_cases:
            raise ReleaseEvaluationError(f"{label} receipt cases differ from protocol")


def prepare_blinded_pool(
    protocol_path: str | Path,
    corpus_path: str | Path,
    released_receipt_path: str | Path,
    candidate_receipt_path: str | Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return the judge-visible pool and private arm/key mapping."""
    protocol_path = Path(protocol_path).resolve()
    corpus_path = Path(corpus_path).resolve()
    released_path = Path(released_receipt_path).resolve()
    candidate_path = Path(candidate_receipt_path).resolve()
    protocol = _load_object(protocol_path, "protocol")
    if protocol.get("evaluation_harness", {}).get(
        "pool_and_scoring_sha256"
    ) != _sha256_file(Path(__file__).resolve()):
        raise ReleaseEvaluationError("pool and scoring harness SHA-256 mismatch")
    released = _load_object(released_path, "released receipt")
    candidate = _load_object(candidate_path, "candidate receipt")
    protocol_hash = _sha256_file(protocol_path)
    _validate_receipts(protocol, protocol_hash, released, candidate)
    jobs = _load_corpus(
        corpus_path,
        str(protocol["corpus"]["sha256"]),
        int(protocol["corpus"]["job_count"]),
    )
    receipts = {
        "released": {case["case_id"]: case["ranked"] for case in released["cases"]},
        "candidate": {case["case_id"]: case["ranked"] for case in candidate["cases"]},
    }
    pool_cases = []
    mapping_cases = []
    for case in protocol["cases"]:
        case_id = case["case_id"]
        job_keys = {
            item["job_key"]
            for policy in ("released", "candidate")
            for item in receipts[policy][case_id]
        }
        items = []
        item_mapping = []
        for job_key in job_keys:
            if job_key not in jobs:
                raise ReleaseEvaluationError(f"receipt references unknown job: {job_key}")
            item_id = "item-" + hashlib.sha256(
                f"{protocol_hash}\0{case_id}\0{job_key}".encode()
            ).hexdigest()[:16]
            job = jobs[job_key]
            items.append({
                "item_id": item_id,
                "title": job.get("title", ""),
                "company": job.get("company", ""),
                "location": job.get("location", ""),
                "seniority": job.get("seniority", ""),
                "salary": job.get("salary", ""),
                "skills": job.get("skills", []),
                "description": job.get("description", ""),
            })
            item_mapping.append({"item_id": item_id, "job_key": job_key})
        items.sort(key=lambda item: item["item_id"])
        item_mapping.sort(key=lambda item: item["item_id"])
        pool_cases.append({
            "case_id": case_id,
            "query": case["query"],
            "constraints": {
                key: case.get(key)
                for key in (
                    "company",
                    "direct_employers_only",
                    "exclude_junior",
                    "singapore_only",
                    "title_phrase",
                )
                if key in case
            },
            "items": items,
        })
        mapping_cases.append({
            "case_id": case_id,
            "items": item_mapping,
            "released_ranked": receipts["released"][case_id],
            "candidate_ranked": receipts["candidate"][case_id],
        })
    pool = {
        "protocol_version": protocol["protocol_version"],
        "protocol_sha256": protocol_hash,
        "candidate_profile": protocol["candidate_profile"],
        "judging": protocol["judging"],
        "submission_instructions": (
            "Judge every item independently from the candidate profile, query, and "
            "constraints. Do not infer ranking arm or rank. Return one JSON object with "
            "rater, protocol_sha256, pool_sha256, and matching cases/items. Each item "
            "needs item_id, relevance (0-3), eligible (boolean), and seniority_fit "
            "(boolean)."
        ),
        "cases": pool_cases,
    }
    mapping = {
        "protocol_sha256": protocol_hash,
        "released_receipt_sha256": _sha256_file(released_path),
        "candidate_receipt_sha256": _sha256_file(candidate_path),
        "released_implementation_sha": released["implementation_sha"],
        "candidate_implementation_sha": candidate["implementation_sha"],
        "cases": mapping_cases,
    }
    return pool, mapping


def _dcg(values: list[int]) -> float:
    return sum((2**value - 1) / math.log2(index + 2) for index, value in enumerate(values))


def _aggregate_judgments(
    pool: dict[str, Any], pool_hash: str, judgment_paths: list[Path]
) -> tuple[dict[tuple[str, str], dict[str, Any]], list[dict[str, Any]]]:
    expected = {
        (case["case_id"], item["item_id"])
        for case in pool["cases"]
        for item in case["items"]
    }
    raters = []
    submitted: dict[tuple[str, str], list[dict[str, Any]]] = {
        key: [] for key in expected
    }
    for path in judgment_paths:
        document = _load_object(path, "judgment")
        if document.get("protocol_sha256") != pool["protocol_sha256"]:
            raise ReleaseEvaluationError(f"{path.name} has the wrong protocol")
        if document.get("pool_sha256") != pool_hash:
            raise ReleaseEvaluationError(f"{path.name} has the wrong pool")
        rater = str(document.get("rater") or "").strip()
        if not rater or rater in raters:
            raise ReleaseEvaluationError("raters must be named and unique")
        raters.append(rater)
        observed: set[tuple[str, str]] = set()
        for case in document.get("cases", []):
            case_id = case.get("case_id")
            for item in case.get("items", []):
                key = (case_id, item.get("item_id"))
                if key not in expected or key in observed:
                    raise ReleaseEvaluationError(f"{rater} submitted an unknown or duplicate item")
                if item.get("relevance") not in {0, 1, 2, 3}:
                    raise ReleaseEvaluationError(f"{rater} submitted invalid relevance")
                if not isinstance(item.get("eligible"), bool) or not isinstance(
                    item.get("seniority_fit"), bool
                ):
                    raise ReleaseEvaluationError(f"{rater} submitted invalid booleans")
                observed.add(key)
                submitted[key].append(item)
        if observed != expected:
            raise ReleaseEvaluationError(f"{rater} did not judge every pooled item")
    required = int(pool["judging"]["raters"])
    if len(raters) != required:
        raise ReleaseEvaluationError(f"expected {required} raters")
    aggregated = {}
    disagreements = []
    for key, values in submitted.items():
        relevances = [int(value["relevance"]) for value in values]
        eligibilities = [bool(value["eligible"]) for value in values]
        seniority = [bool(value["seniority_fit"]) for value in values]
        aggregated[key] = {
            "relevance": int(median(relevances)),
            "eligible": sum(eligibilities) > len(values) / 2,
            "seniority_fit": sum(seniority) > len(values) / 2,
        }
        if len(set(relevances)) > 1 or len(set(eligibilities)) > 1 or len(set(seniority)) > 1:
            disagreements.append({
                "case_id": key[0],
                "item_id": key[1],
                "relevance": relevances,
                "eligible": eligibilities,
                "seniority_fit": seniority,
            })
    return aggregated, disagreements


def score_release(
    protocol_path: str | Path,
    pool_path: str | Path,
    mapping_path: str | Path,
    judgment_paths: list[str | Path],
) -> dict[str, Any]:
    """Aggregate blinded judgments and apply the precommitted promotion rule."""
    protocol_path = Path(protocol_path).resolve()
    pool_path = Path(pool_path).resolve()
    mapping_path = Path(mapping_path).resolve()
    protocol = _load_object(protocol_path, "protocol")
    if protocol.get("evaluation_harness", {}).get(
        "pool_and_scoring_sha256"
    ) != _sha256_file(Path(__file__).resolve()):
        raise ReleaseEvaluationError("pool and scoring harness SHA-256 mismatch")
    pool = _load_object(pool_path, "pool")
    mapping = _load_object(mapping_path, "mapping")
    protocol_hash = _sha256_file(protocol_path)
    if pool.get("protocol_sha256") != protocol_hash or mapping.get("protocol_sha256") != protocol_hash:
        raise ReleaseEvaluationError("pool or mapping has the wrong protocol")
    pool_hash = _sha256_file(pool_path)
    judgments, disagreements = _aggregate_judgments(
        pool, pool_hash, [Path(path).resolve() for path in judgment_paths]
    )
    pool_items = {
        (case["case_id"], item["item_id"]): item
        for case in pool["cases"]
        for item in case["items"]
    }
    reports = []
    for case, mapped in zip(protocol["cases"], mapping["cases"]):
        case_id = case["case_id"]
        if mapped.get("case_id") != case_id:
            raise ReleaseEvaluationError("mapping cases differ from protocol")
        key_to_item = {item["job_key"]: item["item_id"] for item in mapped["items"]}
        eligible_relevant = sum(
            judgment["eligible"] and judgment["relevance"] > 0
            for (judged_case, _), judgment in judgments.items()
            if judged_case == case_id
        )
        ideal = sorted(
            (
                judgment["relevance"]
                for (judged_case, _), judgment in judgments.items()
                if judged_case == case_id and judgment["eligible"]
            ),
            reverse=True,
        )[: int(case["top_k"])]
        arms = {}
        for policy in ("released", "candidate"):
            ranked = mapped[f"{policy}_ranked"]
            ranked_items = [key_to_item[item["job_key"]] for item in ranked]
            labels = [judgments[(case_id, item_id)] for item_id in ranked_items]
            observed = [label["relevance"] if label["eligible"] else 0 for label in labels]
            observed.extend([0] * max(0, len(ideal) - len(observed)))
            ideal_dcg = _dcg(ideal)
            company = str(case.get("company") or "").casefold()
            arms[policy] = {
                "ranked_item_ids": ranked_items,
                "ndcg_at_k": round(_dcg(observed[: len(ideal)]) / ideal_dcg, 4) if ideal_dcg else 0.0,
                "recall_at_k_judged_pool": round(
                    sum(label["eligible"] and label["relevance"] > 0 for label in labels)
                    / eligible_relevant,
                    4,
                ) if eligible_relevant else 0.0,
                "hard_constraint_violations": [
                    item_id for item_id, label in zip(ranked_items, labels) if not label["eligible"]
                ],
                "seniority_errors": [
                    item_id for item_id, label in zip(ranked_items, labels) if not label["seniority_fit"]
                ],
                "empty": not ranked_items,
                "company_constraint_violations": [
                    item_id
                    for item_id in ranked_items
                    if company and company not in str(pool_items[(case_id, item_id)]["company"]).casefold()
                ],
            }
        reports.append({
            "case_id": case_id,
            "released": arms["released"],
            "candidate": arms["candidate"],
            "ndcg_delta": round(arms["candidate"]["ndcg_at_k"] - arms["released"]["ndcg_at_k"], 4),
        })
    candidate_violations = sum(
        len(report["candidate"]["hard_constraint_violations"]) for report in reports
    )
    empty_with_work = [
        report["case_id"]
        for report in reports
        if report["candidate"]["empty"]
        and any(
            case_id == report["case_id"] and label["eligible"] and label["relevance"] > 0
            for (case_id, _), label in judgments.items()
        )
    ]
    company_violations = [
        item_id
        for case, report in zip(protocol["cases"], reports)
        if str(case.get("company") or "").strip()
        for item_id in report["candidate"]["company_constraint_violations"]
    ]
    non_inferior = all(report["ndcg_delta"] >= 0 for report in reports)
    improved = any(report["ndcg_delta"] > 0 for report in reports)
    gates = {
        "no_candidate_hard_constraint_violations": candidate_violations == 0,
        "no_candidate_empty_case_with_relevant_work": not empty_with_work,
        "named_company_searches_only_return_that_company": not company_violations,
        "candidate_non_inferior_every_case": non_inferior,
        "candidate_improves_at_least_one_case": improved,
    }
    return {
        "protocol_sha256": protocol_hash,
        "pool_sha256": pool_hash,
        "mapping_sha256": _sha256_file(mapping_path),
        "released_receipt_sha256": mapping["released_receipt_sha256"],
        "candidate_receipt_sha256": mapping["candidate_receipt_sha256"],
        "released_implementation_sha": mapping["released_implementation_sha"],
        "candidate_implementation_sha": mapping["candidate_implementation_sha"],
        "rater_count": len(judgment_paths),
        "disagreement_count": len(disagreements),
        "disagreements": disagreements,
        "cases": reports,
        "gates": gates,
        "promotion_passed": all(gates.values()),
    }
