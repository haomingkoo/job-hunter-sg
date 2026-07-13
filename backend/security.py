"""Small ASGI guards for request bodies."""

from __future__ import annotations

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
        raw_length = dict(scope.get("headers") or []).get(b"content-length", b"")
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
