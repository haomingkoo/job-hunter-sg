import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from scripts.verify_production import verify_once, verify_until_deployed


COMMIT = "a" * 40


class _ProductionHandler(BaseHTTPRequestHandler):
    commit = COMMIT
    responses = {
        "/": ("text/html", '<div id="root"></div>'),
        "/api/jobs?per_page=1": ("application/json", '{"jobs": [], "total": 0}'),
        "/robots.txt": ("text/plain", "User-agent: *\nAllow: /"),
        "/sitemap.xml": ("application/xml", "<urlset></urlset>"),
        "/llms.txt": ("text/plain", "# Job Hunter SG"),
    }

    def do_GET(self):  # noqa: N802 - stdlib callback name
        if self.path == "/api/health":
            content_type, body = "application/json", json.dumps(
                {"status": "ok", "db": "connected", "commit": self.commit}
            )
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
    assert receipt["public_jobs"] == 0


def test_production_smoke_rejects_a_different_deployed_commit(production_url):
    with pytest.raises(RuntimeError, match="deployed commit"):
        verify_until_deployed(production_url, "b" * 40, wait_seconds=0, poll_seconds=1)
