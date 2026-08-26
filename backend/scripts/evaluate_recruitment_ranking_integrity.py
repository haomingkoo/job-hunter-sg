"""Reproduce the outcome-free temporal ranking-integrity replay."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from recruitment_team.candidate_profile import CandidateEvidenceProfile, CandidateProfileField
from recruitment_team.discovery import JobSearchResult, JobSnapshot, JobSource
from recruitment_team.job_recommender import JobRecommender


DEFAULT_FIXTURE = Path(__file__).resolve().parents[1] / "evals/ranking-integrity/temporal-replay-v1.json"
EVALUATION_KIND = "temporal_replay"


class RankingEvaluationError(ValueError):
    """The fixture cannot support the evaluation claim it requests."""


@dataclass(frozen=True)
class EvaluationCase:
    case_id: str
    cutoff: datetime
    query: str
    direct_employers_only: bool
    similarity_scores: dict[int, float]
    expected_ranked_job_ids: tuple[int, ...]
    direct_before_unknown: tuple[tuple[int, int], ...]


def _timestamp(value: object, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as error:
        raise RankingEvaluationError(f"{label} must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None:
        raise RankingEvaluationError(f"{label} must include a timezone")
    return parsed


def _profile(raw: dict) -> tuple[CandidateEvidenceProfile, datetime]:
    observed_at = _timestamp(raw.get("observed_at"), "profile.observed_at")
    fields = tuple(
        CandidateProfileField(
            field_id=str(item["field_id"]),
            category=item["category"],
            statement=str(item["statement"]),
            resume_evidence_ids=(f"evidence-{item['field_id']}",),
            evidence_quotes=(str(item["statement"]),),
            evidence_kind=item["evidence_kind"],
            evidence_support_score=100,
            score_reason="Immutable synthetic evaluation evidence.",
        )
        for item in raw["fields"]
    )
    return (
        CandidateEvidenceProfile(
            profile_version=str(raw["profile_version"]),
            resume_document_id="synthetic-ranking-evaluation",
            resume_revision="immutable-fixture",
            fields=fields,
            cited_resume_evidence=(),
        ),
        observed_at,
    )


def _job(raw: dict, similarity_score: float) -> JobSnapshot:
    job_id = int(raw["job_id"])
    snapshot = hashlib.sha256(json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return JobSnapshot(
        job_id=job_id,
        title=str(raw["title"]),
        company=str(raw["company"]),
        location="Singapore",
        salary="",
        employment_type="Full Time",
        seniority=str(raw.get("seniority") or ""),
        description=str(raw["description"]),
        skills=tuple(str(item) for item in raw.get("skills") or ()),
        similarity_score=similarity_score,
        source=JobSource(
            source="immutable-synthetic-fixture",
            url=f"https://example.invalid/jobs/{job_id}",
            source_posting_id=str(job_id),
            posted_date=str(raw["observed_at"])[:10],
            closing_date="",
            scraped_at=str(raw["observed_at"]),
            availability="fixture",
            snapshot_sha256=snapshot,
        ),
        employer_relationship=str(raw["employer_relationship"]),
        employer_relationship_evidence=str(raw["employer_relationship_evidence"]),
        data_classification="untrusted_job_data",
    )


def _cases(fixture: dict) -> tuple[EvaluationCase, ...]:
    return tuple(
        EvaluationCase(
            case_id=str(item["case_id"]),
            cutoff=_timestamp(item["cutoff"], f"{item['case_id']}.cutoff"),
            query=str(item["query"]),
            direct_employers_only=bool(item.get("direct_employers_only", True)),
            similarity_scores={int(key): float(value) for key, value in item["similarity_scores"].items()},
            expected_ranked_job_ids=tuple(int(value) for value in item["expected_ranked_job_ids"]),
            direct_before_unknown=tuple(
                (int(pair[0]), int(pair[1])) for pair in item.get("direct_before_unknown") or ()
            ),
        )
        for item in fixture["replays"]
    )


def evaluate_fixture(path: Path, recommender: JobRecommender | None = None) -> dict:
    raw_bytes = path.read_bytes()
    fixture = json.loads(raw_bytes)
    kind = str(fixture.get("evaluation_kind") or "")
    outcomes = fixture.get("outcomes") or []
    if "backtest" in kind and not outcomes:
        raise RankingEvaluationError("an evaluation without observed outcomes cannot be called a backtest")
    if kind != EVALUATION_KIND:
        raise RankingEvaluationError(f"unsupported evaluation_kind: {kind}")
    if outcomes:
        raise RankingEvaluationError("ranking integrity fixtures must not contain candidate outcomes")

    profile, profile_observed_at = _profile(fixture["candidate_profile"])
    jobs = {int(item["job_id"]): item for item in fixture["jobs"]}
    if len(jobs) != len(fixture["jobs"]):
        raise RankingEvaluationError("job_id values must be unique")
    runner = recommender or JobRecommender()
    reports = []
    for case in _cases(fixture):
        if profile_observed_at > case.cutoff:
            raise RankingEvaluationError(f"{case.case_id}: candidate profile is from the future")
        visible_ids = {
            job_id
            for job_id, item in jobs.items()
            if _timestamp(item["observed_at"], f"job {job_id}.observed_at") <= case.cutoff
        }
        score_ids = set(case.similarity_scores)
        if score_ids != visible_ids:
            future = sorted(score_ids - visible_ids)
            missing = sorted(visible_ids - score_ids)
            raise RankingEvaluationError(
                f"{case.case_id}: similarity score set violates as-of corpus; future={future}, missing={missing}"
            )
        snapshots = tuple(_job(jobs[job_id], case.similarity_scores[job_id]) for job_id in sorted(visible_ids))
        result = JobSearchResult(
            query=case.query,
            jobs=snapshots,
            candidate_count=len(snapshots),
            visible_candidate_count=len(snapshots),
            truncated=False,
            valid_empty=not snapshots,
            direct_employers_only=case.direct_employers_only,
        )
        batch = runner.recommend(profile, result)
        ranked_ids = tuple(job.job_id for job in batch.search_result.jobs)
        positions = {job_id: index for index, job_id in enumerate(ranked_ids)}
        violations = []
        if ranked_ids != case.expected_ranked_job_ids:
            violations.append(
                {
                    "type": "unexpected_order",
                    "expected": list(case.expected_ranked_job_ids),
                    "observed": list(ranked_ids),
                }
            )
        for direct_id, unknown_id in case.direct_before_unknown:
            if (
                direct_id not in positions
                or unknown_id not in positions
                or positions[direct_id] >= positions[unknown_id]
            ):
                violations.append({"type": "direct_company_pair_failed", "direct": direct_id, "unknown": unknown_id})
        if not batch.receipt.candidate_profile_used:
            violations.append({"type": "candidate_profile_not_used"})
        reports.append(
            {
                "case_id": case.case_id,
                "cutoff": case.cutoff.isoformat(),
                "as_of_job_ids": sorted(visible_ids),
                "ranked_job_ids": list(ranked_ids),
                "future_leakage_detected": False,
                "passed": not violations,
                "violations": violations,
            }
        )

    return {
        "fixture_version": fixture["fixture_version"],
        "fixture_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "evaluation_kind": kind,
        "interpretation": "temporal_ranking_replay_without_outcomes",
        "is_outcome_backtest": False,
        "passed": all(item["passed"] for item in reports),
        "cases": reports,
    }


def run(path: Path = DEFAULT_FIXTURE) -> dict:
    return evaluate_fixture(path.resolve())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("fixture", nargs="?", type=Path, default=DEFAULT_FIXTURE)
    args = parser.parse_args()
    report = run(args.fixture)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
