import json
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest

from scripts.verify_production import verify_once, verify_until_deployed


COMMIT = "a" * 40


class _ProductionHandler(BaseHTTPRequestHandler):
    commit = COMMIT
    empty_corpus = False
    missing_source = ""
    stale_source = ""
    responses = {
        "/": (
            "text/html",
            '<div id="root"></div><script type="module" src="/assets/index-abc123.js"></script>',
        ),
        "/assets/index-abc123.js": ("text/javascript", "const app = true;"),
        "/robots.txt": ("text/plain", "User-agent: *\nAllow: /"),
        "/sitemap.xml": ("application/xml", "<urlset></urlset>"),
        "/llms.txt": ("text/plain", "# Job Hunter SG"),
    }

    def do_GET(self):  # noqa: N802 - stdlib callback name
        if self.path == "/api/health":
            content_type, body = "application/json", json.dumps(
                {"status": "ok", "db": "connected", "commit": self.commit}
            )
        elif urlsplit(self.path).path == "/api/jobs":
            query = parse_qs(urlsplit(self.path).query)
            source = query.get("source", [""])[0]
            scraped_at = (
                datetime.now(timezone.utc) - timedelta(days=10)
                if source == self.stale_source
                else datetime.now(timezone.utc)
            ).isoformat()
            source_counts = [
                {"value": name, "count": 3}
                for name in ("MyCareersFuture", "Careers@Gov")
                if name != self.missing_source
            ]
            if self.empty_corpus:
                payload = {"jobs": [], "total": 0, "filter_meta": {"sources": []}}
            elif source:
                payload = {
                    "jobs": [{"source": source, "scraped_at": scraped_at}],
                    "total": 1,
                    "filter_meta": {"sources": source_counts},
                }
            else:
                payload = {
                    "jobs": [{"source": "MyCareersFuture", "scraped_at": scraped_at}],
                    "total": 6,
                    "filter_meta": {"sources": source_counts},
                }
            content_type, body = "application/json", json.dumps(payload)
        else:
            content_type, body = self.responses.get(self.path, ("text/plain", "missing"))
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, _format, *_args):
        pass


@pytest.fixture
def production_url():
    _ProductionHandler.commit = COMMIT
    _ProductionHandler.empty_corpus = False
    _ProductionHandler.missing_source = ""
    _ProductionHandler.stale_source = ""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ProductionHandler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_production_smoke_records_exact_commit_and_public_surfaces(production_url):
    receipt = verify_once(production_url, COMMIT)

    assert receipt["status"] == "passed"
    assert receipt["commit"] == COMMIT
    assert receipt["database"] == "connected"
    assert receipt["public_jobs"] == 6
    assert receipt["public_job_sources"] == {
        "MyCareersFuture": 3,
        "Careers@Gov": 3,
    }
    assert set(receipt["source_freshness"]) == {"MyCareersFuture", "Careers@Gov"}
    assert receipt["asset_path"] == "/assets/index-abc123.js"


def test_production_smoke_rejects_a_different_deployed_commit(production_url):
    with pytest.raises(RuntimeError, match="deployed commit"):
        verify_until_deployed(production_url, "b" * 40, wait_seconds=0, poll_seconds=1)


def test_production_smoke_requires_a_hashed_module_asset(production_url):
    original = _ProductionHandler.responses["/"]
    _ProductionHandler.responses["/"] = ("text/html", '<div id="root"></div>')
    try:
        with pytest.raises(RuntimeError, match="hashed module asset"):
            verify_once(production_url, COMMIT)
    finally:
        _ProductionHandler.responses["/"] = original


def test_production_smoke_rejects_an_empty_public_corpus(production_url):
    _ProductionHandler.empty_corpus = True

    with pytest.raises(RuntimeError, match="corpus is empty"):
        verify_once(production_url, COMMIT)


def test_production_smoke_requires_every_maintained_source(production_url):
    _ProductionHandler.missing_source = "Careers@Gov"

    with pytest.raises(RuntimeError, match="missing required sources"):
        verify_once(production_url, COMMIT)


def test_production_smoke_rejects_stale_source_rows(production_url):
    _ProductionHandler.stale_source = "Careers@Gov"

    with pytest.raises(RuntimeError, match="latest public row is stale"):
        verify_once(production_url, COMMIT)
