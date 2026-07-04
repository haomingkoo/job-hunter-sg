import json


def test_parse_resume_returns_bullet_ids():
    import mcp_tools

    data = json.loads(
        mcp_tools.parse_resume(
            "Jane Doe\njane@example.com\n\nEXPERIENCE\n- Built data pipeline processing 10M events daily"
        )
    )

    assert data["stats"]["total_bullets"] == 1
    assert data["bullets"][0]["id"]
    assert data["bullets"][0]["text"] == "Built data pipeline processing 10M events daily"


def test_validate_bullet_edit_rejects_fabricated_metric():
    import mcp_tools

    data = json.loads(
        mcp_tools.validate_bullet_edit(
            "Built data pipeline processing 10M events daily",
            "Built data pipeline processing 10M events daily and cut costs by 40%",
        )
    )

    assert data["accepted"] is False
    assert data["final_text"] == "Built data pipeline processing 10M events daily"


def test_compare_candidate_profile_returns_consistency_gaps():
    import mcp_tools

    data = json.loads(
        mcp_tools.compare_candidate_profile(
            "EXPERIENCE\n- Built Python data pipelines",
            "LinkedIn About: Python, SQL, Tableau dashboards",
        )
    )

    assert "SQL" in data["profile_only_skills"] or "Tableau" in data["profile_only_skills"]
    assert "Do not add" in data["guidance"]


def test_propose_resume_diff_uses_bullet_id_and_gates():
    import mcp_tools

    resume = "EXPERIENCE\n- Built data pipeline processing 10M events daily"
    bullet_id = json.loads(mcp_tools.parse_resume(resume))["bullets"][0]["id"]

    data = json.loads(
        mcp_tools.propose_resume_diff(
            resume,
            bullet_id,
            "Built reliable data pipeline processing 10M events daily",
        )
    )

    assert data["accepted"] is True
    assert data["bullet_id"] == bullet_id
    assert data["original"] == "Built data pipeline processing 10M events daily"


def test_search_jobs_caps_and_shapes_results(monkeypatch):
    import config
    import mcp_tools

    class FakeJob:
        id = 7
        title = "Data Engineer"
        company = "Acme"
        location = "Singapore"
        salary = ""
        source = "test"
        url = "https://example.com/job"
        description = "Build Python data pipelines"
        jd_summary = "Build data platforms."
        skills = ["Python", "SQL"]
        parsed_jd = {"required_skills": ["Python"]}

    class FakeDb:
        closed = False

        def get(self, _model, job_id):
            return FakeJob() if job_id == 7 else None

        def close(self):
            self.closed = True

    monkeypatch.setattr(mcp_tools, "SessionLocal", lambda: FakeDb())
    monkeypatch.setattr(mcp_tools, "encode_text", lambda query: [0.1, 0.2])

    def fake_find_similar_jobs(vector, db, top_k):
        assert vector == [0.1, 0.2]
        assert top_k == config.AGENT_SEARCH_JOBS_LIMIT
        return [(7, 0.98765)]

    monkeypatch.setattr(mcp_tools, "find_similar_jobs", fake_find_similar_jobs)

    data = json.loads(mcp_tools.search_jobs("python data", limit=999))

    assert data["ok"] is True
    assert data["limit"] == config.AGENT_SEARCH_JOBS_LIMIT
    assert data["detail"] is False
    assert data["results"][0]["id"] == 7
    assert data["results"][0]["score"] == 0.98765
    assert "description" not in data["results"][0]

    detailed = json.loads(mcp_tools.search_jobs("python data", limit=999, detail=True))

    assert detailed["detail"] is True
    assert detailed["results"][0]["description"] == "Build Python data pipelines"
    assert detailed["results"][0]["parsed_jd"] == {"required_skills": ["Python"]}


def test_mcp_search_jobs_empty_and_error_are_structured(monkeypatch):
    import mcp_tools

    class FakeDb:
        def close(self):
            return None

    monkeypatch.setattr(mcp_tools, "SessionLocal", lambda: FakeDb())
    monkeypatch.setattr(mcp_tools, "encode_text", lambda query: [0.1, 0.2])
    monkeypatch.setattr(mcp_tools, "find_similar_jobs", lambda *_args, **_kwargs: [])

    empty = json.loads(mcp_tools.search_jobs("missing role"))

    assert empty["ok"] is True
    assert empty["empty"] is True
    assert empty["results"] == []

    def broken_search(*_args, **_kwargs):
        raise RuntimeError("index unavailable")

    monkeypatch.setattr(mcp_tools, "find_similar_jobs", broken_search)
    failed = json.loads(mcp_tools.search_jobs("python data"))

    assert failed["ok"] is False
    assert failed["error"]["code"] == "search_failed"


def test_mcp_server_imports():
    import mcp_server

    assert mcp_server.mcp is not None
