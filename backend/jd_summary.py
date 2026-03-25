"""
Cached job-description summaries for long postings.

We first build a compact structural outline from parsed JD data, then ask the
LLM for a short 2-4 sentence summary that is easier for humans to skim.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ai_service import SEALION_MODEL_INTERACTIVE, _call_sealion


def build_structured_jd_outline(
    *,
    job_title: str,
    description: str,
    parsed_jd: dict | None,
) -> dict:
    parsed = parsed_jd if isinstance(parsed_jd, dict) else {}
    required_skills = [
        str(skill).strip()
        for skill in parsed.get("required_skills", [])[:8]
        if str(skill).strip()
    ]
    preferred_skills = [
        str(skill).strip()
        for skill in parsed.get("preferred_skills", [])[:5]
        if str(skill).strip()
    ]
    single_word_skills = [
        str(skill).strip()
        for skill in parsed.get("single_word_skills", [])[:6]
        if str(skill).strip()
    ]
    responsibilities = [
        str(item).strip()
        for item in parsed.get("key_responsibilities", [])[:5]
        if str(item).strip()
    ]
    competency_signals = parsed.get("competency_signals", {}) if isinstance(parsed.get("competency_signals", {}), dict) else {}
    domain_terms = []
    for terms in competency_signals.values():
        if not isinstance(terms, list):
            continue
        for term in terms:
            label = str(term).strip()
            if label and label not in domain_terms:
                domain_terms.append(label)

    return {
        "job_title": str(job_title or "").strip(),
        "description_excerpt": str(description or "").strip()[:1600],
        "experience_years": str(parsed.get("experience_years", "") or "").strip(),
        "education_level": str(parsed.get("education_level", "") or "").strip(),
        "required_skills": required_skills,
        "preferred_skills": preferred_skills,
        "single_word_skills": single_word_skills,
        "key_responsibilities": responsibilities,
        "competency_signals": domain_terms[:8],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def summarize_job_description(
    *,
    job_title: str,
    description: str,
    parsed_jd: dict | None,
) -> tuple[str | None, str]:
    """
    Generate a short recruiter-style summary for a job description.

    Returns (summary, model_used). The summary is None if generation failed.
    """
    outline = build_structured_jd_outline(
        job_title=job_title,
        description=description,
        parsed_jd=parsed_jd,
    )

    system = (
        "You summarize job descriptions for busy applicants. "
        "Return 2 to 4 concise sentences in plain English. "
        "Sentence 1: what the role is and the functional/domain focus. "
        "Sentence 2: what the person will actually do. "
        "Sentence 3: the strongest must-haves, tools, or seniority cues if useful. "
        "Do not invent salary, scope, team names, or requirements not present in the input. "
        "Do not use bullet points. Do not say 'This role'."
    )
    user = (
        f"JOB TITLE: {outline['job_title']}\n"
        f"EXPERIENCE: {outline['experience_years'] or 'not specified'}\n"
        f"EDUCATION: {outline['education_level'] or 'not specified'}\n"
        f"REQUIRED SKILLS: {', '.join(outline['required_skills']) or 'not specified'}\n"
        f"PREFERRED SKILLS: {', '.join(outline['preferred_skills']) or 'not specified'}\n"
        f"TOOLS/TECH: {', '.join(outline['single_word_skills']) or 'not specified'}\n"
        f"KEY RESPONSIBILITIES: {' | '.join(outline['key_responsibilities']) or 'not specified'}\n"
        f"COMPETENCY SIGNALS: {', '.join(outline['competency_signals']) or 'not specified'}\n"
        f"DESCRIPTION EXCERPT:\n{outline['description_excerpt']}"
    )

    summary = _call_sealion(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_tokens=260,
        model=SEALION_MODEL_INTERACTIVE,
        temperature=0.2,
    )
    cleaned = " ".join(str(summary or "").split()).strip()
    if not cleaned:
        return None, SEALION_MODEL_INTERACTIVE
    return cleaned, SEALION_MODEL_INTERACTIVE
