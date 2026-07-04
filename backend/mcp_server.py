"""MCP stdio server for Job Hunter SG resume/job tools."""

import os
from pathlib import Path

os.chdir(Path(__file__).resolve().parent)

import config
import mcp_tools as tools

try:
    from mcp.server.mcpserver import MCPServer
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as MCPServer


mcp = MCPServer("Job Hunter SG")


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


@mcp.tool()
def search_jobs(
    query: str,
    limit: int = config.AGENT_SEARCH_JOBS_LIMIT,
    detail: bool = False,
) -> str:
    """Search internal jobs DB semantically."""
    return tools.search_jobs(query, limit, detail)


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
