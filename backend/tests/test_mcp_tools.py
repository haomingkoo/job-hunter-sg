import asyncio
import json
from pathlib import Path


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
        assert top_k == config.AGENT_SEARCH_JOBS_LIMIT * 10
        return [(7, 0.98765)]

    monkeypatch.setattr(mcp_tools, "find_similar_jobs", fake_find_similar_jobs)
    monkeypatch.setattr(mcp_tools, "_get_public_job", lambda db, job_id, include_old=False: FakeJob())

    data = json.loads(mcp_tools.search_jobs("python data", limit=999))

    assert data["ok"] is True
    assert data["status"] == "success"
    assert data["query_executed"] is True
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


def test_get_job_does_not_return_hidden_job(monkeypatch):
    import mcp_tools

    class FakeDb:
        def close(self):
            pass

    monkeypatch.setattr(mcp_tools, "SessionLocal", FakeDb)
    monkeypatch.setattr(mcp_tools, "_get_public_job", lambda db, job_id, include_old=False: None)

    data = json.loads(mcp_tools.get_job(7))

    assert data["ok"] is True
    assert data["status"] == "success"
    assert data["query_executed"] is True
    assert data["found"] is False
    assert data["job"] is None
    assert data["job_id"] == 7


def test_get_job_hides_internal_exception_text(monkeypatch):
    import mcp_tools

    class FakeDb:
        def close(self):
            pass

    monkeypatch.setattr(mcp_tools, "SessionLocal", FakeDb)
    monkeypatch.setattr(
        mcp_tools,
        "_get_public_job",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("postgresql://secret-user:secret-password@internal-host/jobs")  # pragma: allowlist secret
        ),
    )

    data = json.loads(mcp_tools.get_job(7))

    assert data["ok"] is False
    assert data["error"]["code"] == "get_job_failed"
    assert data["error"]["message"] == "Job lookup temporarily unavailable."
    assert "secret" not in json.dumps(data)


def test_latest_jobs_returns_compact_public_jobs(monkeypatch):
    import mcp_tools

    class FakeJob:
        id = 7
        title = "Data Engineer"
        company = "Acme"
        location = "Singapore"
        salary = "$7k"
        source = "test"
        url = "https://example.com/job"
        posted_date = "2026-07-03"
        employment_type = "Full Time"
        seniority = "Mid"
        skills = ["Python", "SQL"]
        jd_summary = "Build data products."

    class FakeQuery:
        def filter(self, *args):
            return self

        def order_by(self, *args):
            return self

        def limit(self, n):
            assert n == 5
            return self

        def all(self):
            return [FakeJob()]

    class FakeDb:
        def query(self, _model):
            return FakeQuery()

        def close(self):
            pass

    monkeypatch.setattr(mcp_tools, "SessionLocal", FakeDb)

    data = json.loads(mcp_tools.latest_jobs(limit=5))

    assert data["jobs"][0]["id"] == 7
    assert data["jobs"][0]["jd_summary"] == "Build data products."
    assert "description" not in data["jobs"][0]


def test_latest_jobs_filters_by_source(monkeypatch):
    """The two single-source wrappers collapsed into this parameter."""
    import mcp_tools

    seen = {}

    class FakeQuery:
        def filter(self, *args):
            seen.setdefault("filters", 0)
            seen["filters"] += 1
            return self

        def order_by(self, *args):
            return self

        def limit(self, n):
            return self

        def all(self):
            return []

    class FakeDb:
        def query(self, _model):
            return FakeQuery()

        def close(self):
            pass

    monkeypatch.setattr(mcp_tools, "SessionLocal", FakeDb)

    unfiltered = json.loads(mcp_tools.latest_jobs(limit=3))
    baseline = seen["filters"]
    filtered = json.loads(mcp_tools.latest_jobs(limit=3, source="Careers@Gov"))

    assert unfiltered["jobs"] == []
    assert filtered["jobs"] == []
    assert seen["filters"] > baseline, "source did not add a filter"


def test_source_stats_returns_counts_by_source(monkeypatch):
    import mcp_tools

    class FakeVisibleQuery:
        def filter(self, *args):
            return self

        def count(self):
            return 3

    class FakeStatsQuery:
        def filter(self, *args):
            return self

        def group_by(self, *args):
            return self

        def order_by(self, *args):
            return self

        def all(self):
            return [
                ("MyCareersFuture", 2, "2026-07-04T01:00:00", "2026-07-03T00:00:00"),
                ("Careers@Gov", 1, "2026-07-04T02:00:00", "2026-07-02T00:00:00"),
            ]

    class FakeDb:
        calls = 0

        def query(self, *args):
            self.calls += 1
            return FakeVisibleQuery() if self.calls == 1 else FakeStatsQuery()

        def close(self):
            pass

    monkeypatch.setattr(mcp_tools, "SessionLocal", FakeDb)

    data = json.loads(mcp_tools.source_stats())

    assert data["visible_jobs"] == 3
    assert data["source_count"] == 2
    assert data["sources"][0]["source"] == "MyCareersFuture"
    assert data["sources"][0]["count"] == 2


def test_recommend_skillsfuture_courses_clamps_per_skill(monkeypatch):
    import mcp_tools

    called = {}

    def fake_recommend(skills, per_skill):
        called["skills"] = skills
        called["per_skill"] = per_skill
        return {"recommendations": {"Python": []}}

    monkeypatch.setattr(mcp_tools, "recommend_courses_for_skills", fake_recommend)

    data = json.loads(mcp_tools.recommend_skillsfuture_courses(["Python"], per_skill=99))

    assert called == {"skills": ["Python"], "per_skill": 5}
    assert "Python" in data["recommendations"]


def test_match_resume_to_jobs_uses_ats_terms_without_storing_resume(monkeypatch):
    import mcp_tools

    class FakeJob:
        id = 7
        title = "Data Engineer"
        company = "Acme"
        location = "Singapore"
        salary = "$7k"
        source = "MyCareersFuture"
        url = "https://example.com/job"
        posted_date = "2026-07-03"
        employment_type = "Full Time"
        seniority = "Mid"
        description = "Build Python data pipelines and Kubernetes workloads"
        skills = ["Python", "Kubernetes"]
        parsed_jd = {"required_skills": ["Python", "Kubernetes"]}
        job_terms_preview = ["Python", "Kubernetes"]
        jd_summary = "Build data products."
        hidden = 0

    class FakeDb:
        def get(self, _model, job_id):
            return FakeJob() if job_id == 7 else None

        def close(self):
            pass

    monkeypatch.setattr(mcp_tools, "SessionLocal", FakeDb)
    monkeypatch.setattr(
        mcp_tools,
        "_get_public_job",
        lambda db, job_id, include_old=False: FakeJob() if job_id == 7 else None,
    )
    monkeypatch.setattr(mcp_tools, "encode_text", lambda text: [0.1, 0.2])

    def fake_find_similar_jobs(vector, db, top_k):
        assert top_k == 20
        return [(7, 0.8)]

    monkeypatch.setattr(mcp_tools, "find_similar_jobs", fake_find_similar_jobs)
    monkeypatch.setattr(
        mcp_tools,
        "build_job_ats_terms",
        lambda **kwargs: [{"skill": "Python"}, {"skill": "Kubernetes"}],
    )
    monkeypatch.setattr(
        mcp_tools,
        "match_resume_against_job_terms",
        lambda **kwargs: {
            "matched": [{"skill": "Python", "resume_context": "Built Python services"}],
            "missing": [{"skill": "Kubernetes", "jd_context": "Kubernetes workloads"}],
            "match_percent": 50,
        },
    )

    data = json.loads(mcp_tools.match_resume_to_jobs("Built Python services", limit=2))

    assert data["privacy"]["stored"] is False
    assert data["privacy"]["uses_private_applications"] is False
    assert data["jobs"][0]["job"]["id"] == 7
    assert data["jobs"][0]["fit_score"] == 60
    assert data["jobs"][0]["matched_terms"] == ["Python"]
    assert data["jobs"][0]["missing_terms"] == ["Kubernetes"]
    assert "resume_text" not in json.dumps(data)


def test_match_resume_to_jobs_returns_an_explicit_empty_result_without_newest_fallback(
    monkeypatch,
):
    import mcp_tools

    class FakeDb:
        def close(self):
            pass

        def query(self, *_args):
            raise AssertionError("an empty semantic result must not query newest jobs")

    monkeypatch.setattr(mcp_tools, "SessionLocal", FakeDb)
    monkeypatch.setattr(mcp_tools, "encode_text", lambda _text: [0.1, 0.2])
    monkeypatch.setattr(mcp_tools, "find_similar_jobs", lambda *_args, **_kwargs: [])

    data = json.loads(mcp_tools.match_resume_to_jobs("Built Python services", limit=2))

    assert data["candidate_jobs_checked"] == 0
    assert data["jobs"] == []


def test_mcp_server_imports():
    import mcp_server

    assert mcp_server.mcp is not None


def test_local_mcp_direct_registrations_preserve_tool_metadata():
    import mcp_server

    tools = {tool.name: tool for tool in asyncio.run(mcp_server.mcp.list_tools())}
    expected = {
        "parse_resume": (
            "Parse resume text into sections, stats, and stable bullet IDs.", "resume_text", "resume_text",
        ),
        "score_resume": (
            "Score a resume with optional job-specific ATS blending.",
            "job_description,job_id,resume_text", "resume_text",
        ),
        "extract_skills": ("Extract ATS-style skill phrases from text.", "text", "text"),
        "compare_candidate_profile": (
            "Compare resume and LinkedIn/profile text for consistency gaps.",
            "profile_context,resume_text", "profile_context,resume_text",
        ),
        "validate_bullet_edit": (
            "Validate one proposed bullet rewrite and return gates plus final text.",
            "job_description,original,required_keywords,rewrite", "original,rewrite",
        ),
        "propose_resume_diff": (
            "Validate a rewrite against a resume bullet ID.",
            "bullet_id,job_description,required_keywords,resume_text,rewrite", "bullet_id,resume_text,rewrite",
        ),
    }

    for name, (description, properties, required) in expected.items():
        tool = tools[name]
        assert tool.description == description
        assert tool.inputSchema["title"] == f"{name}Arguments"
        assert ",".join(sorted(tool.inputSchema["properties"])) == properties
        assert ",".join(sorted(tool.inputSchema.get("required", []))) == required


def test_public_mcp_import_is_side_effect_free():
    import mcp_public
    from mcp.server.fastmcp.server import Settings as FastMCPSettings

    assert not hasattr(mcp_public, "mcp")
    assert mcp_public.create_mcp() is not mcp_public.create_mcp()
    assert FastMCPSettings.__pydantic_complete__ is True


def test_streamable_http_mcp_initializes():
    from mcp.shared.version import SUPPORTED_PROTOCOL_VERSIONS
    from starlette.testclient import TestClient

    import mcp_public

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": SUPPORTED_PROTOCOL_VERSIONS[-1],
            "capabilities": {},
            "clientInfo": {"name": "pytest", "version": "0"},
        },
    }

    server = mcp_public.create_mcp()
    with TestClient(server.streamable_http_app()) as client:
        response = client.post(
            "/",
            headers={
                "accept": "application/json, text/event-stream",
                "content-type": "application/json",
            },
            json=payload,
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "Job Hunter SG Jobs" in response.text


def test_fastapi_mcp_exact_path_initializes_without_redirect(monkeypatch):
    from fastapi.testclient import TestClient
    from mcp.shared.version import SUPPORTED_PROTOCOL_VERSIONS

    import main

    monkeypatch.setenv("MCP_API_KEY", "test-mcp-key")

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": SUPPORTED_PROTOCOL_VERSIONS[-1],
            "capabilities": {},
            "clientInfo": {"name": "pytest-parent", "version": "0"},
        },
    }

    with TestClient(main.app, follow_redirects=False) as client:
        response = client.post(
            "/mcp",
            headers={
                "accept": "application/json, text/event-stream",
                "content-type": "application/json",
                "authorization": "Bearer test-mcp-key",
            },
            json=payload,
        )
        tools_response = client.post(
            "/mcp",
            headers={
                "accept": "application/json, text/event-stream",
                "content-type": "application/json",
                "authorization": "Bearer test-mcp-key",
            },
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )

    assert response.status_code == 200
    assert "location" not in response.headers
    assert "Job Hunter SG Jobs" in response.text
    assert tools_response.status_code == 200
    # Some production MCP clients reject otherwise valid dotted tool names.
    assert "jobhunter_latest_jobs" in tools_response.text
    assert "jobhunter." not in tools_response.text


def test_fastapi_public_mcp_discovery_endpoints():
    from fastapi.testclient import TestClient

    import main

    with TestClient(main.app) as client:
        health_response = client.get("/health")
        sitemap_response = client.get("/sitemap.xml")

    assert health_response.status_code == 200
    assert health_response.json()["status"] == "ok"
    assert health_response.json()["server"] == "Job Hunter SG Jobs"
    assert health_response.json()["mcp_enabled"] is False
    assert sitemap_response.status_code == 200
    assert "https://job.kooexperience.com/llms.txt" in sitemap_response.text


def test_public_surface_uses_all_four_primitives_and_no_dotted_names():
    """Public tool names remain compatible with clients that reject dots."""
    import asyncio

    import mcp_public

    async def _surface():
        server = mcp_public.create_mcp()
        return (
            [t.name for t in await server.list_tools()],
            [str(r.uri) for r in await server.list_resources()],
            [t.uriTemplate for t in await server.list_resource_templates()],
            [p.name for p in await server.list_prompts()],
        )

    tools_, resources, templates, prompts = asyncio.run(_surface())

    assert not [n for n in tools_ + prompts if "." in n]
    assert "jobhunter_latest_jobs" in tools_
    # The two single-source variants collapsed into latest_jobs(source=...).
    assert not [n for n in tools_ if "careersgov" in n or "mycareersfuture" in n]
    assert "jobhunter://sources" in resources
    assert "jobhunter://job/{job_id}" in templates
    assert len(prompts) >= 2


def test_public_llms_inventory_matches_registered_public_tools():
    import mcp_public

    tool_names = {
        tool.name
        for tool in asyncio.run(mcp_public.create_mcp().list_tools())
    }
    llms_text = (Path(__file__).resolve().parents[2] / "frontend/public/llms.txt").read_text()

    inventory = next(
        line.removeprefix("- Public tools: ").rstrip(".").split(", ")
        for line in llms_text.splitlines()
        if line.startswith("- Public tools: ")
    )
    assert set(inventory) == tool_names


def test_every_public_resource_declares_a_mime_type():
    """FastMCP silently serves resources as text/plain when mime_type is omitted."""
    import asyncio

    import mcp_public

    resources = asyncio.run(mcp_public.create_mcp().list_resources())

    assert resources
    assert all(r.mimeType == "application/json" for r in resources)
