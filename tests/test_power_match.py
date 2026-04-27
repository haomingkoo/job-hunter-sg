import sys
from pathlib import Path
from types import SimpleNamespace


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from main import _is_power_gap_noise, _power_job_duplicate_key, _select_power_match_candidates


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


def test_power_match_duplicate_key_collapses_reposted_same_role():
    first = SimpleNamespace(
        title="QA/ QC Engineer [Ubi | 5 days | up to $4500] - LCYL",
        company="THE SUPREME HR ADVISORY PTE. LTD.",
        location="SHENTON HOUSE",
        salary="$2,500 - $4,500",
        source="MyCareersFuture",
        source_posting_id="mcf-1",
    )
    second = SimpleNamespace(
        title="QA/ QC Engineer [Ubi | 5 days | up to $4500] - LCYL",
        company="THE SUPREME HR ADVISORY PTE. LTD.",
        location="SHENTON HOUSE",
        salary="$2,500 - $4,500",
        source="MyCareersFuture",
        source_posting_id="mcf-2",
    )

    assert _power_job_duplicate_key(first) == _power_job_duplicate_key(second)


def test_power_match_gap_noise_excludes_office_basics():
    assert _is_power_gap_noise("Microsoft Word")
    assert _is_power_gap_noise("Microsoft Office")
