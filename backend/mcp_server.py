"""MCP server for Job Hunter SG resume/job tools."""

import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BACKEND_DIR.parent
os.environ.setdefault("DATABASE_URL", f"sqlite:///{PROJECT_DIR / 'jobhunter.db'}")

import config
import mcp_tools as tools

from mcp.server.fastmcp import FastMCP


mcp = FastMCP("Job Hunter SG", host="0.0.0.0", streamable_http_path="/")


@mcp.tool()
def parse_resume(resume_text: str) -> str:
    """Parse resume text into sections, stats, and stable bullet IDs."""
    return tools.parse_resume(resume_text)


@mcp.tool()
def score_resume(resume_text: str, job_description: str = "", job_id: int | None = None) -> str:
    """Score a resume with optional job-specific ATS blending."""
    return tools.score_resume(resume_text, job_description, job_id)


@mcp.tool()
def extract_skills(text: str) -> str:
    """Extract ATS-style skill phrases from text."""
    return tools.extract_skills(text)


@mcp.tool()
def compare_candidate_profile(resume_text: str, profile_context: str) -> str:
    """Compare resume and LinkedIn/profile text for consistency gaps."""
    return tools.compare_candidate_profile(resume_text, profile_context)


@mcp.tool()
def get_job(job_id: int) -> str:
    """Fetch one job from the internal jobs DB."""
    return tools.get_job(job_id)


@mcp.tool(name="jobhunter_get_job")
def jobhunter_get_job(job_id: int) -> str:
    """Fetch one public job by ID from the internal jobs DB."""
    return tools.get_job(job_id)


@mcp.tool()
def search_jobs(
    query: str,
    limit: int = config.AGENT_SEARCH_JOBS_LIMIT,
    detail: bool = False,
) -> str:
    """Search internal jobs DB semantically."""
    return tools.search_jobs(query, limit, detail)


@mcp.tool(name="jobhunter_search_jobs")
def jobhunter_search_jobs(query: str, limit: int = 7) -> str:
    """Search public jobs semantically. Call jobhunter.get_job for full details."""
    return tools.search_jobs(query, limit)


@mcp.tool(name="jobhunter_latest_jobs")
def jobhunter_latest_jobs(limit: int = 10) -> str:
    """Fetch the latest public jobs from the internal jobs DB."""
    return tools.latest_jobs(limit)


@mcp.tool(name="jobhunter_latest_careersgov_jobs")
def jobhunter_latest_careersgov_jobs(limit: int = 10) -> str:
    """Fetch the latest public Careers@Gov jobs."""
    return tools.latest_careersgov_jobs(limit)


@mcp.tool(name="jobhunter_latest_mycareersfuture_jobs")
def jobhunter_latest_mycareersfuture_jobs(limit: int = 10) -> str:
    """Fetch the latest public MyCareersFuture jobs."""
    return tools.latest_mycareersfuture_jobs(limit)


@mcp.tool(name="jobhunter_source_stats")
def jobhunter_source_stats() -> str:
    """Report public job counts and freshness by source."""
    return tools.source_stats()


@mcp.tool(name="jobhunter_recommend_skillsfuture_courses")
def jobhunter_recommend_skillsfuture_courses(skills: list[str], per_skill: int = 3) -> str:
    """Recommend official MySkillsFuture courses for skill gaps."""
    return tools.recommend_skillsfuture_courses(skills, per_skill)


@mcp.tool(name="jobhunter_match_resume_to_jobs")
def jobhunter_match_resume_to_jobs(resume_text: str, limit: int = 10) -> str:
    """Rank public jobs against pasted resume text without storing it."""
    return tools.match_resume_to_jobs(resume_text, limit)


@mcp.tool(name="jobhunter_ats_precompute_status")
def jobhunter_ats_precompute_status() -> str:
    """Report public job ATS precompute readiness."""
    return tools.ats_precompute_status()


@mcp.tool()
def validate_bullet_edit(
    original: str,
    rewrite: str,
    job_description: str = "",
    required_keywords: list[str] | None = None,
) -> str:
    """Validate one proposed bullet rewrite and return gates plus final text."""
    return tools.validate_bullet_edit(original, rewrite, job_description, required_keywords)


@mcp.tool()
def propose_resume_diff(
    resume_text: str,
    bullet_id: str,
    rewrite: str,
    job_description: str = "",
    required_keywords: list[str] | None = None,
) -> str:
    """Validate a rewrite against a resume bullet ID."""
    return tools.propose_resume_diff(
        resume_text,
        bullet_id,
        rewrite,
        job_description,
        required_keywords,
    )


if __name__ == "__main__":
    mcp.run()
