"""Capture one exact-checkout ranking arm for blinded release evaluation."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

import numpy as np


def _sha256_file(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return value


def _load_corpus(path: Path, expected_hash: str, expected_count: int) -> list[dict]:
    if _sha256_file(path) != expected_hash:
        raise ValueError("corpus SHA-256 mismatch")
    with path.open(encoding="utf-8") as lines:
        jobs = [json.loads(line) for line in lines if line.strip()]
    if len(jobs) != expected_count or any(not isinstance(job, dict) for job in jobs):
        raise ValueError("corpus shape does not match the protocol")
    return jobs


def _implementation_modules(root: Path) -> dict[str, Any]:
    backend = (root / "backend").resolve()
    sys.path.insert(0, str(backend))
    modules = {
        name: importlib.import_module(name)
        for name in (
            "agent_tool_contract",
            "config",
            "embedding_service",
            "employer_filter",
            "job_precompute",
            "job_visibility",
        )
    }
    for name, module in modules.items():
        module_path = Path(module.__file__).resolve()
        if backend not in module_path.parents:
            raise RuntimeError(f"{name} loaded outside the implementation checkout")
    return modules


def _eligible(
    job: dict,
    case: dict,
    *,
    policy: str,
    modules: dict[str, Any],
) -> bool:
    employer = modules["employer_filter"]
    visibility = modules["job_visibility"]
    precompute = modules["job_precompute"]
    company = str(job.get("company") or "")
    description = str(job.get("description") or "")
    ssic = str(job.get("company_ssic_description") or "")
    if case.get("direct_employers_only", True):
        if policy == "released":
            if employer.is_recruitment_employer(company, ssic, description):
                return False
        elif not employer.is_direct_employer(company, ssic, description):
            return False
    requested_company = str(case.get("company") or "").strip()
    if requested_company and not employer.company_name_matches(company, requested_company):
        return False
    if policy == "released":
        return True
    title = str(job.get("title") or "")
    title_phrase = str(case.get("title_phrase") or "").strip()
    if title_phrase and not visibility.job_title_matches(title, title_phrase):
        return False
    if case.get("singapore_only", True) and not visibility.is_singapore_job_location(
        str(job.get("location") or ""), title
    ):
        return False
    return not case.get("exclude_junior", False) or not visibility.is_junior_posting(
        str(job.get("seniority") or ""),
        title,
        precompute.salary_floor_from_text(str(job.get("salary") or "")),
    )


def _rank_case(
    case: dict,
    jobs: list[dict],
    matrix: np.ndarray,
    *,
    policy: str,
    modules: dict[str, Any],
) -> list[dict[str, Any]]:
    eligible_indices = [
        index
        for index, job in enumerate(jobs)
        if _eligible(job, case, policy=policy, modules=modules)
    ]
    if not eligible_indices:
        return []
    top_k = int(case["top_k"])
    multiplier = int(modules["config"].AGENT_SEARCH_CANDIDATE_MULTIPLIER)
    candidate_limit = max(top_k * multiplier, top_k)
    query_vector = modules["embedding_service"].encode_text(str(case["query"]))
    ranked = modules["embedding_service"].rank_embedding_matrix(
        query_vector,
        eligible_indices,
        matrix[eligible_indices],
        candidate_limit,
    )
    payloads = []
    for index, score in ranked:
        job = jobs[index]
        if policy == "released" and case.get("exclude_junior", False):
            if modules["job_visibility"].is_junior_posting(
                str(job.get("seniority") or ""),
                str(job.get("title") or ""),
                modules["job_precompute"].salary_floor_from_text(
                    str(job.get("salary") or "")
                ),
            ):
                continue
        payloads.append({
            "id": index,
            "key": job["key"],
            "title": job.get("title", ""),
            "company": job.get("company", ""),
            "location": job.get("location", ""),
            "description": job.get("description", ""),
            "source": job.get("source", ""),
            "source_posting_id": job.get("source_posting_id", ""),
            "score": score,
        })
    deduplicated = modules["agent_tool_contract"].deduplicate_job_payloads(payloads)
    return [
        {"job_key": str(job["key"]), "score": round(float(job["score"]), 8)}
        for job in deduplicated[:top_k]
    ]


def capture(
    protocol_path: Path,
    corpus_path: Path,
    matrix_path: Path,
    implementation_root: Path,
    implementation_sha: str,
    policy: str,
) -> dict[str, Any]:
    root = implementation_root.resolve()
    if policy not in {"released", "candidate"}:
        raise ValueError("policy must be released or candidate")
    if _git(root, "rev-parse", "HEAD") != implementation_sha:
        raise ValueError("implementation checkout does not match the requested SHA")
    if _git(root, "status", "--porcelain"):
        raise ValueError("implementation checkout must be clean")
    protocol = _load_json(protocol_path)
    harness_hash = _sha256_file(Path(__file__).resolve())
    if protocol.get("evaluation_harness", {}).get("capture_sha256") != harness_hash:
        raise ValueError("capture harness SHA-256 mismatch")
    if policy == "released" and protocol.get("released_commit") != implementation_sha:
        raise ValueError("released SHA does not match the precommitted protocol")
    corpus_spec = protocol["corpus"]
    jobs = _load_corpus(
        corpus_path,
        str(corpus_spec["sha256"]),
        int(corpus_spec["job_count"]),
    )
    encoder = protocol["encoder"]
    if _sha256_file(matrix_path) != encoder["frozen_matrix_sha256"]:
        raise ValueError("embedding matrix SHA-256 mismatch")
    matrix = np.load(matrix_path, mmap_mode="r")
    if list(matrix.shape) != encoder["frozen_matrix_shape"] or str(matrix.dtype) != encoder["frozen_matrix_dtype"]:
        raise ValueError("embedding matrix shape or dtype mismatch")
    modules = _implementation_modules(root)
    embedding = modules["embedding_service"]
    if (
        embedding.EMBEDDING_MODEL_NAME != encoder["model"]
        or embedding.EMBEDDING_MODEL_REVISION != encoder["revision"]
    ):
        raise ValueError("implementation encoder differs from the protocol")
    cases = [
        {
            "case_id": case["case_id"],
            "ranked": _rank_case(
                case,
                jobs,
                matrix,
                policy=policy,
                modules=modules,
            ),
        }
        for case in protocol["cases"]
    ]
    return {
        "protocol_sha256": _sha256_file(protocol_path),
        "harness_sha256": harness_hash,
        "corpus_sha256": corpus_spec["sha256"],
        "matrix_sha256": encoder["frozen_matrix_sha256"],
        "implementation_sha": implementation_sha,
        "policy": policy,
        "candidate_expansion_multiplier": int(
            modules["config"].AGENT_SEARCH_CANDIDATE_MULTIPLIER
        ),
        "cases": cases,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--matrix", type=Path, required=True)
    parser.add_argument("--implementation-root", type=Path, required=True)
    parser.add_argument("--implementation-sha", required=True)
    parser.add_argument("--policy", choices=("released", "candidate"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = capture(
        args.protocol.resolve(),
        args.corpus.resolve(),
        args.matrix.resolve(),
        args.implementation_root.resolve(),
        args.implementation_sha,
        args.policy,
    )
    args.output.resolve().write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
