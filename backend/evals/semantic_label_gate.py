"""Validate that a semantic corpus contains usable, non-empty labels.

This module is deliberately a coverage gate, not a model-quality scorer. A
quality regression decision additionally needs predictions produced from the
same hash-pinned cases and a label-to-output mapping.
"""

from __future__ import annotations

import json
from typing import Any

from semantic_corpus import SemanticCorpus, assert_privacy_safe_report


class SemanticLabelGateError(ValueError):
    """The corpus cannot support a nonzero labelled regression run."""


def validate_labelled_corpus(
    corpus: SemanticCorpus,
    *,
    minimum_labelled_cases: int = 1,
    minimum_labels: int = 1,
) -> dict[str, Any]:
    """Return privacy-safe label coverage or fail closed below explicit minima."""
    if minimum_labelled_cases < 1 or minimum_labels < 1:
        raise SemanticLabelGateError("label coverage minima must be positive")

    labelled_case_count = 0
    label_count = 0
    label_versions: set[str] = set()
    for case in corpus.cases:
        try:
            payload = json.loads(case.labels.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SemanticLabelGateError("labels must be a readable JSON object") from error
        if not isinstance(payload, dict):
            raise SemanticLabelGateError("labels must be a JSON object")
        label_version = str(payload.get("label_version") or "").strip()
        expected_fields = payload.get("expected_fields")
        if not label_version or not isinstance(expected_fields, list):
            raise SemanticLabelGateError(
                "labels require label_version and an expected_fields list"
            )

        seen_paths: set[str] = set()
        for expected_field in expected_fields:
            if not isinstance(expected_field, dict):
                raise SemanticLabelGateError("every expected field must be an object")
            field_path = str(expected_field.get("field_path") or "").strip()
            expected = str(expected_field.get("expected") or "").strip()
            required = expected_field.get("required")
            if not field_path or not expected or not isinstance(required, bool):
                raise SemanticLabelGateError(
                    "every expected field requires field_path, expected, and boolean required"
                )
            if field_path in seen_paths:
                raise SemanticLabelGateError("expected field paths must be unique per case")
            seen_paths.add(field_path)

        if expected_fields:
            labelled_case_count += 1
            label_count += len(expected_fields)
            label_versions.add(label_version)

    if labelled_case_count < minimum_labelled_cases:
        raise SemanticLabelGateError(
            f"labelled case count {labelled_case_count} is below {minimum_labelled_cases}"
        )
    if label_count < minimum_labels:
        raise SemanticLabelGateError(
            f"label count {label_count} is below {minimum_labels}"
        )

    report = {
        "dataset_version": corpus.dataset_version,
        "case_count": len(corpus.cases),
        "labelled_case_count": labelled_case_count,
        "label_count": label_count,
        "label_versions": sorted(label_versions),
        "coverage_gate": "pass",
    }
    assert_privacy_safe_report(report)
    return report
