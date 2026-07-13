from __future__ import annotations

import asyncio
import os
import sys
import zipfile
from io import BytesIO

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from starlette.datastructures import Headers, UploadFile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


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


def test_docx_zip_bomb_is_rejected_before_parsing():
    from resume_parser import extract_text_from_docx

    archive_bytes = BytesIO()
    with zipfile.ZipFile(archive_bytes, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", b"A" * (2 * 1024 * 1024))

    with pytest.raises(ValueError, match="compression ratio is unsafe"):
        extract_text_from_docx(archive_bytes.getvalue())


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

    assert client.post("/api/resume/agent/chat", json={"message": "Find jobs"}).status_code == 401
    assert client.get("/api/search", params={"q": "engineer"}).status_code == 401
    assert client.get("/api/jobs/recommended", params={"resume_text": "private resume"}).status_code == 405


def test_saved_resume_and_story_counts_are_bounded():
    import secrets

    from fastapi.testclient import TestClient

    import main
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
            for index in range(main._MAX_ACTIVE_STORIES)
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
