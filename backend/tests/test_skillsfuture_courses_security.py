from io import BytesIO
import zipfile

import pytest

import skillsfuture_courses as courses


def _workbook(*files: tuple[str, bytes]) -> bytes:
    content = BytesIO()
    with zipfile.ZipFile(content, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, body in files:
            archive.writestr(name, body)
    return content.getvalue()


@pytest.mark.parametrize(
    "url",
    [
        "http://s3.ap-southeast-1.amazonaws.com/data.xlsx",
        "https://127.0.0.1/data.xlsx",
        "https://s3.ap-southeast-1.amazonaws.com.evil.example/data.xlsx",
        "https://s3.ap-southeast-1.amazonaws.com:8443/data.xlsx",
    ],
)
def test_dataset_download_url_must_use_expected_https_host(url):
    with pytest.raises(ValueError, match="not trusted"):
        courses._validate_download_url(url)


def test_download_rejects_untrusted_url_before_fetch(monkeypatch):
    calls = []

    class PollResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        @staticmethod
        def json():
            return {"code": 0, "data": {"url": "https://127.0.0.1/private.xlsx"}}

    def fake_get(url, **_kwargs):
        calls.append(url)
        return PollResponse()

    monkeypatch.setattr(courses, "_get_with_retries", fake_get)

    with pytest.raises(ValueError, match="not trusted"):
        courses._download_course_rows()
    assert calls == [courses.POLL_URL]


def test_dataset_response_stops_at_byte_limit(monkeypatch):
    class Response:
        headers = {}

        @staticmethod
        def iter_content(chunk_size):
            assert chunk_size == 64 * 1024
            yield b"1234"
            yield b"5678"

    monkeypatch.setattr(courses, "MAX_DOWNLOAD_BYTES", 6)

    with pytest.raises(ValueError, match="too large"):
        courses._read_limited_response(Response())


def test_workbook_rejects_too_many_zip_entries(monkeypatch):
    monkeypatch.setattr(courses, "MAX_XLSX_ENTRIES", 1)
    content = _workbook(("one.xml", b"one"), ("two.xml", b"two"))

    with pytest.raises(ValueError, match="too many files"):
        courses._parse_course_rows(content)


def test_workbook_rejects_excessive_uncompressed_size(monkeypatch):
    monkeypatch.setattr(courses, "MAX_XLSX_UNCOMPRESSED_BYTES", 10)
    content = _workbook(("sheet.xml", b"x" * 20))

    with pytest.raises(ValueError, match="expands beyond"):
        courses._parse_course_rows(content)


def test_workbook_rejects_unsafe_compression_ratio(monkeypatch):
    monkeypatch.setattr(courses, "MAX_XLSX_COMPRESSION_RATIO", 2)
    content = _workbook(("sheet.xml", b"x" * 1024))

    with pytest.raises(ValueError, match="compression ratio"):
        courses._parse_course_rows(content)


def test_concurrent_course_refresh_does_not_block_request_threads(monkeypatch):
    monkeypatch.setattr(courses, "_course_cache", [])
    monkeypatch.setattr(courses, "_last_error", "")
    monkeypatch.setattr(courses, "_last_attempt_ts", 0.0)
    assert courses._refresh_lock.acquire(blocking=False)
    try:
        rows, error = courses.load_courses()
    finally:
        courses._refresh_lock.release()

    assert rows == []
    assert "already in progress" in error
