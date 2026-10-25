from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import HTTPException

import auth


def _decode_status(token: str) -> tuple[int, str]:
    with pytest.raises(HTTPException) as exc_info:
        auth.decode_token(token)
    return exc_info.value.status_code, exc_info.value.detail


def test_create_token_round_trips_subject_version_and_future_expiry() -> None:
    token = auth.create_token(42, 7)

    payload = auth.decode_token(token)

    assert payload["sub"] == "42"
    assert payload["ver"] == 7
    assert payload["exp"] > datetime.now(timezone.utc).timestamp()


def test_create_token_signs_with_hs256() -> None:
    token = auth.create_token(42, 7)

    assert jwt.get_unverified_header(token)["alg"] == "HS256"


def test_decode_token_rejects_expired_token_with_expiry_message() -> None:
    past = datetime.now(timezone.utc) - timedelta(seconds=5)
    token = jwt.encode({"sub": "42", "ver": 0, "exp": past}, auth.SECRET_KEY, algorithm="HS256")

    assert _decode_status(token) == (401, "Token has expired")


def test_decode_token_rejects_token_signed_with_another_secret() -> None:
    token = jwt.encode({"sub": "42", "ver": 0}, "x" * 64, algorithm="HS256")

    assert _decode_status(token) == (401, "Invalid token")


def test_decode_token_rejects_algorithm_outside_the_allow_list() -> None:
    token = jwt.encode({"sub": "42", "ver": 0}, auth.SECRET_KEY, algorithm="HS512")

    assert _decode_status(token) == (401, "Invalid token")


def test_decode_token_rejects_unsigned_none_algorithm_token() -> None:
    token = jwt.encode({"sub": "42", "ver": 0}, None, algorithm="none")

    assert _decode_status(token) == (401, "Invalid token")


def test_decode_token_rejects_tampered_payload() -> None:
    header, _payload, signature = auth.create_token(42, 7).split(".")
    forged = jwt.utils.base64url_encode(b'{"sub":"1","ver":7}').decode()

    assert _decode_status(f"{header}.{forged}.{signature}") == (401, "Invalid token")


def test_decode_token_rejects_non_numeric_expiry_as_invalid() -> None:
    token = jwt.encode({"sub": "42", "exp": "soon"}, auth.SECRET_KEY, algorithm="HS256")

    assert _decode_status(token) == (401, "Invalid token")
