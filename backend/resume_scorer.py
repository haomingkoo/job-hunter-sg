"""
Multi-dimensional resume scoring engine.

Scores a resume on three dimensions (Impact, Presentation, Competencies)
totalling 100 points. Optionally matches keywords against a job description.
Pure stdlib + re — no external dependencies.
"""

from __future__ import annotations

import re
from collections import Counter

from shared_classification import SHARED_KEY_MAP, classify_section_heading

# ── Constants ────────────────────────────────────────────────────────────────

ACTION_VERBS = {
    "achieved", "administered", "advanced", "analyzed", "analysed", "architected",
    "assembled", "assessed", "automated", "built", "calculated",
    "championed", "coached", "collaborated", "communicated", "completed",
    "conceptualized", "conceptualised", "conducted", "consolidated", "constructed",
    "consulted", "contributed", "controlled", "converted", "coordinated",
    "created", "cultivated", "customized", "customised", "decreased", "defined",
    "delivered", "demonstrated", "deployed", "designed", "developed",
    "devised", "diagnosed", "directed", "discovered", "documented",
    "drove", "earned", "edited", "educated", "eliminated", "enabled",
    "encouraged", "engineered", "enhanced", "established", "evaluated",
    "examined", "exceeded", "executed", "expanded", "expedited",
    "facilitated", "finalized", "finalised", "forecasted", "formulated", "founded",
    "generated", "governed", "guided", "headed", "identified",
    "illustrated", "implemented", "improved", "increased", "influenced",
    "initiated", "innovated", "inspected", "installed", "instituted",
    "integrated", "interpreted", "introduced", "invented", "investigated",
    "launched", "led", "leveraged", "maintained", "managed", "mapped",
    "maximized", "maximised", "mentored", "merged", "migrated",
    "minimized", "minimised", "modernized", "modernised", "monitored",
    "motivated", "navigated", "negotiated",
    "operated", "optimized", "optimised", "orchestrated",
    "organized", "organised", "originated",
    "outperformed", "overhauled", "oversaw", "partnered", "performed",
    "piloted", "pioneered", "planned", "prepared", "presented",
    "prioritized", "prioritised", "produced", "programmed", "promoted", "proposed",
    "provided", "published", "pursued", "reached", "realized", "realised",
    "recommended", "reconciled", "recruited", "redesigned", "reduced",
    "refined", "reformed", "regulated", "rehabilitated", "remodeled",
    "reorganized", "reorganised", "represented", "researched", "resolved", "restored",
    "restructured", "revamped", "reviewed", "revitalized", "scaled",
    "secured", "simplified", "solved", "spearheaded",
    "standardized", "standardised", "streamlined", "strengthened", "structured",
    "supervised", "surpassed", "sustained", "synchronized", "synchronised",
    "targeted", "tested", "trained", "transformed", "translated", "troubleshot",
    "unified", "upgraded", "validated", "verified", "visualized", "visualised",
}

AVOIDED_PHRASES = [
    "responsible for",
    "helped",
    "assisted",
    "duties included",
    "various",
    "utilized",
    "proactively",
]

COMMON_MISSPELLINGS = {
    "accomodation", "acheive", "accross", "agressive", "apparant",
    "begining", "beleive", "buisness", "calender", "catagory",
    "commitee", "concensus", "definately", "developement", "dillema",
    "dissapear", "embarass", "enviroment", "excercise", "existance",
    "fourty", "fulfil", "goverment", "harrass", "hygeine",
    "imediately", "independant", "judgement", "knowlege", "liason",
    "maintenence", "millenium", "neccessary", "noticable", "occurence",
    "oppurtunity", "parliment", "posession", "preceed", "privelege",
    "proffesional", "publically", "questionaire", "recieve", "recomend",
    "refered", "relevent", "religous", "repetition", "seperate",
    "succesful", "supercede", "surprize", "tommorow", "untill",
    "wierd", "writting", "wich", "aknowledge", "adress",
}

STANDARD_SECTIONS = [
    "summary", "objective", "experience", "work experience",
    "education", "skills", "certifications", "certification",
    "projects", "awards", "honors", "publications",
    "professional summary", "professional experience",
    "core skills", "core competencies", "technical skills",
    "about", "licenses & certifications", "honors & awards",
    "additional information", "languages", "languages & work authorization",
    "activities", "volunteer", "certifications & technical upskilling",
]

COMPETENCY_KEYWORDS: dict[str, list[str]] = {
    "analytical": [
        "data", "analysis", "research", "metrics", "statistical",
        "evaluate", "optimize", "quantitative", "forecast", "insights",
        "modeled", "assessed", "benchmarked", "analytics", "yield",
        "root cause", "rca", "kpi", "roi", "dashboard", "doe",
        "experiments", "optimization",
    ],
    "communication": [
        "presented", "communicated", "collaborated", "stakeholder",
        "facilitated", "negotiated", "articulated", "liaised",
        "reported", "briefed", "authored", "published", "aligned",
        "engaged", "translated", "partnered", "workshop", "workshops",
        "influenced",
    ],
    "leadership": [
        "led", "managed", "supervised", "mentored", "directed",
        "spearheaded", "oversaw", "headed", "governed", "guided",
        "delegated", "inspired", "owned", "owner", "program-managed",
        "program managed", "roadmap", "accountability",
    ],
    "teamwork": [
        "cross-functional", "collaborated", "partnered", "team",
        "contributed", "coordinated", "cooperated", "supported",
        "aligned", "joint", "cross functional", "stakeholders",
        "multi-site", "global teams", "workshops",
    ],
    "initiative": [
        "initiated", "launched", "created", "established", "pioneered",
        "proposed", "founded", "introduced", "innovated", "championed",
        "conceptualized", "originated", "transformed", "modernized",
        "orchestrated", "built", "deployed", "drove",
    ],
}

_METRIC_RE = re.compile(
    r"\d+%"
    r"|\$[\d,]+"
    r"|\d+\s*(?:team|users|people|projects|systems|clients)"
    r"|\d+[kKmMbB]\b"
    r"|\d{1,3}(?:,\d{3})+"
)

_BULLET_RE = re.compile(
    r"^[\s]*(?:[-*\u2022\u2023\u25E6\u2043\u2219]|\d+[.)]\s)",
    re.MULTILINE,
)

_DATE_FORMATS = [
    re.compile(
        r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
        r"[a-z]*\s+\d{4}\b",
        re.I,
    ),
    re.compile(r"\b\d{1,2}/\d{4}\b"),
    re.compile(
        r"\b\d{4}\s*[-\u2013]\s*(?:\d{4}|present|current)\b", re.I
    ),
]

_NORMALIZED_SECTION_KEYS = {
    "about": "summary",
    "professional summary": "summary",
    "career summary": "summary",
    "summary": "summary",
    "objective": "objective",
    "professional experience": "experience",
    "work experience": "experience",
    "experience": "experience",
    "education": "education",
    "core skills": "skills",
    "core competencies": "skills",
    "technical skills": "skills",
    "skills": "skills",
    "projects": "projects",
    "certifications": "certifications",
    "certification": "certifications",
    "licenses & certifications": "certifications",
    "certifications & technical upskilling": "certifications",
    "honors & awards": "awards",
    "additional information": "additional_information",
    "languages": "languages",
    "languages & work authorization": "languages",
    "activities": "activities",
    "volunteer": "activities",
}

_INLINE_HEADINGS = sorted(STANDARD_SECTIONS, key=len, reverse=True)
_MARKDOWN_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+")
_NOISE_LINE_PATTERNS = [
    re.compile(r"^\s*```"),
    re.compile(r"^\s*(?:---|\*\*\*|___)\s*$"),
    re.compile(r"copy\s*&\s*paste\s+ready", re.I),
    re.compile(r"paste\s+into\s+textedit", re.I),
    re.compile(r"paste\s+method", re.I),
    re.compile(r"shift\+enter", re.I),
    re.compile(r"paragraph\s+break", re.I),
    re.compile(r"description\s+paragraph\s*\(", re.I),
    re.compile(r"bullets?\s*\(", re.I),
    re.compile(r"then\s+type\s+these\s+bullets", re.I),
]


# ── Helpers ──────────────────────────────────────────────────────────────────

def _status(score: int, max_score: int) -> str:
    """Return status label based on score ratio."""
    if max_score == 0:
        return "good_job"
    ratio = score / max_score
    if ratio >= 0.8:
        return "good_job"
    if ratio >= 0.5:
        return "on_track"
    return "needs_work"


def _split_action_sentences(text: str) -> list[str]:
    """Split a line into individual sentences when each starts with an action verb.

    Handles the common case where PDF extraction joins multiple bullets
    onto one line, e.g. "Led X. Directed Y. Achieved Z."
    Returns the original text as a single-element list when splitting
    doesn't apply.
    """
    # Split on sentence boundaries: period/semicolon followed by space
    # and a capitalized word
    parts = re.split(r"(?<=[.;])\s+(?=[A-Z])", text)
    if len(parts) <= 1:
        return [text]

    result: list[str] = []
    for part in parts:
        cleaned = part.strip().rstrip(".")
        if not cleaned:
            continue
        first = cleaned.split()[0].lower().rstrip(",;:") if cleaned.split() else ""
        if first in ACTION_VERBS:
            result.append(cleaned)
        else:
            # If any part doesn't start with an action verb, don't split
            return [text]
    return result if result else [text]


def _clean_line(text: str) -> str:
    stripped = re.sub(r"(\*\*|__)", "", text or "")
    stripped = _MARKDOWN_HEADING_RE.sub("", stripped)
    return stripped.strip()


def _is_noise_line(text: str) -> bool:
    stripped = _clean_line(text)
    if not stripped:
        return False
    return any(pattern.search(stripped) for pattern in _NOISE_LINE_PATTERNS)


def _section_key(line: str) -> str:
    lower = _clean_line(line).lower().rstrip(":")
    return _NORMALIZED_SECTION_KEYS.get(lower, SHARED_KEY_MAP.get(lower, lower))


def _split_inline_heading_line(line: str) -> list[str]:
    stripped = _clean_line(line)
    if not stripped:
        return [""]

    lower = stripped.lower()
    for heading in _INLINE_HEADINGS:
        pattern = re.compile(
            rf"^({re.escape(heading)})(?:\s*[:|]\s*|\s+[-–—]\s+)(.+)$",
            re.I,
        )
        match = pattern.match(stripped)
        if not match:
            continue
        remainder = match.group(2).strip()
        if not remainder:
            continue
        if remainder.lower().startswith(("&", "/", "and ")):
            continue
        # Avoid splitting genuine headers like "Professional Summary:"
        if remainder.lower() in _NORMALIZED_SECTION_KEYS:
            continue
        heading_text = match.group(1).strip()
        if stripped == stripped.upper():
            heading_text = heading_text.upper()
        return [heading_text, remainder]
    return [stripped]


def _iter_resume_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw_line in text.split("\n"):
        if _is_noise_line(raw_line):
            continue
        lines.extend(_split_inline_heading_line(raw_line))
    return lines


def _starts_with_action_verb(text: str) -> bool:
    words = _clean_line(text).split()
    if not words:
        return False
    first = words[0].lower().rstrip(",;:")
    base = first.split("-")[-1] if "-" in first else first
    return first in ACTION_VERBS or base in ACTION_VERBS


class ResumeScorer:
    """Analyses resume text and returns a structured score report."""

    # ── Text extraction helpers ──────────────────────────────────────────

    @staticmethod
    def _extract_bullets(text: str) -> list[str]:
        """Extract bullet-point lines from resume text.

        Detects bullets in three ways:
        1. Lines starting with a bullet character (•, -, *, etc.)
        2. Lines starting with an action verb that follow a subheading/date
        3. Lines that look like achievements (contain metrics)
        """
        _date_re = re.compile(
            r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}"
            r"|\d{1,2}/\d{4}"
            r"|\d{4}\s*[-–]\s*(?:\d{4}|present|current)",
            re.I,
        )
        _achievement_re = re.compile(
            r"\d+%"
            r"|\$[\d,]+"
            r"|\d+\s*(?:team|users|people|projects|systems|clients)"
            r"|team\s+of\s+\d+"
            r"|\d+[kKmMbB]\b"
            r"|\d{1,3}(?:,\d{3})+",
        )
        _all_caps_header = re.compile(r"^[A-Z][A-Z &/\-]{2,}$")
        _role_separator = re.compile(r"[|—–]")

        bullets: list[str] = []
        lines = _iter_resume_lines(text)
        context_window = 0
        current_section = ""
        pending_explicit_index: int | None = None

        for line in lines:
            stripped = _clean_line(line)
            if not stripped:
                context_window = max(0, context_window - 1)
                continue

            is_header = _all_caps_header.match(stripped)
            has_date = bool(_date_re.search(stripped))
            has_role_sep = bool(_role_separator.search(stripped))
            section_key = _section_key(stripped)
            explicit_bullet = bool(_BULLET_RE.match(line))

            if pending_explicit_index is not None and not (explicit_bullet or is_header or has_date or has_role_sep):
                if not bullets[pending_explicit_index].endswith((".", "!", "?", ";")) or stripped[:1].islower():
                    bullets[pending_explicit_index] += " " + stripped
                    continue
            pending_explicit_index = None

            # Explicit markers take priority over dates and separators inside the bullet.
            _non_bullet_sections = {"skills", "certifications", "education", "languages", "awards"}
            if explicit_bullet:
                if current_section in _non_bullet_sections:
                    continue
                cleaned = re.sub(
                    r"^[\s]*(?:[-*\u2022\u2023\u25E6\u2043\u2219]"
                    r"|\d+[.)]\s)\s*",
                    "",
                    line,
                ).strip()
                if cleaned:
                    bullets.append(cleaned)
                    pending_explicit_index = len(bullets) - 1
                continue

            if is_header or section_key in _NORMALIZED_SECTION_KEYS.values():
                current_section = section_key
                context_window = 2
                continue

            if has_date or has_role_sep:
                context_window = 2
                continue

            # Methods 2 & 3: action-verb start or achievement pattern
            starts_with_action = _starts_with_action_verb(stripped)
            looks_like_achievement = bool(_achievement_re.search(stripped))
            bullet_friendly_section = current_section in {
                "experience", "projects", "activities", ""
            }

            if bullet_friendly_section and context_window > 0 and (starts_with_action or looks_like_achievement):
                _sub_bullets = _split_action_sentences(stripped)
                bullets.extend(_sub_bullets)
                context_window = max(0, context_window - 1)
                continue

            # Achievement line even without prior subheading context
            if bullet_friendly_section and starts_with_action and (
                looks_like_achievement or len(stripped.split()) >= 8
            ):
                _sub_bullets = _split_action_sentences(stripped)
                bullets.extend(_sub_bullets)
                continue

            context_window = max(0, context_window - 1)

        return bullets

    @staticmethod
    def _extract_sections(text: str) -> list[str]:
        """Identify section headers in the resume."""
        found: list[str] = []
        for line in _iter_resume_lines(text):
            stripped = _clean_line(line)
            if not stripped:
                continue
            section_key = classify_section_heading(stripped)
            if section_key:
                found.append(section_key)
                continue
            if (
                len(stripped) >= 2
                and stripped == stripped.upper()
                and re.search(r"[A-Z]", stripped)
                and len(stripped.split()) <= 6
            ):
                found.append(_section_key(stripped))
                continue
            if stripped.endswith(":") and len(stripped.split()) <= 5:
                found.append(_section_key(stripped))
        return list(dict.fromkeys(found))  # dedupe, preserve order

    @staticmethod
    def _find_action_verbs(bullet: str) -> bool:
        """Check whether the first word of a bullet is an action verb."""
        return _starts_with_action_verb(bullet)

    # ── Dimension scorers ────────────────────────────────────────────────

    def _score_impact(
        self,
        text: str,
        bullets: list[str],
        sections: list[str] | None = None,
    ) -> dict:
        """Score the Impact dimension (40 pts)."""
        items: dict[str, dict] = {}

        # action_oriented (10)
        action_count = sum(
            1 for b in bullets if self._find_action_verbs(b)
        )
        total_bullets = len(bullets) or 1
        action_pct = action_count / total_bullets
        action_score = min(10, round(action_pct * 10))
        action_suggestions: list[str] = []
        if action_pct < 0.8:
            action_suggestions.append(
                "Start more bullets with strong action verbs "
                "(e.g., Developed, Led, Implemented)"
            )
        items["action_oriented"] = {
            "score": action_score,
            "max": 10,
            "status": _status(action_score, 10),
            "detail": (
                f"{action_count}/{len(bullets)} bullets start "
                f"with action verbs"
            ),
            "suggestions": action_suggestions,
        }

        # specifics (10)
        metric_count = sum(
            1 for b in bullets if _METRIC_RE.search(b)
        )
        metric_pct = metric_count / total_bullets
        specifics_score = min(10, round(metric_pct * 10))
        specifics_suggestions: list[str] = []
        if metric_pct < 0.5:
            specifics_suggestions.append(
                "Quantify achievements with numbers, "
                "percentages, or dollar amounts"
            )
        items["specifics"] = {
            "score": specifics_score,
            "max": 10,
            "status": _status(specifics_score, 10),
            "detail": (
                f"{metric_count}/{len(bullets)} bullets "
                f"contain metrics/numbers"
            ),
            "suggestions": specifics_suggestions,
        }

        # overusage (10)
        words_lower = re.findall(r"[a-z]+", text.lower())
        word_counts = Counter(words_lower)
        stopwords = {
            "the", "a", "an", "and", "or", "of", "to", "in", "for",
            "with", "on", "at", "by", "is", "was", "are", "were", "be",
            "been", "has", "had", "have", "that", "this", "it", "as",
            "from", "not", "but", "i", "my", "me",
        }
        # Technical / domain terms that legitimately repeat on resumes
        _tech_exempt = {
            "python", "java", "javascript", "typescript", "react",
            "node", "django", "flask", "fastapi", "docker",
            "kubernetes", "linux", "windows", "azure", "cloud",
            "database", "software", "development", "engineering",
            "management", "quality", "system", "systems", "data",
            "analytics", "analysis", "machine", "learning", "model",
            "design", "testing", "security", "network", "server",
            "frontend", "backend", "fullstack", "devops", "agile",
            "scrum", "project", "product", "business", "customer",
            "service", "sales", "marketing", "operations", "process",
            "team", "company", "experience", "skills", "education",
            "singapore", "certification", "certified", "automation",
            "digital", "transformation", "program", "manager",
            "leadership", "stakeholder", "stakeholders",
        }
        overused = [
            w for w, c in word_counts.items()
            if c >= 5
            and w not in stopwords
            and w not in _tech_exempt
            and len(w) > 3
        ]
        penalty = min(6, len(overused))
        overusage_score = max(0, 10 - penalty)
        overusage_suggestions: list[str] = []
        if overused:
            top = sorted(overused, key=lambda w: -word_counts[w])[:5]
            overusage_suggestions.append(
                f"Reduce repetition of: {', '.join(top)}"
            )
        items["overusage"] = {
            "score": overusage_score,
            "max": 10,
            "status": _status(overusage_score, 10),
            "detail": f"{len(overused)} non-technical words used 5+ times",
            "suggestions": overusage_suggestions,
        }

        # avoided_words (5)
        text_lower = text.lower()
        filler_hits = sum(
            1 for phrase in AVOIDED_PHRASES if phrase in text_lower
        )
        avoided_score = max(0, 5 - filler_hits)
        avoided_suggestions: list[str] = []
        found_fillers = [
            p for p in AVOIDED_PHRASES if p in text_lower
        ]
        if found_fillers:
            avoided_suggestions.append(
                "Remove filler phrases: "
                + ", ".join(f'"{f}"' for f in found_fillers)
            )
        items["avoided_words"] = {
            "score": avoided_score,
            "max": 5,
            "status": _status(avoided_score, 5),
            "detail": f"{filler_hits} filler phrases found",
            "suggestions": avoided_suggestions,
        }

        # extracurricular (5)
        extra_found = "activities" in (
            sections if sections is not None else self._extract_sections(text)
        )
        extra_score = 5 if extra_found else 3
        extra_suggestions: list[str] = []
        if not extra_found:
            extra_suggestions.append(
                "Optional: add leadership, volunteer, or community activity only if it strengthens your story"
            )
        items["extracurricular"] = {
            "score": extra_score,
            "max": 5,
            "status": _status(extra_score, 5),
            "detail": (
                "Extracurricular/volunteer content detected"
                if extra_found
                else "No extracurricular content detected -- optional for many experienced candidates"
            ),
            "suggestions": extra_suggestions,
        }

        total = sum(item["score"] for item in items.values())
        return {
            "score": total,
            "max": 40,
            "status": _status(total, 40),
            "items": items,
        }

    def _score_presentation(
        self,
        text: str,
        bullets: list[str],
        sections: list[str],
        template_sections: list[str] | None = None,
    ) -> dict:
        """Score the Presentation dimension (30 pts)."""
        items: dict[str, dict] = {}
        words = text.split()
        word_count = len(words)

        # word_count (5)
        # SG market: 1-2 page resumes are common, and experienced candidates
        # can reasonably stretch past 900 words without it being a problem.
        # Only penalize clear extremes.
        if 350 <= word_count <= 1200:
            wc_score = 5
        elif 250 <= word_count <= 1400:
            wc_score = 3
        else:
            wc_score = 1
        wc_suggestions: list[str] = []
        if word_count < 350:
            wc_suggestions.append(
                f"Resume is short ({word_count} words). "
                f"Aim for roughly 350-1200 words depending on experience."
            )
        elif word_count > 1200:
            wc_suggestions.append(
                f"Resume is long ({word_count} words). "
                f"Consider trimming if it runs materially beyond 2 pages."
            )
        items["word_count"] = {
            "score": wc_score,
            "max": 5,
            "status": _status(wc_score, 5),
            "detail": f"{word_count} words",
            "suggestions": wc_suggestions,
        }

        # bullet_count (5)
        bc = len(bullets)
        if 15 <= bc <= 25:
            bc_score = 5
        elif 10 <= bc <= 35:
            bc_score = 3
        else:
            bc_score = 1
        bc_suggestions: list[str] = []
        if bc < 15:
            bc_suggestions.append(
                f"Only {bc} bullets found. "
                f"Aim for 15-25 to demonstrate depth."
            )
        elif bc > 25:
            bc_suggestions.append(
                f"{bc} bullets found. Trim to 15-25 for conciseness."
            )
        items["bullet_count"] = {
            "score": bc_score,
            "max": 5,
            "status": _status(bc_score, 5),
            "detail": f"{bc} bullet points",
            "suggestions": bc_suggestions,
        }

        # section_count (5)
        if template_sections:
            expected = set(template_sections)
        else:
            expected = {"summary", "objective", "experience", "education", "skills", "certifications"}
        matched_sections = [s for s in sections if s in expected]
        sc_count = len(matched_sections)
        expected_count = len(expected)
        if sc_count >= min(4, expected_count):
            sc_score = 5
        elif sc_count >= min(3, expected_count - 1):
            sc_score = 3
        elif sc_count >= 2:
            sc_score = 2
        else:
            sc_score = 1
        missing = expected - set(matched_sections)
        sc_suggestions: list[str] = []
        if missing:
            examples = sorted(missing)[:4]
            prefix = "Your template expects" if template_sections else "Consider adding"
            sc_suggestions.append(
                f"{prefix} sections: {', '.join(examples)}"
            )
        detail_label = "template" if template_sections else "standard"
        items["section_count"] = {
            "score": sc_score,
            "max": 5,
            "status": _status(sc_score, 5),
            "detail": (
                f"{sc_count}/{expected_count} {detail_label} sections found: "
                f"{', '.join(matched_sections) or 'none'}"
            ),
            "suggestions": sc_suggestions,
        }

        # format_consistency (5)
        fmt_score = 5
        fmt_suggestions: list[str] = []
        date_matches: list[str] = []
        for pattern in _DATE_FORMATS:
            date_matches.extend(pattern.findall(text))
        if len(date_matches) >= 2:
            has_slash = any("/" in d for d in date_matches)
            has_month = any(
                re.search(r"[A-Za-z]", d) for d in date_matches
            )
            if has_slash and has_month:
                fmt_score -= 2
                fmt_suggestions.append(
                    "Use a consistent date format throughout "
                    "(e.g., Jan 2024)"
                )
        caps_blocks = [
            line for line in _iter_resume_lines(text)
            if line
            and line == line.upper()
            and len(line.split()) >= 8
        ]
        if caps_blocks:
            fmt_score -= 2
            fmt_suggestions.append(
                "Avoid large ALL CAPS blocks "
                "-- use Title Case for headers"
            )
        fmt_score = max(0, fmt_score)
        items["format_consistency"] = {
            "score": fmt_score,
            "max": 5,
            "status": _status(fmt_score, 5),
            "detail": (
                "Formatting looks consistent"
                if fmt_score >= 4
                else "Some formatting inconsistencies detected"
            ),
            "suggestions": fmt_suggestions,
        }

        # spell_check (5)
        text_words = set(re.findall(r"[a-z]+", text.lower()))
        misspelled = text_words & COMMON_MISSPELLINGS
        sp_penalty = len(misspelled) * 2
        sp_score = max(0, 5 - sp_penalty)
        sp_suggestions: list[str] = []
        if misspelled:
            sp_suggestions.append(
                f"Check spelling: "
                f"{', '.join(sorted(misspelled)[:5])}"
            )
        items["spell_check"] = {
            "score": sp_score,
            "max": 5,
            "status": _status(sp_score, 5),
            "detail": (
                f"{len(misspelled)} potential misspellings found"
            ),
            "suggestions": sp_suggestions,
        }

        # page_estimate (5)
        pages = max(1, round(word_count / 550))
        if 1 <= pages <= 2:
            pg_score = 5
        elif pages == 3:
            pg_score = 3
        else:
            pg_score = 1
        pg_suggestions: list[str] = []
        if pages > 3:
            pg_suggestions.append(
                f"Estimated {pages} pages. Aim for 1-3 pages depending on seniority."
            )
        elif word_count < 250:
            pg_suggestions.append(
                "Resume appears very short. "
                "Consider adding more detail."
            )
        items["page_estimate"] = {
            "score": pg_score,
            "max": 5,
            "status": _status(pg_score, 5),
            "detail": (
                f"~{pages} page(s) estimated ({word_count} words)"
            ),
            "suggestions": pg_suggestions,
        }

        total = sum(item["score"] for item in items.values())
        return {
            "score": total,
            "max": 30,
            "status": _status(total, 30),
            "items": items,
        }

    def _score_competencies(self, text: str) -> dict:
        """Score the Competencies dimension (30 pts)."""
        text_lower = text.lower()
        items: dict[str, dict] = {}

        for comp_name, keywords in COMPETENCY_KEYWORDS.items():
            matched = [kw for kw in keywords if kw in text_lower]
            match_count = len(matched)
            if match_count >= 5:
                score = 6
            elif match_count == 4:
                score = 5
            elif match_count == 3:
                score = 4
            elif match_count == 2:
                score = 3
            elif match_count == 1:
                score = 2
            else:
                score = 1
            suggestions: list[str] = []
            if score < 4:
                missing_kw = [
                    kw for kw in keywords if kw not in text_lower
                ][:3]
                suggestions.append(
                    f"Strengthen {comp_name} with keywords: "
                    f"{', '.join(missing_kw)}"
                )
            missing_all = [kw for kw in keywords if kw not in text_lower]
            items[comp_name] = {
                "score": score,
                "max": 6,
                "status": _status(score, 6),
                "detail": (
                    f"{len(matched)}/{len(keywords)} keywords matched"
                ),
                "matched_keywords": matched,
                "missing_keywords": missing_all[:8],
                "suggestions": suggestions,
            }

        total = sum(item["score"] for item in items.values())
        return {
            "score": total,
            "max": 30,
            "status": _status(total, 30),
            "items": items,
        }

    # ── Keyword matching ─────────────────────────────────────────────────

    @staticmethod
    def _keyword_match(text: str, job_description: str) -> dict:
        """Compare resume against JD using multi-word skill phrase extraction."""
        if not job_description.strip():
            return {"matched": [], "missing": [], "score_percent": 0}

        try:
            from ats_terms import build_job_ats_terms, match_resume_against_job_terms

            jd_terms = build_job_ats_terms(job_description)
            if not jd_terms:
                return {"matched": [], "missing": [], "score_percent": 0}
            result = match_resume_against_job_terms(text, jd_terms, jd_text=job_description)
            return {
                "matched": result.get("matched", []),
                "missing": result.get("missing", []),
                "score_percent": result.get("match_percent", 0),
            }
        except Exception:
            return {"matched": [], "missing": [], "score_percent": 0}

    # ── Suggestions builder ──────────────────────────────────────────────

    @staticmethod
    def _build_suggestions(dimensions: dict) -> list[dict]:
        """Collect top suggestions sorted by potential point gain."""
        suggestions: list[dict] = []
        for _dim_name, dim in dimensions.items():
            for item_name, item in dim["items"].items():
                gap = item["max"] - item["score"]
                if gap > 0 and item["suggestions"]:
                    suggestions.append({
                        "action": (
                            f"Improve "
                            f"{item_name.replace('_', ' ')}"
                        ),
                        "points": gap,
                        "detail": item["suggestions"][0],
                    })
        suggestions.sort(key=lambda s: -s["points"])
        return suggestions[:5]

    # ── Evaluation blocks ────────────────────────────────────────────────

    @staticmethod
    def _build_evaluation_blocks(
        dimensions: dict,
        ats_match: dict | None,
        parsed_jd: dict | None,
        quality_score: int,
    ) -> list[dict]:
        """Generate actionable evaluation blocks beyond the 0-100 score.

        Returns a list of block dicts, each with type, title, icon,
        and items (list of {label, detail, action_type}).
        """
        blocks: list[dict] = []

        # ── a) Role Fit Assessment ──────────────────────────────────────
        role_fit_items: list[dict] = []
        impact_score = dimensions.get("impact", {}).get("score", 0)
        impact_max = dimensions.get("impact", {}).get("max", 40)
        comp_score = dimensions.get("competencies", {}).get("score", 0)
        comp_max = dimensions.get("competencies", {}).get("max", 30)
        pres_score = dimensions.get("presentation", {}).get("score", 0)
        pres_max = dimensions.get("presentation", {}).get("max", 30)

        if impact_score > 30:
            role_fit_items.append({
                "label": "Strong impact",
                "detail": (
                    "Strong quantitative storytelling - your bullets "
                    "show measurable results"
                ),
                "action_type": "positive",
            })
        elif impact_score < 20:
            role_fit_items.append({
                "label": "Impact needs work",
                "detail": (
                    "Impact needs strengthening - add metrics "
                    "to more bullets"
                ),
                "action_type": "reframe",
            })

        if comp_score > 20:
            role_fit_items.append({
                "label": "Strong competencies",
                "detail": (
                    "Competency signals are strong for this "
                    "role type"
                ),
                "action_type": "positive",
            })
        elif comp_score < 15:
            role_fit_items.append({
                "label": "Thin competencies",
                "detail": (
                    "Competency keywords are thin - review the "
                    "missing keywords below"
                ),
                "action_type": "add_skill",
            })

        if pres_score > 25:
            role_fit_items.append({
                "label": "Well organized",
                "detail": (
                    "Resume is well-organized and polished"
                ),
                "action_type": "positive",
            })
        elif pres_score < 15:
            role_fit_items.append({
                "label": "Formatting attention",
                "detail": (
                    "Formatting needs attention - check section "
                    "structure and consistency"
                ),
                "action_type": "reframe",
            })

        if role_fit_items:
            blocks.append({
                "type": "role_fit",
                "title": "Role Fit Assessment",
                "icon": "target",
                "items": role_fit_items,
            })

        # ── b) Skill Gap Analysis ───────────────────────────────────────
        if ats_match and ats_match.get("missing_terms"):
            matched_set = {
                t.lower() for t in ats_match.get("matched_terms", [])
            }
            skill_gap_items: list[dict] = []
            _tool_keywords = {
                "python", "java", "javascript", "typescript", "react",
                "node", "sql", "aws", "azure", "gcp", "docker",
                "kubernetes", "git", "jira", "figma", "tableau",
                "excel", "power bi", "terraform", "linux", "matlab",
                "r", "sas", "spark", "hadoop", "mongodb", "redis",
                "kafka", "elasticsearch", "jenkins", "ci/cd",
                "graphql", "rest", "api", "html", "css", "sass",
                "vue", "angular", "svelte", "django", "flask",
                "fastapi", "spring", "rails", "laravel", "php",
                "swift", "kotlin", "go", "rust", "c++", "c#",
                ".net", "pytorch", "tensorflow", "pandas", "numpy",
                "scikit-learn", "airflow", "dbt", "snowflake",
                "bigquery", "redshift", "postman", "cypress",
                "selenium", "playwright",
            }
            _soft_keywords = {
                "communication", "collaboration", "teamwork",
                "leadership", "problem-solving", "critical thinking",
                "adaptability", "time management", "negotiation",
                "presentation", "mentoring", "coaching",
                "stakeholder management", "conflict resolution",
                "decision making", "strategic thinking",
                "interpersonal", "empathy", "creativity",
                "self-motivated", "detail-oriented", "proactive",
                "initiative", "accountability",
            }

            for missing in ats_match["missing_terms"][:5]:
                missing_lower = missing.lower()

                # Strategy 1: semantically similar matched term
                similar = None
                for m in matched_set:
                    if (
                        missing_lower in m
                        or m in missing_lower
                        or (
                            len(missing_lower) > 3
                            and len(m) > 3
                            and missing_lower[:4] == m[:4]
                        )
                    ):
                        similar = m
                        break

                if similar:
                    skill_gap_items.append({
                        "label": missing,
                        "detail": (
                            f"You have '{similar}'. Reframe a "
                            f"bullet to also mention '{missing}'."
                        ),
                        "action_type": "reframe",
                    })
                elif missing_lower in _tool_keywords:
                    skill_gap_items.append({
                        "label": missing,
                        "detail": (
                            "Consider adding this to your Skills "
                            "section if you have experience."
                        ),
                        "action_type": "add_skill",
                    })
                elif missing_lower in _soft_keywords:
                    skill_gap_items.append({
                        "label": missing,
                        "detail": (
                            "Weave this into an achievement bullet "
                            "rather than listing it standalone."
                        ),
                        "action_type": "weave_in",
                    })
                else:
                    # Default: classify as add_skill for tools/tech
                    # patterns, weave_in otherwise
                    words = missing_lower.split()
                    looks_technical = (
                        len(words) <= 2
                        and not any(
                            w in _soft_keywords for w in words
                        )
                    )
                    if looks_technical:
                        skill_gap_items.append({
                            "label": missing,
                            "detail": (
                                "Consider adding this to your "
                                "Skills section if you have "
                                "experience."
                            ),
                            "action_type": "add_skill",
                        })
                    else:
                        skill_gap_items.append({
                            "label": missing,
                            "detail": (
                                "Weave this into an achievement "
                                "bullet rather than listing it "
                                "standalone."
                            ),
                            "action_type": "weave_in",
                        })

            if skill_gap_items:
                blocks.append({
                    "type": "skill_gaps",
                    "title": "Skill Gap Analysis",
                    "icon": "puzzle",
                    "items": skill_gap_items,
                })

        # ── c) Interview Prep Angles ────────────────────────────────────
        if parsed_jd:
            interview_items: list[dict] = []
            comp_signals = parsed_jd.get("competency_signals", {})
            if isinstance(comp_signals, dict):
                for comp_name, signal_kws in comp_signals.items():
                    if isinstance(signal_kws, list) and len(signal_kws) >= 2:
                        kw_sample = ", ".join(signal_kws[:4])
                        interview_items.append({
                            "label": comp_name.replace("_", " ").title(),
                            "detail": (
                                f"They'll likely ask about "
                                f"{comp_name}. Prepare a story "
                                f"showing {kw_sample}."
                            ),
                            "action_type": "weave_in",
                        })

            exp_years = str(
                parsed_jd.get("experience_years", "")
            ).strip()
            if exp_years:
                interview_items.append({
                    "label": "Seniority alignment",
                    "detail": (
                        f"JD asks for {exp_years} experience. "
                        f"Ensure your resume highlights relevant "
                        f"tenure and progression."
                    ),
                    "action_type": "reframe",
                })

            if interview_items:
                blocks.append({
                    "type": "interview_angles",
                    "title": "Interview Prep Angles",
                    "icon": "lightbulb",
                    "items": interview_items,
                })

        return blocks

    # ── ATS keyword match against parsed JD ─────────────────────────────

    @staticmethod
    def _ats_match_from_parsed_jd(
        resume_text: str,
        parsed_jd: dict,
    ) -> dict:
        """Score ATS keyword overlap between resume and a pre-parsed JD.

        Terms come from required_skills, preferred_skills and
        single_word_skills, lowercased and matched as substrings of the
        resume text.
        """
        terms: list[str] = []
        for key in ("required_skills", "preferred_skills", "single_word_skills"):
            terms.extend(parsed_jd.get(key, []))

        # Deduplicate while preserving order
        seen: set[str] = set()
        unique_terms: list[str] = []
        for term in terms:
            lower = term.lower().strip()
            if lower and lower not in seen:
                seen.add(lower)
                unique_terms.append(lower)

        if not unique_terms:
            return {
                "matched_terms": [],
                "missing_terms": [],
                "matched": 0,
                "total": 0,
                "match_pct": 0.0,
            }

        resume_lower = resume_text.lower()
        matched: list[str] = []
        missing: list[str] = []
        for term in unique_terms:
            if term in resume_lower:
                matched.append(term)
            else:
                missing.append(term)

        match_pct = (len(matched) / len(unique_terms)) * 100

        return {
            "matched_terms": matched,
            "missing_terms": missing,
            "matched": len(matched),
            "total": len(unique_terms),
            "match_pct": round(match_pct, 1),
        }

    # ── Main entry point ─────────────────────────────────────────────────

    def analyze(
        self,
        resume_text: str,
        job_description: str = "",
        parsed_jd: dict | None = None,
        template_sections: list[str] | None = None,
        resume_document: dict | None = None,
    ) -> dict:
        """Score a resume and return a structured report.

        When *parsed_jd* is provided the overall score blends quality
        (60 %) with ATS keyword match (40 %).  Without it the score
        reflects quality only (backward-compatible).
        """
        text = resume_text.strip()
        if resume_document is None:
            from resume_document import create_resume_document

            resume_document = create_resume_document(text)
        canonical_bullets = [
            block
            for block in resume_document.get("blocks", [])
            if block.get("kind") == "bullet"
        ]
        bullets = [str(block.get("text") or "") for block in canonical_bullets]
        sections = [
            str(section.get("key"))
            for section in resume_document.get("sections", [])
            if section.get("key")
        ]

        impact = self._score_impact(text, bullets, sections)
        presentation = self._score_presentation(
            text, bullets, sections, template_sections,
        )
        competencies = self._score_competencies(text)

        dimensions = {
            "impact": impact,
            "presentation": presentation,
            "competencies": competencies,
        }

        quality_score = (
            impact["score"]
            + presentation["score"]
            + competencies["score"]
        )
        keyword_match = self._keyword_match(text, job_description)
        top_suggestions = self._build_suggestions(dimensions)

        sg_tips = [
            "Mention residency status (SG Citizen/PR)"
            " -- many roles require it",
            "SkillsFuture/WSQ certifications resonate"
            " with SG employers",
            "MyCareersFuture uses skills-based matching"
            " -- list specific skills",
        ]

        ats_match: dict | None = None
        if parsed_jd:
            ats_match = self._ats_match_from_parsed_jd(text, parsed_jd)
            ats_match_pct = ats_match["match_pct"]
            overall = round(quality_score * 0.6 + ats_match_pct * 0.4)
            ats_match["blended"] = True
        else:
            overall = quality_score

        result: dict = {
            "overall_score": overall,
            "quality_score": quality_score,
            "dimensions": dimensions,
            "keyword_match": keyword_match,
            "top_suggestions": top_suggestions,
            "sg_tips": sg_tips,
            "detected_sections": list(dict.fromkeys(sections)),
            "resume_evidence": {
                "document_revision": resume_document.get("revision"),
                "sections": list(dict.fromkeys(sections)),
                "bullets": [
                    {
                        "id": block.get("id"),
                        "section_key": block.get("section_key") or "",
                    }
                    for block in canonical_bullets
                ],
            },
        }
        if ats_match is not None:
            result["ats_match"] = ats_match

        result["evaluation_blocks"] = self._build_evaluation_blocks(
            dimensions, ats_match, parsed_jd, quality_score,
        )

        return result
