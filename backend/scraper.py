#!/usr/bin/env python3
"""
SG Job Scraper — Singapore Job Aggregator
==========================================
Scrapes / queries multiple Singapore job portals:
  1. MyCareersFuture  (MCF public API)
  2. Careers@Gov 2.0  (Workday-powered backend)
  3. SSG-WSG Skills Framework API (job roles + skills data)
  4. NodeFlair        (HTML scrape)
  5. Indeed SG        (HTML scrape)
  6. JobStreet SG     (HTML scrape)

Features:
  - Uses APIs where available, falls back to scraping
  - Deduplicates across all sources
  - Exports to JSON and CSV
  - CLI with keyword search

Requirements:
  pip install requests beautifulsoup4

Usage:
  python sg_job_scraper.py "software engineer"
  python sg_job_scraper.py "data analyst" --sources mcf,careersgov
  python sg_job_scraper.py "react developer" --limit 50 --output jobs.csv
"""

import argparse
import csv
import hashlib
import json
import logging
import os
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Optional
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

# ─── Configuration ──────────────────────────────────────────────────────────────

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


# ─── Data Model ─────────────────────────────────────────────────────────────────

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
    scraped_at: str = field(default_factory=lambda: datetime.now().isoformat())

    @property
    def dedup_key(self) -> str:
        """Generate a key for deduplication based on title + company."""
        raw = f"{self.title.lower().strip()}|{self.company.lower().strip()}"
        return hashlib.md5(raw.encode()).hexdigest()


# ═══════════════════════════════════════════════════════════════════════════════
# SOURCE 1: MyCareersFuture (MCF) — Public API
# ═══════════════════════════════════════════════════════════════════════════════

class MyCareersFutureScraper:
    """
    Uses the public MCF API at api.mycareersfuture.gov.sg
    This is the same API the website calls internally.
    """
    BASE_URL = "https://api.mycareersfuture.gov.sg/v2/jobs"

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
                # Salary — API now returns {minimum: int, maximum: int} directly
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

                # Extract skills from metadata
                skills = []
                for skill in item.get("skills", []):
                    if isinstance(skill, dict):
                        skills.append(skill.get("skill", ""))
                    elif isinstance(skill, str):
                        skills.append(skill)

                # Extract location — build from address fields
                location_data = item.get("address") or {}
                location = ""
                if isinstance(location_data, dict):
                    street = location_data.get("street", "")
                    building = location_data.get("building", "")
                    block = location_data.get("block", "")
                    location = building or street or (f"Blk {block}" if block else "")
                elif isinstance(location_data, str):
                    location = location_data

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
                    location=location or "Singapore",
                    salary=salary_str,
                    source="MyCareersFuture",
                    url=f"https://www.mycareersfuture.gov.sg/job/{uuid}" if uuid else "",
                    posted_date=item.get("metadata", {}).get("newPostingDate", "") if isinstance(item.get("metadata"), dict) else "",
                    employment_type=_extract_employment_type(item),
                    seniority=seniority,
                    description=_clean_html(item.get("description", "")),
                    skills=skills,
                )
                jobs.append(job)

        except requests.exceptions.RequestException as e:
            log.warning(f"[MCF] Request failed: {e}")
        except (KeyError, ValueError, TypeError) as e:
            log.warning(f"[MCF] Parse error: {e}")

        return jobs


# ═══════════════════════════════════════════════════════════════════════════════
# SOURCE 2: Careers@Gov 2.0 (Workday backend)
# ═══════════════════════════════════════════════════════════════════════════════

class CareersGovScraper:
    """
    Careers@Gov 2.0 is powered by Workday (sggovterp.wd102.myworkdayjobs.com).
    We can hit Workday's public job search endpoint.
    """
    BASE_URL = "https://sggovterp.wd102.myworkdayjobs.com/wday/cxs/sggovterp/PublicServiceCareers/jobs"

    @staticmethod
    def _extract_skills_from_detail(detail: dict) -> list[str]:
        skills: list[str] = []
        for tag_section in detail.get("skillTags", []):
            if isinstance(tag_section, str):
                skills.append(tag_section)
            elif isinstance(tag_section, dict):
                value = tag_section.get("name", "")
                if value:
                    skills.append(value)
        if not skills:
            tag_line = detail.get("tagLine", "")
            if tag_line:
                skills = [s.strip() for s in tag_line.split(",") if s.strip()]
        deduped: list[str] = []
        seen: set[str] = set()
        for skill in skills:
            normalized = re.sub(r"\s+", " ", (skill or "").strip())
            lowered = normalized.lower()
            if not normalized or lowered in seen:
                continue
            seen.add(lowered)
            deduped.append(normalized)
        return deduped

    def search(self, keyword: str, limit: int = 20, offset: int = 0) -> list[Job]:
        log.info(f"[Careers@Gov] Searching for '{keyword}' (limit={limit})...")
        jobs = []
        try:
            payload = {
                "appliedFacets": {},
                "limit": min(limit, 20),
                "offset": offset,
                "searchText": keyword,
            }
            headers = {
                **HEADERS,
                "Content-Type": "application/json",
            }
            resp = SESSION.post(self.BASE_URL, json=payload, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            results = data.get("jobPostings", [])
            total = data.get("total", 0)
            log.info(f"[Careers@Gov] Got {len(results)} results (total: {total})")

            for item in results:
                title = item.get("title", "")
                external_path = item.get("externalPath", "")
                url = f"https://sggovterp.wd102.myworkdayjobs.com/en-US/PublicServiceCareers{external_path}" if external_path else ""

                # Workday API fields:
                # - locationsText: actual office location (e.g. "Paya Lebar Quarter")
                # - postedOn: posted date string (e.g. "Posted 30+ Days Ago")
                # - bulletFields: just the job requisition ID
                location = item.get("locationsText", "") or "Singapore"
                posted = item.get("postedOn", "")
                description = ""
                skills: list[str] = []
                agency = location

                if external_path:
                    detail = self.get_job_detail(external_path)
                    if detail:
                        description = _clean_html(detail.get("jobDescription", ""))
                        skills = self._extract_skills_from_detail(detail)
                        company_name = detail.get("companyName", "") or detail.get("company", "")
                        if company_name:
                            agency = company_name

                job = Job(
                    title=title,
                    company="Singapore Public Service",
                    location=location,
                    salary="",
                    source="Careers@Gov",
                    url=url,
                    posted_date=posted,
                    employment_type="Full-time",
                    seniority="",
                    description=description,
                    skills=skills,
                    agency=agency,
                )
                jobs.append(job)

        except requests.exceptions.RequestException as e:
            log.warning(f"[Careers@Gov] Request failed: {e}")
        except (KeyError, ValueError, TypeError) as e:
            log.warning(f"[Careers@Gov] Parse error: {e}")

        return jobs

    def get_job_detail(self, external_path: str) -> dict:
        """Fetch full job details from individual job page."""
        try:
            url = f"https://sggovterp.wd102.myworkdayjobs.com/wday/cxs/sggovterp/PublicServiceCareers{external_path}"
            resp = SESSION.get(url, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            return data.get("jobPostingInfo", {})
        except Exception as e:
            log.warning(f"[Careers@Gov] Detail fetch failed: {e}")
            return {}


# ═══════════════════════════════════════════════════════════════════════════════
# SOURCE 3: SSG-WSG Skills Framework API
# ═══════════════════════════════════════════════════════════════════════════════

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
                # Extract skills from various possible fields
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


# ═══════════════════════════════════════════════════════════════════════════════
# SOURCE 4: NodeFlair (HTML Scrape)
# ═══════════════════════════════════════════════════════════════════════════════

class NodeFlairScraper:
    """Scrapes NodeFlair for tech jobs with salary data."""
    BASE_URL = "https://www.nodeflair.com/jobs"

    def search(self, keyword: str, limit: int = 20) -> list[Job]:
        log.info(f"[NodeFlair] Searching for '{keyword}'...")
        jobs = []
        try:
            params = {"query": keyword, "page": 1}
            resp = SESSION.get(self.BASE_URL, params=params, timeout=15)
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "html.parser")
            cards = soup.select('[class*="jobListingCard"], [class*="job-card"], .listingCard, article')

            if not cards:
                # Try finding job items by common patterns
                cards = soup.find_all("div", {"data-testid": re.compile(r"job", re.I)})
                if not cards:
                    cards = soup.find_all("a", href=re.compile(r"/jobs/"))

            log.info(f"[NodeFlair] Found {len(cards)} cards")

            for card in cards[:limit]:
                try:
                    # Try multiple selectors for title
                    title_el = (
                        card.select_one('[class*="title"], h2, h3') or
                        card.find("a", href=re.compile(r"/jobs/"))
                    )
                    title = title_el.get_text(strip=True) if title_el else ""
                    if not title:
                        continue

                    company_el = card.select_one('[class*="company"], [class*="Company"]')
                    company = company_el.get_text(strip=True) if company_el else ""

                    salary_el = card.select_one('[class*="salary"], [class*="Salary"]')
                    salary = salary_el.get_text(strip=True) if salary_el else ""

                    link_el = card.find("a", href=True)
                    href = link_el["href"] if link_el else ""
                    url = f"https://www.nodeflair.com{href}" if href and not href.startswith("http") else href

                    job = Job(
                        title=title,
                        company=company,
                        location="Singapore",
                        salary=salary,
                        source="NodeFlair",
                        url=url,
                    )
                    if job.title:
                        jobs.append(job)
                except Exception:
                    continue

        except requests.exceptions.RequestException as e:
            log.warning(f"[NodeFlair] Request failed: {e}")

        return jobs


# ═══════════════════════════════════════════════════════════════════════════════
# SOURCE 5: Indeed SG (HTML Scrape)
# ═══════════════════════════════════════════════════════════════════════════════

class IndeedSGScraper:
    """Scrapes Indeed Singapore for job listings."""
    BASE_URL = "https://sg.indeed.com/jobs"

    def search(self, keyword: str, limit: int = 20) -> list[Job]:
        log.info(f"[Indeed SG] Searching for '{keyword}'...")
        jobs = []
        try:
            params = {"q": keyword, "l": "Singapore", "limit": min(limit, 50)}
            resp = SESSION.get(self.BASE_URL, params=params, timeout=15)
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "html.parser")

            # Indeed uses various class patterns
            cards = soup.select(".job_seen_beacon, .jobsearch-ResultsList .result, .tapItem, [data-jk]")
            log.info(f"[Indeed SG] Found {len(cards)} cards")

            for card in cards[:limit]:
                try:
                    title_el = card.select_one("h2 a, .jobTitle a, [class*='jobTitle'] a, h2 span")
                    title = title_el.get_text(strip=True) if title_el else ""
                    if not title:
                        title_el = card.select_one("h2, .jobTitle, [class*='jobTitle']")
                        title = title_el.get_text(strip=True) if title_el else ""

                    company_el = card.select_one("[data-testid='company-name'], .companyName, [class*='company']")
                    company = company_el.get_text(strip=True) if company_el else ""

                    location_el = card.select_one("[data-testid='text-location'], .companyLocation, [class*='location']")
                    location = location_el.get_text(strip=True) if location_el else "Singapore"

                    salary_el = card.select_one("[class*='salary'], .salary-snippet, [data-testid='attribute_snippet_testid']")
                    salary = salary_el.get_text(strip=True) if salary_el else ""

                    # Get job URL
                    link_el = card.select_one("h2 a, .jobTitle a, a[data-jk]")
                    href = link_el.get("href", "") if link_el else ""
                    url = f"https://sg.indeed.com{href}" if href and not href.startswith("http") else href

                    snippet_el = card.select_one(".job-snippet, [class*='snippet']")
                    desc = snippet_el.get_text(strip=True) if snippet_el else ""

                    if title:
                        jobs.append(Job(
                            title=title,
                            company=company,
                            location=location,
                            salary=salary,
                            source="Indeed SG",
                            url=url,
                            description=desc,
                        ))
                except Exception:
                    continue

        except requests.exceptions.RequestException as e:
            log.warning(f"[Indeed SG] Request failed: {e}")

        return jobs


# ═══════════════════════════════════════════════════════════════════════════════
# SOURCE 6: JobStreet SG (HTML Scrape)
# ═══════════════════════════════════════════════════════════════════════════════

class JobStreetScraper:
    """Scrapes JobStreet Singapore for job listings."""
    BASE_URL = "https://www.jobstreet.com.sg"

    def search(self, keyword: str, limit: int = 20) -> list[Job]:
        log.info(f"[JobStreet] Searching for '{keyword}'...")
        jobs = []
        try:
            url = f"{self.BASE_URL}/jobs/{quote_plus(keyword)}-jobs"
            resp = SESSION.get(url, timeout=15)
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "html.parser")

            # JobStreet uses data attributes and article tags
            cards = soup.select("article[data-search-sol-meta], [data-testid*='job-card'], article")
            if not cards:
                # Try script tag with JSON data
                scripts = soup.find_all("script", type="application/json")
                for script in scripts:
                    try:
                        data = json.loads(script.string)
                        self._extract_from_json(data, jobs, limit)
                    except (json.JSONDecodeError, TypeError):
                        continue

            log.info(f"[JobStreet] Found {len(cards)} cards")

            for card in cards[:limit]:
                try:
                    title_el = card.select_one("h1 a, h3 a, [data-automation='jobTitle'] a, [class*='title'] a")
                    if not title_el:
                        title_el = card.select_one("h1, h3, [data-automation='jobTitle'], [class*='title']")
                    title = title_el.get_text(strip=True) if title_el else ""

                    company_el = card.select_one("[data-automation='jobCompany'], [class*='company']")
                    company = company_el.get_text(strip=True) if company_el else ""

                    location_el = card.select_one("[data-automation='jobLocation'], [class*='location']")
                    location = location_el.get_text(strip=True) if location_el else "Singapore"

                    salary_el = card.select_one("[data-automation='jobSalary'], [class*='salary']")
                    salary = salary_el.get_text(strip=True) if salary_el else ""

                    link_el = card.select_one("a[href*='/job/'], h1 a, h3 a")
                    href = link_el.get("href", "") if link_el else ""
                    full_url = href if href.startswith("http") else f"{self.BASE_URL}{href}" if href else ""

                    if title:
                        jobs.append(Job(
                            title=title,
                            company=company,
                            location=location,
                            salary=salary,
                            source="JobStreet",
                            url=full_url,
                        ))
                except Exception:
                    continue

        except requests.exceptions.RequestException as e:
            log.warning(f"[JobStreet] Request failed: {e}")

        return jobs

    def _extract_from_json(self, data, jobs: list, limit: int, _depth: int = 0):
        """Try to extract jobs from embedded JSON data."""
        if _depth > 5:  # Guard against deeply nested / malicious JSON
            return
        if isinstance(data, dict):
            for key, val in data.items():
                if key in ("jobs", "jobCards", "data") and isinstance(val, list):
                    for item in val[:limit]:
                        if isinstance(item, dict) and ("title" in item or "jobTitle" in item):
                            jobs.append(Job(
                                title=item.get("title") or item.get("jobTitle", ""),
                                company=item.get("company", {}).get("name", "") if isinstance(item.get("company"), dict) else item.get("company", ""),
                                location=item.get("location", "Singapore"),
                                salary=item.get("salary", ""),
                                source="JobStreet",
                                url=item.get("url", item.get("jobUrl", "")),
                            ))
                elif isinstance(val, dict):
                    self._extract_from_json(val, jobs, limit, _depth + 1)


# ═══════════════════════════════════════════════════════════════════════════════
# SOURCE 7: Adzuna API (Official — free tier at developer.adzuna.com)
# ═══════════════════════════════════════════════════════════════════════════════

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
                ))

        except requests.exceptions.RequestException as e:
            # Sanitize error — URL contains API credentials as query params
            err_type = type(e).__name__
            err_status = getattr(getattr(e, "response", None), "status_code", "N/A")
            log.warning(f"[Adzuna] Request failed: {err_type} (status={err_status})")
        return jobs


# ═══════════════════════════════════════════════════════════════════════════════
# SOURCE 8: Jooble API (Official — free at jooble.org/api/about)
# ═══════════════════════════════════════════════════════════════════════════════

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
                ))

        except requests.exceptions.RequestException as e:
            # Sanitize error — URL contains API key in path
            err_type = type(e).__name__
            err_status = getattr(getattr(e, "response", None), "status_code", "N/A")
            log.warning(f"[Jooble] Request failed: {err_type} (status={err_status})")
        return jobs


# ═══════════════════════════════════════════════════════════════════════════════
# AGGREGATOR — Combines all sources with deduplication
# ═══════════════════════════════════════════════════════════════════════════════

class JobAggregator:
    """Aggregates jobs from all sources and deduplicates."""

    SOURCE_MAP = {
        # API-based sources (reliable)
        "mcf": ("MyCareersFuture", MyCareersFutureScraper),
        "careersgov": ("Careers@Gov", CareersGovScraper),
        "adzuna": ("Adzuna", AdzunaScraper),
        "jooble": ("Jooble", JoobleScraper),
        # HTML scrapers — may be blocked (403) by the target site
        "nodeflair": ("NodeFlair", NodeFlairScraper),
        "indeed": ("Indeed SG", IndeedSGScraper),
        "jobstreet": ("JobStreet SG", JobStreetScraper),
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
        """
        Search across all (or selected) sources, deduplicate, and return results.

        Returns dict with:
            keyword, total_raw, total_deduped, duplicates_removed,
            ssg_recommended_skills, by_source, jobs
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

        # ── Deduplication ───────────────────────────────────────────────────
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

        # ── Enrich with SSG Skills Framework ────────────────────────────────
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


# ─── Export helpers ─────────────────────────────────────────────────────────────

def export_json(results: dict, filepath: str):
    """Export results to JSON file."""
    output = {
        **{k: v for k, v in results.items() if k != "jobs"},
        "jobs": [asdict(j) for j in results["jobs"]],
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    log.info(f"Saved {len(results['jobs'])} jobs to {filepath}")


def export_csv(results: dict, filepath: str):
    """Export results to CSV file."""
    if not results["jobs"]:
        log.warning("No jobs to export.")
        return

    fields = [
        "title", "company", "location", "salary", "source", "url",
        "posted_date", "employment_type", "seniority", "skills",
        "description", "agency", "scraped_at",
    ]
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for job in results["jobs"]:
            row = asdict(job)
            row["skills"] = "; ".join(row["skills"]) if row["skills"] else ""
            if len(row.get("description", "")) > 500:
                row["description"] = row["description"][:500] + "..."
            row.pop("dedup_key", None)
            writer.writerow(row)
    log.info(f"Saved {len(results['jobs'])} jobs to {filepath}")


def _extract_employment_type(item: dict) -> str:
    """Extract employment type from MCF API response.

    MCF uses multiple field names across API versions:
    - employmentType (string)
    - employmentTypes (list of dicts with {employmentType: str})
    - employment_type (string)
    """
    # Try singular string first
    emp = item.get("employmentType")
    if isinstance(emp, str) and emp:
        return emp

    # Try plural list: [{employmentType: "Full Time", ...}]
    emp_list = item.get("employmentTypes", [])
    if isinstance(emp_list, list) and emp_list:
        first = emp_list[0]
        if isinstance(first, dict):
            return first.get("employmentType", "") or first.get("employment_type", "")
        if isinstance(first, str):
            return first

    # Try snake_case
    emp_snake = item.get("employment_type")
    if isinstance(emp_snake, str) and emp_snake:
        return emp_snake

    return ""


def _clean_html(text: str) -> str:
    """Strip HTML tags from text."""
    if not text:
        return ""
    soup = BeautifulSoup(text, "html.parser")
    return soup.get_text(separator=" ", strip=True)


def print_summary(results: dict):
    """Print a nice summary to terminal."""
    print("\n" + "=" * 70)
    print(f"  SG JOB SCRAPER — Results for '{results['keyword']}'")
    print("=" * 70)
    print(f"  Searched at: {results['searched_at']}")
    print(f"  Total raw results:   {results['total_raw']}")
    print(f"  After dedup:         {results['total_deduped']}")
    print(f"  Duplicates removed:  {results['duplicates_removed']}")
    print()
    print("  Results by source:")
    for src, count in results["by_source"].items():
        print(f"    {src:20s} {count:>4} jobs")
    print()

    if results["ssg_recommended_skills"]:
        print("  SSG Skills Framework — Recommended skills for this role:")
        skills_str = ", ".join(results["ssg_recommended_skills"][:15])
        print(f"    {skills_str}")
        if len(results["ssg_recommended_skills"]) > 15:
            print(f"    ... and {len(results['ssg_recommended_skills']) - 15} more")
        print()

    print("  Top jobs:")
    print(f"  {'Title':<35} {'Company':<25} {'Source':<20} {'Salary'}")
    print("  " + "-" * 100)
    for job in results["jobs"][:25]:
        title = job.title[:33] + ".." if len(job.title) > 35 else job.title
        company = job.company[:23] + ".." if len(job.company) > 25 else job.company
        source = job.source[:18] + ".." if len(job.source) > 20 else job.source
        salary = job.salary[:20] if job.salary else "-"
        print(f"  {title:<35} {company:<25} {source:<20} {salary}")

    if len(results["jobs"]) > 25:
        print(f"\n  ... and {len(results['jobs']) - 25} more jobs. Export to see all.")
    print("=" * 70 + "\n")


# ─── CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="SG Job Scraper — Search across Singapore job portals",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python sg_job_scraper.py "software engineer"
  python sg_job_scraper.py "data analyst" --sources mcf,careersgov
  python sg_job_scraper.py "react developer" --limit 50 --output results.csv
  python sg_job_scraper.py "product manager" --output results.json --no-skills

Available sources: mcf, careersgov, nodeflair, indeed, jobstreet
        """,
    )
    parser.add_argument("keyword", help="Job search keyword (e.g., 'software engineer')")
    parser.add_argument(
        "--sources", "-s",
        help="Comma-separated sources (default: all). Options: mcf,careersgov,nodeflair,indeed,jobstreet",
        default=None,
    )
    parser.add_argument("--limit", "-l", type=int, default=20, help="Max jobs per source (default: 20)")
    parser.add_argument("--output", "-o", help="Output file path (.json or .csv)")
    parser.add_argument("--no-skills", action="store_true", help="Skip SSG Skills Framework enrichment")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    sources = args.sources.split(",") if args.sources else None

    aggregator = JobAggregator()
    results = aggregator.search_all(
        keyword=args.keyword,
        sources=sources,
        limit_per_source=args.limit,
        enrich_skills=not args.no_skills,
    )

    # Print summary
    print_summary(results)

    # Export
    if args.output:
        filepath = args.output
    else:
        safe_keyword = re.sub(r"[^a-zA-Z0-9]+", "_", args.keyword).strip("_")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = f"sg_jobs_{safe_keyword}_{timestamp}.json"

    if filepath.endswith(".csv"):
        export_csv(results, filepath)
    else:
        export_json(results, filepath)
        csv_path = filepath.replace(".json", ".csv")
        export_csv(results, csv_path)

    print(f"Done! Files saved. Found {results['total_deduped']} unique jobs across {len(results['by_source'])} sources.\n")


if __name__ == "__main__":
    main()
