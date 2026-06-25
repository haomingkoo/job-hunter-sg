"""
JD quality analysis: prompt injection detection, red flag scanning,
duplicate detection, and quality scoring.

All analysis is pure regex/heuristic - no LLM calls. Runs at parse time
and stores results in parsed_jd["_analysis"].
"""

from __future__ import annotations

import hashlib
import re


# ── Prompt injection patterns ────────────────────────────────────────────────

_INJECTION_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("instruction_override", re.compile(
        r"(ignore|disregard|forget)\s+(all\s+)?(previous|above|prior|earlier)\s+"
        r"(instructions?|prompts?|rules?|context)",
        re.IGNORECASE,
    )),
    ("role_hijack", re.compile(
        r"(you\s+are\s+now|act\s+as|pretend\s+to\s+be|switch\s+to|"
        r"new\s+instruction|system\s*:\s*|<\|system\|>)",
        re.IGNORECASE,
    )),
    ("output_manipulation", re.compile(
        r"(output\s+only|respond\s+with|return\s+exactly|"
        r"say\s+nothing\s+else|print\s+the\s+following)",
        re.IGNORECASE,
    )),
    ("data_exfiltration", re.compile(
        r"(reveal|show|display|output|print)\s+(your|the|all)\s+"
        r"(system\s+prompt|instructions?|api\s*key|secret|password|token)",
        re.IGNORECASE,
    )),
    ("encoded_injection", re.compile(
        r"(base64|atob|decode|\\x[0-9a-f]{2}|&#x?[0-9a-f]+;)",
        re.IGNORECASE,
    )),
]


def detect_prompt_injection(text: str) -> list[dict]:
    """Scan text for prompt injection attempts. Returns list of findings."""
    findings: list[dict] = []
    for label, pattern in _INJECTION_PATTERNS:
        matches = pattern.findall(text)
        if matches:
            # Find actual position for context
            for m in pattern.finditer(text):
                start = max(0, m.start() - 40)
                end = min(len(text), m.end() + 40)
                findings.append({
                    "type": "prompt_injection",
                    "category": label,
                    "match": m.group()[:80],
                    "context": text[start:end].replace("\n", " ")[:120],
                })
                break  # one example per category is enough
    return findings


# ── Red flag detection ───────────────────────────────────────────────────────

_RED_FLAG_PATTERNS: list[tuple[str, str, re.Pattern]] = [
    # Scam signals
    ("scam", "upfront_payment", re.compile(
        r"(pay\s+(a\s+)?fee|registration\s+fee|processing\s+fee|"
        r"deposit\s+required|investment\s+required|buy\s+(our|the)\s+kit)",
        re.IGNORECASE,
    )),
    ("scam", "mlm_signals", re.compile(
        r"(multi.?level|network\s+marketing|unlimited\s+earning|"
        r"passive\s+income|be\s+your\s+own\s+boss|work\s+from\s+home\s+\$|"
        r"earn\s+\$?\d{3,}\s*(per|a|/)\s*(day|hour)|financial\s+freedom)",
        re.IGNORECASE,
    )),
    ("scam", "personal_info_harvest", re.compile(
        r"(send\s+(your\s+)?(nric|ic\s+number|passport|bank\s+account|"
        r"credit\s+card)|whatsapp\s+\+?\d{8,}|telegram\s+@)",
        re.IGNORECASE,
    )),

    # Discriminatory language
    ("discrimination", "age", re.compile(
        r"(young\s+(and\s+)?energetic|fresh\s+grad(uate)?s?\s+only|"
        r"below\s+\d{2}\s+years|maximum\s+age|age\s+limit|"
        r"prefer(red|ably)?\s+(young|mature))",
        re.IGNORECASE,
    )),
    ("discrimination", "gender", re.compile(
        r"(male\s+only|female\s+only|ladies\s+only|gentlemen\s+only|"
        r"prefer(red|ably)?\s+(male|female)|"
        r"must\s+be\s+(male|female)|looking\s+for\s+(a\s+)?(male|female))",
        re.IGNORECASE,
    )),
    ("discrimination", "race_nationality", re.compile(
        r"(chinese\s+only|malay\s+only|indian\s+only|"
        r"singaporean\s+only|pr\s+only|citizen\s+only|"
        r"no\s+foreigner|local\s+only)",
        re.IGNORECASE,
    )),
    ("discrimination", "marital_status", re.compile(
        r"(single\s+only|married\s+only|no\s+children|"
        r"must\s+be\s+(single|married|unmarried))",
        re.IGNORECASE,
    )),

    # Exploitative conditions
    ("exploitative", "unpaid_labor", re.compile(
        r"(unpaid\s+(internship|position|role|work)|"
        r"no\s+(salary|pay|compensation|remuneration)|"
        r"commission\s+only|purely?\s+commission)",
        re.IGNORECASE,
    )),
    ("exploitative", "unreasonable_hours", re.compile(
        r"(24/7\s+availability|on.?call\s+24|"
        r"must\s+work\s+(weekends?|holidays?|public\s+holidays?)|"
        r"no\s+(off\s+days?|leave|mc))",
        re.IGNORECASE,
    )),

    # Low effort / spam
    ("low_quality", "copy_paste_spam", re.compile(
        r"(!!{3,}|urgently?\s+hiring|immediate\s+hiring|"
        r"fast\s+hiring|walk.?in\s+interview|"
        r"no\s+experience\s+needed.*earn\s+\$)",
        re.IGNORECASE,
    )),
]


def detect_red_flags(text: str) -> list[dict]:
    """Scan for suspicious, discriminatory, or exploitative content."""
    findings: list[dict] = []
    for severity, category, pattern in _RED_FLAG_PATTERNS:
        for m in pattern.finditer(text):
            start = max(0, m.start() - 40)
            end = min(len(text), m.end() + 40)
            findings.append({
                "type": "red_flag",
                "severity": severity,
                "category": category,
                "match": m.group()[:80],
                "context": text[start:end].replace("\n", " ")[:120],
            })
            break  # one example per category
    return findings


# ── JD quality scoring ───────────────────────────────────────────────────────

def score_jd_quality(
    *,
    title: str,
    description: str,
    parsed_jd: dict | None,
    salary: str,
    company: str,
) -> dict:
    """
    Score JD quality 0-100 across dimensions.
    Higher = more complete and informative.
    """
    parsed = parsed_jd if isinstance(parsed_jd, dict) else {}
    desc = (description or "").strip()
    word_count = len(desc.split())

    scores: dict[str, int] = {}

    # Completeness (does it have the basics?)
    completeness = 0
    if (title or "").strip():
        completeness += 15
    if (company or "").strip():
        completeness += 10
    if (salary or "").strip() and salary.lower() not in ("not specified", "n/a", ""):
        completeness += 15
    if word_count >= 50:
        completeness += 10
    if word_count >= 150:
        completeness += 5
    if word_count >= 300:
        completeness += 5
    scores["completeness"] = min(60, completeness)

    # Specificity (does it have structured info?)
    specificity = 0
    required = parsed.get("required_skills", [])
    preferred = parsed.get("preferred_skills", [])
    responsibilities = parsed.get("key_responsibilities", [])
    experience = parsed.get("experience_years", "")
    education = parsed.get("education_level", "")

    if len(required) >= 3:
        specificity += 8
    elif len(required) >= 1:
        specificity += 4
    if len(preferred) >= 2:
        specificity += 4
    if len(responsibilities) >= 3:
        specificity += 6
    elif len(responsibilities) >= 1:
        specificity += 3
    if experience:
        specificity += 4
    if education:
        specificity += 3
    scores["specificity"] = min(25, specificity)

    # Clarity (length, formatting, no spam signals)
    clarity = 0
    if 100 <= word_count <= 800:
        clarity += 8  # right length range
    elif word_count > 800:
        clarity += 4  # too long but at least has content
    # Has some structure (bullets, line breaks)
    if desc.count("\n") >= 3 or desc.count("•") >= 2 or desc.count("- ") >= 2:
        clarity += 4
    # Not all caps
    upper_ratio = sum(1 for c in desc if c.isupper()) / max(1, len(desc))
    if upper_ratio < 0.3:
        clarity += 3
    scores["clarity"] = min(15, clarity)

    total = sum(scores.values())
    return {
        "score": total,
        "max_score": 100,
        "breakdown": scores,
        "word_count": word_count,
    }


# ── Duplicate detection ──────────────────────────────────────────────────────

def compute_content_hash(description: str) -> str:
    """Compute a normalized hash for duplicate detection."""
    normalized = re.sub(r"\s+", " ", (description or "").strip().lower())
    # Remove common boilerplate that varies between postings
    normalized = re.sub(
        r"(posted\s+\d+\s+days?\s+ago|apply\s+(now|here|today)|"
        r"ref(erence)?\s*(no|number|id|code)\s*:?\s*\w+|"
        r"job\s*(id|ref|code)\s*:?\s*\w+)",
        "",
        normalized,
    )
    return hashlib.md5(normalized.encode()).hexdigest()[:16]


# ── Sanitize for LLM input ──────────────────────────────────────────────────

def sanitize_for_llm(text: str) -> str:
    """
    Strip potential injection patterns from text before sending to LLM.
    Preserves legitimate JD content.
    """
    cleaned = text
    # Remove encoded content
    cleaned = re.sub(r"base64[:\s]+[A-Za-z0-9+/=]{20,}", "[REMOVED_ENCODED]", cleaned)
    # Remove suspicious instruction-like blocks
    cleaned = re.sub(
        r"(ignore|disregard|forget)\s+(all\s+)?(previous|above|prior)\s+"
        r"(instructions?|prompts?|rules?|context)[^.]*\.",
        "[REMOVED_INSTRUCTION]",
        cleaned,
        flags=re.IGNORECASE,
    )
    # Remove role hijack attempts
    cleaned = re.sub(
        r"(you\s+are\s+now|act\s+as|pretend\s+to\s+be)\s+[^.]{0,100}\.",
        "[REMOVED_ROLE_OVERRIDE]",
        cleaned,
        flags=re.IGNORECASE,
    )
    # Remove system prompt markers
    cleaned = re.sub(r"<\|system\|>|<\|assistant\|>|<\|user\|>", "", cleaned)
    return cleaned


# ── Main analysis entry point ────────────────────────────────────────────────

def analyze_job_description(
    *,
    title: str,
    description: str,
    parsed_jd: dict | None,
    salary: str = "",
    company: str = "",
    agency: str = "",
) -> dict:
    """
    Full analysis of a job description. Returns a dict to store in
    parsed_jd["_analysis"].
    """
    desc = (description or "").strip()
    if not desc:
        return {"skipped": True, "reason": "empty_description"}

    injection_findings = detect_prompt_injection(desc)
    red_flags = detect_red_flags(desc)
    quality = score_jd_quality(
        title=title,
        description=desc,
        parsed_jd=parsed_jd,
        salary=salary,
        company=company,
    )
    content_hash = compute_content_hash(desc)

    return {
        "prompt_injection": injection_findings,
        "red_flags": red_flags,
        "quality": quality,
        "content_hash": content_hash,
        "agency": (agency or "").strip(),
        "has_injection": len(injection_findings) > 0,
        "has_red_flags": len(red_flags) > 0,
        "flag_count": len(injection_findings) + len(red_flags),
    }
