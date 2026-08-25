"""Typed discovery port over the existing LangChain job tools."""

from __future__ import annotations

import hashlib
import json
from bisect import bisect_right
from dataclasses import dataclass, replace
from statistics import median
from typing import Protocol

from sqlalchemy import and_, or_

from .recovery import classify_failure, normalize_failure_code


JOB_REASONING_REQUIREMENT_FIELDS = (
    "required_skills",
    "preferred_skills",
    "experience_years",
    "education_level",
    "key_responsibilities",
    "archetype",
)


@dataclass(frozen=True)
class JobSource:
    source: str
    url: str
    source_posting_id: str
    posted_date: str
    closing_date: str
    scraped_at: str
    availability: str
    snapshot_sha256: str


@dataclass(frozen=True)
class JobPostingVariant:
    job_id: int
    salary: str
    source: JobSource


@dataclass(frozen=True)
class JobSnapshot:
    job_id: int
    title: str
    company: str
    location: str
    salary: str
    employment_type: str
    seniority: str
    description: str
    skills: tuple[str, ...]
    similarity_score: float | None
    source: JobSource
    posting_variants: tuple[JobPostingVariant, ...] = ()
    sector: str = ""
    parsed_jd: dict | None = None
    job_terms_preview: tuple[str, ...] = ()
    salary_context: dict | None = None
    fact_context_status: str = "unavailable"
    employer_relationship: str | None = None
    employer_relationship_evidence: str = ""

    @classmethod
    def from_payload(cls, payload: dict) -> "JobSnapshot":
        def source_from(item: dict) -> JobSource:
            snapshot_sha256 = hashlib.sha256(
                json.dumps(
                    item,
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                ).encode()
            ).hexdigest()
            return JobSource(
                source=str(item.get("source") or ""),
                url=str(item.get("url") or ""),
                source_posting_id=str(item.get("source_posting_id") or ""),
                posted_date=str(item.get("posted_date") or ""),
                closing_date=str(item.get("closing_date") or ""),
                scraped_at=str(item.get("scraped_at") or ""),
                availability=str(item.get("availability") or "unknown"),
                snapshot_sha256=snapshot_sha256,
            )

        raw_variants = payload.get("posting_variants") or [payload]
        variants = tuple(
            JobPostingVariant(
                job_id=int(item["id"]),
                salary=str(item.get("salary") or ""),
                source=source_from(item),
            )
            for item in raw_variants
        )
        score = payload.get("score")
        return cls(
            job_id=int(payload["id"]),
            title=str(payload.get("title") or ""),
            company=str(payload.get("company") or ""),
            location=str(payload.get("location") or ""),
            salary=str(payload.get("salary") or ""),
            employment_type=str(payload.get("employment_type") or ""),
            seniority=str(payload.get("seniority") or ""),
            description=str(payload.get("description") or ""),
            skills=tuple(str(skill) for skill in payload.get("skills") or []),
            similarity_score=float(score) if isinstance(score, (int, float)) else None,
            source=source_from(payload),
            posting_variants=variants,
            sector=str(payload.get("sector") or ""),
            parsed_jd=(payload.get("parsed_jd") if isinstance(payload.get("parsed_jd"), dict) else None),
            job_terms_preview=tuple(str(term) for term in payload.get("job_terms_preview") or []),
            salary_context=(payload.get("salary_context") if isinstance(payload.get("salary_context"), dict) else None),
            fact_context_status=str(payload.get("fact_context_status") or "unavailable"),
            employer_relationship=(
                str(payload["employer_relationship"])
                if payload.get("employer_relationship") is not None
                else None
            ),
            employer_relationship_evidence=str(
                payload.get("employer_relationship_evidence") or ""
            ),
        )


@dataclass(frozen=True)
class JobSearchResult:
    query: str
    jobs: tuple[JobSnapshot, ...]
    candidate_count: int | None
    visible_candidate_count: int | None
    truncated: bool
    valid_empty: bool
    failure_type: str | None = None
    failure_code: str | None = None
    eligible_candidate_count: int | None = None
    company: str = ""
    direct_employers_only: bool = True
    exclude_junior: bool = False
    singapore_only: bool = True
    title_phrase: str = ""


class DiscoveryPort(Protocol):
    def search_jobs(
        self,
        query: str,
        *,
        company: str = "",
        direct_employers_only: bool = True,
        exclude_junior: bool = False,
        singapore_only: bool = True,
        title_phrase: str = "",
    ) -> JobSearchResult: ...

    def get_job(self, job_id: int) -> JobSnapshot | None: ...


def _enrich_job_facts(payloads: list[dict]) -> list[dict]:
    """Attach stored requirements and observed pay context to search results.

    Salary context is descriptive. A missing posting salary is never imputed.
    """
    from database import SessionLocal
    from job_visibility import apply_public_job_visibility
    from models import ScrapedJob

    job_ids = [int(item["id"]) for item in payloads if item.get("id") is not None]
    if not job_ids:
        return [dict(item) for item in payloads]

    with SessionLocal() as db:
        jobs = apply_public_job_visibility(db.query(ScrapedJob)).filter(ScrapedJob.id.in_(job_ids)).all()
        jobs_by_id = {job.id: job for job in jobs}
        pairs = {
            ((job.sector or "").strip(), (job.seniority or "").strip())
            for job in jobs
            if (job.sector or "").strip() and (job.seniority or "").strip()
        }
        salary_groups: dict[tuple[str, str], list[int]] = {pair: [] for pair in pairs}
        if pairs:
            conditions = [
                and_(ScrapedJob.sector == sector, ScrapedJob.seniority == seniority) for sector, seniority in pairs
            ]
            salary_rows = (
                apply_public_job_visibility(
                    db.query(
                        ScrapedJob.sector,
                        ScrapedJob.seniority,
                        ScrapedJob.salary_floor,
                    )
                )
                .filter(ScrapedJob.salary_floor > 0, or_(*conditions))
                .all()
            )
            for sector, seniority, salary_floor in salary_rows:
                salary_groups[(sector, seniority)].append(int(salary_floor))

    enriched = []
    for payload in payloads:
        item = dict(payload)
        job = jobs_by_id.get(int(item["id"]))
        if job is None:
            item["fact_context_status"] = "source_row_unavailable"
            enriched.append(item)
            continue
        parsed_jd = job.parsed_jd if isinstance(job.parsed_jd, dict) else {}
        item.update(
            {
                "fact_context_status": "available",
                "sector": job.sector or "",
                "parsed_jd": {
                    field: parsed_jd[field] for field in JOB_REASONING_REQUIREMENT_FIELDS if field in parsed_jd
                },
                "job_terms_preview": (
                    [str(term) for term in job.job_terms_preview] if isinstance(job.job_terms_preview, list) else []
                ),
            }
        )
        pair = ((job.sector or "").strip(), (job.seniority or "").strip())
        group = sorted(salary_groups.get(pair, []))
        if group:
            salary_floor = int(job.salary_floor or 0)
            item["salary_context"] = {
                "basis": "current visible postings with stated salary",
                "sector": pair[0],
                "self_reported_seniority": pair[1],
                "sample_count": len(group),
                "median_salary_floor": median(group),
                "posting_salary_floor": salary_floor or None,
                "posting_floor_percentile": (
                    round(100 * bisect_right(group, salary_floor) / len(group), 1) if salary_floor else None
                ),
            }
        enriched.append(item)
    return enriched


class LangChainJobDiscovery:
    """Production adapter that reuses the existing constrained LangChain tools."""

    def search_jobs(
        self,
        query: str,
        *,
        company: str = "",
        direct_employers_only: bool = True,
        exclude_junior: bool = False,
        singapore_only: bool = True,
        title_phrase: str = "",
    ) -> JobSearchResult:
        from resume_agent.tools import search_jobs

        result = search_jobs.invoke(
            {
                "query": query,
                "detail": True,
                "company": company,
                "direct_employers_only": direct_employers_only,
                "exclude_junior": exclude_junior,
                "singapore_only": singapore_only,
                "title_phrase": title_phrase,
            }
        )
        if not result.get("ok"):
            error = result.get("error") if isinstance(result.get("error"), dict) else {}
            failure_code = normalize_failure_code(str(error.get("code") or result.get("failure_type") or ""))
            decision = classify_failure(failure_code, attempts_remaining=False)
            return JobSearchResult(
                query=query,
                jobs=(),
                candidate_count=None,
                visible_candidate_count=None,
                truncated=False,
                valid_empty=False,
                failure_type=decision.failure_type,
                failure_code=decision.failure_code,
                company=company,
                direct_employers_only=direct_employers_only,
                exclude_junior=exclude_junior,
                singapore_only=singapore_only,
                title_phrase=title_phrase,
            )
        jobs = tuple(JobSnapshot.from_payload(item) for item in _enrich_job_facts(result["results"]))
        return JobSearchResult(
            query=query,
            jobs=jobs,
            candidate_count=result.get("candidate_count"),
            visible_candidate_count=result.get("visible_candidate_count"),
            truncated=bool(result.get("truncated")),
            valid_empty=not jobs,
            eligible_candidate_count=result.get("eligible_candidate_count"),
            company=company,
            direct_employers_only=direct_employers_only,
            exclude_junior=exclude_junior,
            singapore_only=singapore_only,
            title_phrase=title_phrase,
        )

    def get_job(self, job_id: int) -> JobSnapshot | None:
        from resume_agent.tools import get_job

        result = get_job.invoke({"job_id": job_id})
        if not result.get("ok"):
            failure_type = str(result.get("failure_type") or "unavailable")
            raise RuntimeError(f"job source failure: {failure_type}")
        payload = result.get("job")
        if isinstance(payload, dict):
            payload = _enrich_job_facts([payload])[0]
        return JobSnapshot.from_payload(payload) if isinstance(payload, dict) else None


class ScriptedDiscovery:
    """Deterministic discovery adapter for module and transport tests."""

    def __init__(
        self,
        searches: list[JobSearchResult],
        jobs_by_id: dict[int, JobSnapshot] | None = None,
    ):
        self._searches = iter(searches)
        self._jobs_by_id = dict(jobs_by_id or {})
        self.search_count = 0

    def search_jobs(
        self,
        query: str,
        *,
        company: str = "",
        direct_employers_only: bool = True,
        exclude_junior: bool = False,
        singapore_only: bool = True,
        title_phrase: str = "",
    ) -> JobSearchResult:
        self.search_count += 1
        result = next(self._searches)
        return replace(
            result,
            query=query,
            company=company,
            direct_employers_only=direct_employers_only,
            exclude_junior=exclude_junior,
            singapore_only=singapore_only,
            title_phrase=title_phrase,
        )

    def get_job(self, job_id: int) -> JobSnapshot | None:
        return self._jobs_by_id.get(job_id)
