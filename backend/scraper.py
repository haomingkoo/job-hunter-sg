#!/usr/bin/env python3
"""Fetch and deduplicate jobs from supported Singapore sources."""

import hashlib
import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from urllib.parse import urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

import config as app_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("sg_scraper")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "en-SG,en;q=0.9",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def _normalize_key_part(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _canonical_job_url(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = urlsplit(value.strip())
    except ValueError:
        return value.strip().lower()
    path = re.sub(r"/+$", "", parsed.path or "")
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, "", ""))


def _extract_openings(item: dict) -> int:
    for key in (
        "numberOfVacancies",
        "number_of_vacancies",
        "vacancies",
        "noOfVacancies",
        "numberOfOpenings",
        "openings",
    ):
        value = item.get(key)
        if value in (None, ""):
            continue
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return min(parsed, 10000)
    return 1

@dataclass
class Job:
    title: str
    company: str
    location: str = ""
    salary: str = ""
    source: str = ""
    url: str = ""
    posted_date: str = ""
    employment_type: str = ""
    seniority: str = ""
    description: str = ""
    skills: list = field(default_factory=list)
    agency: str = ""  # For gov jobs
    closing_date: str = ""
    source_posting_id: str = ""
    openings: int = 1
    scraped_at: str = field(default_factory=lambda: datetime.now().isoformat())

    @property
    def dedup_key(self) -> str:
        """Generate a source-aware key that preserves distinct real postings."""
        source = _normalize_key_part(self.source)
        source_id = _normalize_key_part(self.source_posting_id)
        if source and source_id:
            raw = f"source-id|{source}|{source_id}"
            return hashlib.md5(raw.encode()).hexdigest()

        url = _canonical_job_url(self.url)
        if source and url:
            raw = f"url|{source}|{url}"
            return hashlib.md5(raw.encode()).hexdigest()

        raw = "|".join(
            [
                "listing",
                source,
                _normalize_key_part(self.title),
                _normalize_key_part(self.company),
                _normalize_key_part(self.agency),
                _normalize_key_part(self.location),
                _normalize_key_part(self.posted_date),
                _normalize_key_part(self.closing_date),
            ]
        )
        return hashlib.md5(raw.encode()).hexdigest()



class MyCareersFutureScraper:
    """
    Uses the public MCF API at api.mycareersfuture.gov.sg
    This is the same API the website calls internally.
    """
    BASE_URL = "https://api.mycareersfuture.gov.sg/v2/jobs"

    @staticmethod
    def _location(item: dict) -> str:
        """Return a useful job region, not the posting company's office building."""
        address = item.get("address") if isinstance(item.get("address"), dict) else {}
        if address.get("isOverseas"):
            return str(address.get("overseasCountry") or "Overseas").strip()

        company = item.get("postedCompany") if isinstance(item.get("postedCompany"), dict) else {}
        ssic = str(company.get("ssicCode2020") or company.get("ssicCode") or "").strip()
        if ssic.startswith("78"):
            return "Singapore"

        districts = address.get("districts") if isinstance(address.get("districts"), list) else []
        for district in districts:
            if not isinstance(district, dict):
                continue
            region = str(district.get("region") or district.get("location") or "").strip()
            if region:
                return region
        return "Singapore"

    def search(self, keyword: str, limit: int = 20, page: int = 0) -> list[Job]:
        log.info(f"[MCF] Searching for '{keyword}' (limit={limit}, page={page})...")
        jobs = []
        try:
            params = {
                "search": keyword,
                "limit": min(limit, 100),
                "page": page,
                "sortBy": "new_posting_date",
            }
            resp = SESSION.get(self.BASE_URL, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            results = data.get("results", [])
            log.info(f"[MCF] Got {len(results)} results (total: {data.get('total', '?')})")

            for item in results:
                salary_data = item.get("salary") or {}
                salary_min = salary_data.get("minimum")
                salary_max = salary_data.get("maximum")
                # Handle both old format (nested .amount) and new format (direct int)
                if isinstance(salary_min, dict):
                    salary_min = salary_min.get("amount")
                if isinstance(salary_max, dict):
                    salary_max = salary_max.get("amount")
                salary_str = ""
                if salary_min and salary_max:
                    salary_str = f"${int(salary_min):,} - ${int(salary_max):,}"
                elif salary_min:
                    salary_str = f"${int(salary_min):,}+"

                skills = []
                for skill in item.get("skills", []):
                    if isinstance(skill, dict):
                        skills.append(skill.get("skill", ""))
                    elif isinstance(skill, str):
                        skills.append(skill)

                location = self._location(item)

                uuid = item.get("uuid", "")
                title = item.get("title", "Unknown")
                company_name = item.get("postedCompany", {}).get("name", "Unknown")

                # Position levels — now returns [{id: int, position: str}]
                seniority = ""
                pos_levels = item.get("positionLevels", [])
                if pos_levels:
                    first = pos_levels[0]
                    seniority = first.get("position", "") if isinstance(first, dict) else str(first)

                job = Job(
                    title=title,
                    company=company_name,
                    location=location,
                    salary=salary_str,
                    source="MyCareersFuture",
                    url=f"https://www.mycareersfuture.gov.sg/job/{uuid}" if uuid else "",
                    posted_date=item.get("metadata", {}).get("newPostingDate", "") if isinstance(item.get("metadata"), dict) else "",
                    employment_type=_extract_employment_type(item),
                    seniority=seniority,
                    description=_clean_html(item.get("description", "")),
                    skills=skills,
                    source_posting_id=uuid,
                    openings=_extract_openings(item),
                )
                jobs.append(job)

        except requests.exceptions.RequestException as e:
            log.warning(f"[MCF] Request failed: {e}")
        except (KeyError, ValueError, TypeError) as e:
            log.warning(f"[MCF] Parse error: {e}")

        return jobs



class CareersGovScraper:
    """
    Careers@Gov data sourced from OpenGovSG's pre-parsed JSON dump.
    https://github.com/opengovsg/careersgovsg-jobs-data
    Credit: Alwyn Tan @ Open Government Products
    """
    DATA_URL = "https://raw.githubusercontent.com/opengovsg/careersgovsg-jobs-data/main/data/job-listings.json"

    _cached_jobs: list[dict] | None = None
    _cache_time: float = 0

    @classmethod
    def _fetch_data(cls) -> list[dict]:
        """Fetch the full JSON dump, cached for CAREERSGOV_CACHE_TTL_SECONDS."""
        if cls._cached_jobs is not None and (time.time() - cls._cache_time) < app_config.CAREERSGOV_CACHE_TTL_SECONDS:
            return cls._cached_jobs
        log.info("[Careers@Gov] Fetching from OpenGovSG JSON dump...")
        resp = SESSION.get(cls.DATA_URL, timeout=app_config.CAREERSGOV_HTTP_TIMEOUT_SECONDS)
        resp.raise_for_status()
        cls._cached_jobs = resp.json()
        cls._cache_time = time.time()
        log.info(f"[Careers@Gov] Loaded {len(cls._cached_jobs)} jobs")
        return cls._cached_jobs

    @staticmethod
    def _build_url(item: dict) -> str:
        job_id = item.get("jobId", "")
        posting_no = item.get("postingNo", "")
        if job_id and posting_no:
            return f"https://jobs.careers.gov.sg/jobs/hrp/{job_id}/{posting_no}"
        return ""

    @staticmethod
    def _build_description(item: dict) -> str:
        parts = [
            item.get("jobDescription", ""),
            item.get("jobResponsibilities", ""),
            item.get("jobRequirements", ""),
        ]
        combined = "\n\n".join(p.strip() for p in parts if p.strip())
        return _clean_html(combined) if "<" in combined else combined

    @classmethod
    def _detail_payload(cls, item: dict) -> dict:
        payload = dict(item)
        payload["jobDescription"] = cls._build_description(item)
        payload.setdefault("companyName", item.get("agency", "") or "Singapore Public Service")
        payload.setdefault("company", item.get("agency", "") or "Singapore Public Service")
        return payload

    def get_job_detail(self, external_path: str) -> dict:
        """Return one Careers@Gov detail record from the cached OpenGovSG dump."""
        target = (external_path or "").strip()
        if not target:
            return {}
        try:
            target_path = urlsplit(target).path or target
        except ValueError:
            target_path = target

        for item in self._fetch_data():
            job_id = str(item.get("jobId") or "").strip()
            posting_no = str(item.get("postingNo") or "").strip()
            url = self._build_url(item)
            candidates = {
                target_field
                for target_field in (
                    url,
                    urlsplit(url).path if url else "",
                    f"/jobs/hrp/{job_id}/{posting_no}" if job_id and posting_no else "",
                    f"{job_id}/{posting_no}" if job_id and posting_no else "",
                    f"{job_id}:{posting_no}" if job_id and posting_no else "",
                    str(item.get("externalPath") or "").strip(),
                    str(item.get("external_path") or "").strip(),
                    str(item.get("url") or "").strip(),
                )
                if target_field
            }
            if target in candidates or target_path in candidates:
                return self._detail_payload(item)
        return {}

    @staticmethod
    def _parse_timestamp(item: dict, field: str) -> str:
        ts = item.get(field, "")
        if ts:
            try:
                dt = datetime.fromtimestamp(int(ts) / 1000)
                return dt.strftime("%Y-%m-%d")
            except (ValueError, OSError):
                pass
        return ""

    def _to_job(self, item: dict) -> Job:
        posted = self._parse_timestamp(item, "startDate")
        if not posted:
            posted = self._parse_timestamp(item, "closingDate")
        closing = self._parse_timestamp(item, "closingDate")
        job_id = str(item.get("jobId") or "").strip()
        posting_no = str(item.get("postingNo") or "").strip()
        return Job(
            title=(item.get("jobTitle") or "").strip(),
            company="Singapore Public Service",
            location=(item.get("location") or "Singapore").strip(),
            salary="",
            source="Careers@Gov",
            url=self._build_url(item),
            posted_date=posted,
            employment_type=(item.get("workArrangement") or item.get("employmentType") or "Full-time").strip(),
            seniority=item.get("experienceRequired", ""),
            description=self._build_description(item),
            skills=[],
            agency=(item.get("agency") or "").strip(),
            closing_date=closing,
            source_posting_id=":".join(part for part in (job_id, posting_no) if part),
            openings=_extract_openings(item),
        )

    def search(self, keyword: str, limit: int = 20, offset: int = 0) -> list[Job]:
        log.info(f"[Careers@Gov] Searching for '{keyword}' (limit={limit}, offset={offset})...")
        try:
            data = self._fetch_data()
        except Exception as e:
            log.warning(f"[Careers@Gov] Failed to fetch data: {e}")
            return []

        if keyword:
            kw = keyword.lower()
            data = [j for j in data if kw in (j.get("jobTitle") or "").lower()
                    or kw in (j.get("agency") or "").lower()
                    or kw in (j.get("jobDescription") or "").lower()]

        page = data[offset:offset + limit]
        log.info(f"[Careers@Gov] Got {len(page)} results (total matched: {len(data)})")
        return [self._to_job(item) for item in page]

    def fetch_all(self) -> list[Job]:
        """Fetch all jobs in a single call (for full crawl)."""
        try:
            data = self._fetch_data()
        except Exception as e:
            log.warning(f"[Careers@Gov] Failed to fetch data: {e}")
            return []
        log.info(f"[Careers@Gov] Converting {len(data)} jobs...")
        return [self._to_job(item) for item in data]



class SSGSkillsFrameworkAPI:
    """
    Uses the public SSG-WSG Skills Framework API for job role data.
    Base URL: https://public-api.ssg-wsg.sg

    Auth: OAuth2 client_credentials flow.
      1. POST /dp-oauth/oauth/token with Basic auth (base64 client_id:client_secret)
      2. Use Bearer token on all subsequent requests (expires in 3600s)

    Set env vars: SKILLSFUTURE_CLIENTID, SKILLSFUTURE_SECRET
    """
    BASE_URL = "https://public-api.ssg-wsg.sg"
    TOKEN_URL = "https://public-api.ssg-wsg.sg/dp-oauth/oauth/token"

    def __init__(self):
        import base64 as _b64
        self._b64 = _b64
        self._client_id = os.environ.get("SKILLSFUTURE_CLIENTID", os.environ.get("skillsfuture_clientid", ""))
        self._client_secret = os.environ.get("SKILLSFUTURE_SECRET", os.environ.get("skillsfuture_secret", ""))
        self._token: str = ""
        self._token_expiry: float = 0

    def _get_token(self) -> str:
        """Get or refresh OAuth2 access token."""
        if self._token and time.time() < self._token_expiry:
            return self._token
        if not self._client_id or not self._client_secret:
            log.warning("[SSG] No credentials set (SKILLSFUTURE_CLIENTID / SKILLSFUTURE_SECRET)")
            return ""
        try:
            basic = self._b64.b64encode(
                f"{self._client_id}:{self._client_secret}".encode()
            ).decode()
            resp = requests.post(
                self.TOKEN_URL,
                data={"grant_type": "client_credentials"},
                headers={
                    "Authorization": f"Basic {basic}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            self._token = data["access_token"]
            self._token_expiry = time.time() + data.get("expires_in", 3600) - 60
            log.info("[SSG] OAuth2 token acquired")
            return self._token
        except Exception as e:
            # Sanitize error — request may contain Basic auth credentials
            log.warning(f"[SSG] Token request failed: {type(e).__name__}")
            return ""

    def _get_headers(self) -> dict:
        """Build auth headers with Bearer token."""
        token = self._get_token()
        headers = {**HEADERS}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _unwrap(self, data: dict):
        """Unwrap SSG response envelope: {status, data, meta}."""
        if isinstance(data, dict) and "data" in data:
            return data["data"]
        return data

    def search_job_roles(self, keyword: str) -> list[dict]:
        """Search for job roles matching a keyword."""
        log.info(f"[SSG] Searching job roles for '{keyword}'...")
        try:
            resp = SESSION.get(
                f"{self.BASE_URL}/skillsFramework/jobRoles/titles",
                params={"keyword": keyword},
                headers=self._get_headers(),
                timeout=10,
            )
            resp.raise_for_status()
            inner = self._unwrap(resp.json())
            # Response: {jobRoles: [{id, title, AlternativeTitles}, ...]}
            if isinstance(inner, dict) and "jobRoles" in inner:
                results = inner["jobRoles"]
            elif isinstance(inner, list):
                results = inner
            else:
                results = []
            log.info(f"[SSG] Got {len(results)} job role matches")
            return results
        except Exception as e:
            log.warning(f"[SSG] Job roles search failed: {e}")
            return []

    def get_job_role_details(self, role_id: str) -> dict:
        """Get detailed info for a specific job role."""
        try:
            # The list endpoint returns full details including salary and skills
            resp = SESSION.get(
                f"{self.BASE_URL}/skillsFramework/jobRoles",
                headers=self._get_headers(),
                timeout=10,
            )
            resp.raise_for_status()
            inner = self._unwrap(resp.json())
            if isinstance(inner, dict) and "jobRoles" in inner:
                for role in inner["jobRoles"]:
                    if str(role.get("id", "")) == str(role_id):
                        return role
            return {}
        except Exception as e:
            log.warning(f"[SSG] Job role detail failed: {e}")
            return {}

    def get_skills_for_role(self, keyword: str) -> list[str]:
        """Get recommended skills for a job role keyword."""
        roles = self.search_job_roles(keyword)
        all_skills = []
        for role in roles[:3]:
            role_id = role.get("id") or role.get("jobRoleId", "")
            if role_id:
                details = self.get_job_role_details(str(role_id))
                for field in ("skills", "tsc", "ccs"):
                    for s in details.get(field, []):
                        name = ""
                        if isinstance(s, dict):
                            name = s.get("skillName", "") or s.get("name", "") or s.get("title", "")
                        elif isinstance(s, str):
                            name = s
                        if name and name not in all_skills:
                            all_skills.append(name)
        return all_skills



class AdzunaScraper:
    """Adzuna official API — free tier, SG supported."""
    BASE_URL = "https://api.adzuna.com/v1/api/jobs/sg/search/1"

    def search(self, keyword: str, limit: int = 20) -> list[Job]:
        app_id = os.environ.get("ADZUNA_APP_ID", "")
        app_key = os.environ.get("ADZUNA_APP_KEY", "")
        if not app_id or not app_key:
            log.info("[Adzuna] Skipped — ADZUNA_APP_ID/ADZUNA_APP_KEY not set")
            return []
        log.info(f"[Adzuna] Searching for '{keyword}'...")
        jobs = []
        try:
            params = {
                "app_id": app_id,
                "app_key": app_key,
                "what": keyword,
                "results_per_page": min(limit, 50),
                "sort_by": "relevance",
                "content-type": "application/json",
            }
            resp = SESSION.get(self.BASE_URL, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            log.info(f"[Adzuna] Got {len(results)} results (total: {data.get('count', '?')})")

            for item in results:
                salary_min = item.get("salary_min")
                salary_max = item.get("salary_max")
                salary_str = ""
                if salary_min and salary_max:
                    salary_str = f"${int(salary_min):,} - ${int(salary_max):,}"
                elif salary_min:
                    salary_str = f"${int(salary_min):,}+"

                company = item.get("company", {})
                company_name = company.get("display_name", "") if isinstance(company, dict) else str(company)
                location = item.get("location", {})
                loc_name = location.get("display_name", "Singapore") if isinstance(location, dict) else "Singapore"
                category = item.get("category", {})
                cat_label = category.get("label", "") if isinstance(category, dict) else ""

                jobs.append(Job(
                    title=item.get("title", "").replace("<strong>", "").replace("</strong>", ""),
                    company=company_name,
                    location=loc_name,
                    salary=salary_str,
                    source="Adzuna",
                    url=item.get("redirect_url", ""),
                    posted_date=item.get("created", ""),
                    description=item.get("description", "").replace("<strong>", "").replace("</strong>", ""),
                    employment_type=item.get("contract_type", ""),
                    seniority=cat_label,
                    source_posting_id=str(item.get("id") or ""),
                    openings=_extract_openings(item),
                ))

        except requests.exceptions.RequestException as e:
            # Sanitize error — URL contains API credentials as query params
            err_type = type(e).__name__
            err_status = getattr(getattr(e, "response", None), "status_code", "N/A")
            log.warning(f"[Adzuna] Request failed: {err_type} (status={err_status})")
        return jobs



class JoobleScraper:
    """Jooble official API — free, 67+ countries including SG."""

    def search(self, keyword: str, limit: int = 20) -> list[Job]:
        api_key = os.environ.get("JOOBLE_API_KEY", "")
        if not api_key:
            log.info("[Jooble] Skipped — JOOBLE_API_KEY not set")
            return []
        log.info(f"[Jooble] Searching for '{keyword}'...")
        jobs = []
        try:
            resp = SESSION.post(
                f"https://jooble.org/api/{api_key}",
                json={"keywords": keyword, "location": "Singapore", "page": 1},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            results = data.get("jobs", [])
            log.info(f"[Jooble] Got {len(results)} results (total: {data.get('totalCount', '?')})")

            for item in results[:limit]:
                jobs.append(Job(
                    title=item.get("title", ""),
                    company=item.get("company", ""),
                    location=item.get("location", "Singapore"),
                    salary=item.get("salary", ""),
                    source="Jooble",
                    url=item.get("link", ""),
                    posted_date=item.get("updated", ""),
                    description=item.get("snippet", ""),
                    employment_type=item.get("type", ""),
                    source_posting_id=str(item.get("id") or item.get("link") or ""),
                    openings=_extract_openings(item),
                ))

        except requests.exceptions.RequestException as e:
            # Sanitize error — URL contains API key in path
            err_type = type(e).__name__
            err_status = getattr(getattr(e, "response", None), "status_code", "N/A")
            log.warning(f"[Jooble] Request failed: {err_type} (status={err_status})")
        return jobs



class JobAggregator:
    """Aggregates jobs from all sources and deduplicates."""

    SOURCE_MAP = {
        "mcf": ("MyCareersFuture", MyCareersFutureScraper),
        "careersgov": ("Careers@Gov", CareersGovScraper),
        "adzuna": ("Adzuna", AdzunaScraper),
        "jooble": ("Jooble", JoobleScraper),
    }

    def __init__(self):
        self.ssg_api = SSGSkillsFrameworkAPI()

    def search_all(
        self,
        keyword: str,
        sources: Optional[list[str]] = None,
        limit_per_source: int = 20,
        enrich_skills: bool = True,
    ) -> dict:
        """Search across all (or selected) sources, deduplicate, and return results.

        Returns {keyword, total_raw, total_deduped, duplicates_removed,
        ssg_recommended_skills, by_source, jobs}.
        """
        if sources is None:
            sources = list(self.SOURCE_MAP.keys())

        all_jobs: list[Job] = []
        source_counts: dict[str, int] = {}

        for src_key in sources:
            if src_key not in self.SOURCE_MAP:
                log.warning(f"Unknown source: {src_key}. Skipping.")
                continue

            name, scraper_cls = self.SOURCE_MAP[src_key]
            try:
                scraper = scraper_cls()
                if src_key == "careersgov":
                    jobs = scraper.search(keyword, limit=limit_per_source, offset=0)
                else:
                    jobs = scraper.search(keyword, limit=limit_per_source)
                source_counts[name] = len(jobs)
                all_jobs.extend(jobs)
                # Be polite between sources
                time.sleep(0.5)
            except Exception as e:
                log.error(f"[{name}] Scraper crashed: {e}")
                source_counts[name] = 0

        total_raw = len(all_jobs)
        seen_keys: dict[str, Job] = {}
        for job in all_jobs:
            key = job.dedup_key
            if key in seen_keys:
                # Keep the one with more info, merge sources
                existing = seen_keys[key]
                if (len(job.description) > len(existing.description)) or (job.salary and not existing.salary):
                    job.description = job.description or existing.description
                    job.salary = job.salary or existing.salary
                    job.skills = list(set(job.skills + existing.skills))
                    job.source = f"{existing.source}, {job.source}"
                    seen_keys[key] = job
                else:
                    existing.source = f"{existing.source}, {job.source}"
            else:
                seen_keys[key] = job

        deduped_jobs = list(seen_keys.values())

        ssg_skills = []
        if enrich_skills:
            log.info("[SSG] Fetching recommended skills from Skills Framework...")
            ssg_skills = self.ssg_api.get_skills_for_role(keyword)
            if ssg_skills:
                log.info(f"[SSG] Found {len(ssg_skills)} recommended skills for '{keyword}'")

        return {
            "keyword": keyword,
            "searched_at": datetime.now().isoformat(),
            "total_raw": total_raw,
            "total_deduped": len(deduped_jobs),
            "duplicates_removed": total_raw - len(deduped_jobs),
            "ssg_recommended_skills": ssg_skills,
            "by_source": source_counts,
            "jobs": deduped_jobs,
        }


def _extract_employment_type(item: dict) -> str:
    """Extract employment type from MCF API response.

    MCF uses multiple field names across API versions:
    - employmentType (string)
    - employmentTypes (list of dicts with {employmentType: str})
    - employment_type (string)
    """
    emp = item.get("employmentType")
    if isinstance(emp, str) and emp:
        return emp

    emp_list = item.get("employmentTypes", [])
    if isinstance(emp_list, list) and emp_list:
        first = emp_list[0]
        if isinstance(first, dict):
            return first.get("employmentType", "") or first.get("employment_type", "")
        if isinstance(first, str):
            return first

    emp_snake = item.get("employment_type")
    if isinstance(emp_snake, str) and emp_snake:
        return emp_snake

    return ""


def _clean_html(text: str) -> str:
    """Strip HTML tags while preserving paragraph and bullet boundaries."""
    if not text:
        return ""
    soup = BeautifulSoup(text, "html.parser")
    for tag in soup.find_all(["br"]):
        tag.replace_with("\n")
    for tag in soup.find_all(["li"]):
        content = tag.get_text(" ", strip=True)
        tag.replace_with(f"\n- {content}\n")
    for tag in soup.find_all(["p", "div", "section"]):
        content = tag.get_text(" ", strip=True)
        if content:
            tag.replace_with(f"\n{content}\n")
    cleaned = soup.get_text(separator=" ", strip=False)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()
