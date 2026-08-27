"""
Backfill embedding vectors for scraped jobs that are missing them.

Usage:
    python backfill_embeddings.py            # refresh missing or stale embeddings
    python backfill_embeddings.py --force     # re-embed all jobs
    python backfill_embeddings.py --missing-only  # never rewrite legacy vectors
    python backfill_embeddings.py --limit 500 # process at most 500 jobs
"""

from __future__ import annotations

import argparse
import time

from database import SessionLocal
from embedding_service import (
    EMBEDDING_MODEL_IDENTITY,
    refresh_job_embeddings,
)


def backfill(
    force: bool = False,
    limit: int | None = None,
    missing_only: bool = False,
) -> None:
    db = SessionLocal()
    try:
        started_at = time.time()

        def report(state: dict[str, int | bool]) -> None:
            elapsed = time.time() - started_at
            refreshed = int(state["refreshed"])
            rate = refreshed / elapsed if elapsed > 0 else 0
            print(
                f"  scanned={state['scanned']}/{state['searchable']} "
                f"refreshed={refreshed} rewrites={state['vector_rewrites']} "
                f"unresolved={state['unresolved']} "
                f"({rate:.1f} refreshes/sec)"
            )

        result = refresh_job_embeddings(
            db,
            force=force,
            missing_only=missing_only,
            limit=limit,
            on_progress=report,
        )
        if result["searchable"] == 0:
            print("No jobs to backfill.")
            return
        print(
            f"Done. Scanned {result['scanned']}; refreshed {result['refreshed']}; "
            f"rewrote {result['vector_rewrites']} vectors; "
            f"left {result['unresolved']} unresolved in "
            f"{time.time() - started_at:.1f}s using {EMBEDDING_MODEL_IDENTITY}."
        )

    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill job embedding vectors")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--force",
        action="store_true",
        help="Re-embed all jobs, even those with existing vectors",
    )
    mode.add_argument(
        "--missing-only",
        action="store_true",
        help="Embed missing vectors without rewriting unproven legacy vectors",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of jobs to process",
    )
    args = parser.parse_args()
    backfill(force=args.force, limit=args.limit, missing_only=args.missing_only)
