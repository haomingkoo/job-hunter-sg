"""V3-specific tools bound to the open-agent orchestrator.

Two audiences share this module. The target-assessment runner binds
`ask_candidate`, `read_candidate_evidence`, `read_target_job` and
`propose_resume_edit` around a `TargetAssessmentRequest`. The conversational
coordinator binds those four plus `read_shortlist` and `search_jobs` around a
`ConversationContext`. Both shapes arrive through the same `context`
ContextVars, so a tool that needs a field the other shape does not carry says
so rather than dereferencing `None`.

`search_jobs` here is not the assessment runner's `guarded_search_jobs`
(runner.py), which wraps `resume_agent.tools.search_jobs` with `detail=False`.
This one goes through the typed DiscoveryPort on the conversation context, the
same port the SearchJobs command uses.
"""

from __future__ import annotations

from dataclasses import asdict
from types import SimpleNamespace
from typing import Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field

import config
from validation_gates import _extract_numbers, run_all_gates

from ..conversation_model import PreferenceUpdatePayload
from ..interface import PreferenceUpdate
from . import context
from .guardrails import has_repeated_call


_NO_CONTEXT = {"ok": False, "failure_type": "business", "reason": "No active assessment context."}
# A tool that answers the same question twice has told the agent nothing new.
_REPEATED_CALL = {
    "ok": False,
    "failure_type": "validation",
    "reason": "identical_call_no_new_information",
    "retry": False,
}
_NO_CONVERSATION = {
    "ok": False,
    "failure_type": "business",
    "reason": "No active conversation context.",
}


class _ResumeMatch(BaseModel):
    statement: str = Field(min_length=1)
    resume_quote: str = Field(min_length=1)


class _RankedMatch(BaseModel):
    job_id: int
    matched: list[_ResumeMatch] = Field(min_length=1)
    stretch: list[_ResumeMatch] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    level_fit: Literal["aligned", "stretch", "below_candidate_level", "unclear"]
    pay_position: Literal[
        "above_peer_median",
        "near_peer_median",
        "below_peer_median",
        "salary_not_stated",
        "insufficient_context",
    ]


class _WriteShortlistPayload(BaseModel):
    matches: list[_RankedMatch] = Field(min_length=1)


class _RecordPreferencesPayload(BaseModel):
    updates: list[PreferenceUpdatePayload] = Field(min_length=1)


def _posting(job) -> dict:
    """A posting as the coordinator needs to reason about it.

    `description` and `skills` are here on purpose. Naming a job is not the whole
    bug: the reply that prompted #146 asked the candidate to paste a job
    description, and an agent that can see only a title still has to. Source
    provenance and posting variants are omitted -- those are what the UI renders
    from `case_facts`, not what a reply is written from.
    """
    return {
        "job_id": job.job_id,
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "salary": job.salary,
        "seniority": job.seniority,
        "employment_type": job.employment_type,
        "skills": list(job.skills),
        "description": job.description,
        "sector": job.sector,
        "parsed_requirements": job.parsed_jd or {},
        "ats_terms": list(job.job_terms_preview),
        "salary_context": job.salary_context,
        "fact_context_status": job.fact_context_status,
    }


@tool
def ask_candidate(questions: list[str]) -> dict:
    """Ask the candidate about real evidence gaps. Send every question you have at once.

    Pass all the gaps you want closed in one call. Calling this pauses the whole
    assessment until the candidate replies, so asking three times in a row costs
    them three waits; asking once costs one. Only ask about gaps you cannot
    resolve from their resume or an answer they already gave.

    This tool must be bound with interrupt_on={"ask_candidate": True} on the
    orchestrator agent -- calling it pauses the graph before any further tool
    call executes. The candidate's next message answers it; that answer
    becomes citable evidence for later propose_resume_edit calls in this
    thread. This is enforced by the interrupt, not by prompted convention.
    """
    return {"ok": True, "questions": list(questions)}


@tool
def read_candidate_evidence() -> dict:
    """Read the candidate's evidence-cited profile fields for the active run.

    Returns each field with its resume_evidence_ids, so a citation in a
    persona submission or a proposed edit can point at real evidence.
    """
    request = context.current_request()
    if request is None:
        return dict(_NO_CONTEXT)
    history = context.tool_call_history()
    if history is not None and has_repeated_call(history, "read_candidate_evidence", {}):
        return dict(_REPEATED_CALL)
    if request.candidate_profile is None:
        # Say what to do instead. Live on 2026-08-02 the coordinator called this
        # twelve times against a thread with no profile, each time told only what
        # was missing, until the run hit its iteration cap. A refusal a model
        # cannot act on is a refusal it will retry.
        return {
            "ok": False,
            "failure_type": "business",
            "reason": (
                "No evidence profile exists for this thread yet, and calling this "
                "again will not create one. The candidate's resume is in the "
                "resume block of this turn, one block per line as "
                "'block_id: text': read it from there instead, and cite those "
                "block IDs in propose_resume_edit."
            ),
            "retry": False,
        }
    return {
        "ok": True,
        "fields": [asdict(field) for field in request.candidate_profile.fields],
    }


@tool
def read_target_job() -> dict:
    """Read the target job posting and its derived role-success criteria for the active run."""
    request = context.current_request()
    if request is None:
        return dict(_NO_CONTEXT)
    if request.target_job is None or request.role_profile is None:
        return {
            "ok": False,
            "failure_type": "business",
            "reason": "No target job has been selected in this thread yet; read_shortlist first.",
        }
    return {
        "ok": True,
        "target_job": asdict(request.target_job),
        "role_profile": asdict(request.role_profile),
    }


@tool
def read_shortlist() -> dict:
    """Read the job postings this thread has already found or shortlisted.

    Includes anything found earlier in this same turn. Read this before
    answering anything about "these roles", "the jobs you found" or a job the
    candidate names: the postings are not in the conversation transcript, and a
    search run by the Search button or by an earlier turn reaches you only
    through this tool. Never ask the candidate to paste a posting that is
    already here.
    """
    from ..coordinator.context import current_conversation, merged_recommendations

    conversation = current_conversation()
    if conversation is None:
        return dict(_NO_CONVERSATION)
    # Mid-turn, not as the turn started: an agent that just searched and then
    # asks what it has must see what it just found, and it must be the same list
    # RecruitmentTeam writes to the thread.
    latest_query, recommendations = merged_recommendations(conversation)
    return {
        "ok": True,
        "latest_search_query": latest_query,
        "recommendations": [_posting(job) for job in recommendations],
        "shortlisted_jobs": [_posting(job) for job in conversation.shortlisted_jobs],
        "selected_target_job_id": (
            conversation.target_job.job_id if conversation.target_job else None
        ),
        "candidate_profile_available": conversation.candidate_profile is not None,
        "published_matches": (
            list(conversation.drafted_matches)
            if conversation.drafted_matches
            else (
                []
                if any(result.jobs for result in conversation.search_results)
                else list(conversation.published_matches)
            )
        ),
    }


@tool(args_schema=_RecordPreferencesPayload)
def record_preferences(updates: list[PreferenceUpdatePayload]) -> dict:
    """Record preferences explicitly stated or withdrawn in the latest message.

    Use one update per independently retractable fact. evidence_quote must be an
    exact phrase from the candidate's latest message. A removal's value must
    exactly match the stored preference it withdraws. Put an independent exclusion
    such as "not entry level" in constraints; use seniority for a desired level or
    career track such as "senior individual contributor".
    """
    from ..coordinator.context import current_conversation

    conversation = current_conversation()
    if conversation is None:
        return dict(_NO_CONVERSATION)
    parsed = [PreferenceUpdatePayload.model_validate(update) for update in updates]
    invalid_quotes = [
        update.evidence_quote
        for update in parsed
        if update.evidence_quote.strip() not in conversation.latest_user_message
    ]
    if invalid_quotes:
        return {
            "accepted": False,
            "reason": "Every preference needs an exact quote from the latest message.",
            "invalid_quotes": invalid_quotes,
        }
    stored = {(fact.field, fact.value) for fact in conversation.preferences}
    invalid_removals = [
        {"field": update.field, "value": update.value}
        for update in parsed
        if update.operation == "remove" and (update.field, update.value.strip()) not in stored
    ]
    if invalid_removals:
        return {
            "accepted": False,
            "reason": "A removal must exactly match a stored preference.",
            "invalid_removals": invalid_removals,
        }
    conversation.drafted_preferences.clear()
    conversation.drafted_preferences.extend(
        PreferenceUpdate(
            field=update.field,
            value=update.value.strip(),
            evidence_quote=update.evidence_quote.strip(),
            operation=update.operation,
        )
        for update in parsed
    )
    return {"accepted": True, "recorded": len(parsed)}


@tool(args_schema=_WriteShortlistPayload)
def write_shortlist(matches: list[_RankedMatch]) -> dict:
    """Publish the ordered jobs worth showing, with evidence-backed rationales.

    Use after reading or searching postings. Order the entries best-first and
    omit roles that violate the candidate's stated constraints. Every matched
    point needs an exact resume quote. Level and pay are separate judgments;
    salary context is evidence, never a formula or an imputed offer.
    """
    from ..coordinator.context import current_conversation, merged_recommendations

    conversation = current_conversation()
    if conversation is None:
        return dict(_NO_CONVERSATION)
    _, recommendations = merged_recommendations(conversation)
    known_jobs = {
        job.job_id: job for job in (*recommendations, *conversation.shortlisted_jobs)
    }
    parsed = [_RankedMatch.model_validate(match) for match in matches]
    job_ids = [match.job_id for match in parsed]
    if len(job_ids) != len(set(job_ids)):
        return {
            "accepted": False,
            "reason": "Each job may appear only once in the published shortlist.",
        }
    unknown = [job_id for job_id in job_ids if job_id not in known_jobs]
    if unknown:
        return {
            "accepted": False,
            "reason": f"Unknown job IDs: {', '.join(str(job_id) for job_id in unknown)}.",
            "known_job_ids": list(known_jobs),
        }

    blocks = (conversation.resume_document or {}).get("blocks") or []
    resume_text = "\n".join(str(block.get("text") or "") for block in blocks)
    for match in parsed:
        for point in (*match.matched, *match.stretch):
            quote = point.resume_quote.strip()
            if quote not in resume_text:
                return {
                    "accepted": False,
                    "reason": (
                        f"Job {match.job_id} cites a phrase that is not verbatim in "
                        "the resume. Copy an exact quote from read_candidate_evidence."
                    ),
                    "job_id": match.job_id,
                    "invalid_quote": quote,
                }
        job = known_jobs[match.job_id]
        has_salary = bool(job.salary.strip())
        if match.pay_position == "salary_not_stated" and has_salary:
            return {
                "accepted": False,
                "reason": f"Job {match.job_id} states a salary; do not label it missing.",
            }
        if match.pay_position != "salary_not_stated" and not has_salary:
            return {
                "accepted": False,
                "reason": f"Job {match.job_id} states no salary; do not infer one.",
            }
        if (
            match.pay_position
            in {"above_peer_median", "near_peer_median", "below_peer_median"}
            and job.salary_context is None
        ):
            return {
                "accepted": False,
                "reason": f"Job {match.job_id} has no peer salary context.",
            }

    conversation.drafted_matches.clear()
    conversation.drafted_matches.extend(match.model_dump() for match in parsed)
    return {"accepted": True, "published_job_ids": job_ids}


@tool
def search_jobs(query: str) -> dict:
    """Search the current internal Singapore job corpus by role or responsibility.

    Write `query` positively, in the words a posting would use: the search
    matches on meaning and cannot express "not", so naming what to avoid
    retrieves exactly that. Judge the results yourself and search again with a
    better phrase if they are wrong. Results land on the candidate's shortlist,
    so they see what you found.

    Seniority labels and salary context are facts in each result. Judge them
    together; do not assume an employer's self-reported level is reliable.
    """
    from ..coordinator.context import current_conversation

    conversation = current_conversation()
    if conversation is None:
        return dict(_NO_CONVERSATION)

    args = {"query": query}
    history = context.tool_call_history()
    if history is not None and has_repeated_call(history, "search_jobs", args):
        return {
            "ok": False,
            "failure_type": "validation",
            "reason": "identical_call_no_new_information",
        }

    result = conversation.discovery.search_jobs(query)
    if history is not None:
        history.append(SimpleNamespace(tool_calls=[{"name": "search_jobs", "args": args}]))
    # Every result is recorded, failures included, so the turn's search history
    # stays observable. Which of them may change the thread is decided when the
    # sink is drained, not here.
    conversation.search_results.append(result)

    if result.failure_type:
        # Returned, not raised. A source failure mid-turn is information the
        # agent can act on, not the end of the turn.
        return {
            "ok": False,
            "failure_type": result.failure_type,
            "retryable": result.retryable,
            "query": result.query,
        }
    return {
        "ok": True,
        "query": result.query,
        "valid_empty": result.valid_empty,
        "truncated": result.truncated,
        "jobs": [_posting(job) for job in result.jobs],
    }


@tool
def propose_resume_edit(block_id: str, rewrite: str) -> dict:
    """Draft an in-place, evidence-safe rewrite of one existing resume block.

    `block_id` must be a canonical block ID visible in the active resume
    document. `rewrite` must replace that block's text without introducing
    new numeric facts and must stay within one block (no line breaks) -- this
    tool cannot insert or delete a block. A valid proposal remains pending
    until the candidate explicitly accepts it.
    """
    document = context.current_document()
    edits = context.proposed_edits()
    if document is None or edits is None:
        return {"accepted": False, "reason": "No active assessment context.", "block_id": block_id}
    if len(edits) >= config.OPEN_AGENT_MAX_PROPOSED_EDITS:
        return {
            "accepted": False,
            "reason": "Per-run proposed-edit cap reached; checkpoint back to the candidate before proposing more.",
            "block_id": block_id,
            "checkpoint_required": True,
        }
    blocks = document.get("blocks", [])
    block = next((b for b in blocks if b.get("id") == block_id), None)
    if not block:
        # Name them. Block IDs are opaque hashes, so an agent that has not been
        # handed one cannot derive it from any resume text it can read. Live on
        # 2026-08-02 the coordinator guessed, was told only "Unknown resume
        # block.", guessed again, then repeated the identical call to the
        # iteration cap -- a 503 on "improve my resume for these roles".
        known = [str(b.get("id")) for b in blocks]
        return {
            "accepted": False,
            "reason": f"Unknown resume block. Editable block IDs: {', '.join(known)}.",
            "block_id": block_id,
            "known_block_ids": known,
        }

    clean_rewrite = (rewrite or "").strip()
    if "\n" in clean_rewrite or "\r" in clean_rewrite:
        return {"accepted": False, "reason": "A replacement must stay within one resume block.", "block_id": block_id}

    original_text = str(block.get("text") or "")
    new_numbers = _extract_numbers(clean_rewrite) - _extract_numbers(original_text)
    if new_numbers:
        return {
            "accepted": False,
            "reason": f"Unsupported numeric facts: {', '.join(sorted(new_numbers))}",
            "block_id": block_id,
        }

    failed = [gate for gate in run_all_gates(original_text, clean_rewrite) if not gate.passed]
    if failed:
        return {"accepted": False, "reason": "; ".join(gate.message for gate in failed), "block_id": block_id}

    edits.append({
        "block_id": block_id,
        "section_key": block.get("section_key", ""),
        "entry_id": block.get("entry_id", ""),
        "original": original_text,
        "rewrite": clean_rewrite,
        "document_revision": document.get("revision"),
        "status": "pending",
    })
    return {"accepted": True, "application_status": "pending_user_review", "block_id": block_id, "rewrite": clean_rewrite}
