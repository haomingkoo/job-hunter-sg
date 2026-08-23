from __future__ import annotations


def test_dynamic_skill_cold_build_is_single_flight(monkeypatch):
    import skill_extractor

    monkeypatch.setattr(
        skill_extractor,
        "_dynamic_cache",
        {"skills": {}, "built_at": 0, "job_count": 0},
    )
    assert skill_extractor._dynamic_cache_lock.acquire(blocking=False)
    try:
        assert skill_extractor.build_dynamic_skills(None) == {}
    finally:
        skill_extractor._dynamic_cache_lock.release()


def test_dynamic_skill_build_caps_database_rows(monkeypatch):
    import skill_extractor

    seen_limits: list[int] = []

    class Query:
        def filter(self, *_args):
            return self

        def limit(self, value: int):
            seen_limits.append(value)
            return self

        def yield_per(self, _value: int):
            return self

        def __iter__(self):
            return iter([])

    class Session:
        def query(self, *_args):
            return Query()

    monkeypatch.setattr(
        skill_extractor,
        "_dynamic_cache",
        {"skills": {}, "built_at": 0, "job_count": 0},
    )

    assert skill_extractor.build_dynamic_skills(Session()) == {}
    assert seen_limits == [skill_extractor.ANALYTICS_MAX_ROWS]


def test_stored_skill_normalization_preserves_caller_length_policy():
    from skill_extractor import normalize_skill_strings

    long_skill = "x" * 70
    raw = [" AWS ; Kubernetes ", {"Cloud": "aws|Terraform"}, long_skill]

    assert normalize_skill_strings(raw, max_length=60) == [
        "AWS",
        "Kubernetes",
        "Cloud",
        "Terraform",
    ]
    assert normalize_skill_strings(raw, max_length=80)[-1] == long_skill
