"""Tools shared by conversational and target-assessment agent loops."""

from __future__ import annotations

from dataclasses import asdict
from typing import Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field

import config
from employer_filter import company_name_matches, is_recruitment_employer
from validation_gates import extract_numbers, run_all_gates

from ..assessment_contracts import (
    TargetAssessmentRequest,
    TargetSynthesisSubmission,
    render_target_synthesis,
    validate_target_synthesis,
)
from ..conversation_model import PreferenceUpdatePayload
from ..fair_hiring import mentions_protected_status
from ..interface import ConfirmedEvidenceFact, PreferenceUpdate, confirmed_evidence_fact
from ..resume_edit_evidence import ResumeEditEvidenceRequest
from . import context
from .evidence_view import candidate_evidence_view, target_role_view


_NO_CONTEXT = {"ok": False, "failure_type": "business", "reason": "No active assessment context."}
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


class _RecordCandidateEvidencePayload(BaseModel):
    evidence_quotes: list[str] = Field(min_length=1)


class _PlanStep(BaseModel):
    step: str = Field(min_length=1)
    status: Literal["pending", "in_progress", "completed"]


class _WritePlanPayload(BaseModel):
    steps: list[_PlanStep] = Field(min_length=1)


def _posting(job) -> dict:
    """A posting as the coordinator needs to reason about it.

    `description` and `skills` are here on purpose. Naming a job is not the whole
    bug: the reply that prompted #146 asked the candidate to paste a job
    description, and an agent that can see only a title still has to. Source
    provenance and posting variants are omitted -- those are what the UI renders
    from `case_facts`, not what a reply is written from.
    """
    return {
        "data_classification": job.data_classification,
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
        "employer_relationship": job.employer_relationship,
        "employer_relationship_evidence": job.employer_relationship_evidence,
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
    protected_questions = [question for question in questions if mentions_protected_status(question)]
    if protected_questions:
        return {
            "ok": False,
            "failure_type": "validation",
            "reason": (
                "Do not ask about nationality, citizenship, permanent-resident, residency, "
                "or immigration status. If the posting genuinely requires legal eligibility, "
                "ask only whether the candidate is authorised to work in the location or "
                "requires employer sponsorship."
            ),
            "retry": False,
        }
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
    if request.candidate_profile is None:
        raise RuntimeError("candidate evidence tool requires a current candidate profile")
    return {
        "ok": True,
        "data_classification": "untrusted_candidate_data",
        **candidate_evidence_view(request),
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
    evidence = target_role_view(request)
    return {
        "ok": True,
        "data_classification": "untrusted_job_data",
        "target_job": evidence["target_job"],
        "role_profile": evidence["role_success_profile"],
        "fair_hiring_note": (
            "Protected-status preferences are excluded from assessment and must not be "
            "mentioned or scored. Lawful work-authorisation requirements remain allowed."
        ),
    }


@tool(args_schema=TargetSynthesisSubmission)
def submit_target_assessment_synthesis(claims: list[dict]) -> dict:
    """Submit the final candidate-facing assessment as evidence-linked claims.

    Every claim cites role criteria. Strengths also cite linked candidate-profile
    fields plus their resume evidence, or candidate-confirmed evidence. Do not add
    market colour, character judgments, hiring probability, or arithmetic derived
    from dates. A rejected submission can be corrected and submitted again.
    """

    request = context.current_request()
    if not isinstance(request, TargetAssessmentRequest):
        return {**_NO_CONTEXT, "retry": False}
    missing_specialists = context.missing_required_specialists()
    if missing_specialists:
        return {
            "ok": False,
            "accepted": False,
            "retry": True,
            "failure_type": "validation",
            "failure_code": "required_specialists_missing",
            "missing_specialists": list(missing_specialists),
            "reason": (
                "Delegate to every missing specialist and wait for each accepted structured "
                "submission before submitting the synthesis again."
            ),
        }
    submission = TargetSynthesisSubmission(claims=claims)
    failures = validate_target_synthesis(request, submission)
    if failures:
        attempt = context.record_synthesis_validation_failure(failures[0])
        retry = attempt < config.RECRUITMENT_SYNTHESIS_VALIDATION_ATTEMPTS
        return {
            "ok": False,
            "accepted": False,
            "retry": retry,
            "failure_type": "validation",
            "failure_code": "structured_output_invalid",
            "validation_code": failures[0],
            "validation_codes": list(failures),
            "attempt": attempt,
            "attempt_limit": config.RECRUITMENT_SYNTHESIS_VALIDATION_ATTEMPTS,
            "reason": (
                "Synthesis rejected. Keep each claim close to its cited records, cite only "
                "known linked IDs, and remove unsupported durations, ranges, percentages, "
                "scores, money amounts, or speculative market and hiring assertions from the "
                "named claim. Do not replace a rejected quantity with number words. Correct "
                "the named claim and submit once more."
                if retry
                else "Synthesis validation budget exhausted; do not submit again."
            ),
        }
    rendered = render_target_synthesis(submission)
    context.store_submitted_synthesis(
        rendered,
        [claim.model_dump() for claim in submission.claims],
    )
    return {"ok": True, "accepted": True, "claim_count": len(submission.claims)}


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
        "selected_target_job_id": (conversation.target_job.job_id if conversation.target_job else None),
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


@tool(args_schema=_RecordCandidateEvidencePayload)
def record_candidate_evidence(evidence_quotes: list[str]) -> dict:
    """Store factual evidence explicitly stated in the candidate's latest message.

    Each quote must occur exactly in the latest message. Candidate evidence is not a
    role, salary, location, seniority, or constraint preference. The returned IDs can
    be cited by propose_resume_edit in this turn or a later turn.
    """
    from ..coordinator.context import current_conversation

    conversation = current_conversation()
    if conversation is None:
        return dict(_NO_CONVERSATION)
    quotes = [quote.strip() for quote in evidence_quotes if quote.strip()]
    invalid = [quote for quote in quotes if quote not in conversation.latest_user_message]
    if not quotes or invalid:
        return {
            "accepted": False,
            "reason": "Every candidate-evidence quote must occur exactly in the latest message.",
            "invalid_quotes": invalid,
        }
    known = {fact.evidence_id for fact in (*conversation.confirmed_evidence, *conversation.drafted_confirmed_evidence)}
    recorded: list[ConfirmedEvidenceFact] = []
    for quote in quotes:
        fact = confirmed_evidence_fact(
            quote,
            source_run_id=conversation.latest_user_run_id,
            source_message_id=conversation.latest_user_message_id,
        )
        if fact.evidence_id in known:
            continue
        conversation.drafted_confirmed_evidence.append(fact)
        recorded.append(fact)
        known.add(fact.evidence_id)
    return {
        "accepted": True,
        "recorded": len(recorded),
        "evidence_ids": [fact.evidence_id for fact in recorded],
    }


@tool(args_schema=_WritePlanPayload)
def write_plan(steps: list[_PlanStep]) -> dict:
    """Publish or revise the candidate-visible plan for this recruitment goal.

    Replace the whole plan with the current truthful state. Keep steps concise and
    outcome-oriented. Call when beginning multi-step work or when progress or
    candidate feedback materially changes the plan. Repeating the
    current plan is an accepted no-op; a changed plan replaces it.
    """
    from ..coordinator.context import current_conversation

    conversation = current_conversation()
    if conversation is None:
        return dict(_NO_CONVERSATION)
    parsed = [_PlanStep.model_validate(step) for step in steps]
    normalized = [step.step.strip().casefold() for step in parsed]
    if len(normalized) != len(set(normalized)):
        return {
            "accepted": False,
            "reason": "Each plan step must be distinct.",
        }
    next_plan = [step.model_dump() for step in parsed]
    current_plan = conversation.drafted_plan or list(conversation.plan)
    if next_plan == current_plan:
        return {"accepted": True, "recorded": len(parsed), "changed": False}
    conversation.drafted_plan.clear()
    conversation.drafted_plan.extend(next_plan)
    return {"accepted": True, "recorded": len(parsed), "changed": True}


@tool(args_schema=_WriteShortlistPayload)
def write_shortlist(matches: list[_RankedMatch]) -> dict:
    """Publish the ordered jobs worth showing, with evidence-backed rationales.

    Use after reading or searching postings. Order the entries best-first and
    omit roles that violate the candidate's stated constraints. Every matched
    point needs an exact resume quote. Level and pay are separate judgments;
    salary context is evidence, never a formula or an imputed offer.
    In a profile-backed general search, the tool reports and omits jobs with no
    direct profile-term match. A named-employer search still keeps visible
    stretch roles from the company the candidate explicitly requested.
    """
    from ..coordinator.context import current_conversation, merged_recommendations

    conversation = current_conversation()
    if conversation is None:
        return dict(_NO_CONVERSATION)
    _, recommendations = merged_recommendations(conversation)
    known_jobs = {job.job_id: job for job in (*recommendations, *conversation.shortlisted_jobs)}
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

    latest_search = conversation.search_results[-1] if conversation.search_results else None
    excluded: list[int] = []
    if latest_search is not None:
        latest_job_ids = {job.job_id for job in latest_search.jobs}
        ineligible = [
            job_id
            for job_id in job_ids
            if job_id not in latest_job_ids
            or (latest_search.company and not company_name_matches(known_jobs[job_id].company, latest_search.company))
            or (
                latest_search.direct_employers_only
                and is_recruitment_employer(
                    known_jobs[job_id].company,
                    description=known_jobs[job_id].description,
                )
            )
        ]
        if ineligible:
            return {
                "accepted": False,
                "reason": (
                    "The shortlist includes jobs outside the latest employer constraints. "
                    "Use only jobs returned by the constrained search."
                ),
                "ineligible_job_ids": ineligible,
            }

        receipt = latest_search.ranking_receipt
        if receipt is not None and receipt.candidate_profile_used and not latest_search.company:
            evidence_matches = {
                item.job_id: item.profile_term_match_count
                for item in receipt.jobs
            }
            excluded = [
                match.job_id
                for match in parsed
                if evidence_matches.get(match.job_id, 0) == 0
            ]
            if excluded:
                parsed = [match for match in parsed if match.job_id not in excluded]
                job_ids = [match.job_id for match in parsed]
                if not parsed:
                    return {
                        "accepted": False,
                        "reason": (
                            "None of these jobs has a direct profile-term match. "
                            "Refine the search or explain that no evidence-supported match was found."
                        ),
                        "excluded_job_ids": excluded,
                    }

    blocks = (conversation.resume_document or {}).get("blocks") or []
    resume_text = "\n".join(str(block.get("text") or "") for block in blocks)
    pay_position_corrections: list[dict[str, object]] = []
    for index, match in enumerate(parsed):
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
        if (
            match.pay_position == "salary_not_stated"
            and has_salary
            and job.salary_context is None
        ):
            parsed[index] = match.model_copy(update={"pay_position": "insufficient_context"})
            pay_position_corrections.append(
                {
                    "job_id": match.job_id,
                    "from": "salary_not_stated",
                    "to": "insufficient_context",
                    "reason": "The posting states salary but has no peer salary context.",
                }
            )
            continue
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
            match.pay_position in {"above_peer_median", "near_peer_median", "below_peer_median"}
            and job.salary_context is None
        ):
            return {
                "accepted": False,
                "reason": f"Job {match.job_id} has no peer salary context.",
            }

    conversation.drafted_matches.clear()
    conversation.drafted_matches.extend(match.model_dump() for match in parsed)
    result = {"accepted": True, "published_job_ids": job_ids}
    if excluded:
        result["excluded_job_ids"] = excluded
        result["exclusion_reason"] = "No direct profile-term match."
    if pay_position_corrections:
        result["pay_position_corrections"] = pay_position_corrections
    return result


@tool
def search_jobs(
    query: str,
    company: str = "",
    direct_employers_only: bool = True,
    exclude_junior: bool = False,
    singapore_only: bool = True,
    title_phrase: str = "",
) -> dict:
    """Search the current internal Singapore job corpus by role or responsibility.

    Write `query` positively, in the words a posting would use: the search
    matches on meaning and cannot express "not", so naming what to avoid
    retrieves exactly that. Judge the results yourself and search again with a
    better phrase if they are wrong. Results land on the candidate's shortlist,
    so they see what you found.

    `direct_employers_only` is retained as a compatibility field. When true,
    it excludes postings with known recruitment-agency or other intermediary
    evidence. Employer relationships without that evidence remain unverified
    and may be included, so do not call the results verified direct-employer
    postings. Pass `company` when the candidate names a target employer;
    matching uses whole normalized words. Set `direct_employers_only=False`
    only when the candidate wants agency-listed roles. Set
    `exclude_junior=True` when the candidate's stated target or evidence
    clearly rules out entry-level work.
    Seniority labels and salary context are facts in each result. Judge them
    together; do not assume an employer's self-reported level is reliable.
    Keep `singapore_only=True` unless the candidate explicitly asks for overseas roles.
    Pass `title_phrase="manager"` when the candidate explicitly targets manager-level
    titles and engineer-level retrieval would crowd those roles out.
    """
    from ..coordinator.context import current_conversation

    conversation = current_conversation()
    if conversation is None:
        return dict(_NO_CONVERSATION)

    batch = conversation.recommender.search(
        conversation.candidate_profile,
        conversation.discovery,
        query,
        company=company,
        direct_employers_only=direct_employers_only,
        exclude_junior=exclude_junior,
        singapore_only=singapore_only,
        title_phrase=title_phrase,
    )
    result = batch.search_result
    # Every result is recorded, failures included, so the turn's search history
    # stays observable. Which of them may change the thread is decided when the
    # sink is drained, not here.
    conversation.search_results.append(result)

    if result.failure_type:
        from ..recovery import classify_failure

        decision = classify_failure(result.failure_code or "unclassified_failure")
        # Returned, not raised. A source failure mid-turn is information the
        # agent can act on, not the end of the turn.
        return {
            "ok": False,
            "failure_type": decision.failure_type,
            "failure_code": decision.failure_code,
            "retryable": decision.retryable,
            "retry": decision.retryable,
            "recovery_action": decision.recovery_action,
            "query": result.query,
        }
    return {
        "ok": True,
        "query": result.query,
        "valid_empty": result.valid_empty,
        "truncated": result.truncated,
        "candidate_count": result.candidate_count,
        "eligible_candidate_count": result.eligible_candidate_count,
        "visible_candidate_count": result.visible_candidate_count,
        "ranking_receipt": asdict(batch.receipt),
        "jobs": [_posting(job) for job in result.jobs],
    }


@tool
def propose_resume_edit(
    block_id: str,
    rewrite: str,
    candidate_evidence_ids: list[str] | None = None,
) -> dict:
    """Draft an in-place, evidence-safe rewrite of one existing resume block.

    `block_id` must be a canonical block ID visible in the active resume
    document. `rewrite` must replace that block's text without introducing
    new facts unless candidate_evidence_ids cites exact profile fields returned by
    read_candidate_evidence or candidate-confirmed evidence IDs returned by
    record_candidate_evidence. It must stay within one block (no line breaks) --
    this tool cannot insert or delete a block. A valid proposal remains pending
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
    requested_ids = list(dict.fromkeys(candidate_evidence_ids or []))
    request = context.current_request()
    available_evidence = {
        field.field_id: "\n".join((field.statement, *field.evidence_quotes))
        for field in getattr(request.candidate_profile, "fields", ())
    }
    available_evidence.update(
        {
            fact.evidence_id: fact.evidence_quote
            for fact in (
                *getattr(request, "confirmed_evidence", ()),
                *getattr(request, "drafted_confirmed_evidence", ()),
            )
        }
    )
    unknown_evidence_ids = [evidence_id for evidence_id in requested_ids if evidence_id not in available_evidence]
    if unknown_evidence_ids:
        return {
            "accepted": False,
            "reason": f"Unknown candidate evidence IDs: {', '.join(unknown_evidence_ids)}",
            "block_id": block_id,
        }
    supporting_evidence = "\n".join(available_evidence[evidence_id] for evidence_id in requested_ids)
    supported_source = "\n".join(part for part in (original_text, supporting_evidence) if part)
    new_numbers = extract_numbers(clean_rewrite) - extract_numbers(supported_source)
    if new_numbers:
        return {
            "accepted": False,
            "reason": f"Unsupported numeric facts: {', '.join(sorted(new_numbers))}",
            "block_id": block_id,
        }

    failed = [
        gate
        for gate in run_all_gates(
            original_text,
            clean_rewrite,
            supporting_evidence=supporting_evidence,
        )
        if not gate.passed
    ]
    if failed:
        return {"accepted": False, "reason": "; ".join(gate.message for gate in failed), "block_id": block_id}

    evidence_result = request.edit_evidence_validator.validate(
        ResumeEditEvidenceRequest(
            original=original_text,
            supporting_evidence=supporting_evidence,
            rewrite=clean_rewrite,
        )
    )
    if not evidence_result.supported:
        claims = "; ".join(evidence_result.unsupported_claims)
        gap = evidence_result.reason.strip()
        detail = ". ".join(part for part in (claims, gap) if part)
        return {
            "accepted": False,
            "reason": (
                f"{detail}. Remove the unsupported claims or cite candidate evidence that directly establishes them."
            ),
            "failure_code": evidence_result.failure_code or "unsupported_claims",
            "block_id": block_id,
        }

    edits.append(
        {
            "block_id": block_id,
            "section_key": block.get("section_key", ""),
            "entry_id": block.get("entry_id", ""),
            "original": original_text,
            "rewrite": clean_rewrite,
            "document_revision": document.get("revision"),
            "evidence_ids": requested_ids,
            "status": "pending",
        }
    )
    return {
        "accepted": True,
        "application_status": "pending_user_review",
        "block_id": block_id,
        "rewrite": clean_rewrite,
    }
