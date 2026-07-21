"""Load hash-pinned semantic evaluation cases without exposing private inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any


_ARTIFACT_NAMES = ("resume", "target_job", "labels")
_FORBIDDEN_REPORT_KEYS = {
    "corpus_dir",
    "labels_path",
    "manifest_path",
    "raw_text",
    "resume_path",
    "resume_text",
    "target_job_path",
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class CorpusError(ValueError):
    pass


@dataclass(frozen=True)
class CorpusArtifact:
    ref: str
    sha256: str
    path: Path


@dataclass(frozen=True)
class CorpusCase:
    case_id: str
    role_family: str
    resume: CorpusArtifact
    target_job: CorpusArtifact
    labels: CorpusArtifact


@dataclass(frozen=True)
class SemanticCorpus:
    dataset_version: str
    cases: tuple[CorpusCase, ...]


def load_corpus(manifest_path: str | Path, corpus_dir: str | Path) -> SemanticCorpus:
    """Load and verify one explicitly located corpus manifest."""
    manifest = _json_object(Path(manifest_path).expanduser().resolve(), "manifest")
    root = Path(corpus_dir).expanduser().resolve()
    if not root.is_dir():
        raise CorpusError("corpus_dir must be an existing directory")

    dataset_version = str(manifest.get("dataset_version") or "").strip()
    raw_cases = manifest.get("cases")
    if not dataset_version or not isinstance(raw_cases, list) or not raw_cases:
        raise CorpusError("manifest requires dataset_version and at least one case")

    cases: list[CorpusCase] = []
    seen_ids: set[str] = set()
    for raw_case in raw_cases:
        if not isinstance(raw_case, dict):
            raise CorpusError("every case must be an object")
        case_id = str(raw_case.get("case_id") or "").strip()
        role_family = str(raw_case.get("role_family") or "").strip()
        if not case_id or case_id in seen_ids or not role_family:
            raise CorpusError("case_id must be unique and role_family is required")
        seen_ids.add(case_id)
        artifacts = {
            name: _artifact(root, raw_case.get(name), f"{case_id}.{name}")
            for name in _ARTIFACT_NAMES
        }
        if not artifacts["resume"].path.read_bytes():
            raise CorpusError(f"{case_id}.resume must not be empty")
        _json_object(artifacts["target_job"].path, f"{case_id}.target_job")
        _json_object(artifacts["labels"].path, f"{case_id}.labels")
        cases.append(CorpusCase(case_id, role_family, **artifacts))
    return SemanticCorpus(dataset_version, tuple(cases))


def privacy_safe_summary(corpus: SemanticCorpus) -> dict[str, Any]:
    """Return metadata suitable for logs or CI output."""
    report = {
        "dataset_version": corpus.dataset_version,
        "case_count": len(corpus.cases),
        "cases": [
            {
                "case_id": case.case_id,
                "role_family": case.role_family,
                "artifact_sha256": {
                    name: getattr(case, name).sha256 for name in _ARTIFACT_NAMES
                },
            }
            for case in corpus.cases
        ],
    }
    assert_privacy_safe_report(report)
    return report


def assert_privacy_safe_report(
    report: Any,
    *,
    private_values: tuple[str, ...] = (),
) -> None:
    """Reject raw-input fields, absolute paths, or supplied private text."""
    def visit(value: Any) -> None:
        if isinstance(value, dict):
            forbidden = _FORBIDDEN_REPORT_KEYS & {str(key) for key in value}
            if forbidden:
                raise CorpusError(f"report contains private field: {sorted(forbidden)[0]}")
            for item in value.values():
                visit(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                visit(item)
        elif isinstance(value, Path):
            raise CorpusError("report contains a path object")
        elif isinstance(value, str) and (
            os.path.isabs(value) or PureWindowsPath(value).is_absolute()
        ):
            raise CorpusError("report contains an absolute path")

    visit(report)
    serialized = json.dumps(report, ensure_ascii=False)
    for value in private_values:
        if value and value in serialized:
            raise CorpusError("report contains private source content")


def _artifact(root: Path, value: Any, label: str) -> CorpusArtifact:
    if not isinstance(value, dict):
        raise CorpusError(f"{label} must contain ref and sha256")
    ref = str(value.get("ref") or "").strip()
    expected_hash = str(value.get("sha256") or "").strip().lower()
    relative = Path(ref)
    if not ref or relative.is_absolute() or ".." in relative.parts:
        raise CorpusError(f"{label}.ref must stay within corpus_dir")
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise CorpusError(f"{label}.ref must stay within corpus_dir") from error
    if not path.is_file() or not _SHA256_RE.fullmatch(expected_hash):
        raise CorpusError(f"{label} requires an existing file and lowercase SHA-256")
    actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual_hash != expected_hash:
        raise CorpusError(f"{label} SHA-256 mismatch")
    return CorpusArtifact(ref, expected_hash, path)


def _json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CorpusError(f"{label} must be a readable JSON object") from error
    if not isinstance(value, dict):
        raise CorpusError(f"{label} must be a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--corpus-dir", required=True)
    args = parser.parse_args()
    try:
        corpus = load_corpus(args.manifest, args.corpus_dir)
    except CorpusError as error:
        parser.exit(2, f"error: {error}\n")
    print(json.dumps(
        privacy_safe_summary(corpus),
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
