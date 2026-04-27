import sys
from pathlib import Path

import pytest
from pydantic import ValidationError


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from schemas import ForgotPasswordRequest, ResetPasswordRequest


def test_forgot_password_request_accepts_email():
    req = ForgotPasswordRequest(email="user@example.com")

    assert str(req.email) == "user@example.com"


def test_reset_password_request_requires_reasonable_password():
    with pytest.raises(ValidationError):
        ResetPasswordRequest(token="a" * 40, password="short")


def test_password_reset_hash_is_not_raw_token():
    from main import _password_reset_hash

    token = "sample-reset-token"
    hashed = _password_reset_hash(token)

    assert hashed != token
    assert len(hashed) == 64
    assert hashed == _password_reset_hash(token)
