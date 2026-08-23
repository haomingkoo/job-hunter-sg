"""MCP server for Job Hunter SG resume/job tools."""

import config
import mcp_tools as tools

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.server import Settings as FastMCPSettings


FastMCPSettings.model_rebuild()
mcp = FastMCP("Job Hunter SG", host="0.0.0.0", streamable_http_path="/")

mcp.tool()(tools.parse_resume)
mcp.tool()(tools.score_resume)
mcp.tool()(tools.extract_skills)
mcp.tool(
    description="Compare resume and LinkedIn/profile text for consistency gaps.",
)(tools.compare_candidate_profile)


@mcp.tool(name="jobhunter_get_job")
def jobhunter_get_job(job_id: int) -> str:
    """Fetch one public job by ID from the internal jobs DB."""
    return tools.get_job(job_id)


@mcp.tool(name="jobhunter_search_jobs")
def jobhunter_search_jobs(
    query: str,
    limit: int = config.AGENT_SEARCH_JOBS_LIMIT,
    detail: bool = False,
) -> str:
    """Search jobs semantically by role, skill, or company. Call jobhunter_get_job for full details."""
    return tools.search_jobs(query, limit, detail)


@mcp.tool(name="jobhunter_latest_jobs")
def jobhunter_latest_jobs(limit: int = 10, source: str = "") -> str:
    """Fetch the latest jobs, newest first.

    Pass source to narrow to one board, e.g. "MyCareersFuture" or "Careers@Gov";
    omit it for all sources. Read jobhunter://sources for the available values.
    """
    return tools.latest_jobs(limit, source=source or None)


@mcp.tool(name="jobhunter_recommend_skillsfuture_courses")
def jobhunter_recommend_skillsfuture_courses(skills: list[str], per_skill: int = 3) -> str:
    """Recommend official MySkillsFuture courses for skill gaps."""
    return tools.recommend_skillsfuture_courses(skills, per_skill)


@mcp.tool(name="jobhunter_match_resume_to_jobs")
def jobhunter_match_resume_to_jobs(resume_text: str, limit: int = 10) -> str:
    """Rank public jobs against pasted resume text without storing it."""
    return tools.match_resume_to_jobs(resume_text, limit)

mcp.tool()(tools.validate_bullet_edit)
mcp.tool()(tools.propose_resume_diff)


@mcp.resource(
    "jobhunter://sources",
    name="sources",
    title="Job Sources and Freshness",
    description="Job counts and last-updated time per source.",
    mime_type="application/json",
)
def sources_resource() -> str:
    return tools.source_stats()


@mcp.resource(
    "jobhunter://status/ats",
    name="ats-status",
    title="ATS Term Precompute Status",
    description="How much of the corpus has precomputed ATS skill terms.",
    mime_type="application/json",
)
def ats_status_resource() -> str:
    return tools.ats_precompute_status()


@mcp.resource(
    "jobhunter://job/{job_id}",
    name="job",
    title="Job by ID",
    description="One job posting addressed directly by its ID.",
    mime_type="application/json",
)
def job_resource(job_id: str) -> str:
    return tools.get_job(int(job_id))


if __name__ == "__main__":
    mcp.run()
