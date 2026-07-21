"""Declarative tool access by orchestration role."""

from ..tools import extract_skills, get_job, propose_edit, score_resume, search_jobs


ORCHESTRATOR_TOOLS = (
    search_jobs,
    get_job,
    score_resume,
    extract_skills,
    propose_edit,
)
# Assessment synthesis is read-only. Editing is a separate explicit capability.
SYNTHESIS_TOOLS: tuple = ()
