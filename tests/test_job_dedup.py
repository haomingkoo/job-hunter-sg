import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from scraper import Job


def test_dedup_key_uses_source_posting_id_before_title_company():
    first = Job(
        title="Software Engineer",
        company="Example Pte Ltd",
        source="MyCareersFuture",
        source_posting_id="uuid-1",
    )
    second = Job(
        title="Software Engineer",
        company="Example Pte Ltd",
        source="MyCareersFuture",
        source_posting_id="uuid-2",
    )

    assert first.dedup_key != second.dedup_key


def test_dedup_key_collapses_same_source_url_with_tracking_noise():
    first = Job(
        title="Software Engineer",
        company="Example Pte Ltd",
        source="JobStreet",
        url="https://www.jobstreet.com.sg/job/12345?tracking=abc",
    )
    second = Job(
        title="Software Engineer",
        company="Example Pte Ltd",
        source="JobStreet",
        url="https://www.jobstreet.com.sg/job/12345?tracking=xyz#apply",
    )

    assert first.dedup_key == second.dedup_key
