#!/usr/bin/env python3
"""
Tests for the CareersGovScraper data mapping after the upstream OpenGovSG
feed unified hrp + greenhouse (GovTech) + workable (PSD) into one JSON dump.
Run: cd backend && python -m pytest tests/test_careersgov_scraper.py -v
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scraper import CareersGovScraper  # noqa: E402


class TestBuildUrl:
    def test_hrp_url(self):
        url = CareersGovScraper._build_url(
            {"platform": "hrp", "jobId": "17039645", "postingNo": "005056a3-d347-1fe1-95b6-5ed7ecd682a7"}
        )
        assert url == "https://jobs.careers.gov.sg/jobs/hrp/17039645/005056a3-d347-1fe1-95b6-5ed7ecd682a7"

    def test_hrp_default_when_platform_missing(self):
        # Older snapshots from before the platform field was added must keep working.
        url = CareersGovScraper._build_url({"jobId": "17039645", "postingNo": "abc"})
        assert url == "https://jobs.careers.gov.sg/jobs/hrp/17039645/abc"

    def test_greenhouse_url(self):
        url = CareersGovScraper._build_url(
            {"platform": "greenhouse", "jobId": "4001978201", "postingNo": ""}
        )
        assert url == "https://job-boards.greenhouse.io/govtech/jobs/4001978201"

    def test_workable_url(self):
        url = CareersGovScraper._build_url(
            {"platform": "workable", "jobId": "psd-sg", "postingNo": "69C959EF15"}
        )
        assert url == "https://apply.workable.com/psd-sg/j/69C959EF15/"

    def test_empty_when_required_ids_missing(self):
        assert CareersGovScraper._build_url({"platform": "hrp", "jobId": "", "postingNo": ""}) == ""
        assert CareersGovScraper._build_url({"platform": "greenhouse", "jobId": ""}) == ""
        assert CareersGovScraper._build_url({"platform": "workable", "jobId": "psd-sg", "postingNo": ""}) == ""

    def test_unknown_platform_returns_empty(self):
        assert CareersGovScraper._build_url({"platform": "linkedin", "jobId": "x", "postingNo": "y"}) == ""


class TestToJob:
    def test_hrp_source_posting_id_unprefixed(self):
        job = CareersGovScraper()._to_job(
            {
                "platform": "hrp",
                "jobId": "17039645",
                "postingNo": "005056a3",
                "jobTitle": "Executive",
                "agency": "Ministry of Transport",
                "jobDescription": "Plain text.",
            }
        )
        # Unprefixed so dedup_keys for the 2k+ existing HRP rows stay stable.
        assert job.source_posting_id == "17039645:005056a3"
        assert job.source == "Careers@Gov"
        assert job.agency == "Ministry of Transport"
        assert job.url.endswith("/jobs/hrp/17039645/005056a3")

    def test_greenhouse_source_posting_id_prefixed(self):
        job = CareersGovScraper()._to_job(
            {
                "platform": "greenhouse",
                "jobId": "4001978201",
                "postingNo": "",
                "jobTitle": "Assistant Director",
                "agency": "Government Technology Agency",
                "jobDescription": "<p>HTML body.</p>",
                "location": "Singapore",
            }
        )
        assert job.source_posting_id == "greenhouse:4001978201"
        assert job.agency == "Government Technology Agency"
        assert job.url == "https://job-boards.greenhouse.io/govtech/jobs/4001978201"
        # HTML stripped for storage.
        assert "<p>" not in job.description

    def test_workable_source_posting_id_prefixed(self):
        # Workable jobs all share jobId="psd-sg" — prefix is what prevents collision.
        job_a = CareersGovScraper()._to_job(
            {
                "platform": "workable",
                "jobId": "psd-sg",
                "postingNo": "69C959EF15",
                "jobTitle": "Assistant Director, ServiceSG",
                "agency": "Public Service Division",
                "jobDescription": "<p>Body.</p>",
            }
        )
        job_b = CareersGovScraper()._to_job(
            {
                "platform": "workable",
                "jobId": "psd-sg",
                "postingNo": "8FCA50DA02",
                "jobTitle": "Other Role",
                "agency": "Public Service Division",
                "jobDescription": "<p>Body.</p>",
            }
        )
        assert job_a.source_posting_id == "workable:psd-sg:69C959EF15"
        assert job_b.source_posting_id == "workable:psd-sg:8FCA50DA02"
        assert job_a.dedup_key != job_b.dedup_key
        assert job_a.url == "https://apply.workable.com/psd-sg/j/69C959EF15/"

    def test_null_closing_date_handled(self):
        # Greenhouse/Workable entries now report closingDate: null when no deadline.
        job = CareersGovScraper()._to_job(
            {
                "platform": "greenhouse",
                "jobId": "4001978201",
                "postingNo": "",
                "jobTitle": "Role",
                "agency": "Government Technology Agency",
                "jobDescription": "Body.",
                "closingDate": None,
                "startDate": 1776924763000,
            }
        )
        assert job.closing_date == ""
        assert job.posted_date  # parsed from startDate
