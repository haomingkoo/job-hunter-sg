"""Typed discovery port over the existing LangChain job tools."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Protocol


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
    retryable: bool = False


class DiscoveryPort(Protocol):
    def search_jobs(self, query: str) -> JobSearchResult: ...

    def get_job(self, job_id: int) -> JobSnapshot | None: ...


class LangChainJobDiscovery:
    """Production adapter that reuses the existing constrained LangChain tools."""

    def search_jobs(self, query: str) -> JobSearchResult:
        from resume_agent.tools import search_jobs

        result = search_jobs.invoke({"query": query, "detail": True})
        if not result.get("ok"):
            return JobSearchResult(
                query=query,
                jobs=(),
                candidate_count=None,
                visible_candidate_count=None,
                truncated=False,
                valid_empty=False,
                failure_type=str(result.get("failure_type") or "unavailable"),
                retryable=bool(result.get("retryable")),
            )
        jobs = tuple(JobSnapshot.from_payload(item) for item in result["results"])
        return JobSearchResult(
            query=query,
            jobs=jobs,
            candidate_count=result.get("candidate_count"),
            visible_candidate_count=result.get("visible_candidate_count"),
            truncated=bool(result.get("truncated")),
            valid_empty=not jobs,
        )

    def get_job(self, job_id: int) -> JobSnapshot | None:
        from resume_agent.tools import get_job

        result = get_job.invoke({"job_id": job_id})
        if not result.get("ok"):
            failure_type = str(result.get("failure_type") or "unavailable")
            raise RuntimeError(f"job source failure: {failure_type}")
        payload = result.get("job")
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

    def search_jobs(self, query: str) -> JobSearchResult:
        self.search_count += 1
        result = next(self._searches)
        return JobSearchResult(query=query, **{key: value for key, value in result.__dict__.items() if key != "query"})

    def get_job(self, job_id: int) -> JobSnapshot | None:
        return self._jobs_by_id.get(job_id)
