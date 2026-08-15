#!/usr/bin/env python3
"""Check repository Markdown links and the maintainer handbook index."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
SKIP_PARTS = {".git", ".venv", "node_modules", "dist", "static"}
INLINE_LINK_RE = re.compile(r"!?\[[^\]]*\]\((<[^>]+>|[^)\s]+)(?:\s+[^)]*)?\)")
REFERENCE_DEFINITION_RE = re.compile(
    r"^\s{0,3}\[([^\]]+)\]:\s*(<[^>]+>|\S+)",
    re.MULTILINE,
)
REFERENCE_USAGE_RE = re.compile(r"!?\[([^\]]+)\]\[([^\]]*)\]")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$", re.MULTILINE)
REQUIRED_HANDBOOK_LINKS = {
    "../README.md",
    "getting-started.md",
    "architecture.md",
    "sources.md",
    "operations.md",
    "../CONTRIBUTING.md",
    "../DEPLOY.md",
    "ci.md",
    "quality-gates.md",
}
REQUIRED_HEADINGS = {
    "## Current maintainer path",
    "## Historical evidence",
    "## Design records",
}


def _skip(path: Path, root: Path) -> bool:
    parts = path.relative_to(root).parts
    return bool(SKIP_PARTS.intersection(parts)) or any(
        part.startswith(".") and part != ".github" for part in parts[:-1]
    )


def markdown_files(root: Path = ROOT) -> list[Path]:
    return sorted(path for path in root.rglob("*.md") if not _skip(path, root))


def without_fenced_code(text: str) -> str:
    lines: list[str] = []
    fence = ""
    for line in text.splitlines():
        marker = line.lstrip()[:3]
        if marker in {"```", "~~~"}:
            fence = "" if fence == marker else marker if not fence else fence
            continue
        if not fence:
            lines.append(line)
    return "\n".join(lines)


def _reference_label(value: str) -> str:
    return " ".join(value.casefold().split())


def link_targets(text: str) -> tuple[list[str], list[str]]:
    """Return inline/reference targets and undefined full/collapsed references."""
    body = without_fenced_code(text)
    targets = INLINE_LINK_RE.findall(body)
    definitions = {
        _reference_label(label): target
        for label, target in REFERENCE_DEFINITION_RE.findall(body)
    }
    targets.extend(definitions.values())

    missing: list[str] = []
    for text_label, reference_label in REFERENCE_USAGE_RE.findall(body):
        label = _reference_label(reference_label or text_label)
        if label not in definitions:
            missing.append(reference_label or text_label)
    return targets, missing


def _target_parts(raw: str) -> tuple[str, str] | None:
    target = raw[1:-1] if raw.startswith("<") and raw.endswith(">") else raw
    split = urlsplit(target)
    if split.scheme or split.netloc:
        return None
    return unquote(split.path), unquote(split.fragment)


def _heading_slug(value: str) -> str:
    value = re.sub(r"!?\[([^\]]+)\]\([^)]+\)", r"\1", value)
    value = re.sub(r"<[^>]+>|[`*_~]", "", value).strip().casefold()
    value = re.sub(r"[^\w\- ]", "", value)
    return re.sub(r"\s+", "-", value)


def heading_anchors(text: str) -> set[str]:
    counts: dict[str, int] = {}
    anchors: set[str] = set()
    for _marks, heading in HEADING_RE.findall(without_fenced_code(text)):
        base = _heading_slug(heading)
        duplicate = counts.get(base, 0)
        anchors.add(base if duplicate == 0 else f"{base}-{duplicate}")
        counts[base] = duplicate + 1
    return anchors


def check_docs(root: Path = ROOT) -> tuple[list[str], int, int]:
    errors: list[str] = []
    checked_links = 0
    handbook = root / "docs" / "README.md"
    root_readme = root / "README.md"

    if not handbook.is_file():
        errors.append("missing authoritative docs/README.md")
    else:
        handbook_text = handbook.read_text(encoding="utf-8")
        handbook_targets, _missing = link_targets(handbook_text)
        handbook_paths = {
            parts[0]
            for target in handbook_targets
            if (parts := _target_parts(target)) is not None
        }
        for target in sorted(REQUIRED_HANDBOOK_LINKS - handbook_paths):
            errors.append(f"docs/README.md is missing required link: {target}")
        for heading in sorted(REQUIRED_HEADINGS):
            if heading not in handbook_text:
                errors.append(f"docs/README.md is missing required heading: {heading}")

    if not root_readme.is_file():
        errors.append("missing README.md")
    else:
        readme_targets, _missing = link_targets(root_readme.read_text(encoding="utf-8"))
        readme_paths = {
            parts[0]
            for target in readme_targets
            if (parts := _target_parts(target)) is not None
        }
        if "docs/README.md" not in readme_paths:
            errors.append("README.md is missing the maintainer handbook link: docs/README.md")

    files = markdown_files(root)
    anchor_cache: dict[Path, set[str]] = {}
    for markdown in files:
        targets, missing_references = link_targets(markdown.read_text(encoding="utf-8"))
        for label in missing_references:
            errors.append(f"{markdown.relative_to(root)}: undefined reference link: {label}")
        for target in targets:
            parts = _target_parts(target)
            if parts is None:
                continue
            path, fragment = parts
            checked_links += 1
            candidate = markdown if not path else (
                (root / path.lstrip("/")) if path.startswith("/") else (markdown.parent / path)
            )
            try:
                resolved = candidate.resolve()
                resolved.relative_to(root.resolve())
            except ValueError:
                errors.append(f"{markdown.relative_to(root)}: link escapes repository: {target}")
                continue
            if not resolved.exists():
                errors.append(f"{markdown.relative_to(root)}: broken local link: {target}")
                continue
            if fragment and resolved.suffix.casefold() == ".md":
                anchors = anchor_cache.setdefault(
                    resolved,
                    heading_anchors(resolved.read_text(encoding="utf-8")),
                )
                if fragment not in anchors:
                    errors.append(f"{markdown.relative_to(root)}: missing Markdown anchor: {target}")

    return errors, len(files), checked_links


def main() -> int:
    errors, file_count, checked_links = check_docs()
    if errors:
        print("Documentation check failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"Documentation check passed: {file_count} files, {checked_links} local links")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
