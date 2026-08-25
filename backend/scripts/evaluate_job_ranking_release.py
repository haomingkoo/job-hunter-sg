"""Prepare or score the blinded job-ranking release evaluation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from job_ranking_release_evaluation import prepare_blinded_pool, score_release


def _write(path: Path, value: dict) -> None:
    path.resolve().write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--protocol", type=Path, required=True)
    prepare.add_argument("--corpus", type=Path, required=True)
    prepare.add_argument("--released", type=Path, required=True)
    prepare.add_argument("--candidate", type=Path, required=True)
    prepare.add_argument("--pool-output", type=Path, required=True)
    prepare.add_argument("--mapping-output", type=Path, required=True)
    score = commands.add_parser("score")
    score.add_argument("--protocol", type=Path, required=True)
    score.add_argument("--pool", type=Path, required=True)
    score.add_argument("--mapping", type=Path, required=True)
    score.add_argument("--judgment", type=Path, action="append", required=True)
    score.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        pool, mapping = prepare_blinded_pool(
            args.protocol, args.corpus, args.released, args.candidate
        )
        _write(args.pool_output, pool)
        _write(args.mapping_output, mapping)
    else:
        _write(
            args.output,
            score_release(args.protocol, args.pool, args.mapping, args.judgment),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
