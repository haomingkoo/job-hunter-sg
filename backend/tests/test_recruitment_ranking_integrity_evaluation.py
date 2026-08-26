from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.evaluate_recruitment_ranking_integrity import (
    RankingEvaluationError,
    evaluate_fixture,
)


FIXTURES = Path(__file__).resolve().parents[1] / "evals/ranking-integrity"
TEMPORAL = FIXTURES / "temporal-replay-v1.json"


def test_temporal_replay_is_reproducible_and_not_an_outcome_backtest() -> None:
    report = evaluate_fixture(TEMPORAL)
    assert report["passed"] is True
    assert report["evaluation_kind"] == "temporal_replay"
    assert report["interpretation"] == "temporal_ranking_replay_without_outcomes"
    assert report["is_outcome_backtest"] is False


def test_temporal_replay_excludes_future_jobs_then_admits_them_after_observation() -> None:
    report = evaluate_fixture(TEMPORAL)
    january, february = report["cases"]

    assert january["as_of_job_ids"] == [201, 203, 204]
    assert january["ranked_job_ids"] == [201, 203, 204]
    assert february["as_of_job_ids"] == [201, 202, 203, 204]
    assert february["ranked_job_ids"] == [202, 201, 203, 204]
    assert all(case["future_leakage_detected"] is False for case in report["cases"])


def test_temporal_replay_fails_closed_when_a_future_job_has_a_similarity_score(
    tmp_path: Path,
) -> None:
    fixture = json.loads(TEMPORAL.read_text())
    fixture["replays"][0]["similarity_scores"]["202"] = 1.0
    tampered = tmp_path / "future-leakage.json"
    tampered.write_text(json.dumps(fixture))

    with pytest.raises(RankingEvaluationError, match=r"violates as-of corpus; future=\[202\]"):
        evaluate_fixture(tampered)


def test_outcome_free_fixture_cannot_call_itself_a_backtest(tmp_path: Path) -> None:
    fixture = json.loads(TEMPORAL.read_text())
    fixture["evaluation_kind"] = "outcome_backtest"
    mislabeled = tmp_path / "not-a-backtest.json"
    mislabeled.write_text(json.dumps(fixture))

    with pytest.raises(RankingEvaluationError, match="without observed outcomes"):
        evaluate_fixture(mislabeled)
