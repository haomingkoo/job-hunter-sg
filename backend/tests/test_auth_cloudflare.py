from __future__ import annotations

import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from jwt.algorithms import RSAAlgorithm

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import auth


TEAM_DOMAIN = "https://example.cloudflareaccess.com"
AUDIENCE = "example-audience"


class _JwksResponse:
    def __init__(self, keys: list[dict]):
        self._keys = keys

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return {"keys": self._keys}


def _key_pair(kid: str):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = RSAAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    jwk.update({"kid": kid, "alg": "RS256", "use": "sig"})
    return private_key, jwk


def _assertion(private_key, kid: str, **claim_overrides) -> str:
    claims = {
        "iss": TEAM_DOMAIN,
        "aud": [AUDIENCE],
        "email": "person@example.com",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
    }
    claims.update(claim_overrides)
    return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": kid})


@pytest.fixture(autouse=True)
def cloudflare_config(monkeypatch):
    monkeypatch.setenv("CF_ACCESS_TEAM_DOMAIN", TEAM_DOMAIN)
    monkeypatch.setenv("CF_ACCESS_AUD", AUDIENCE)
    monkeypatch.setattr(auth, "AUTH_MODE", "cloudflare")
    auth._CF_JWKS_CACHE.clear()
    auth._CF_JWKS_NEXT_MISS_REFRESH.clear()


def test_email_header_alone_is_never_trusted(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://production.example/app")

    with pytest.raises(HTTPException) as exc_info:
        auth.get_current_user(
            authorization=f"Bearer {auth.create_token(1)}",
            cf_access_email="attacker@example.com",
            cf_access_assertion=None,
            db=object(),
        )

    assert exc_info.value.status_code == 401


def test_cloudflare_headers_fail_closed_when_configuration_is_missing(monkeypatch):
    monkeypatch.delenv("CF_ACCESS_AUD")

    with pytest.raises(HTTPException) as exc_info:
        auth.get_optional_user(
            authorization=f"Bearer {auth.create_token(1)}",
            cf_access_email=None,
            cf_access_assertion="not-a-jwt",
            db=object(),
        )

    assert exc_info.value.status_code == 401


def test_valid_assertion_uses_signed_email_and_caches_matching_key(monkeypatch):
    private_key, jwk = _key_pair("key-1")
    requests = []

    def fake_get(url, timeout):
        requests.append((url, timeout))
        return _JwksResponse([jwk])

    created = []
    monkeypatch.setattr(auth.requests, "get", fake_get)
    monkeypatch.setattr(
        auth,
        "_get_cf_user",
        lambda email, db: created.append((email, db)) or "signed-in-user",
    )
    assertion = _assertion(private_key, "key-1")

    first = auth.get_current_user(
        authorization=None,
        cf_access_email="person@example.com",
        cf_access_assertion=assertion,
        db="db",
    )
    second = auth.get_current_user(
        authorization=None,
        cf_access_email="PERSON@example.com",
        cf_access_assertion=assertion,
        db="db",
    )

    assert first == second == "signed-in-user"
    assert created == [("person@example.com", "db"), ("person@example.com", "db")]
    assert requests == [(f"{TEAM_DOMAIN}/cdn-cgi/access/certs", 5)]


def test_unknown_kid_refreshes_cached_jwks_for_key_rotation(monkeypatch):
    first_private_key, first_jwk = _key_pair("key-1")
    second_private_key, second_jwk = _key_pair("key-2")
    responses = iter([_JwksResponse([first_jwk]), _JwksResponse([second_jwk])])
    request_count = 0

    def fake_get(url, timeout):
        nonlocal request_count
        request_count += 1
        return next(responses)

    monkeypatch.setattr(auth.requests, "get", fake_get)

    assert auth._validate_cloudflare_assertion(
        _assertion(first_private_key, "key-1"), "person@example.com"
    ) == "person@example.com"
    assert auth._validate_cloudflare_assertion(
        _assertion(second_private_key, "key-2"), "person@example.com"
    ) == "person@example.com"
    assert request_count == 2

    with pytest.raises(HTTPException):
        auth._validate_cloudflare_assertion(
            _assertion(first_private_key, "unknown-key"), "person@example.com"
        )
    assert request_count == 2


def test_concurrent_jwks_refresh_fails_fast_instead_of_parking_workers(monkeypatch):
    _, jwk = _key_pair("key-1")
    fetch_started = threading.Event()
    release_fetch = threading.Event()
    fetch_count = 0

    def blocked_fetch(_team_domain):
        nonlocal fetch_count
        fetch_count += 1
        fetch_started.set()
        assert release_fetch.wait(5)
        auth._CF_JWKS_CACHE[TEAM_DOMAIN] = (auth.time.monotonic() + 300, [jwk])
        return [jwk]

    monkeypatch.setattr(auth, "_fetch_cloudflare_jwks", blocked_fetch)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(auth._cloudflare_signing_key, TEAM_DOMAIN, "key-1")
        assert fetch_started.wait(5)
        second = pool.submit(auth._cloudflare_signing_key, TEAM_DOMAIN, "key-1")
        try:
            with pytest.raises(auth.CloudflareJwksUnavailable, match="refreshing"):
                second.result(timeout=1)
        finally:
            release_fetch.set()
        assert first.result(timeout=5) is not None

    assert fetch_count == 1


def test_jwks_refresh_unavailability_is_temporary_not_invalid_auth(monkeypatch):
    private_key, _ = _key_pair("key-1")
    fetch_count = 0

    def offline(_team_domain):
        nonlocal fetch_count
        fetch_count += 1
        raise auth.requests.ConnectionError("offline")

    monkeypatch.setattr(
        auth,
        "_fetch_cloudflare_jwks",
        offline,
    )

    with pytest.raises(HTTPException) as exc_info:
        auth._validate_cloudflare_assertion(
            _assertion(private_key, "key-1"), "person@example.com"
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.headers == {"Retry-After": "2"}
    with pytest.raises(auth.CloudflareJwksUnavailable):
        auth._cloudflare_signing_key(TEAM_DOMAIN, "key-1")
    assert fetch_count == 1


def test_cold_unknown_kid_uses_refresh_cooldown(monkeypatch):
    _, trusted_jwk = _key_pair("trusted-key")
    fetch_count = 0

    def fetch(_team_domain):
        nonlocal fetch_count
        fetch_count += 1
        auth._CF_JWKS_CACHE[TEAM_DOMAIN] = (
            auth.time.monotonic() + 300,
            [trusted_jwk],
        )
        return [trusted_jwk]

    monkeypatch.setattr(auth, "_fetch_cloudflare_jwks", fetch)

    for _ in range(2):
        with pytest.raises(ValueError, match="No matching"):
            auth._cloudflare_signing_key(TEAM_DOMAIN, "missing-key")

    assert fetch_count == 1

def test_assertion_signed_by_an_untrusted_key_is_rejected(monkeypatch):
    _, trusted_jwk = _key_pair("key-1")
    attacker_private_key, _ = _key_pair("attacker-key")
    monkeypatch.setattr(
        auth.requests, "get", lambda url, timeout: _JwksResponse([trusted_jwk])
    )

    with pytest.raises(HTTPException) as exc_info:
        auth._validate_cloudflare_assertion(
            _assertion(attacker_private_key, "key-1"), "person@example.com"
        )

    assert exc_info.value.status_code == 401


@pytest.mark.parametrize(
    "claim_overrides",
    [
        {"iss": "https://attacker.example"},
        {"aud": ["wrong-audience"]},
        {"email": "other@example.com"},
    ],
)
def test_invalid_issuer_audience_or_header_email_fails_closed(
    monkeypatch, claim_overrides
):
    private_key, jwk = _key_pair("key-1")
    monkeypatch.setattr(
        auth.requests, "get", lambda url, timeout: _JwksResponse([jwk])
    )

    with pytest.raises(HTTPException) as exc_info:
        auth.get_optional_user(
            authorization=f"Bearer {auth.create_token(1)}",
            cf_access_email="person@example.com",
            cf_access_assertion=_assertion(
                private_key, "key-1", **claim_overrides
            ),
            db=object(),
        )

    assert exc_info.value.status_code == 401


def test_app_jwt_fallback_is_unchanged_without_cloudflare_headers(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_MODE", "password")
    expected_user = type("ExpectedUser", (), {"token_version": 0})()

    class Query:
        def filter(self, _condition):
            return self

        def first(self):
            return expected_user

    class DB:
        def query(self, _model):
            return Query()

    monkeypatch.setattr(auth, "decode_token", lambda token: {"sub": "42", "ver": 0})

    assert auth.get_current_user(
        authorization="Bearer app-token",
        cf_access_email=None,
        cf_access_assertion=None,
        db=DB(),
    ) is expected_user


def test_password_mode_ignores_cloudflare_identity_headers(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_MODE", "password")
    expected_user = object()
    monkeypatch.setattr(auth, "_get_jwt_user", lambda token, db: expected_user)
    monkeypatch.setattr(
        auth,
        "_validate_cloudflare_assertion",
        lambda *_args: pytest.fail("password mode must not use Cloudflare identity"),
    )

    assert auth.get_current_user(
        authorization="Bearer app-token",
        cf_access_email="spoofed@example.com",
        cf_access_assertion="spoofed-assertion",
        db=object(),
    ) is expected_user
    assert auth.get_optional_user(
        authorization="Bearer app-token",
        cf_access_email="spoofed@example.com",
        cf_access_assertion="spoofed-assertion",
        db=object(),
    ) is expected_user


def test_cloudflare_mode_rejects_app_jwt_without_access_assertion(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_MODE", "cloudflare")

    with pytest.raises(HTTPException) as exc_info:
        auth.get_current_user(
            authorization=f"Bearer {auth.create_token(1)}",
            cf_access_email=None,
            cf_access_assertion=None,
            db=object(),
        )

    assert exc_info.value.status_code == 401


def test_cloudflare_identity_never_merges_with_password_account():
    existing = type("ExistingUser", (), {"password_hash": "bcrypt-hash"})()

    class Query:
        def filter(self, _condition):
            return self

        def first(self):
            return existing

    class DB:
        def query(self, _model):
            return Query()

    with pytest.raises(HTTPException) as exc_info:
        auth._get_cf_user("person@example.com", DB())

    assert exc_info.value.status_code == 401


def test_cloudflare_identity_does_not_recreate_a_missing_account():
    class Query:
        def filter(self, _condition):
            return self

        def first(self):
            return None

    class DB:
        def query(self, _model):
            return Query()

        def add(self, _user):
            raise AssertionError("Cloudflare auth must not create accounts implicitly")

    with pytest.raises(HTTPException) as exc_info:
        auth._get_cf_user("deleted@example.com", DB())

    assert exc_info.value.status_code == 401
