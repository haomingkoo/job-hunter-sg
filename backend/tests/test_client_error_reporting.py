import logging

from fastapi.testclient import TestClient


def _reset_client_error_rate_limit():
    """_PUBLIC_RATE_LIMITER is a process-wide singleton shared across the
    whole test suite, and FastAPI's TestClient always reports client IP as
    "testclient" -- so every test hitting this endpoint shares one rate-limit
    bucket. Reset the specific key directly rather than assume a clean slate,
    which would make these tests order-dependent and fragile."""
    import main

    main._PUBLIC_RATE_LIMITER._hits.pop("client-error:testclient", None)


def test_client_error_report_logs_and_strips_html():
    """main.py's own logging setup doesn't propagate cleanly to pytest's
    caplog fixture (verified: the log line reaches stdout correctly but
    caplog.records stays empty), so this attaches a handler directly to the
    "jobhunter" logger instead -- the same pattern used successfully for
    test_activity_stream.py's equivalent check."""
    import main

    _reset_client_error_rate_limit()
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    logger = logging.getLogger("jobhunter")
    handler = _Capture()
    logger.addHandler(handler)
    try:
        with TestClient(main.app) as client:
            response = client.post(
                "/api/client-error",
                json={
                    "message": "TypeError: <script>alert(1)</script>Failed to fetch",
                    "stack": "at foo (bar.js:1:1)",
                    "url": "https://jobhunter.kooexperience.com/#team",
                    "user_agent": "Mozilla/5.0 test-agent",
                },
            )
    finally:
        logger.removeHandler(handler)

    assert response.status_code == 204
    assert response.content == b""
    matching = [r for r in records if "CLIENT ERROR" in r.getMessage()]
    assert len(matching) == 1
    logged = matching[0].getMessage()
    assert "<script>" not in logged
    assert "Failed to fetch" in logged
    assert "https://jobhunter.kooexperience.com/#team" in logged
    assert "at foo (bar.js:1:1)" in logged


def test_client_error_report_requires_a_message():
    import main

    _reset_client_error_rate_limit()
    with TestClient(main.app) as client:
        response = client.post("/api/client-error", json={"message": ""})

    assert response.status_code == 422


def test_client_error_report_is_rate_limited_per_ip():
    import main

    _reset_client_error_rate_limit()
    with TestClient(main.app) as client:
        for _ in range(20):
            ok = client.post("/api/client-error", json={"message": "repeat"})
            assert ok.status_code == 204
        limited = client.post("/api/client-error", json={"message": "one too many"})

    assert limited.status_code == 429
    _reset_client_error_rate_limit()
