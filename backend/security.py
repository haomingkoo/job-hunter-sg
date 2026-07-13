"""Small ASGI security guards shared by public endpoints."""

from __future__ import annotations

import threading
import time
from collections import deque

from starlette.responses import JSONResponse


class RequestTooLarge(Exception):
    pass


class RequestBodyLimitMiddleware:
    def __init__(self, app, default_max_bytes: int, path_limits: dict[str, int] | None = None):
        self.app = app
        self.default_max_bytes = default_max_bytes
        self.path_limits = path_limits or {}

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        limit = self.path_limits.get(scope.get("path", ""), self.default_max_bytes)
        headers = dict(scope.get("headers") or [])
        raw_length = headers.get(b"content-length", b"")
        try:
            content_length = int(raw_length) if raw_length else None
        except ValueError:
            content_length = None
        if content_length is not None and content_length > limit:
            await JSONResponse({"detail": "Request body too large"}, status_code=413)(scope, receive, send)
            return

        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message.get("type") == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise RequestTooLarge
            return message

        try:
            await self.app(scope, limited_receive, send)
        except RequestTooLarge:
            await JSONResponse({"detail": "Request body too large"}, status_code=413)(scope, receive, send)


class SecurityHeadersMiddleware:
    """Add browser hardening headers without buffering response bodies."""

    _CONTENT_SECURITY_POLICY = (
        "default-src 'self'; base-uri 'self'; object-src 'none'; "
        "frame-ancestors 'none'; form-action 'self'; img-src 'self' data: https:; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "script-src 'self' 'unsafe-inline'; connect-src 'self' https:; "
        "font-src 'self' data: https://fonts.gstatic.com"
    ).encode()

    _PRIVATE_PREFIXES = (
        "/api/account",
        "/api/admin",
        "/api/ai",
        "/api/auth",
        "/api/job-alerts",
        "/api/memory",
        "/api/resume",
        "/api/search",
        "/api/skillsfuture",
        "/api/stories",
        "/api/tracked",
        "/api/usage",
    )
    _PRIVATE_JOB_PATHS = ("/api/jobs/power-match", "/api/jobs/recommended")

    def __init__(self, app, hsts: bool = False):
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")

        async def send_with_headers(message):
            if message.get("type") == "http.response.start":
                headers = list(message.get("headers") or [])
                headers.extend(
                    [
                        (b"content-security-policy", self._CONTENT_SECURITY_POLICY),
                        (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
                        (b"referrer-policy", b"no-referrer"),
                        (b"x-content-type-options", b"nosniff"),
                        (b"x-frame-options", b"DENY"),
                    ]
                )
                if self.hsts:
                    headers.append(
                        (b"strict-transport-security", b"max-age=31536000; includeSubDomains")
                    )
                if (
                    path.startswith(self._PRIVATE_PREFIXES)
                    or path in self._PRIVATE_JOB_PATHS
                    or (
                        path.startswith("/api/jobs/")
                        and path.endswith(("/match", "/parsed"))
                    )
                ):
                    headers.append((b"cache-control", b"no-store"))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)


class FixedWindowRateLimiter:
    def __init__(self, max_keys: int = 10_000):
        self._hits: dict[str, deque[float]] = {}
        self._max_keys = max_keys
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window_seconds: int, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        cutoff = current - window_seconds
        with self._lock:
            hits = self._hits.get(key)
            if hits is None:
                if len(self._hits) >= self._max_keys:
                    oldest_key = min(
                        self._hits,
                        key=lambda existing: self._hits[existing][-1],
                    )
                    self._hits.pop(oldest_key, None)
                hits = deque()
                self._hits[key] = hits
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= limit:
                return False
            hits.append(current)
            return True
