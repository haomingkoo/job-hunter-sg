from datetime import datetime, timezone


def test_public_job_cutoff_iso_uses_configured_age():
    from job_visibility import public_job_cutoff_iso

    now = datetime(2026, 7, 4, tzinfo=timezone.utc)

    assert public_job_cutoff_iso(60, now).startswith("2026-05-05T00:00:00")
