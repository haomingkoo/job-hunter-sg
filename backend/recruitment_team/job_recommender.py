"""Deterministic, evidence-visible reranking for coordinator job discovery."""

from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction

import config
from employer_filter import employer_relationship_rank
from skill_extractor import extract_skill_phrases

from .candidate_profile import CandidateEvidenceProfile
from .discovery import DiscoveryPort, JobSearchResult, JobSnapshot


RANKING_POLICY_VERSION = "candidate-evidence-rerank-v1"
RANKING_COMPONENT_ORDER = (
    "profile_term_match_count",
    "profile_term_coverage",
    "employer_relationship_when_requested",
    "semantic_similarity",
    "source_order",
)


@dataclass(frozen=True)
class RankedJobReceipt:
    job_id: int
    source_position: int
    final_position: int
    profile_term_match_count: int
    profile_term_coverage: float
    matched_profile_terms: tuple[str, ...]
    considered_job_terms: tuple[str, ...]
    semantic_similarity: float | None
    employer_relationship: str
    employer_relationship_evidence: str
    employer_relationship_rank: int


@dataclass(frozen=True)
class RankingReceipt:
    policy_version: str
    query: str
    candidate_profile_used: bool
    candidate_profile_version: str
    component_order: tuple[str, ...]
    candidate_generation_scope: str
    candidate_queries: tuple[str, ...]
    employer_preference_applied: bool
    jobs: tuple[RankedJobReceipt, ...]


@dataclass(frozen=True)
class RecommendationBatch:
    search_result: JobSearchResult
    receipt: RankingReceipt


def ranking_receipt_from_dict(value: dict) -> RankingReceipt:
    """Rehydrate a persisted receipt at the Recruitment Team interface."""
    return RankingReceipt(
        policy_version=str(value["policy_version"]),
        query=str(value["query"]),
        candidate_profile_used=bool(value["candidate_profile_used"]),
        candidate_profile_version=str(value.get("candidate_profile_version") or ""),
        component_order=tuple(str(item) for item in value["component_order"]),
        candidate_generation_scope=str(value["candidate_generation_scope"]),
        candidate_queries=tuple(
            str(item) for item in value.get("candidate_queries") or (value["query"],)
        ),
        employer_preference_applied=bool(value.get("employer_preference_applied")),
        jobs=tuple(
            RankedJobReceipt(
                job_id=int(item["job_id"]),
                source_position=int(item["source_position"]),
                final_position=int(item["final_position"]),
                profile_term_match_count=int(
                    item.get("profile_term_match_count")
                    if item.get("profile_term_match_count") is not None
                    else len(item.get("matched_profile_terms") or ())
                ),
                profile_term_coverage=float(item["profile_term_coverage"]),
                matched_profile_terms=tuple(str(term) for term in item["matched_profile_terms"]),
                considered_job_terms=tuple(str(term) for term in item["considered_job_terms"]),
                semantic_similarity=(
                    float(item["semantic_similarity"]) if item.get("semantic_similarity") is not None else None
                ),
                employer_relationship=str(item["employer_relationship"]),
                employer_relationship_evidence=str(item.get("employer_relationship_evidence") or ""),
                employer_relationship_rank=int(item["employer_relationship_rank"]),
            )
            for item in value["jobs"]
        ),
    )


def _normalized_phrase(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def _flatten_terms(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        terms: list[str] = []
        for item in value:
            terms.extend(_flatten_terms(item))
        return terms
    return []


def _job_terms(job: JobSnapshot) -> tuple[str, ...]:
    parsed = job.parsed_jd or {}
    supplied = [
        *job.skills,
        *job.job_terms_preview,
        *_flatten_terms(parsed.get("required_skills")),
        *_flatten_terms(parsed.get("preferred_skills")),
    ]
    extracted = extract_skill_phrases(
        " ".join((job.title, job.description)),
        job_skills=[str(term) for term in supplied],
    )
    seen: set[str] = set()
    terms: list[str] = []
    for raw in (*supplied, *extracted):
        term = _normalized_phrase(raw)
        if term and term not in seen:
            seen.add(term)
            terms.append(term)
    return tuple(terms)


def _profile_text(profile: CandidateEvidenceProfile | None) -> str:
    if profile is None:
        return ""
    # Transferable hypotheses are useful prompts for human review, not evidence
    # that the candidate owns a term. Reranking uses direct fields only.
    evidence = [
        text
        for field in profile.fields
        if field.evidence_kind == "direct"
        for text in (field.statement, *field.evidence_quotes)
    ]
    return f" {_normalized_phrase(' '.join(evidence))} "


def _profile_search_query(profile: CandidateEvidenceProfile | None) -> str:
    """Build a compact role-neutral retrieval view from direct evidence only.

    The embedding encoder truncates long inputs. Feeding every reviewed field
    would therefore make whichever resume section happened to come first an
    undocumented recall policy. Preserve explicit domains, skills and
    credentials, then add known skill phrases extracted across every direct
    statement. If the profile contains none of those semantics, keep its direct
    statements rather than inventing a substitute query.
    """
    if profile is None:
        return ""
    statements = [
        field.statement.strip()
        for field in profile.fields
        if field.evidence_kind == "direct"
        and field.statement.strip()
    ]
    explicit_terms = [
        field.statement.strip()
        for field in profile.fields
        if field.evidence_kind == "direct"
        and field.category in {"domain", "stated_skill", "credential"}
        and field.statement.strip()
    ]
    extracted_terms = extract_skill_phrases(" ".join(statements))
    compact_terms = list(dict.fromkeys((*explicit_terms, *extracted_terms)))
    return " ".join(compact_terms or dict.fromkeys(statements))


def _merged_search_result(results: tuple[JobSearchResult, ...]) -> JobSearchResult:
    primary = results[0]
    seen: set[int] = set()
    jobs: list[JobSnapshot] = []
    for result in results:
        for job in result.jobs:
            if job.job_id not in seen:
                seen.add(job.job_id)
                jobs.append(job)
    return JobSearchResult(
        query=primary.query,
        jobs=tuple(jobs),
        candidate_count=None,
        visible_candidate_count=len(jobs),
        truncated=any(result.truncated for result in results),
        valid_empty=not jobs,
        failure_type=primary.failure_type,
        failure_code=primary.failure_code,
        eligible_candidate_count=primary.eligible_candidate_count,
        company=primary.company,
        direct_employers_only=primary.direct_employers_only,
        exclude_junior=primary.exclude_junior,
        singapore_only=primary.singapore_only,
        title_phrase=primary.title_phrase,
    )


def _term_coverage(profile_text: str, terms: tuple[str, ...]) -> tuple[Fraction, tuple[str, ...]]:
    if not profile_text or not terms:
        return Fraction(0, 1), ()
    matched = tuple(term for term in terms if f" {term} " in profile_text)
    return Fraction(len(matched), len(terms)), matched


class JobRecommender:
    """Rerank one discovery result and explain every deterministic component.

    Candidate generation unions the explicit search intent with one role-neutral
    direct-evidence query. This gives relevant prior-industry employers a path
    into reranking without hard-coding company prestige or a named employer.
    """

    def search(
        self,
        candidate_profile: CandidateEvidenceProfile | None,
        discovery: DiscoveryPort,
        query: str,
        *,
        company: str = "",
        direct_employers_only: bool = True,
        exclude_junior: bool = False,
        singapore_only: bool = True,
        title_phrase: str = "",
    ) -> RecommendationBatch:
        constraints = {
            "company": company,
            "direct_employers_only": direct_employers_only,
            "exclude_junior": exclude_junior,
            "singapore_only": singapore_only,
            "title_phrase": title_phrase,
        }
        primary = discovery.search_jobs(query, **constraints)
        results = [primary]
        profile_query = _profile_search_query(candidate_profile)
        if (
            not primary.failure_type
            and profile_query
            and _normalized_phrase(profile_query) != _normalized_phrase(query)
        ):
            secondary = discovery.search_jobs(profile_query, **constraints)
            if not secondary.failure_type:
                results.append(secondary)
        return self.recommend(
            candidate_profile,
            _merged_search_result(tuple(results)),
            candidate_queries=tuple(result.query for result in results),
        )

    def recommend(
        self,
        candidate_profile: CandidateEvidenceProfile | None,
        search_result: JobSearchResult,
        *,
        candidate_queries: tuple[str, ...] | None = None,
    ) -> RecommendationBatch:
        profile_text = _profile_text(candidate_profile)
        scored: list[tuple[JobSnapshot, int, Fraction, tuple[str, ...], tuple[str, ...], str, int]] = []
        for source_position, job in enumerate(search_result.jobs, start=1):
            terms = _job_terms(job)
            coverage, matched = _term_coverage(profile_text, terms)
            relationship = job.employer_relationship or "unknown"
            scored.append(
                (
                    job,
                    source_position,
                    coverage,
                    matched,
                    terms,
                    relationship,
                    employer_relationship_rank(relationship),
                )
            )

        prefer_relationship = search_result.direct_employers_only and candidate_profile is not None
        scored.sort(
            key=lambda item: (
                -len(item[3]),
                -item[2],
                -(item[6] if prefer_relationship else 0),
                -(item[0].similarity_score if item[0].similarity_score is not None else float("-inf")),
                item[1],
                item[0].job_id,
            )
        )
        ranked_jobs = tuple(item[0] for item in scored[: config.AGENT_SEARCH_JOBS_LIMIT])
        queries = candidate_queries or (search_result.query,)
        receipt = RankingReceipt(
            policy_version=RANKING_POLICY_VERSION,
            query=search_result.query,
            candidate_profile_used=candidate_profile is not None,
            candidate_profile_version=(candidate_profile.profile_version if candidate_profile else ""),
            component_order=RANKING_COMPONENT_ORDER,
            candidate_generation_scope=(
                "query_and_profile_search_union"
                if len(queries) > 1
                else "query_search_only"
            ),
            candidate_queries=queries,
            employer_preference_applied=prefer_relationship,
            jobs=tuple(
                RankedJobReceipt(
                    job_id=job.job_id,
                    source_position=source_position,
                    final_position=final_position,
                    profile_term_match_count=len(matched),
                    profile_term_coverage=float(coverage),
                    matched_profile_terms=matched,
                    considered_job_terms=terms,
                    semantic_similarity=job.similarity_score,
                    employer_relationship=relationship,
                    employer_relationship_evidence=job.employer_relationship_evidence,
                    employer_relationship_rank=relationship_rank,
                )
                for final_position, (
                    job,
                    source_position,
                    coverage,
                    matched,
                    terms,
                    relationship,
                    relationship_rank,
                ) in enumerate(scored, start=1)
            ),
        )
        return RecommendationBatch(
            search_result=search_result.with_ranking(ranked_jobs, receipt),
            receipt=receipt,
        )
