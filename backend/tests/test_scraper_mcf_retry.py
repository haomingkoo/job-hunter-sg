import pytest
import requests

import scraper
from scraper import MyCareersFutureScraper


class _Response:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {"results": [{"uuid": "job-1", "title": "Data Engineer"}], "total": 1}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"{self.status_code} error", response=self)

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(scraper.time, "sleep", lambda _seconds: None)


def _session_returning(monkeypatch, outcomes):
    calls = []

    def fake_get(*_args, **_kwargs):
        calls.append(1)
        outcome = outcomes[len(calls) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(scraper.SESSION, "get", fake_get)
    return calls


def test_mcf_search_retries_a_read_timeout(monkeypatch):
    calls = _session_returning(monkeypatch, [requests.exceptions.ReadTimeout("read timed out"), _Response()])

    jobs = MyCareersFutureScraper().search("", limit=100, page=521)

    assert [job.source_posting_id for job in jobs] == ["job-1"]
    assert len(calls) == 2


def test_mcf_search_retries_a_server_error(monkeypatch):
    calls = _session_returning(monkeypatch, [_Response(status_code=503), _Response()])

    jobs = MyCareersFutureScraper().search("", limit=100, page=3)

    assert len(jobs) == 1
    assert len(calls) == 2


def test_mcf_search_gives_up_after_repeated_timeouts(monkeypatch):
    calls = _session_returning(monkeypatch, [requests.exceptions.ReadTimeout("read timed out")] * 10)

    assert MyCareersFutureScraper().search("", limit=100, page=7) == []
    assert len(calls) == scraper.MCF_REQUEST_ATTEMPTS


def test_mcf_search_does_not_retry_a_client_error(monkeypatch):
    calls = _session_returning(monkeypatch, [_Response(status_code=400), _Response()])

    assert MyCareersFutureScraper().search("", limit=100, page=0) == []
    assert len(calls) == 1
