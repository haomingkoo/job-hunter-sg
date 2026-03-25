"""
Canonical ATS term extraction and matching helpers.

This module is intentionally independent from FastAPI app code so the same
term-building logic can be reused by score, job-match, power-match, and
tailoring validation without drifting.
"""

from __future__ import annotations

import re

from skill_extractor import extract_skill_phrases, match_resume_skills_with_context

ATS_ALLOWED_SINGLE_TERMS: set[str] = {
    "python", "sql", "excel", "tableau", "powerbi", "aws", "azure", "gcp",
    "docker", "kubernetes", "terraform", "linux", "react", "typescript",
    "javascript", "java", "node", "nodejs", "golang", "rust", "git",
    "agile", "scrum", "analytics", "ai", "leadership", "communication",
    "spc", "jira", "manufacturing", "semiconductor", "lithography",
    "metrology", "yield", "reliability", "validation", "integration",
    "eqms", "feol", "beol", "doe", "semulator3d", "hbm3e", "lpddr5x",
    "opnet", "qunetsim", "ns-3", "matlab",
}

ATS_SINGLE_GENERIC_NOISE: set[str] = {
    "experience", "professional", "organization", "performance",
    "development", "transformation", "documentation", "collaboration",
    "engineering", "integration", "automation", "validation", "reliability",
}

ATS_MULTIWORD_NOISE: set[str] = {
    "professional experience", "professional summary", "core skills",
    "core competencies", "technical skills", "additional information",
    "certification", "certifications", "education", "languages",
    "personal information", "medical study", "selected bullet",
    "resume score", "summary section",
}

ATS_DISPLAY_EXCLUDE: set[str] = ATS_MULTIWORD_NOISE | {
    "professional learning communities",
    "exit interviews",
    "loan processing",
    "subject matter expert",
    "basket weaving",
}

ATS_OUTLINE_NOISE: set[str] = {
    "job description",
    "description",
    "overview",
    "key responsibilities",
    "responsibilities",
    "requirements",
    "what we are looking for",
    "work experience and knowledge",
    "source tags & skill cues",
}

_ATS_CONTEXT_RE = re.compile(
    r"(areas?\s+of\s+study|field[s]?\s+of\s+study|degree(?:\s+or)?\s+above|"
    r"bachelor|master|phd|major(?:ing)?\s+in|equivalent work experience|disciplines?)",
    re.IGNORECASE,
)
_ATS_WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9+#./-]{1,}")
_ATS_TITLE_SPLIT_RE = re.compile(r"\s*(?:[-–/|]|,)\s*")
_ATS_TITLE_NOISE = {
    "assistant", "associate", "executive", "senior", "snr", "junior",
    "lead", "principal", "manager", "engineer", "director", "officer",
    "analyst", "specialist", "staff", "head", "vp", "avp", "am", "m",
}


def _normalize_term(term: str) -> str:
    return re.sub(r"\s+", " ", str(term or "").strip())


def _find_context(text: str, phrase: str) -> str:
    source = str(text or "")
    needle = str(phrase or "").strip()
    if not source or not needle:
        return ""

    lower_source = source.lower()
    lower_phrase = needle.lower()
    idx = lower_source.find(lower_phrase)
    if idx == -1:
        return ""

    start = max(0, idx - 120)
    end = min(len(source), idx + len(needle) + 120)
    for boundary in ".!?\n":
        last_b = lower_source.rfind(boundary, start, idx)
        if last_b != -1 and last_b > start:
            start = last_b + 1
            break
    for boundary in ".!?\n":
        next_b = lower_source.find(boundary, idx + len(needle))
        if next_b != -1 and next_b < end:
            end = next_b + 1
            break

    snippet = source[start:end].strip()
    if start > 0:
        snippet = "..." + snippet
    if end < len(source):
        snippet = snippet + "..."
    return snippet


def _extract_single_word_terms(text: str) -> list[str]:
    lowered = str(text or "").lower()
    if not lowered.strip():
        return []

    found: list[str] = []
    for term in ATS_ALLOWED_SINGLE_TERMS:
        escaped = re.escape(term)
        pattern = re.compile(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", re.IGNORECASE)
        if pattern.search(lowered):
            found.append(term)
    found.sort()
    return found


def _extract_title_seed_phrases(job_title: str) -> list[str]:
    title = str(job_title or "").strip()
    if not title:
        return []

    phrases: list[str] = []

    for chunk in re.findall(r"\(([^)]+)\)", title):
        for piece in _ATS_TITLE_SPLIT_RE.split(chunk):
            normalized = _normalize_term(piece).lower()
            if 2 <= len(normalized.split()) <= 5:
                phrases.append(normalized)

    stripped_title = re.sub(r"\([^)]*\)", " ", title)
    words = [w.lower() for w in _ATS_WORD_RE.findall(stripped_title)]
    filtered = [w for w in words if w not in _ATS_TITLE_NOISE]
    if 2 <= len(filtered) <= 5:
        phrases.append(" ".join(filtered))

    deduped: list[str] = []
    seen: set[str] = set()
    for phrase in phrases:
        if not phrase or phrase in seen:
            continue
        seen.add(phrase)
        deduped.append(phrase)
    return deduped


def _extract_outline_terms(text: str) -> list[str]:
    source = str(text or "")
    if not source.strip():
        return []

    candidates: list[str] = []

    for chunk in re.findall(r"\[([^\]]{3,80})\]", source):
        normalized = _normalize_term(chunk)
        if normalized:
            candidates.append(normalized)

    for raw_line in source.splitlines():
        stripped = re.sub(r"^[\s•*\-–]+", "", raw_line or "").strip(" :")
        if not stripped or len(stripped) < 3 or len(stripped) > 80:
            continue
        if stripped.endswith((".", ";")):
            continue
        lowered = stripped.lower()
        if lowered in ATS_OUTLINE_NOISE:
            continue
        words = stripped.split()
        if not (1 <= len(words) <= 6):
            continue
        title_like = all(
            word[:1].isupper() or word.lower() in {"and", "&", "of", "to", "the", "for", "with", "in", "on"}
            for word in words
        )
        if title_like:
            candidates.append(stripped)

    deduped: list[str] = []
    seen: set[str] = set()
    for term in candidates:
        normalized = _normalize_term(term)
        lowered = normalized.lower()
        if not normalized or lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(normalized)
    return deduped


def _looks_like_study_area(term: str, context: str) -> bool:
    lowered = term.lower()
    return (
        lowered.endswith(" study")
        or lowered in {"computer science", "engineering", "mathematics", "statistics", "medical study"}
        or bool(_ATS_CONTEXT_RE.search(context or ""))
    )


def _is_noise_term(term: str, context: str = "") -> bool:
    lowered = term.lower()
    if not lowered:
        return True
    if lowered in ATS_DISPLAY_EXCLUDE:
        return True
    if len(lowered.split()) == 1 and lowered in ATS_SINGLE_GENERIC_NOISE:
        return True
    if len(lowered.split()) == 1 and lowered not in ATS_ALLOWED_SINGLE_TERMS:
        return True
    if _looks_like_study_area(lowered, context):
        return True
    return False


def build_job_ats_terms(
    jd_text: str,
    job_skills: list[str] | None = None,
    parsed_jd: dict | None = None,
    job_title: str = "",
    limit: int | None = None,
    db_session=None,
) -> list[dict]:
    """
    Build one canonical ATS term list from the JD body, parsed JD metadata,
    source skill tags, and title hints.
    """
    description = str(jd_text or "")
    parsed = parsed_jd if isinstance(parsed_jd, dict) else {}
    skills_list = job_skills if isinstance(job_skills, list) else []

    required_terms = parsed.get("required_skills", []) if isinstance(parsed.get("required_skills", []), list) else []
    preferred_terms = parsed.get("preferred_skills", []) if isinstance(parsed.get("preferred_skills", []), list) else []
    parsed_single_terms = parsed.get("single_word_skills", []) if isinstance(parsed.get("single_word_skills", []), list) else []
    competency_signals = parsed.get("competency_signals", {}) if isinstance(parsed.get("competency_signals", {}), dict) else {}

    extracted_phrases = extract_skill_phrases(description, skills_list, db_session=db_session)
    title_phrases = extract_skill_phrases(job_title, skills_list, db_session=db_session) if job_title else []
    title_seed_phrases = _extract_title_seed_phrases(job_title)
    outline_terms = _extract_outline_terms(description)
    title_single_terms = _extract_single_word_terms(job_title)
    fallback_single_terms = parsed_single_terms or _extract_single_word_terms(description)

    competency_terms: list[str] = []
    for matched_keywords in competency_signals.values():
        if not isinstance(matched_keywords, list):
            continue
        for keyword in matched_keywords:
            normalized = _normalize_term(keyword).lower()
            if normalized:
                competency_terms.append(normalized)

    priority_rows: list[tuple[int, str, dict]] = []

    def add_terms(terms: list[str], priority: int, source: str, *, required: bool = False, preferred: bool = False, technical: bool = False) -> None:
        for term in terms:
            normalized = _normalize_term(term)
            context = _find_context(description, normalized)
            if _is_noise_term(normalized, context):
                continue
            priority_rows.append((
                priority,
                normalized.lower(),
                {
                    "skill": normalized.lower(),
                    "source": source,
                    "required": required,
                    "preferred": preferred,
                    "technical": technical,
                    "jd_context": context,
                },
            ))

    add_terms(required_terms, 100, "required", required=True)
    add_terms(extracted_phrases, 90, "description")
    add_terms(preferred_terms, 80, "preferred", preferred=True)
    add_terms(outline_terms, 75, "outline")
    add_terms(fallback_single_terms, 70, "single_word", technical=True)
    add_terms(skills_list, 60, "source_tags")
    add_terms(title_seed_phrases, 58, "title_seed")
    add_terms(title_phrases, 55, "title")
    add_terms(title_single_terms, 50, "title", technical=True)
    add_terms(competency_terms, 40, "competency")

    merged: dict[str, dict] = {}
    for priority, key, item in priority_rows:
        existing = merged.get(key)
        if existing is None or priority > existing["_priority"]:
            merged[key] = {**item, "_priority": priority}
        else:
            existing["required"] = existing["required"] or item["required"]
            existing["preferred"] = existing["preferred"] or item["preferred"]
            existing["technical"] = existing["technical"] or item["technical"]
            if not existing.get("jd_context") and item.get("jd_context"):
                existing["jd_context"] = item["jd_context"]

    ordered = sorted(
        merged.values(),
        key=lambda item: (
            -item["_priority"],
            0 if len(item["skill"].split()) >= 2 else 1,
            item["skill"],
        ),
    )
    final = [{k: v for k, v in item.items() if k != "_priority"} for item in ordered]
    if limit is not None:
        final = final[:limit]
    return final


def match_resume_against_job_terms(
    resume_text: str,
    job_terms: list[dict] | list[str],
    jd_text: str = "",
) -> dict:
    terms = []
    for item in job_terms or []:
        if isinstance(item, dict):
            skill = _normalize_term(item.get("skill", ""))
        else:
            skill = _normalize_term(item)
        if skill:
            terms.append(skill.lower())

    return match_resume_skills_with_context(
        resume_text=resume_text,
        jd_skills=terms,
        jd_text=jd_text,
    )


def merge_job_terms_with_match(job_terms: list[dict], match_result: dict) -> list[dict]:
    matched_by_skill = {
        _normalize_term(item.get("skill", "")).lower(): item
        for item in match_result.get("matched", [])
        if _normalize_term(item.get("skill", ""))
    }
    missing_by_skill = {
        _normalize_term(item.get("skill", "")).lower(): item
        for item in match_result.get("missing", [])
        if _normalize_term(item.get("skill", ""))
    }

    merged: list[dict] = []
    for term in job_terms:
        key = _normalize_term(term.get("skill", "")).lower()
        if not key:
            continue
        if key in matched_by_skill:
            merged.append({**term, **matched_by_skill[key]})
        elif key in missing_by_skill:
            merged.append({**term, **missing_by_skill[key]})
        else:
            merged.append(term)
    return merged
