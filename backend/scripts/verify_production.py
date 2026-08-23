"""Verify that public production is healthy at one exact Git commit."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
import json
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen


REQUIRED_PUBLIC_SOURCES = ("MyCareersFuture", "Careers@Gov")
PUBLIC_SOURCE_FRESHNESS_DAYS = 3


class _ModuleAssetParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.sources: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "script" and values.get("type") == "module" and values.get("src"):
            self.sources.append(values["src"] or "")


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

    jobs_path = "/api/jobs?per_page=1&sort=newest"
    jobs = json.loads(_get(base_url, jobs_path))
    if not isinstance(jobs.get("jobs"), list) or not isinstance(jobs.get("total"), int):
        raise RuntimeError("public jobs response is missing jobs or total")
    if jobs["total"] <= 0 or not jobs["jobs"]:
        raise RuntimeError("public jobs corpus is empty")

    source_rows = jobs.get("filter_meta", {}).get("sources", [])
    if not isinstance(source_rows, list):
        raise RuntimeError("public jobs response is missing source counts")
    source_counts = {
        str(row.get("value") or ""): row.get("count")
        for row in source_rows
        if isinstance(row, dict)
    }
    missing_sources = [
        source
        for source in REQUIRED_PUBLIC_SOURCES
        if not isinstance(source_counts.get(source), int) or source_counts[source] <= 0
    ]
    if missing_sources:
        raise RuntimeError(f"public jobs corpus is missing required sources: {missing_sources}")

    freshness_cutoff = datetime.now(timezone.utc) - timedelta(days=PUBLIC_SOURCE_FRESHNESS_DAYS)
    freshness_date = freshness_cutoff.date()
    source_freshness: dict[str, str] = {}
    freshness_paths: list[str] = []
    for source in REQUIRED_PUBLIC_SOURCES:
        freshness_path = "/api/jobs?" + urlencode(
            {
                "source": source,
                "scraped_from": freshness_date.isoformat(),
                "per_page": 1,
                "sort": "newest",
            }
        )
        recent = json.loads(_get(base_url, freshness_path))
        recent_jobs = recent.get("jobs")
        if not isinstance(recent.get("total"), int) or recent["total"] <= 0 or not isinstance(recent_jobs, list) or not recent_jobs:
            raise RuntimeError(
                f"{source} has no public rows scraped since {freshness_date.isoformat()}"
            )
        newest = recent_jobs[0]
        if not isinstance(newest, dict) or newest.get("source") != source:
            raise RuntimeError(f"{source} freshness response has the wrong source")
        scraped_at = str(newest.get("scraped_at") or "").strip()
        if not scraped_at:
            raise RuntimeError(f"{source} freshness response is missing scraped_at")
        try:
            scraped_datetime = datetime.fromisoformat(scraped_at.replace("Z", "+00:00"))
            if scraped_datetime.tzinfo is None:
                raise ValueError("timezone is missing")
        except ValueError:
            raise RuntimeError(f"{source} freshness response has invalid scraped_at") from None
        if scraped_datetime.astimezone(timezone.utc) < freshness_cutoff:
            raise RuntimeError(f"{source} latest public row is stale: {scraped_at}")
        source_freshness[source] = scraped_at
        freshness_paths.append(freshness_path)

    index = _get(base_url, "/")
    if b'id="root"' not in index:
        raise RuntimeError('/ is missing marker b\'id="root"\'')
    parser = _ModuleAssetParser()
    parser.feed(index.decode(errors="replace"))
    asset_path = next(
        (
            source
            for source in parser.sources
            if re.fullmatch(r"/assets/[^/]+-[A-Za-z0-9_-]+\.js", source)
        ),
        "",
    )
    if not asset_path:
        raise RuntimeError("/ is missing its hashed module asset")
    if not _get(base_url, asset_path):
        raise RuntimeError(f"{asset_path} is empty")

    checks = {
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
        "public_job_sources": source_counts,
        "source_freshness": source_freshness,
        "asset_path": asset_path,
        "checked_paths": ["/api/health", jobs_path, *freshness_paths, "/", asset_path, *checks],
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
