import sys
from pathlib import Path
from types import SimpleNamespace


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from main import _select_power_match_candidates


class FakeQuery:
    def __init__(self, results):
        self.results = results
        self.all_calls = 0
        self.limit_values = []

    def options(self, *args, **kwargs):
        return self

    def filter(self, *args):
        return self

    def order_by(self, *args):
        return self

    def limit(self, value):
        self.limit_values.append(value)
        return self

    def all(self):
        self.all_calls += 1
        return list(self.results)


class FakeDb:
    def __init__(self, results):
        self.query_obj = FakeQuery(results)

    def query(self, _model):
        return self.query_obj


def test_power_match_candidates_do_not_backfill_with_newest_jobs():
    matched_job = SimpleNamespace(id=1)
    db = FakeDb([matched_job])

    result = _select_power_match_candidates(
        db=db,
        resume_text="Python Kubernetes AWS platform engineering",
        resume_skills=["Python", "Kubernetes", "AWS"],
        limit=100,
    )

    assert result == [matched_job]
    assert db.query_obj.all_calls == 1
    assert db.query_obj.limit_values == [100]
