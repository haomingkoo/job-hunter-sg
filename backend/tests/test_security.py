from __future__ import annotations

import asyncio
import base64
import hashlib
import os
from pathlib import Path
import re
import secrets
import sys
import threading
import zipfile
from datetime import datetime, timezone
from io import BytesIO

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from starlette.datastructures import Headers, UploadFile
from starlette.responses import Response

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.mark.parametrize(
    ("schema", "payload"),
    [
        ("SignupRequest", {"email": "candidate@example.com", "password": "Password1!", "name": "Candidate"}),  # pragma: allowlist secret
        ("VerifyEmailRequest", {"token": "t" * 20, "password": "Password1!", "name": "Candidate"}),  # pragma: allowlist secret
        ("CloudflareRegisterRequest", {"name": "Candidate"}),
    ],
)
def test_terms_acceptance_schemas_share_the_same_validation(schema, payload):
    from pydantic import ValidationError

    import schemas

    model = getattr(schemas, schema)
    if schema == "SignupRequest" and schemas._ALLOWED_DOMAINS:
        payload = {**payload, "email": f"candidate@{schemas._ALLOWED_DOMAINS[0]}"}
    with pytest.raises(ValidationError, match="You must accept the Terms of Service and Privacy Notice"):
        model(**payload, accepted_terms=False)
    assert model(**payload, accepted_terms=True).accepted_terms is True


def _http_scope(*, headers: list[tuple[bytes, bytes]] | None = None) -> dict:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/test",
        "raw_path": b"/test",
        "query_string": b"",
        "headers": headers or [],
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 80),
    }


async def _run_asgi(app, scope: dict, request_messages: list[dict] | None = None) -> list[dict]:
    requests = iter(request_messages or [{"type": "http.request", "body": b""}])
    responses: list[dict] = []

    async def receive() -> dict:
        return next(requests)

    async def send(message: dict) -> None:
        responses.append(message)

    await app(scope, receive, send)
    return responses


async def _read_request_body(scope, receive, send) -> None:
    body = bytearray()
    more_body = True
    while more_body:
        message = await receive()
        body.extend(message.get("body", b""))
        more_body = message.get("more_body", False)
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": bytes(body)})


def test_body_limit_rejects_oversized_content_length_without_reading_body():
    from security import RequestBodyLimitMiddleware

    app = RequestBodyLimitMiddleware(_read_request_body, default_max_bytes=5)
    responses = asyncio.run(
        _run_asgi(app, _http_scope(headers=[(b"content-length", b"6")]))
    )

    assert responses[0]["status"] == 413
    assert b"Request body too large" in responses[1]["body"]


def test_body_limit_rejects_streamed_body_without_content_length():
    from security import RequestBodyLimitMiddleware

    app = RequestBodyLimitMiddleware(_read_request_body, default_max_bytes=5)
    responses = asyncio.run(
        _run_asgi(
            app,
            _http_scope(),
            [
                {"type": "http.request", "body": b"abc", "more_body": True},
                {"type": "http.request", "body": b"def", "more_body": False},
            ],
        )
    )

    assert responses[0]["status"] == 413
    assert b"Request body too large" in responses[1]["body"]


def test_body_limit_uses_path_specific_override():
    from security import RequestBodyLimitMiddleware

    app = RequestBodyLimitMiddleware(
        _read_request_body,
        default_max_bytes=3,
        path_limits={"/upload": 6},
    )
    scope = _http_scope(headers=[(b"content-length", b"6")])
    scope["path"] = "/upload"
    scope["raw_path"] = b"/upload"
    responses = asyncio.run(
        _run_asgi(
            app,
            scope,
            [{"type": "http.request", "body": b"abcdef", "more_body": False}],
        )
    )

    assert responses[0]["status"] == 200
    assert responses[1]["body"] == b"abcdef"


def test_body_limit_supports_dynamic_path_prefixes():
    from security import RequestBodyLimitMiddleware

    app = RequestBodyLimitMiddleware(
        _read_request_body,
        default_max_bytes=3,
        path_limits={"/api/applications/workspaces/*": 6},
    )
    scope = _http_scope(headers=[(b"content-length", b"6")])
    scope["path"] = "/api/applications/workspaces/42/submitted-resume"
    scope["raw_path"] = scope["path"].encode()
    responses = asyncio.run(
        _run_asgi(
            app,
            scope,
            [{"type": "http.request", "body": b"abcdef", "more_body": False}],
        )
    )

    assert responses[0]["status"] == 200
    assert responses[1]["body"] == b"abcdef"


def test_fixed_window_rate_limiter_enforces_limit_and_resets():
    from security import FixedWindowRateLimiter

    limiter = FixedWindowRateLimiter()

    assert limiter.allow("client-a", limit=2, window_seconds=60, now=0)
    assert limiter.allow("client-a", limit=2, window_seconds=60, now=1)
    assert not limiter.allow("client-a", limit=2, window_seconds=60, now=59)
    assert limiter.allow("client-b", limit=2, window_seconds=60, now=59)
    assert limiter.allow("client-a", limit=2, window_seconds=60, now=60)


def test_fixed_window_rate_limiter_bounds_identity_keys():
    from security import FixedWindowRateLimiter

    limiter = FixedWindowRateLimiter(max_keys=2)
    assert limiter.allow("old", limit=1, window_seconds=60, now=0)
    assert limiter.allow("newer", limit=1, window_seconds=60, now=1)
    assert limiter.allow("newest", limit=1, window_seconds=60, now=2)

    assert set(limiter._hits) == {"newer", "newest"}


def test_client_ip_uses_cloudflare_header_only_when_explicitly_trusted(monkeypatch):
    import security

    request = Request(
        _http_scope(headers=[(b"cf-connecting-ip", b"203.0.113.8")])
    )
    monkeypatch.setattr(security, "_TRUST_CLOUDFLARE_IP_HEADER", False)
    assert security.get_client_ip(request) == "127.0.0.1"

    monkeypatch.setattr(security, "_TRUST_CLOUDFLARE_IP_HEADER", True)
    assert security.get_client_ip(request) == "203.0.113.8"

    invalid = Request(
        _http_scope(headers=[(b"cf-connecting-ip", b"not-an-ip")])
    )
    assert security.get_client_ip(invalid) == "127.0.0.1"


def test_security_headers_harden_private_responses():
    from security import SecurityHeadersMiddleware

    async def ok(_scope, _receive, send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    scope = _http_scope()
    scope["path"] = "/api/account"
    responses = asyncio.run(_run_asgi(SecurityHeadersMiddleware(ok, hsts=True), scope))
    headers = dict(responses[0]["headers"])

    assert headers[b"cache-control"] == b"no-store"
    assert headers[b"x-frame-options"] == b"DENY"
    assert headers[b"x-content-type-options"] == b"nosniff"
    assert headers[b"referrer-policy"] == b"no-referrer"
    assert b"frame-ancestors 'none'" in headers[b"content-security-policy"]
    assert b"max-age=31536000" in headers[b"strict-transport-security"]


def test_csp_hashes_every_inline_script_without_allowing_arbitrary_inline_code():
    from security import SecurityHeadersMiddleware

    index = (Path(__file__).resolve().parents[2] / "frontend" / "index.html").read_text()
    inline_scripts = re.findall(
        r'<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)</script>',
        index,
    )
    expected_hashes = {
        "'sha256-"
        + base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
        + "'"
        for script in inline_scripts
    }
    policy = SecurityHeadersMiddleware._CONTENT_SECURITY_POLICY.decode()

    assert inline_scripts
    assert "script-src 'self' 'unsafe-inline'" not in policy
    assert expected_hashes == set(SecurityHeadersMiddleware._INLINE_SCRIPT_HASHES)


def test_security_headers_wrap_spa_fallback():
    import main
    from security import SecurityHeadersMiddleware

    assert main.app.user_middleware[0].cls is SecurityHeadersMiddleware


@pytest.mark.parametrize(
    "path",
    [
        "/api/ai/coach",
        "/api/applications/workspaces",
        "/api/jobs/42/match",
        "/api/jobs/42/parsed",
        "/api/jobs/power-match",
        "/api/jobs/recommended",
        "/api/memory",
        "/api/recruitment-team/threads/thread-1",
        "/api/search",
        "/api/skillsfuture/recommend",
        "/api/usage",
    ],
)
def test_security_headers_prevent_caching_authenticated_responses(path):
    from security import SecurityHeadersMiddleware

    async def ok(_scope, _receive, send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    scope = _http_scope()
    scope["path"] = path
    responses = asyncio.run(_run_asgi(SecurityHeadersMiddleware(ok), scope))

    assert dict(responses[0]["headers"])[b"cache-control"] == b"no-store"


def test_security_headers_leave_public_job_responses_cacheable():
    from security import SecurityHeadersMiddleware

    async def ok(_scope, _receive, send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    scope = _http_scope()
    scope["path"] = "/api/jobs/42"
    responses = asyncio.run(_run_asgi(SecurityHeadersMiddleware(ok), scope))

    assert b"cache-control" not in dict(responses[0]["headers"])


def test_security_headers_replace_weaker_private_cache_directive():
    from security import SecurityHeadersMiddleware

    async def ok(_scope, _receive, send) -> None:
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"cache-control", b"no-cache")],
        })
        await send({"type": "http.response.body", "body": b"ok"})

    scope = _http_scope()
    scope["path"] = "/api/recruitment-team/runs/run-1/stream"
    responses = asyncio.run(_run_asgi(SecurityHeadersMiddleware(ok), scope))
    cache_headers = [
        value
        for name, value in responses[0]["headers"]
        if name.lower() == b"cache-control"
    ]

    assert cache_headers == [b"no-store"]


@pytest.mark.parametrize(
    "value",
    [
        "javascript:alert(document.domain)",
        "data:text/html,<script>alert(1)</script>",
        "https://example.com/jobs/1\nX-Injected: true",
        "https://user:secret@example.com/jobs/1",  # pragma: allowlist secret
    ],
)
def test_stored_url_schemas_reject_unsafe_values(value):
    from pydantic import ValidationError
    from schemas import ApplicationWorkspaceCreate, NegotiationEvidence, TrackedJobCreate, TrackedJobUpdate

    constructors = (
        lambda: TrackedJobCreate(company="Example", role="Engineer", source_url=value),
        lambda: TrackedJobUpdate(source_url=value),
        lambda: ApplicationWorkspaceCreate(
            company="Example",
            title="Engineer",
            job_description="Build reliable systems.",
            source_url=value,
        ),
        lambda: NegotiationEvidence(
            label="Written offer",
            value="$9,000",
            definition="Monthly base",
            source_url=value,
        ),
    )

    for construct in constructors:
        with pytest.raises(ValidationError):
            construct()


def test_stored_url_schemas_preserve_blank_and_normalize_http_urls():
    from schemas import NegotiationEvidence, TrackedJobCreate, TrackedJobUpdate

    assert TrackedJobCreate(company="Example", role="Engineer").source_url == ""
    assert TrackedJobUpdate(source_url=None).source_url is None
    evidence = NegotiationEvidence(
        label="Written offer",
        value="$9,000",
        definition="Monthly base",
        source_url="  HTTPS://example.com/offer?id=1  ",
    )

    assert evidence.source_url == "HTTPS://example.com/offer?id=1"


@pytest.mark.parametrize(
    ("request_type", "field_name", "base"),
    [
        ("StartThreadRequest", "message", {"resume_version_id": 1}),
        ("SendMessageRequest", "message", {}),
        ("AnswerAssessmentQuestionRequest", "answer", {}),
    ],
)
def test_recruitment_requests_bound_user_messages(request_type, field_name, base):
    from pydantic import ValidationError
    from recruitment_team import http_routes

    model = getattr(http_routes, request_type)
    payload = {
        **base,
        field_name: "x" * (http_routes.RECRUITMENT_MESSAGE_MAX_CHARS + 1),
        "idempotency_key": "test",
    }

    with pytest.raises(ValidationError):
        model(**payload)


def test_cloudflare_mode_rejects_unsafe_requests_without_a_trusted_origin(
    monkeypatch,
):
    import auth
    from main import reject_cross_site_cloudflare_writes

    monkeypatch.setattr(auth, "AUTH_MODE", "cloudflare")
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://job.example.com")

    async def call(origin: str | None):
        scope = _http_scope(
            headers=[] if origin is None else [(b"origin", origin.encode())]
        )
        request = Request(scope)

        async def next_request(_request: Request) -> Response:
            return Response(status_code=204)

        return await reject_cross_site_cloudflare_writes(request, next_request)

    assert asyncio.run(call(None)).status_code == 403
    assert asyncio.run(call("https://evil.example")).status_code == 403
    assert asyncio.run(call("https://job.example.com")).status_code == 204


def test_docx_zip_bomb_is_rejected_before_parsing():
    from resume_parser import parse_resume

    archive_bytes = BytesIO()
    with zipfile.ZipFile(archive_bytes, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", b"<Types />")
        archive.writestr("word/document.xml", b"A" * (2 * 1024 * 1024))

    with pytest.raises(ValueError, match="compression ratio is unsafe"):
        parse_resume(
            "resume.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            archive_bytes.getvalue(),
        )


def test_arbitrary_zip_is_not_accepted_as_docx():
    from resume_parser import parse_resume

    archive_bytes = BytesIO()
    with zipfile.ZipFile(archive_bytes, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("payload.txt", b"not a Word document")

    with pytest.raises(ValueError, match="does not match DOCX format"):
        parse_resume(
            "resume.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            archive_bytes.getvalue(),
        )


def test_resume_upload_rejects_more_than_five_megabytes():
    from main import MAX_FILE_SIZE, upload_resume

    upload = UploadFile(
        file=BytesIO(b"x" * (MAX_FILE_SIZE + 1)),
        filename="resume.pdf",
        headers=Headers({"content-type": "application/pdf"}),
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            upload_resume(
                request=Request(_http_scope()),
                file=upload,
                user=None,
                db=None,
            )
        )

    assert exc_info.value.status_code == 413
    assert upload.file.closed


def test_resume_upload_parsing_runs_off_the_event_loop(monkeypatch):
    import main
    import resume_upload

    caller_thread = threading.get_ident()
    parser_threads: list[int] = []

    def fake_parse_resume(**_kwargs) -> dict:
        parser_threads.append(threading.get_ident())
        return {
            "text": "Parsed resume",
            "file_type": "pdf",
            "word_count": 2,
            "line_count": 1,
            "parse_quality": {},
        }

    class FakeSession:
        def add(self, _value) -> None:
            pass

        def commit(self) -> None:
            pass

    monkeypatch.setattr(resume_upload, "parse_resume_isolated", fake_parse_resume)
    upload = UploadFile(
        file=BytesIO(b"small-pdf"),
        filename="resume.pdf",
        headers=Headers({"content-type": "application/pdf"}),
    )

    result = asyncio.run(
        main.upload_resume(
            request=Request(_http_scope()),
            file=upload,
            user=None,
            db=FakeSession(),
        )
    )

    assert result["text"] == "Parsed resume"
    assert parser_threads and parser_threads[0] != caller_thread


def test_resume_upload_rejects_when_parser_capacity_is_full(monkeypatch):
    import main
    import resume_upload

    monkeypatch.setattr(resume_upload, "_RESUME_PARSE_SLOTS", threading.BoundedSemaphore(0))
    upload = UploadFile(
        file=BytesIO(b"small-pdf"),
        filename="resume.pdf",
        headers=Headers({"content-type": "application/pdf"}),
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            main.upload_resume(
                request=Request(_http_scope()),
                file=upload,
                user=None,
                db=None,
            )
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.headers == {"Retry-After": "2"}


def test_auth_email_links_keep_tokens_out_of_query_strings(monkeypatch):
    from types import SimpleNamespace

    import main

    messages: list[tuple[str, str]] = []
    monkeypatch.setattr(
        main,
        "send_email",
        lambda _email, _subject, text, html: messages.append((text, html)),
    )
    user = SimpleNamespace(email="person@example.com", name="Person")

    main._send_verification_email(user, "verification-token")
    main._send_password_reset_email(user, "reset-token")

    combined = "\n".join(part for message in messages for part in message)
    assert "/#verify_token=verification-token" in combined
    assert "/#reset_token=reset-token" in combined
    assert "/?verify_token=" not in combined
    assert "/?reset_token=" not in combined


def test_job_search_bounds_expensive_public_queries():
    from fastapi.testclient import TestClient

    from main import app
    from security import contains_like_pattern

    client = TestClient(app)

    assert client.get("/api/jobs", params={"q": "one two three four five six seven eight nine"}).status_code == 422
    assert client.get("/api/jobs", params={"page": 501}).status_code == 422
    assert client.get(
        "/api/jobs",
        params=[("location", f"location-{index}") for index in range(21)],
    ).status_code == 422
    assert contains_like_pattern("%_") == r"%\%\_%"


def test_unused_live_skills_proxy_is_not_public():
    from fastapi.testclient import TestClient

    from main import app

    assert TestClient(app).get("/api/skills", params={"q": "engineer"}).status_code == 404


def test_hidden_jobs_are_not_available_by_detail_or_as_similarity_targets():
    from fastapi.testclient import TestClient

    from database import SessionLocal
    from main import app
    from models import ScrapedJob

    marker = secrets.token_hex(8)
    with SessionLocal() as db:
        hidden = ScrapedJob(
            title=f"Hidden {marker} Engineer",
            company="Hidden Employer",
            dedup_key=secrets.token_hex(16),
            posted_at_sort=datetime.now(timezone.utc).isoformat(),
            hidden=1,
        )
        visible = ScrapedJob(
            title=f"Visible {marker} Engineer",
            company="Visible Employer",
            dedup_key=secrets.token_hex(16),
            posted_at_sort=datetime.now(timezone.utc).isoformat(),
        )
        db.add_all([hidden, visible])
        db.commit()
        hidden_id = hidden.id
        visible_id = visible.id

    try:
        client = TestClient(app)
        assert client.get(f"/api/jobs/{hidden_id}").status_code == 404
        assert client.get(f"/api/jobs/{hidden_id}/similar").status_code == 404
        assert client.get(f"/api/jobs/{visible_id}").status_code == 200
        similar = client.get(f"/api/jobs/{visible_id}/similar")
        assert similar.status_code == 200
        assert hidden_id not in {job["id"] for job in similar.json()}
    finally:
        with SessionLocal() as db:
            db.query(ScrapedJob).filter(
                ScrapedJob.id.in_([hidden_id, visible_id])
            ).delete(synchronize_session=False)
            db.commit()


def test_background_seed_is_single_flight():
    import main

    started = threading.Event()
    release = threading.Event()

    def blocking_seed() -> None:
        started.set()
        assert release.wait(2)

    assert main._start_seed_task(blocking_seed)
    assert started.wait(2)
    assert not main._start_seed_task(lambda: None)
    release.set()
    assert main._SEED_RUN_LOCK.acquire(timeout=2)
    main._SEED_RUN_LOCK.release()


def test_tracked_job_ownership_does_not_reveal_other_record_ids():
    import main
    from database import SessionLocal
    from models import TrackedJob, User
    from schemas import TrackedJobUpdate

    marker = secrets.token_hex(8)
    with SessionLocal() as db:
        owner = User(
            email=f"owner-{marker}@example.com",
            password_hash="unused",  # pragma: allowlist secret
            name="Owner",
        )
        intruder = User(
            email=f"intruder-{marker}@example.com",
            password_hash="unused",  # pragma: allowlist secret
            name="Intruder",
        )
        db.add_all([owner, intruder])
        db.flush()
        tracked = TrackedJob(user_id=owner.id, company="Employer", role="Role")
        db.add(tracked)
        db.commit()
        tracked_id = tracked.id

        with pytest.raises(HTTPException) as update_error:
            main.update_tracked(
                tracked_id,
                TrackedJobUpdate(notes="changed"),
                intruder,
                db,
            )
        with pytest.raises(HTTPException) as delete_error:
            main.delete_tracked(tracked_id, intruder, db)

        assert update_error.value.status_code == 404
        assert delete_error.value.status_code == 404
        assert db.get(TrackedJob, tracked_id).notes == ""

        db.delete(tracked)
        db.delete(owner)
        db.delete(intruder)
        db.commit()


def test_health_returns_503_when_database_is_unavailable():
    from main import health

    class BrokenSession:
        def execute(self, _statement) -> None:
            raise RuntimeError("database offline")

    with pytest.raises(HTTPException) as exc_info:
        health(BrokenSession())

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Database unavailable"


@pytest.mark.parametrize(
    ("configured_key", "authorization", "expected_status"),
    [
        (None, None, 503),
        ("server-secret", None, 401),
        ("server-secret", "Bearer wrong-secret", 401),
    ],
)
def test_mcp_proxy_requires_configured_valid_bearer(
    monkeypatch,
    configured_key: str | None,
    authorization: str | None,
    expected_status: int,
):
    from main import _ASGIProxy

    if configured_key is None:
        monkeypatch.delenv("MCP_API_KEY", raising=False)
    else:
        monkeypatch.setenv("MCP_API_KEY", configured_key)
    headers = [] if authorization is None else [(b"authorization", authorization.encode())]

    responses = asyncio.run(_run_asgi(_ASGIProxy(), _http_scope(headers=headers)))

    assert responses[0]["status"] == expected_status
    if expected_status == 401:
        assert (b"www-authenticate", b"Bearer") in responses[0]["headers"]


def test_rag_agent_and_legacy_live_search_require_accounts():
    from fastapi.testclient import TestClient

    from main import app

    client = TestClient(app)

    assert client.post("/api/resume/agent/start", json={"message": "Find jobs"}).status_code == 401
    assert client.post("/api/search", params={"q": "engineer"}).status_code == 401
    # These routes are POST-only, so an unauthenticated GET is 405. Once the built
    # frontend exists in backend/static, main.py mounts StaticFiles at "/" and the
    # same GET returns 404 instead. What matters here is that neither serves data.
    no_data = {404, 405}
    assert client.get("/api/search", params={"q": "engineer"}).status_code in no_data
    assert client.get("/api/jobs/power-match").status_code in no_data
    assert client.get("/api/resume/tailor/missing/result").status_code in no_data
    assert client.get("/api/jobs/recommended", params={"resume_text": "private resume"}).status_code in no_data


def test_unsubscribe_link_requires_confirmation_before_mutating(monkeypatch):
    from fastapi.testclient import TestClient

    import main
    from database import SessionLocal
    from job_alerts import create_unsubscribe_token
    from models import JobAlertPreference, User

    marker = secrets.token_hex(8)
    monkeypatch.setenv("ALERT_UNSUBSCRIBE_SECRET", f"unsubscribe-{marker}")
    with SessionLocal() as db:
        user = User(
            email=f"unsubscribe-{marker}@example.com",
            password_hash="unused",  # pragma: allowlist secret
            name="Unsubscribe Test",
        )
        db.add(user)
        db.flush()
        pref = JobAlertPreference(user_id=user.id, enabled=True)
        db.add(pref)
        token = create_unsubscribe_token(user)
        db.commit()
        user_id = user.id

    try:
        client = TestClient(main.app)
        preview = client.get("/api/job-alerts/unsubscribe", params={"token": token})

        assert preview.status_code == 200
        assert "Confirm" in preview.text
        with SessionLocal() as db:
            assert bool(
                db.query(JobAlertPreference)
                .filter(JobAlertPreference.user_id == user_id)
                .one()
                .enabled
            )

        confirmed = client.post("/api/job-alerts/unsubscribe", params={"token": token})
        assert confirmed.status_code == 200
        with SessionLocal() as db:
            assert not bool(
                db.query(JobAlertPreference)
                .filter(JobAlertPreference.user_id == user_id)
                .one()
                .enabled
            )

        with SessionLocal() as db:
            db.query(JobAlertPreference).filter(JobAlertPreference.user_id == user_id).delete()
            db.query(User).filter(User.id == user_id).delete()
            db.commit()
            replacement = User(
                email=f"replacement-{marker}@example.com",
                password_hash="unused",  # pragma: allowlist secret
                name="Replacement Account",
            )
            db.add(replacement)
            db.flush()
            assert replacement.id == user_id
            db.add(JobAlertPreference(user_id=replacement.id, enabled=True))
            db.commit()

        stale = client.post("/api/job-alerts/unsubscribe", params={"token": token})
        assert stale.status_code == 400
        with SessionLocal() as db:
            assert bool(
                db.query(JobAlertPreference)
                .filter(JobAlertPreference.user_id == user_id)
                .one()
                .enabled
            )

    finally:
        with SessionLocal() as db:
            db.query(JobAlertPreference).filter(JobAlertPreference.user_id == user_id).delete()
            db.query(User).filter(User.id == user_id).delete()
            db.commit()


def test_story_usage_storage_is_bounded_per_account(monkeypatch):
    import story_bank
    from story_routes import record_story_usage
    from database import SessionLocal
    from models import InterviewStory, StoryUsage, User

    marker = secrets.token_hex(8)
    with SessionLocal() as db:
        user = User(
            email=f"story-usage-{marker}@example.com",
            password_hash="unused",  # pragma: allowlist secret
            name="Story Usage Test",
        )
        db.add(user)
        db.flush()
        story = InterviewStory(user_id=user.id, title="Bounded story")
        db.add(story)
        db.flush()
        db.add(StoryUsage(story_id=story.id, user_id=user.id))
        db.commit()
        user_id = user.id
        story_id = story.id

        monkeypatch.setattr(story_bank, "MAX_STORY_USAGES", 1)
        with pytest.raises(HTTPException) as exc_info:
            record_story_usage(story_id, {}, user, db)

        assert exc_info.value.status_code == 409
        assert db.query(StoryUsage).filter(StoryUsage.user_id == user_id).count() == 1

    with SessionLocal() as db:
        db.query(StoryUsage).filter(StoryUsage.user_id == user_id).delete()
        db.query(InterviewStory).filter(InterviewStory.user_id == user_id).delete()
        db.query(User).filter(User.id == user_id).delete()
        db.commit()


def test_saved_resume_and_story_counts_are_bounded():
    import secrets

    from fastapi.testclient import TestClient

    import main
    from story_bank import MAX_ACTIVE_STORIES
    from auth import get_current_user, hash_password
    from database import SessionLocal
    from models import InterviewStory, ResumeVersion, User

    db = SessionLocal()
    user = User(
        email=f"bounded-{secrets.token_hex(8)}@example.com",
        password_hash=hash_password("TestPassword123!"),
        name="Bounded Storage Test",
        tier="user",
    )
    try:
        db.add(user)
        db.commit()
        db.refresh(user)
        db.add_all(
            ResumeVersion(
                user_id=user.id,
                label=f"Resume {index}",
                resume_text="A" * 50,
            )
            for index in range(main._MAX_ACTIVE_RESUME_VERSIONS)
        )
        db.add_all(
            InterviewStory(user_id=user.id, title=f"Story {index}")
            for index in range(MAX_ACTIVE_STORIES)
        )
        db.commit()

        main.app.dependency_overrides[get_current_user] = lambda: user
        client = TestClient(main.app)
        resume_response = client.post(
            "/api/resume/versions",
            json={"label": "One more", "resume_text": "B" * 50},
        )
        story_response = client.post("/api/stories", json={"title": "One more"})

        assert resume_response.status_code == 409
        assert story_response.status_code == 409
    finally:
        main.app.dependency_overrides.pop(get_current_user, None)
        db.rollback()
        db.query(ResumeVersion).filter(ResumeVersion.user_id == user.id).delete()
        db.query(InterviewStory).filter(InterviewStory.user_id == user.id).delete()
        db.query(User).filter(User.id == user.id).delete()
        db.commit()
        db.close()
