"""Public hosted MCP surface for Job Hunter SG jobs.

Names use underscores, never dots. The MCP spec's charset allows dots but the
Claude API's tool-name validation (`[a-zA-Z0-9_-]`) does not, so a dot-namespaced
name is spec-legal and still broken on the largest client.
"""

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
            "Read-only access to the public Job Hunter SG database of Singapore roles. "
            "Read the jobhunter://sources resource when source coverage matters, "
            "jobhunter_search_jobs for role or skill queries, jobhunter_latest_jobs for "
            "recent openings (pass source to narrow to one board), and jobhunter_get_job "
            "or the jobhunter://job/{job_id} resource for full details."
        ),
        website_url="https://job.kooexperience.com",
        host="0.0.0.0",
        streamable_http_path="/",
        stateless_http=True,
    )


def jobhunter_latest_jobs(limit: int = 10, source: str = "") -> str:
    """Fetch the latest public Singapore jobs, newest first.

    Pass source to narrow to one board, e.g. "MyCareersFuture" or "Careers@Gov";
    omit it for all sources. Read jobhunter://sources for the available values.
    """
    return tools.latest_jobs(limit, source=source or None)


def jobhunter_search_jobs(query: str, limit: int = 7) -> str:
    """Search public Singapore jobs semantically by role, skill, or company. Call jobhunter_get_job for full details."""
    return tools.search_jobs(query, limit)


def jobhunter_get_job(job_id: int) -> str:
    """Fetch one public job by ID from the Job Hunter SG database. Use after latest or search results."""
    return tools.get_job(job_id)


def jobhunter_recommend_skillsfuture_courses(skills: list[str], per_skill: int = 3) -> str:
    """Recommend SkillsFuture courses for a list of skills. Use to close a gap found in a job's requirements."""
    return tools.recommend_skillsfuture_courses(skills, per_skill)


# ── Resources ────────────────────────────────────────────────────────────────
# Both were zero-argument tools returning the same content on every call, which is
# the static-resource heuristic rather than a tool.


def sources_resource() -> str:
    return tools.source_stats()


def ats_status_resource() -> str:
    return tools.ats_precompute_status()


def job_resource(job_id: str) -> str:
    return tools.get_job(int(job_id))


# ── Prompts ──────────────────────────────────────────────────────────────────


def find_singapore_roles(role: str, must_have_skills: str = "", source: str = "") -> str:
    return (
        "Find suitable Singapore roles for this search.\n"
        f"Role: {role}\n"
        f"Must-have skills: {must_have_skills or 'not specified'}\n"
        f"Preferred source: {source or 'any public source'}\n\n"
        "First read the jobhunter://sources resource. Then call jobhunter_search_jobs "
        "with a concise query built from the role and must-have skills. If a source "
        "is requested, explain whether that source has coverage. For the best matches, "
        "call jobhunter_get_job and summarize title, company, salary/location if "
        "present, key requirements, and URL."
    )


def close_a_skill_gap(role: str, current_skills: str = "") -> str:
    return (
        "Work out what this candidate is missing for a target role, then how to close it.\n"
        f"Target role: {role}\n"
        f"Skills they already have: {current_skills or 'not stated, ask first'}\n\n"
        "Call jobhunter_search_jobs for the role and open three or four of the results "
        "with jobhunter_get_job. Collect the requirements that recur across them, since "
        "a requirement in one posting is noise and a requirement in most is the real bar. "
        "Subtract what the candidate already has. Pass the remainder to "
        "jobhunter_recommend_skillsfuture_courses. Report the recurring requirements, the "
        "genuine gaps, and the courses, and say plainly which gaps no course fixes quickly."
    )


def create_mcp() -> FastMCP:
    server = _new_server()
    server.tool(
        name="jobhunter_latest_jobs",
        title="Latest Jobs",
        annotations=READONLY_DB,
    )(jobhunter_latest_jobs)
    server.tool(
        name="jobhunter_search_jobs",
        title="Search Jobs",
        annotations=READONLY_DB,
    )(jobhunter_search_jobs)
    server.tool(
        name="jobhunter_get_job",
        title="Get Job",
        annotations=READONLY_DB,
    )(jobhunter_get_job)
    server.tool(
        name="jobhunter_recommend_skillsfuture_courses",
        title="Recommend SkillsFuture Courses",
        annotations=READONLY_EXTERNAL,
    )(jobhunter_recommend_skillsfuture_courses)

    # mime_type is required: FastMCP silently serves every resource as text/plain
    # otherwise, whatever the return type.
    server.resource(
        "jobhunter://sources",
        name="sources",
        title="Job Sources and Freshness",
        description="Public job counts and last-updated time per source. Read before comparing source coverage.",
        mime_type="application/json",
    )(sources_resource)
    server.resource(
        "jobhunter://status/ats",
        name="ats-status",
        title="ATS Term Precompute Status",
        description="How much of the public corpus has precomputed ATS skill terms.",
        mime_type="application/json",
    )(ats_status_resource)
    server.resource(
        "jobhunter://job/{job_id}",
        name="job",
        title="Job by ID",
        description="One public job posting addressed directly by its ID.",
        mime_type="application/json",
    )(job_resource)

    server.prompt(
        name="find_singapore_roles",
        title="Find Singapore Roles",
        description="Search the public Singapore job database and summarize source coverage, matches, and next steps.",
    )(find_singapore_roles)
    server.prompt(
        name="close_a_skill_gap",
        title="Close a Skill Gap",
        description="Find what a target role keeps asking for, subtract what the candidate has, and recommend courses for the rest.",
    )(close_a_skill_gap)
    return server


mcp = create_mcp()
