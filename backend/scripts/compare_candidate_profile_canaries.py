"""Compare Candidate Evidence Profile canary reports without reading resume content."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


MINIMUM_MODEL_CANDIDATES = 2


def _labelled_path(value: str) -> tuple[str, Path]:
    label, separator, raw_path = value.partition("=")
    if not separator or not label.strip() or not raw_path.strip():
        raise argparse.ArgumentTypeError("--report must use label=/path/to/report.json")
    return label.strip(), Path(raw_path).expanduser().resolve()


def _candidate(label: str, path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    spans = payload.get("spans") or []
    model_attempts = [span for span in spans if span.get("name") == "candidate_profile.model_attempt"]
    validations = [span for span in spans if span.get("name") == "candidate_profile.validation"]
    completed_scope_ids = list((payload.get("checkpoint") or {}).get("completed_scope_ids") or [])
    run = payload.get("run") or {}
    error = payload.get("error") or {}
    profile = payload.get("profile") or {}
    profile_evidence_ids = {
        str(item.get("evidence_id")) for item in profile.get("cited_resume_evidence") or [] if item.get("evidence_id")
    }
    field_citation_ids = {
        str(evidence_id)
        for field in profile.get("fields") or []
        for evidence_id in field.get("resume_evidence_ids") or []
    }
    evaluation = payload.get("evaluation") or {}
    field_evaluations = evaluation.get("field_evaluations") or []
    return {
        "label": label,
        "report_path": str(path),
        "status": payload.get("status"),
        "model_name": run.get("model_name") or error.get("model_name"),
        "execution_policy": payload.get("execution_policy"),
        "parse_quality": (payload.get("parse_report") or {}).get("parse_quality"),
        "document_block_count": (payload.get("parse_report") or {}).get("document_block_count"),
        "profile_field_count": len(profile.get("fields") or []),
        "profile_evidence_count": len(profile_evidence_ids),
        "field_citation_count": len(field_citation_ids),
        "citation_coverage_complete": profile_evidence_ids == field_citation_ids,
        "evaluation_result": evaluation.get("result"),
        "evaluation_score": evaluation.get("score"),
        "evaluation_field_count": len(field_evaluations),
        "evaluation_labels": dict(Counter(row.get("label") for row in field_evaluations if row.get("label"))),
        "completed_scope_count": len(completed_scope_ids),
        "completed_scope_ids": completed_scope_ids,
        "model_call_count": run.get("model_call_count") or error.get("model_call_count") or len(model_attempts),
        "input_tokens": run.get("input_tokens") or error.get("input_tokens"),
        "output_tokens": run.get("output_tokens") or error.get("output_tokens"),
        "model_attempt_duration_ms": [span.get("duration_ms") for span in model_attempts],
        "validation_codes": [
            (span.get("attributes") or {}).get("validation_code")
            for span in validations
            if (span.get("attributes") or {}).get("validation_code")
        ],
        "failure": (
            {
                "type": error.get("type"),
                "failure_type": error.get("failure_type"),
                "cause_type": error.get("cause_type"),
                "failed_scope_id": error.get("failed_scope_id"),
                "validation_code": error.get("validation_code"),
            }
            if error
            else None
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report",
        action="append",
        required=True,
        type=_labelled_path,
        help="Named input in label=/path/to/report.json form; provide at least two.",
    )
    parser.add_argument("--output", required=True, help="Output JSON comparison path.")
    args = parser.parse_args(argv)
    if len(args.report) < MINIMUM_MODEL_CANDIDATES:
        parser.error(f"provide at least {MINIMUM_MODEL_CANDIDATES} --report values")
    labels = [label for label, _path in args.report]
    if len(labels) != len(set(labels)):
        parser.error("--report labels must be unique")

    candidates = [_candidate(label, path) for label, path in args.report]
    baseline_policy = candidates[0]["execution_policy"]
    comparison = {
        "comparison_version": "candidate-profile-model-comparison-v1",
        "candidate_count": len(candidates),
        "same_execution_policy": all(item["execution_policy"] == baseline_policy for item in candidates),
        "all_completed": all(item["status"] == "completed" for item in candidates),
        "candidates": candidates,
    }
    output_path = Path(args.output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(comparison, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output_path), "all_completed": comparison["all_completed"]}))
    return 0 if comparison["all_completed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
