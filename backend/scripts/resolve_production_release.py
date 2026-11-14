"""Print the Git SHA that production should serve, from GitHub's deployment list.

Railway files one GitHub deployment per commit for the whole environment, shared
by the web service and both cron services. Statuses from any of them land on it,
and Railway has posted them on superseded commits. So a deployment_status event
names neither the service nor, reliably, the release. The newest production
deployment is the commit Railway last set out to ship.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import re
import sys


_FULL_SHA = re.compile(r"[0-9a-f]{40}")


def resolve_release_sha(deployments: list[dict], environment: str) -> str:
    candidates = [d for d in deployments if d.get("environment") == environment]
    if not candidates:
        raise RuntimeError(f"GitHub lists no deployments for {environment!r}")
    newest = max(
        candidates,
        key=lambda d: datetime.fromisoformat(str(d["created_at"]).replace("Z", "+00:00")),
    )
    sha = str(newest.get("sha") or "")
    if not _FULL_SHA.fullmatch(sha):
        raise RuntimeError(f"newest deployment SHA {sha!r} is not a full lowercase Git SHA")
    return sha


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("environment")
    args = parser.parse_args()
    print(resolve_release_sha(json.load(sys.stdin), args.environment))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
