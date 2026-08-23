"""CLI entry point for matched-job email digests."""

from __future__ import annotations

import argparse
import json

from database import init_db
from job_alerts import run_job_alerts


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description="Send opt-in Job Hunter SG match alert digests.")
    parser.add_argument("--dry-run", action="store_true", help="Find due alerts without sending email or writing history.")
    parser.add_argument(
        "--limit-users",
        type=_positive_int,
        default=None,
        help="Maximum number of opted-in users to process.",
    )
    args = parser.parse_args()

    init_db()
    stats = run_job_alerts(dry_run=args.dry_run, limit_users=args.limit_users)
    print(json.dumps(stats, indent=2, sort_keys=True, default=str))
    if not args.dry_run and not stats.get("email_configured"):
        return 2
    if stats.get("errors"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
