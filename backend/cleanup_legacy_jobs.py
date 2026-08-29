#!/usr/bin/env python3
"""Audit or execute the backup-gated cleanup of legacy hidden jobs."""

from __future__ import annotations

import argparse
import json
from uuid import UUID

from database import SessionLocal
from job_store import (
    count_unreferenced_legacy_hidden_jobs,
    prune_unreferenced_legacy_hidden_jobs,
)


def cleanup_legacy_jobs(
    *,
    execute: bool,
    expected_candidates: int | None = None,
    backup_id: str = "",
    batch_size: int = 5000,
) -> dict[str, int | str]:
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero")
    if execute:
        if expected_candidates is None or expected_candidates <= 0:
            raise ValueError("--expected-candidates must be greater than zero")
        try:
            UUID(backup_id)
        except ValueError:
            raise ValueError("--backup-id must be a Railway backup UUID") from None

    db = SessionLocal()
    try:
        initial = count_unreferenced_legacy_hidden_jobs(db)
        result: dict[str, int | str] = {
            "mode": "execute" if execute else "dry-run",
            "initial_candidates": initial,
            "deleted": 0,
            "final_candidates": initial,
            "backup_id": backup_id,
        }
        if not execute:
            return result
        if initial != expected_candidates:
            raise RuntimeError(
                f"candidate count changed: expected {expected_candidates}, found {initial}"
            )

        deleted = 0
        while deleted < expected_candidates:
            batch_deleted = prune_unreferenced_legacy_hidden_jobs(
                db,
                min(batch_size, expected_candidates - deleted),
            )
            if not batch_deleted:
                break
            deleted += batch_deleted
            print(json.dumps({"deleted": deleted, "expected": expected_candidates}), flush=True)

        final = count_unreferenced_legacy_hidden_jobs(db)
        result["deleted"] = deleted
        result["final_candidates"] = final
        if deleted != expected_candidates or final:
            raise RuntimeError(
                f"cleanup stopped after {deleted} deletes with {final} candidates remaining"
            )
        return result
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--expected-candidates", type=int)
    parser.add_argument("--backup-id", default="")
    parser.add_argument("--batch-size", type=int, default=5000)
    args = parser.parse_args()
    result = cleanup_legacy_jobs(
        execute=args.execute,
        expected_candidates=args.expected_candidates,
        backup_id=args.backup_id,
        batch_size=args.batch_size,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
