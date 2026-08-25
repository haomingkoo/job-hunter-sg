"""
Career-agent helpers for job-specific application packs.

This is intentionally framework-light for now: one orchestrated skill run that
can later be moved behind a persisted graph once application cases need resume,
approval, and replay semantics.
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any

from ai_service import call_sealion_json
from config import SEALION_FAST_MODEL
from prompt_safety import UNTRUSTED_DATA_RULE, xml_data_block
from resume_structurer import get_all_bullets, structure_resume
from validation_gates import gate_unsupported_claims, numeric_metric_claims_verifiable


_DEFAULT_PACK: dict[str, Any] = {
    "verdict": {
        "decision": "maybe",
        "fit_score": 0,
        "rationale": "",
        "strengths": [],
        "risks": [],
    },
    "ats": {
        "matched_terms": [],
        "missing_terms": [],
        "critical_gaps": [],
    },
    "evidence_questions": [],
    "resume": {
        "summary": "",
        "bullet_upgrades": [],
    },
    "application_assets": {
        "cover_letter": "",
        "recruiter_dm": "",
        "follow_up_email": "",
    },
    "interview": {
        "likely_questions": [],
        "star_answers": [],
        "interviewer_questions": [],
    },
    "guardrails": [],
}


def _clean_text(value: Any, limit: int = 4000) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def _clean_list(value: Any, limit: int = 8, item_limit: int = 220) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _clean_text(item, item_limit)
        key = text.lower()
        if text and key not in seen:
            cleaned.append(text)
            seen.add(key)
        if len(cleaned) >= limit:
            break
    return cleaned


def _extract_resume_bullets(resume_text: str, limit: int = 18) -> list[str]:
    structured = structure_resume(str(resume_text or ""))
    logical = [
        _clean_text(item.get("text"), 300)
        for item in get_all_bullets(structured)
        if item.get("text")
    ]
    if logical:
        return logical[:limit]

    bullets: list[str] = []
    for raw in str(resume_text or "").splitlines():
        line = re.sub(r"^[\s>*-]*(?:[•\-\*]|\d+[.)])?\s*", "", raw).strip()
        if 18 <= len(line) <= 240:
            bullets.append(line)
        if len(bullets) >= limit:
            break
    return bullets


def _source_numbers(source: str) -> set[str]:
    return set(re.findall(r"(?<!\w)\d+(?:[.,]\d+)?%?\+?(?!\w)", source or ""))


def _unverified_numbers(text: str, source: str) -> list[str]:
    allowed = _source_numbers(source)
    return sorted(num for num in _source_numbers(text) if num not in allowed)


def _claims_sponsor_as_employer(resume_text: str, generated: str) -> bool:
    sponsors = {
        match.group(1).strip(" .")
        for match in re.finditer(
            r"\bsponsored by\s+([^,;.\n]{2,80})",
            resume_text,
            re.IGNORECASE,
        )
    }
    sponsors.update(
        match.group(1).strip(" .")
        for match in re.finditer(
            r"\b([A-Z][\w&'.]*(?:\s+[A-Z][\w&'.]*){0,5})-sponsored\b",
            resume_text,
        )
    )
    for sponsor in sponsors:
        escaped = re.escape(sponsor)
        if re.search(
            rf"(?:^|[.!?]\s+)at\s+{escaped}\b|"
            rf"\b(?:current role|worked|working|employed|experience)\s+(?:at|with)\s+{escaped}\b|"
            rf"\bas\s+an?\b[^,.]{{0,60}}\bat\s+{escaped}\b|"
            rf"\b(?:role|position|job|engineer|manager|director)\b[^,.]{{0,40}}\bat\s+{escaped}\b",
            generated,
            re.IGNORECASE,
        ):
            return True
    return False


def _resume_role_evidence(resume_text: str) -> list[dict[str, Any]]:
    roles: list[dict[str, Any]] = []
    for section in structure_resume(resume_text).get("sections", []):
        if section.get("key") != "experience":
            continue
        for entry in section.get("entries", []):
            company = _clean_text(entry.get("company"), 120)
            date_range = _clean_text(entry.get("date_range"), 120)
            evidence = " ".join([
                _clean_text(entry.get("heading"), 200),
                _clean_text(entry.get("subheading"), 240),
                *[
                    _clean_text(bullet.get("text"), 400)
                    for bullet in entry.get("bullets", [])
                    if isinstance(bullet, dict)
                ],
            ]).strip()
            roles.append({
                "company": company,
                "current": "present" in date_range.lower(),
                "evidence": evidence,
            })
    return roles


_ROLE_LEADERSHIP_CLAIM_RE = re.compile(
    r"\b(?:led|leading|managed|managing|directed|supervised|headed|oversaw)\b",
    re.IGNORECASE,
)
_ROLE_LEADERSHIP_EVIDENCE_RE = re.compile(
    r"\b(?:led|leading|leadership|manager|managed|managing|directed|supervised|"
    r"headed|oversaw|direct reports?)\b",
    re.IGNORECASE,
)


def _role_claims_verifiable(roles: list[dict[str, Any]], generated: str) -> bool:
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", generated):
        if not sentence.strip():
            continue
        named_roles = [
            role for role in roles
            if role["company"] and role["company"].lower() in sentence.lower()
        ]
        current_claim = bool(re.search(r"\b(?:current role|currently)\b", sentence, re.IGNORECASE))
        candidates = named_roles or ([role for role in roles if role["current"]] if current_claim else [])
        if not candidates:
            continue
        if current_claim and not named_roles and len(candidates) != 1:
            return False
        for role in candidates:
            evidence = role["evidence"]
            if (
                _ROLE_LEADERSHIP_CLAIM_RE.search(sentence)
                and not _ROLE_LEADERSHIP_EVIDENCE_RE.search(evidence)
            ):
                return False
            if not numeric_metric_claims_verifiable(evidence, sentence):
                return False
            if not gate_unsupported_claims(evidence, sentence).passed:
                return False
    return True


def _generated_claims_verifiable(
    resume_text: str,
    generated: str,
    roles: list[dict[str, Any]],
) -> bool:
    return (
        numeric_metric_claims_verifiable(resume_text, generated)
        and gate_unsupported_claims(resume_text, generated).passed
        and not _claims_sponsor_as_employer(resume_text, generated)
        and _role_claims_verifiable(roles, generated)
    )


def _coerce_decision(value: Any) -> str:
    decision = str(value or "").lower().strip()
    if decision in {"shortlist", "maybe", "weak_fit"}:
        return decision
    if decision in {"reject", "weak", "low"}:
        return "weak_fit"
    return "maybe"


def _normalise_pack(raw: Any, *, resume_text: str, match_result: dict[str, Any]) -> dict[str, Any]:
    pack = copy.deepcopy(_DEFAULT_PACK)
    if isinstance(raw, dict):
        for key, default_value in _DEFAULT_PACK.items():
            value = raw.get(key)
            if isinstance(default_value, dict):
                if isinstance(value, dict):
                    pack[key].update(value)
            elif value is not None:
                pack[key] = value

    verdict = pack["verdict"]
    verdict["decision"] = _coerce_decision(verdict.get("decision"))
    try:
        verdict["fit_score"] = max(0, min(100, int(verdict.get("fit_score") or 0)))
    except (TypeError, ValueError):
        verdict["fit_score"] = 0
    verdict["rationale"] = _clean_text(verdict.get("rationale"), 500)
    verdict["strengths"] = _clean_list(verdict.get("strengths"), 5)
    verdict["risks"] = _clean_list(verdict.get("risks"), 5)

    matched = (match_result.get("matched") or []) if isinstance(match_result, dict) else []
    missing = (match_result.get("missing") or []) if isinstance(match_result, dict) else []
    local_matched = [item.get("skill", "") for item in matched if isinstance(item, dict)]
    local_missing = [item.get("skill", "") for item in missing if isinstance(item, dict)]
    pack["ats"]["matched_terms"] = _clean_list(pack["ats"].get("matched_terms") or local_matched, 12, 80)
    pack["ats"]["missing_terms"] = _clean_list(pack["ats"].get("missing_terms") or local_missing, 12, 80)
    pack["ats"]["critical_gaps"] = _clean_list(pack["ats"].get("critical_gaps"), 6, 160)

    questions = []
    raw_questions = pack.get("evidence_questions")
    for index, item in enumerate(raw_questions if isinstance(raw_questions, list) else []):
        if not isinstance(item, dict):
            continue
        prompt = _clean_text(item.get("prompt"), 260)
        if not prompt:
            continue
        questions.append({
            "id": _clean_text(item.get("id") or f"q{index + 1}", 40),
            "prompt": prompt,
            "target_area": _clean_text(item.get("target_area"), 120),
            "why_it_matters": _clean_text(item.get("why_it_matters"), 220),
            "answer_type": _clean_text(item.get("answer_type") or "metric_or_scope", 60),
        })
        if len(questions) >= 5:
            break
    pack["evidence_questions"] = questions

    resume = pack["resume"]
    role_evidence = _resume_role_evidence(resume_text)
    resume["summary"] = _clean_text(resume.get("summary"), 700)
    withheld_unverified = False
    if resume["summary"] and not _generated_claims_verifiable(
        resume_text, resume["summary"], role_evidence
    ):
        resume["summary"] = ""
        withheld_unverified = True
    upgrades = []
    source_for_numbers = resume_text
    normalized_resume = _clean_text(resume_text, 20_000).lower()
    raw_upgrades = resume.get("bullet_upgrades")
    for item in raw_upgrades if isinstance(raw_upgrades, list) else []:
        if not isinstance(item, dict):
            continue
        original = _clean_text(item.get("original"), 300)
        rewrite = _clean_text(item.get("rewrite"), 300)
        if not original or not rewrite:
            continue
        unverified = _unverified_numbers(rewrite, source_for_numbers)
        unsupported_claim = not gate_unsupported_claims(original, rewrite).passed
        changed_metric_meaning = not numeric_metric_claims_verifiable(original, rewrite)
        original_not_found = original.lower() not in normalized_resume
        upgrades.append({
            "original": original,
            "rewrite": rewrite,
            "reason": _clean_text(item.get("reason"), 220),
            "needs_user_fact": (
                bool(item.get("needs_user_fact"))
                or bool(unverified)
                or unsupported_claim
                or changed_metric_meaning
                or original_not_found
            ),
            "unverified_numbers": unverified,
        })
        if len(upgrades) >= 5:
            break
    resume["bullet_upgrades"] = upgrades

    assets = pack["application_assets"]
    for key, limit in (
        ("cover_letter", 2600),
        ("recruiter_dm", 900),
        ("follow_up_email", 900),
    ):
        text = _clean_text(assets.get(key), limit)
        if text and not _generated_claims_verifiable(resume_text, text, role_evidence):
            text = ""
            withheld_unverified = True
        assets[key] = text

    interview = pack["interview"]
    interview["likely_questions"] = _clean_list(interview.get("likely_questions"), 10, 180)
    interview["interviewer_questions"] = _clean_list(interview.get("interviewer_questions"), 6, 180)
    stories = []
    raw_stories = interview.get("star_answers")
    for item in raw_stories if isinstance(raw_stories, list) else []:
        if not isinstance(item, dict):
            continue
        question = _clean_text(item.get("question"), 180)
        answer = _clean_text(item.get("answer"), 900)
        if question and answer and _generated_claims_verifiable(
            resume_text, answer, role_evidence
        ):
            stories.append({
                "question": question,
                "answer": answer,
                "source": _clean_text(item.get("source"), 180),
            })
        elif answer:
            withheld_unverified = True
        if len(stories) >= 4:
            break
    interview["star_answers"] = stories

    pack["guardrails"] = _clean_list(pack.get("guardrails"), 6, 180) or [
        "Review every generated asset before applying.",
        "Replace placeholders and verify any metric before use.",
        "Do not submit content that adds claims not supported by your experience.",
    ]
    if withheld_unverified:
        pack["guardrails"] = [
            "Some generated text was withheld because its factual claims could not be verified against the resume.",
            *pack["guardrails"],
        ][:6]
    return pack


def _local_fallback_pack(
    *,
    resume_text: str,
    job_title: str,
    job_company: str,
    match_result: dict[str, Any],
) -> dict[str, Any]:
    matched = [item.get("skill", "") for item in match_result.get("matched", []) if isinstance(item, dict)]
    missing = [item.get("skill", "") for item in match_result.get("missing", []) if isinstance(item, dict)]
    bullets = _extract_resume_bullets(resume_text, 5)
    target = f"{job_title} at {job_company}".strip(" at") or "this role"
    return _normalise_pack(
        {
            "verdict": {
                "decision": "maybe",
                "fit_score": 0,
                "rationale": "The AI model was unavailable, so this pack only includes local ATS signals and evidence prompts.",
                "strengths": matched[:4],
                "risks": missing[:4],
            },
            "ats": {
                "matched_terms": matched[:12],
                "missing_terms": missing[:12],
                "critical_gaps": missing[:5],
            },
            "evidence_questions": [
                {
                    "id": f"evidence_{index + 1}",
                    "prompt": f"What metric, team size, scope, or timeline can you add to this experience: {bullet}",
                    "target_area": target,
                    "why_it_matters": "The agent needs defensible proof before strengthening the application.",
                    "answer_type": "metric_or_scope",
                }
                for index, bullet in enumerate(bullets[:3])
            ],
            "guardrails": [
                "AI generation was unavailable; rerun the pack before using final copy.",
                "Add only metrics and scope that you can defend in interview.",
            ],
        },
        resume_text=resume_text,
        match_result=match_result,
    ) | {"degraded": True}


def build_application_pack(
    *,
    resume_text: str,
    job_title: str,
    job_company: str,
    job_description: str,
    job_terms: list[dict[str, Any]],
    match_result: dict[str, Any],
    parsed_jd: dict[str, Any] | None = None,
    user_direction: str = "",
) -> dict[str, Any]:
    """Run the career-agent application-pack skill and return normalised JSON."""

    resume_bullets = _extract_resume_bullets(resume_text)
    matched_terms = [item.get("skill", "") for item in match_result.get("matched", []) if isinstance(item, dict)]
    missing_terms = [item.get("skill", "") for item in match_result.get("missing", []) if isinstance(item, dict)]
    top_terms = [str(item.get("skill", "")) for item in job_terms[:18] if isinstance(item, dict) and item.get("skill")]

    system = """You are Job Hunter SG's career application agent.

You produce one job-specific application pack using only the resume and job context supplied.

Rules:
- Act like a direct senior recruiter, ATS analyst, resume editor, and interview coach.
- Never invent numbers, companies, dates, certifications, tools, or achievements.
- Treat numbers and requirements in the job description as employer context, never as candidate evidence.
- Copy each bullet_upgrades.original verbatim from the resume context.
- If a stronger bullet needs a missing metric, ask an evidence question instead of making one up.
- Keep Singapore hiring context in mind.
- Prefer exact hard skills and role wording from the job description.
- Be specific, concise, and practical.
- Return ONLY valid JSON matching the requested schema.

SECURITY: {untrusted_rule}""".format(untrusted_rule=UNTRUSTED_DATA_RULE)

    schema = {
        "verdict": {
            "decision": "shortlist|maybe|weak_fit",
            "fit_score": "0-100 integer",
            "rationale": "one direct paragraph",
            "strengths": ["specific strengths from resume matched to JD"],
            "risks": ["specific gaps or weak evidence"],
        },
        "ats": {
            "matched_terms": ["job terms present in resume"],
            "missing_terms": ["important job terms missing or weak"],
            "critical_gaps": ["gaps that could affect shortlist odds"],
        },
        "evidence_questions": [
            {
                "id": "short_snake_case",
                "prompt": "question to ask user before finalising",
                "target_area": "bullet/skill/role area",
                "why_it_matters": "why this answer improves the application",
                "answer_type": "metric_or_scope|example|preference",
            }
        ],
        "resume": {
            "summary": "tailored resume summary, 3-4 lines, no invented claims",
            "bullet_upgrades": [
                {
                    "original": "resume bullet or sentence being upgraded",
                    "rewrite": "defensible rewrite using only known facts",
                    "reason": "why this improves fit",
                    "needs_user_fact": False,
                }
            ],
        },
        "application_assets": {
            "cover_letter": "250-350 word cover letter",
            "recruiter_dm": "short LinkedIn/recruiter DM",
            "follow_up_email": "short follow-up email after applying",
        },
        "interview": {
            "likely_questions": ["likely interview question"],
            "star_answers": [
                {
                    "question": "behavioral question",
                    "answer": "30-60 second STAR answer using resume facts only",
                    "source": "source experience used",
                }
            ],
            "interviewer_questions": ["smart question to ask the interviewer"],
        },
        "guardrails": ["things user must verify before sending"],
    }

    user_payload = {
        "target_job": {
            "title": job_title,
            "company": job_company,
            "description_excerpt": job_description[:3500],
            "parsed_jd": parsed_jd or {},
            "top_job_terms": top_terms,
        },
        "resume": {
            "full_text_excerpt": resume_text[:15000],
            "candidate_bullets": resume_bullets,
        },
        "local_ats_match": {
            "matched_terms": matched_terms[:15],
            "missing_terms": missing_terms[:15],
        },
        "user_direction": user_direction,
        "required_json_schema": schema,
    }

    content = call_sealion_json(
        messages=[
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": xml_data_block(
                    "application_context_data",
                    json.dumps(user_payload, ensure_ascii=False),
                ),
            },
        ],
        max_tokens=4500,
        model=SEALION_FAST_MODEL,
        max_retries=1,
    )
    if not content:
        return _local_fallback_pack(
            resume_text=resume_text,
            job_title=job_title,
            job_company=job_company,
            match_result=match_result,
        )

    try:
        raw = json.loads(content)
    except (TypeError, json.JSONDecodeError):
        return _local_fallback_pack(
            resume_text=resume_text,
            job_title=job_title,
            job_company=job_company,
            match_result=match_result,
        )

    pack = _normalise_pack(
        raw,
        resume_text=resume_text,
        match_result=match_result,
    )
    pack["degraded"] = False
    pack["agent"] = {
        "workflow": "application_pack_v1",
        "skills": [
            "recruiter_verdict",
            "ats_gap_analysis",
            "achievement_rewriter",
            "cover_letter",
            "interview_prep",
        ],
    }
    return pack
