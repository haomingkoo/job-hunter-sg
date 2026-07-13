"""Public hosted MCP surface for Job Hunter SG jobs."""

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

import mcp_tools as tools


READONLY_DB = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
READONLY_EXTERNAL = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)


def _new_server() -> FastMCP:
    return FastMCP(
        "Job Hunter SG Jobs",
        instructions=(
            "Use these read-only tools to search the public Job Hunter SG database "
            "for Singapore roles. Start with jobhunter.source_stats when source "
            "coverage matters, use jobhunter.latest_jobs for recent openings, "
            "jobhunter.search_jobs for role or skill queries, and jobhunter.get_job "
            "for full details."
        ),
        website_url="https://job.kooexperience.com",
        host="0.0.0.0",
        streamable_http_path="/",
        stateless_http=True,
    )


def jobhunter_source_stats() -> str:
    """Report public job counts and freshness by source. Use this before comparing source coverage."""
    return tools.source_stats()


def jobhunter_latest_jobs(limit: int = 10) -> str:
    """Fetch the latest public Singapore jobs. Call jobhunter.get_job for full details."""
    return tools.latest_jobs(limit)


def jobhunter_latest_careersgov_jobs(limit: int = 10) -> str:
    """Fetch the latest public Careers@Gov jobs. Call jobhunter.get_job for full details."""
    return tools.latest_careersgov_jobs(limit)


def jobhunter_latest_mycareersfuture_jobs(limit: int = 10) -> str:
    """Fetch the latest public MyCareersFuture jobs. Call jobhunter.get_job for full details."""
    return tools.latest_mycareersfuture_jobs(limit)


def jobhunter_search_jobs(query: str, limit: int = 7) -> str:
    """Search public Singapore jobs semantically by role, skill, or company. Call jobhunter.get_job for full details."""
    return tools.search_jobs(query, limit)


def jobhunter_get_job(job_id: int) -> str:
    """Fetch one public job by ID from the Job Hunter SG database. Use after latest or search results."""
    return tools.get_job(job_id)


def jobhunter_ats_precompute_status() -> str:
    """Report parsed JD, term preview, and embedding readiness. Use this before relying on ATS matching coverage."""
    return tools.ats_precompute_status()


def jobhunter_recommend_skillsfuture_courses(skills: list[str], per_skill: int = 3) -> str:
    """Recommend official MySkillsFuture courses for public skill gaps. Use after identifying missing skills."""
    return tools.recommend_skillsfuture_courses(skills, per_skill)


def find_singapore_roles(role: str, must_have_skills: str = "", source: str = "") -> str:
    return (
        "Find suitable Singapore roles for this search.\n"
        f"Role: {role}\n"
        f"Must-have skills: {must_have_skills or 'not specified'}\n"
        f"Preferred source: {source or 'any public source'}\n\n"
        "First call jobhunter.source_stats. Then call jobhunter.search_jobs with "
        "a concise query built from the role and must-have skills. If a source "
        "is requested, explain whether that source has coverage in source_stats. "
        "For the best matches, call jobhunter.get_job and summarize title, "
        "company, salary/location if present, key requirements, and URL."
    )


def create_mcp() -> FastMCP:
    server = _new_server()
    server.tool(
        name="jobhunter.source_stats",
        title="Source Stats",
        annotations=READONLY_DB,
    )(jobhunter_source_stats)
    server.tool(
        name="jobhunter.latest_jobs",
        title="Latest Jobs",
        annotations=READONLY_DB,
    )(jobhunter_latest_jobs)
    server.tool(
        name="jobhunter.latest_careersgov_jobs",
        title="Latest CareersGov Jobs",
        annotations=READONLY_DB,
    )(jobhunter_latest_careersgov_jobs)
    server.tool(
        name="jobhunter.latest_mycareersfuture_jobs",
        title="Latest MyCareersFuture Jobs",
        annotations=READONLY_DB,
    )(jobhunter_latest_mycareersfuture_jobs)
    server.tool(
        name="jobhunter.search_jobs",
        title="Search Jobs",
        annotations=READONLY_DB,
    )(jobhunter_search_jobs)
    server.tool(
        name="jobhunter.get_job",
        title="Get Job",
        annotations=READONLY_DB,
    )(jobhunter_get_job)
    server.tool(
        name="jobhunter.ats_precompute_status",
        title="ATS Precompute Status",
        annotations=READONLY_DB,
    )(jobhunter_ats_precompute_status)
    server.tool(
        name="jobhunter.recommend_skillsfuture_courses",
        title="Recommend SkillsFuture Courses",
        annotations=READONLY_EXTERNAL,
    )(jobhunter_recommend_skillsfuture_courses)
    server.prompt(
        name="jobhunter.find_singapore_roles",
        title="Find Singapore Roles",
        description="Search the public Singapore job database and summarize source coverage, matches, and next steps.",
    )(find_singapore_roles)
    return server


mcp = create_mcp()
