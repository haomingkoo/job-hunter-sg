from __future__ import annotations

import pytest
from fastapi import HTTPException

from auth import get_current_user, get_optional_user


def test_unsigned_cloudflare_email_header_is_never_authentication():
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(
            authorization=None,
            cf_access_email="victim@example.com",
            db=None,
        )

    assert exc_info.value.status_code == 401
    assert get_optional_user(
        authorization=None,
        cf_access_email="victim@example.com",
        db=None,
    ) is None
