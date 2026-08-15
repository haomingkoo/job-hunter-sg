from pathlib import Path

from scripts.check_docs import check_docs


HANDBOOK = """# Handbook

## Current maintainer path
## Historical evidence
## Design records

[Root][root]
[Setup][setup]
[Architecture](architecture.md)
[Sources](sources.md)
[Operations](operations.md)
[Contributing](../CONTRIBUTING.md)
[Deploy](../DEPLOY.md)
[CI](ci.md)
[Quality](quality-gates.md)

[root]: ../README.md
[setup]: getting-started.md#install
"""


def _repository(tmp_path: Path) -> Path:
    (tmp_path / "docs").mkdir()
    (tmp_path / ".pytest_cache").mkdir()
    (tmp_path / "README.md").write_text("[Handbook](docs/README.md)\n")
    (tmp_path / "CONTRIBUTING.md").write_text("# Contributing\n")
    (tmp_path / "DEPLOY.md").write_text("# Deploy\n")
    (tmp_path / "docs" / "README.md").write_text(HANDBOOK)
    (tmp_path / "docs" / "getting-started.md").write_text("# Setup\n\n## Install\n")
    for name in ("architecture.md", "sources.md", "operations.md", "ci.md", "quality-gates.md"):
        (tmp_path / "docs" / name).write_text(f"# {name}\n")
    (tmp_path / ".pytest_cache" / "README.md").write_text("[ignored](missing.md)\n")
    return tmp_path


def test_reference_links_fragments_and_hidden_generated_dirs(tmp_path):
    errors, file_count, checked_links = check_docs(_repository(tmp_path))

    assert errors == []
    assert file_count == 10
    assert checked_links == 10


def test_missing_reference_and_markdown_anchor_are_reported(tmp_path):
    root = _repository(tmp_path)
    handbook = root / "docs" / "README.md"
    handbook.write_text(HANDBOOK + "\n[Missing][nowhere]\n[Bad](getting-started.md#absent)\n")

    errors, _file_count, _checked_links = check_docs(root)

    assert "docs/README.md: undefined reference link: nowhere" in errors
    assert "docs/README.md: missing Markdown anchor: getting-started.md#absent" in errors
