"""
Job description pre-parser -- runs at scrape time for fast downstream matching.

Pure local computation (regex + string matching), no LLM calls.
Target: ~50ms per job description.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from resume_scorer import COMPETENCY_KEYWORDS
from skill_extractor import extract_skill_phrases

log = logging.getLogger("jobhunter.jd_preparser")

SINGLE_WORD_TECH: set[str] = {
    "python", "java", "javascript", "typescript", "go", "golang",
    "rust", "c++", "c#", "ruby", "php", "swift", "kotlin", "scala",
    "r", "sql", "nosql", "mongodb", "postgresql", "mysql", "redis",
    "elasticsearch", "docker", "kubernetes", "terraform", "ansible",
    "jenkins", "react", "angular", "vue", "svelte", "nextjs",
    "django", "flask", "fastapi", "spring", "express", "node",
    "nodejs", "aws", "azure", "gcp", "linux", "git", "jira",
    "confluence", "tableau", "powerbi", "excel", "figma", "sketch",
    "pytorch", "tensorflow", "keras", "scikit-learn", "pandas",
    "numpy", "spark", "hadoop", "airflow", "kafka", "rabbitmq",
    "graphql", "rest", "grpc", "websocket", "html", "css", "sass",
    "tailwind", "opnet", "qunetsim", "ns-3", "matlab",
}

# Markers that split required vs preferred skills
_PREFERRED_MARKERS: list[str] = [
    "preferred",
    "nice to have",
    "bonus",
    "good to have",
    "desirable",
    "advantageous",
]

# Regex for experience years extraction
_EXPERIENCE_RE = re.compile(
    r"(?:"
    r"(?:at\s+least|minimum|min\.?)\s+(\d+)\s*\+?\s*years?"
    r"|(\d+)\s*\+\s*years?"
    r"|(\d+)\s*[-–]\s*(\d+)\s*years?"
    r"|(\d+)\s+years?\s+(?:of\s+)?(?:experience|exp)"
    r")",
    re.IGNORECASE,
)

# Education level keywords ordered by highest to lowest
_EDUCATION_LEVELS: list[tuple[str, list[str]]] = [
    ("phd", ["phd", "ph.d", "doctorate", "doctoral"]),
    ("master", ["master's", "masters", "master", "msc", "m.sc",
                "mba", "m.b.a"]),
    ("bachelor", ["bachelor's", "bachelors", "bachelor", "bsc",
                  "b.sc", "b.a.", "b.eng", "undergraduate"]),
    ("diploma", ["diploma", "polytechnic", "poly"]),
    ("degree", ["degree"]),
]

# Bullet-point line pattern
_BULLET_LINE_RE = re.compile(
    r"^\s*(?:[-*\u2022\u2023\u25E6\u2043\u2219]|\d{1,2}[.)]\s)",
    re.MULTILINE,
)

# Precompile patterns for tech terms that contain special regex chars
_TECH_PATTERNS: dict[str, re.Pattern[str]] = {}
for _term in SINGLE_WORD_TECH:
    _escaped = re.escape(_term)
    _TECH_PATTERNS[_term] = re.compile(
        rf"\b{_escaped}\b", re.IGNORECASE
    )


def _find_preferred_split(text: str) -> int:
    """Find the character index where 'preferred' section begins.

    Returns -1 if no preferred marker found.
    """
    text_lower = text.lower()
    earliest = -1
    for marker in _PREFERRED_MARKERS:
        idx = text_lower.find(marker)
        if idx != -1 and (earliest == -1 or idx < earliest):
            earliest = idx
    return earliest


def _extract_experience_years(text: str) -> str:
    """Extract experience years requirement from JD text.

    Returns strings like "5+", "3-5", "3", or "" if not found.
    """
    match = _EXPERIENCE_RE.search(text)
    if not match:
        return ""

    # Group 1: "at least/minimum N years"
    if match.group(1):
        return f"{match.group(1)}+"
    # Group 2: "N+ years"
    if match.group(2):
        return f"{match.group(2)}+"
    # Groups 3-4: "N-M years"
    if match.group(3) and match.group(4):
        return f"{match.group(3)}-{match.group(4)}"
    # Group 5: "N years of experience"
    if match.group(5):
        return match.group(5)

    return ""


def _extract_education_level(text: str) -> str:
    """Extract the highest education level mentioned in the JD."""
    text_lower = text.lower()
    for level, keywords in _EDUCATION_LEVELS:
        for kw in keywords:
            pattern = re.compile(
                rf"\b{re.escape(kw)}\b", re.IGNORECASE
            )
            if pattern.search(text_lower):
                return level
    return ""


def _extract_single_word_tech(text: str) -> list[str]:
    """Find single-word tech terms in the JD text."""
    found: list[str] = []
    for term, pattern in _TECH_PATTERNS.items():
        if pattern.search(text):
            found.append(term)
    found.sort()
    return found


def _extract_prose_noun_phrases(text: str) -> list[str]:
    """Extract capitalized multi-word noun phrases from prose text.

    Catches domain terms like "Real Estate", "Life Sciences", "Digital Twin",
    "Information Technology" that aren't in the static known-skills list.
    """
    # Match 2-4 word capitalized phrases (Title Case)
    pattern = re.compile(
        r"\b([A-Z][a-z]+(?:\s+(?:and|&|of|for|in)\s+)?[A-Z][a-z]+"
        r"(?:\s+[A-Z][a-z]+)?(?:\s+[A-Z][a-z]+)?)\b"
    )
    # Also match phrases after "such as", "including", "include", "e.g."
    enum_pattern = re.compile(
        r"(?:such\s+as|including|include|e\.g\.?|areas?\s+(?:of|like)|"
        r"fields?\s+(?:such\s+as|like|including))\s+"
        r"([^.;]{10,120})",
        re.IGNORECASE,
    )
    # Parenthetical terms: (DNA, CET, AMR, etc.)
    paren_pattern = re.compile(r"\(([A-Z][A-Za-z&/ ]{1,30})\)")

    found: list[str] = []
    seen: set[str] = set()

    def _add(term: str) -> None:
        cleaned = term.strip(" ,;.()").strip()
        if len(cleaned) < 3 or len(cleaned) > 40:
            return
        words = cleaned.split()
        if len(words) < 2 or len(words) > 4:
            return
        lower = cleaned.lower()
        if lower in {
            "the role", "the team", "the company", "the candidate",
            "we are", "you will", "you are", "this role",
            "what the", "what we", "what you", "how you",
            "in addition", "as well", "at least", "such as",
        }:
            return
        if lower not in seen:
            seen.add(lower)
            found.append(cleaned)

    for m in pattern.finditer(text):
        _add(m.group(1))

    for m in enum_pattern.finditer(text):
        chunk = m.group(1)
        for part in re.split(r",\s*(?:and\s+|or\s+)?|\s+and\s+|\s+or\s+", chunk):
            part = part.strip()
            if part and len(part) >= 3:
                _add(part)
                if len(part.split()) == 1 and part[0].isupper() and len(part) >= 3:
                    lower = part.lower()
                    if lower not in seen:
                        seen.add(lower)
                        found.append(part)

    for m in paren_pattern.finditer(text):
        term = m.group(1).strip()
        if 2 <= len(term) <= 10 and term.upper() == term:
            lower = term.lower()
            if lower not in seen:
                seen.add(lower)
                found.append(term)

    return found


def _extract_requirement_phrases(text: str) -> list[str]:
    """Extract skill-like phrases from requirement bullet lines.

    Targets patterns like:
    - "Proficient in X"
    - "Knowledge of X"
    - "Experience in/with X"
    - "Trained in X"
    - "qualification in X"
    """
    patterns = [
        re.compile(r"(?:proficien(?:t|cy))\s+(?:in|with)\s+([^,.;]{3,40})", re.I),
        re.compile(r"(?:knowledge|understanding)\s+(?:of|in)\s+([^,.;]{3,40})", re.I),
        re.compile(r"(?:trained|background|qualification)\s+in\s+([^,.;]{3,40})", re.I),
        re.compile(r"(?:familiar(?:ity)?)\s+with\s+([^,.;]{3,40})", re.I),
        re.compile(r"(?:experience)\s+(?:in|with)\s+([^,.;]{3,40})", re.I),
    ]
    found: list[str] = []
    seen: set[str] = set()
    for pat in patterns:
        for m in pat.finditer(text):
            term = m.group(1).strip()
            words = term.split()
            if 1 <= len(words) <= 4:
                lower = term.lower()
                if lower not in seen:
                    seen.add(lower)
                    found.append(term)
    return found


def _extract_bullet_lines(text: str, limit: int = 8) -> list[str]:
    """Extract up to `limit` responsibility phrases from bullet-point lines."""
    lines = text.split("\n")
    bullets: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if not _BULLET_LINE_RE.match(line):
            continue

        cleaned = re.sub(
            r"^\s*(?:[-*\u2022\u2023\u25E6\u2043\u2219]"
            r"|\d{1,2}[.)]\s)\s*",
            "",
            line,
        ).strip()

        if cleaned and len(cleaned) >= 15:
            bullets.append(cleaned)
            if len(bullets) >= limit:
                break

    return bullets


def _extract_competency_signals(
    text: str,
) -> dict[str, list[str]]:
    """Match COMPETENCY_KEYWORDS against JD text, keeping the matched keywords."""
    text_lower = text.lower()
    signals: dict[str, list[str]] = {}

    for competency, keywords in COMPETENCY_KEYWORDS.items():
        matched = [kw for kw in keywords if kw in text_lower]
        if matched:
            signals[competency] = matched

    return signals


_ARCHETYPE_SIGNALS: dict[str, list[str]] = {
    "Builder": [
        "build", "create", "greenfield", "from scratch", "0 to 1",
        "zero to one", "new product", "mvp", "prototype", "founding",
        "early stage", "startup", "launch", "establish",
    ],
    "Scaler": [
        "scale", "growth", "optimize", "performance", "throughput",
        "high-volume", "expand", "reliability", "sre", "platform",
        "migrate", "infrastructure", "distributed",
    ],
    "Operator": [
        "maintain", "operate", "support", "monitor", "incident",
        "compliance", "audit", "process", "sop", "governance",
        "itil", "run the", "day-to-day",
    ],
    "Specialist": [
        "expert", "specialist", "deep", "domain", "research",
        "phd", "principal", "staff engineer", "architecture",
        "niche", "subject matter",
    ],
    "Leader": [
        "lead", "manage", "director", "head of", "vp ",
        "strategy", "vision", "stakeholder", "executive",
        "team of", "report to", "direct reports", "mentor",
    ],
}


def classify_archetype(
    description: str, title: str = "", competency_signals: dict | None = None,
) -> str:
    """Classify a job into an archetype based on JD signals."""
    text_lower = f" {(description + ' ' + title).lower()} "
    scores: dict[str, int] = {}
    for archetype, keywords in _ARCHETYPE_SIGNALS.items():
        scores[archetype] = sum(1 for kw in keywords if kw in text_lower)
    best = max(scores, key=scores.get)
    return best if scores[best] >= 2 else "Generalist"


def preparse_job_description(
    description: str,
    skills: list[str] | None = None,
    db_session=None,
    job_title: str = "",
) -> dict:
    """Pre-parse a job description into structured fields.

    Pure regex/string matching, no LLM calls. Runs in ~50ms.
    """
    if not description or not description.strip():
        return {
            "required_skills": [],
            "preferred_skills": [],
            "single_word_skills": [],
            "competency_signals": {},
            "experience_years": "",
            "education_level": "",
            "key_responsibilities": [],
            "parsed_at": datetime.now(timezone.utc).isoformat(),
        }

    split_idx = _find_preferred_split(description)

    if split_idx != -1:
        required_text = description[:split_idx]
        preferred_text = description[split_idx:]
    else:
        required_text = description
        preferred_text = ""

    all_skills = extract_skill_phrases(
        description,
        skills,
        db_session=db_session,
    )
    if job_title:
        title_skills = extract_skill_phrases(
            job_title,
            skills,
            db_session=db_session,
        )
        for skill in title_skills:
            if skill not in all_skills:
                all_skills.append(skill)

    # Extract additional terms from prose (CareersGov, long-form JDs)
    prose_terms = _extract_prose_noun_phrases(description)
    requirement_terms = _extract_requirement_phrases(description)
    seen_lower = {s.lower() for s in all_skills}
    for term in prose_terms + requirement_terms:
        if term.lower() not in seen_lower:
            seen_lower.add(term.lower())
            all_skills.append(term)
    required_lower = required_text.lower()
    preferred_lower = preferred_text.lower()

    required_skills: list[str] = []
    preferred_skills: list[str] = []

    for skill in all_skills:
        skill_lower = skill.lower()
        parts = skill_lower.split()
        pattern = (
            r"\b"
            + r"[\s\-]+".join(re.escape(p) for p in parts)
            + r"\b"
        )

        in_preferred = (
            bool(re.search(pattern, preferred_lower))
            if preferred_text
            else False
        )
        in_required = bool(re.search(pattern, required_lower))

        if in_preferred and not in_required:
            preferred_skills.append(skill)
        else:
            required_skills.append(skill)

    single_word = _extract_single_word_tech(description)
    competency_signals = _extract_competency_signals(description)
    experience_years = _extract_experience_years(description)
    education_level = _extract_education_level(description)
    key_responsibilities = _extract_bullet_lines(description)

    return {
        "required_skills": required_skills,
        "preferred_skills": preferred_skills,
        "single_word_skills": single_word,
        "competency_signals": competency_signals,
        "experience_years": experience_years,
        "education_level": education_level,
        "key_responsibilities": key_responsibilities,
        "archetype": classify_archetype(description, job_title, competency_signals),
        "parsed_at": datetime.now(timezone.utc).isoformat(),
    }
