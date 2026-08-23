"""Fail unless a hash-pinned semantic corpus has nonzero valid label coverage.

This is a regression-readiness gate. It does not claim model quality without a
separately supplied, case-aligned prediction artifact.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from evals.semantic_label_gate import (  # noqa: E402
    SemanticLabelGateError,
    validate_labelled_corpus,
)
from semantic_corpus import CorpusError, load_corpus  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--corpus-dir", required=True)
    parser.add_argument("--minimum-labelled-cases", type=int, default=1)
    parser.add_argument("--minimum-labels", type=int, default=1)
    args = parser.parse_args()
    try:
        corpus = load_corpus(args.manifest, args.corpus_dir)
        report = validate_labelled_corpus(
            corpus,
            minimum_labelled_cases=args.minimum_labelled_cases,
            minimum_labels=args.minimum_labels,
        )
    except (CorpusError, SemanticLabelGateError) as error:
        parser.exit(2, f"error: {error}\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
