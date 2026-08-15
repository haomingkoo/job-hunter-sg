"""Verify that public production is healthy at one exact Git commit."""

from __future__ import annotations

import argparse
import json
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


def _get(base_url: str, path: str) -> bytes:
    request = Request(
        urljoin(base_url.rstrip("/") + "/", path.lstrip("/")),
        headers={"User-Agent": "job-hunter-sg-production-smoke/1.0"},
    )
    with urlopen(request, timeout=20) as response:
        if response.status != 200:
            raise RuntimeError(f"{path} returned HTTP {response.status}")
        return response.read()


def verify_once(base_url: str, expected_sha: str) -> dict:
    health = json.loads(_get(base_url, "/api/health"))
    if health.get("commit") != expected_sha:
        raise RuntimeError(
            f"deployed commit is {health.get('commit')!r}, expected {expected_sha!r}"
        )
    if health.get("status") != "ok" or health.get("db") != "connected":
        raise RuntimeError(f"unhealthy API/database response: {health!r}")

    jobs = json.loads(_get(base_url, "/api/jobs?per_page=1"))
    if not isinstance(jobs.get("jobs"), list) or not isinstance(jobs.get("total"), int):
        raise RuntimeError("public jobs response is missing jobs or total")

    checks = {
        "/": b'id="root"',
        "/robots.txt": b"User-agent:",
        "/sitemap.xml": b"<urlset",
        "/llms.txt": b"# Job Hunter SG",
    }
    for path, marker in checks.items():
        if marker not in _get(base_url, path):
            raise RuntimeError(f"{path} is missing marker {marker!r}")

    return {
        "status": "passed",
        "base_url": base_url.rstrip("/"),
        "commit": expected_sha,
        "database": "connected",
        "public_jobs": jobs["total"],
        "checked_paths": ["/api/health", "/api/jobs?per_page=1", *checks],
    }


def verify_until_deployed(
    base_url: str,
    expected_sha: str,
    wait_seconds: int,
    poll_seconds: int,
) -> dict:
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            return verify_once(base_url, expected_sha)
        except (HTTPError, URLError, json.JSONDecodeError, RuntimeError) as exc:
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"production did not accept commit {expected_sha} within {wait_seconds}s: {exc}"
                ) from exc
            print(f"Waiting for {expected_sha}: {exc}", file=sys.stderr)
            time.sleep(poll_seconds)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("base_url")
    parser.add_argument("expected_sha")
    parser.add_argument("--wait-seconds", type=int, default=900)
    parser.add_argument("--poll-seconds", type=int, default=15)
    args = parser.parse_args()

    if len(args.expected_sha) != 40 or any(c not in "0123456789abcdef" for c in args.expected_sha):
        parser.error("expected_sha must be a full lowercase Git SHA")
    receipt = verify_until_deployed(
        args.base_url,
        args.expected_sha,
        max(0, args.wait_seconds),
        max(1, args.poll_seconds),
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
