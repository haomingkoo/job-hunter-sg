"""
Skill phrase extractor -- extracts multi-word skill phrases from job descriptions.

Uses a combination of:
1. Known skills dictionary (common multi-word tech/business terms)
2. The job's existing skills array from the database
3. Pattern matching for noun phrases

No external dependencies -- pure stdlib + re.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections import Counter
from typing import Optional

from config import ANALYTICS_MAX_ROWS

log = logging.getLogger("jobhunter.skills")

# 200+ common multi-word skills in tech, business, and SG-specific domains.
# All stored lowercase for case-insensitive matching.

KNOWN_SKILLS: set[str] = {
    "software engineering", "software development", "software architecture",
    "software testing", "software design", "software deployment",
    "full stack", "full stack development", "full-stack development",
    "front end", "front end development", "front-end development",
    "back end", "back end development", "back-end development",
    "web development", "web application", "web services",
    "mobile development", "mobile application",
    "api development", "api design", "api integration",
    "microservices architecture", "event-driven architecture",
    "object-oriented programming", "functional programming",
    "test-driven development", "behavior-driven development",
    "pair programming", "code review", "code quality",
    "technical debt", "legacy system",
    "open source", "version control",
    "embedded systems", "real-time systems",
    "low-level programming", "systems programming",
    "machine learning", "deep learning", "reinforcement learning",
    "transfer learning", "federated learning",
    "natural language processing", "computer vision",
    "speech recognition", "image recognition",
    "generative ai", "large language models",
    "prompt engineering", "model training", "model deployment",
    "model evaluation", "model optimization",
    "data analysis", "data analytics", "data engineering",
    "data science", "data mining", "data modeling",
    "data governance", "data quality", "data pipeline",
    "data warehouse", "data lake", "data integration",
    "data visualization", "data management", "data architecture",
    "data migration", "data security", "data privacy",
    "big data", "real-time data", "streaming data",
    "statistical analysis", "statistical modeling",
    "predictive modeling", "predictive analytics",
    "prescriptive analytics", "descriptive analytics",
    "time series analysis", "regression analysis",
    "classification models", "clustering algorithms",
    "neural networks", "convolutional neural networks",
    "recurrent neural networks", "transformer models",
    "feature engineering", "feature selection",
    "a/b testing", "hypothesis testing",
    "artificial intelligence", "business intelligence",
    "robotic process automation",
    "cloud computing", "cloud architecture", "cloud migration",
    "cloud security", "cloud infrastructure", "cloud native",
    "hybrid cloud",
    "amazon web services", "google cloud platform",
    "microsoft azure",
    "ci/cd pipeline", "ci/cd pipelines",
    "continuous integration", "continuous deployment",
    "continuous delivery",
    "infrastructure as code", "configuration management",
    "container orchestration",
    "site reliability", "site reliability engineering",
    "platform engineering", "build automation",
    "release management", "deployment automation",
    "monitoring and alerting", "log management",
    "incident management", "incident response",
    "disaster recovery", "high availability",
    "load balancing", "auto scaling",
    "information security", "network security",
    "application security", "cyber security",
    "penetration testing", "vulnerability assessment",
    "threat modeling", "security audit",
    "identity and access management", "access control",
    "security operations", "security compliance",
    "security architecture", "endpoint security",
    "zero trust", "zero trust architecture",
    "database administration", "database design",
    "database management", "database optimization",
    "relational database", "graph database",
    "nosql database",
    "network administration", "network engineering",
    "network architecture", "network monitoring",
    "software-defined networking",
    "project management", "program management", "product management",
    "portfolio management", "delivery management",
    "engineering management", "people management",
    "stakeholder management", "vendor management",
    "change management", "risk management",
    "crisis management", "conflict resolution",
    "performance management", "talent management",
    "resource management", "capacity planning",
    "team leadership", "team building", "team management",
    "cross-functional collaboration", "cross-functional teams",
    "cross functional collaboration", "cross functional teams",
    "executive leadership", "thought leadership",
    "servant leadership", "situational leadership",
    "decision making", "problem solving",
    "strategic thinking", "critical thinking",
    "emotional intelligence", "active listening",
    "agile methodology", "agile development",
    "scrum methodology", "scrum master",
    "kanban methodology", "lean methodology",
    "waterfall methodology",
    "design thinking", "systems thinking",
    "process improvement", "process optimization",
    "process automation", "process engineering",
    "process mapping", "process reengineering",
    "business process", "business process management",
    "workflow automation", "workflow optimization",
    "root cause analysis", "failure mode analysis",
    "lean manufacturing", "lean six sigma", "six sigma",
    "total quality management", "quality management",
    "quality assurance", "quality control",
    "continuous improvement",
    "business development", "business analysis",
    "business strategy", "business planning",
    "business transformation", "business operations",
    "business continuity", "business intelligence",
    "strategic planning", "strategic management",
    "corporate strategy", "go-to-market strategy",
    "market research", "market analysis",
    "competitive analysis", "competitive intelligence",
    "swot analysis", "gap analysis",
    "cost reduction", "cost optimization",
    "revenue growth", "revenue optimization",
    "profit and loss", "budget management",
    "financial analysis", "financial modeling",
    "financial planning", "financial reporting",
    "risk assessment", "due diligence",
    "mergers and acquisitions",
    "account management", "key account management",
    "client management", "client relations",
    "customer relationship management",
    "customer success", "customer experience",
    "customer service", "customer support",
    "customer acquisition", "customer retention",
    "sales management", "sales operations",
    "sales strategy", "sales enablement",
    "lead generation", "demand generation",
    "pipeline management", "deal closing",
    "digital marketing", "content marketing",
    "social media marketing", "email marketing",
    "search engine optimization", "search engine marketing",
    "conversion optimization",
    "marketing automation", "marketing analytics",
    "brand management", "brand strategy",
    "public relations", "media relations",
    "event management", "campaign management",
    "supply chain management", "supply chain optimization",
    "logistics management", "inventory management",
    "procurement management", "warehouse management",
    "operations management", "operational excellence",
    "facilities management", "fleet management",
    "modeling and simulation", "modelling and simulation",
    "system modeling", "system modelling",
    "end-to-end systems", "end-to-end system modeling",
    "end-to-end system modelling",
    "communication networks", "quantum networks",
    "enterprise applications", "industrial applications",
    "scenario analysis", "simulation tools",
    "performance metrics", "response time", "error rates",
    "technical documentation", "telecommunications engineering",
    "electrical engineering",
    "semiconductor manufacturing", "semiconductor operations",
    "process integration", "process control", "process validation",
    "yield engineering", "yield improvement", "yield optimization",
    "yield ramp", "quality systems", "quality metrics",
    "engineering systems", "manufacturing quality systems",
    "manufacturing operations", "product engineering operations",
    "front end operations", "front-end operations",
    "wafer fabrication", "defect metrology", "equipment engineering",
    "wet process development", "pattern quality", "lithography process",
    "cross-site operations", "global operations", "fab operations",
    "inline detection", "predictive quality control", "virtual doe",
    "design of experiments", "root cause corrective action",
    "human resources", "talent acquisition",
    "employee engagement", "employee relations",
    "learning and development", "training and development",
    "organizational development", "succession planning",
    "workforce planning", "compensation and benefits",
    "performance review", "onboarding process",
    "regulatory compliance", "corporate governance",
    "internal audit", "external audit",
    "legal compliance", "policy development",
    "data protection", "privacy compliance",
    "user experience", "user interface",
    "ux design", "ui design", "ux/ui design",
    "user research", "usability testing",
    "interaction design", "visual design",
    "information architecture", "wireframing and prototyping",
    "design systems", "responsive design",
    "accessibility compliance", "human-centered design",
    "graphic design", "motion design",
    "skills framework",
    "digital transformation", "smart nation",
    "industry transformation",
    "government technology",
    "public sector", "civil service",
    "singapore standards",
    "blockchain technology", "distributed ledger",
    "internet of things", "edge computing",
    "quantum computing", "augmented reality",
    "virtual reality", "mixed reality",
    "digital twin", "3d printing",
    "autonomous systems", "computer-aided design",
    "technical writing", "technical support", "technical architecture",
    "systems integration", "enterprise architecture",
    "service delivery", "service management",
    "business requirements", "requirements gathering",
    "knowledge management", "intellectual property",
}

# Build a lookup keyed by the first word for fast filtering
_SKILL_BY_FIRST_WORD: dict[str, list[str]] = {}
for _skill in KNOWN_SKILLS:
    _first = _skill.split()[0]
    _SKILL_BY_FIRST_WORD.setdefault(_first, []).append(_skill)

# Sort each group longest-first so we prefer longer matches
for _key in _SKILL_BY_FIRST_WORD:
    _SKILL_BY_FIRST_WORD[_key].sort(key=len, reverse=True)


def _find_context(text: str, phrase: str) -> str:
    """Find the sentence containing a phrase, for context display."""
    text_lower = text.lower()
    phrase_lower = phrase.lower()
    idx = text_lower.find(phrase_lower)
    if idx == -1:
        return ""

    # Walk backwards to find sentence start
    start = max(0, idx - 120)
    for boundary in ".!?\n":
        last_b = text_lower.rfind(boundary, start, idx)
        if last_b != -1 and last_b > start:
            start = last_b + 1
            break

    # Walk forwards to find sentence end
    end = min(len(text), idx + len(phrase) + 120)
    for boundary in ".!?\n":
        next_b = text_lower.find(boundary, idx + len(phrase))
        if next_b != -1 and next_b < end:
            end = next_b + 1
            break

    snippet = text[start:end].strip()
    # Add ellipsis if we trimmed
    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet = snippet + "..."
    return snippet



def _normalize_skill(raw: str) -> str:
    """Lowercase and collapse whitespace."""
    return re.sub(r"\s+", " ", raw.strip().lower())


def normalize_skill_strings(raw_skills, *, max_length: int) -> list[str]:
    """Flatten, clean, and case-insensitively deduplicate stored skill values."""
    collected: list[str] = []

    def visit(value) -> None:
        if isinstance(value, str):
            for part in re.split(r"[;,|/]", value):
                cleaned = part.strip()
                if cleaned:
                    collected.append(cleaned)
        elif isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            for key, item in value.items():
                visit(key)
                visit(item)

    visit(raw_skills)

    deduped: list[str] = []
    seen: set[str] = set()
    for skill in collected:
        cleaned = re.sub(r"\s+", " ", skill).strip(" -•\t")
        lower = cleaned.lower()
        if not cleaned or len(cleaned) < 2 or len(cleaned) > max_length or lower in seen:
            continue
        seen.add(lower)
        deduped.append(cleaned)
    return deduped


def _find_known_skills_in_text(text_lower: str) -> list[str]:
    """Scan text for all known multi-word skill phrases.

    Uses word-boundary regex for each candidate so we don't get false
    positives from substrings (e.g., "learning" inside "machine learning").
    Prefers longer phrases when there is overlap.
    """
    found: list[str] = []
    # Track character spans to avoid overlapping matches
    covered: list[tuple[int, int]] = []

    # Collect all words in the text for fast first-word check
    words_in_text = set(re.findall(r"[a-z][a-z/\-]*", text_lower))

    # Only check skills whose first word appears in the text
    candidates: list[str] = []
    for first_word, skills in _SKILL_BY_FIRST_WORD.items():
        if first_word in words_in_text:
            candidates.extend(skills)

    # Sort longest-first for greedy matching
    candidates.sort(key=len, reverse=True)

    for skill in candidates:
        # Build a pattern that allows flexible whitespace/hyphens between words
        parts = skill.split()
        if len(parts) < 2:
            continue
        pattern = r"\b" + r"[\s\-]+".join(re.escape(p) for p in parts) + r"\b"
        for m in re.finditer(pattern, text_lower):
            span = (m.start(), m.end())
            # Check overlap with already-covered spans
            overlaps = any(
                not (span[1] <= c[0] or span[0] >= c[1])
                for c in covered
            )
            if not overlaps:
                covered.append(span)
                found.append(skill)
                break  # one match per skill is enough

    return found


def extract_skill_phrases(
    jd_text: str,
    job_skills: list[str] | None = None,
    db_session=None,
    use_dynamic_skills: bool = False,
) -> list[str]:
    """Extract multi-word skill phrases from a job description.

    Args:
        jd_text: The full job description text.
        job_skills: Optional list of skills from the database (MCF provides these).

    Returns:
        List of skill phrases found in the JD, ordered by relevance
        (frequency in text, then alphabetical).
    """
    if not jd_text or not jd_text.strip():
        return []

    text_lower = jd_text.lower()

    # 1. Match against known skills dictionary (static)
    found_skills: list[str] = _find_known_skills_in_text(text_lower)

    # 2. Build the valid skills set (static + dynamic from scraped JDs)
    valid_skills = set(KNOWN_SKILLS)
    if db_session and use_dynamic_skills:
        try:
            dynamic = build_dynamic_skills(db_session)
            valid_skills.update(dynamic.keys())
        except Exception as e:
            log.warning(f"Dynamic skill build failed, using static only: {e}")

    # 3. Add job_skills from the database that are multi-word
    if job_skills:
        for raw_skill in job_skills:
            normalized = _normalize_skill(raw_skill)
            if not normalized:
                continue
            word_count = len(normalized.split())
            if word_count >= 2 and normalized not in found_skills:
                # If the phrase appears in the JD text, always include it
                parts = normalized.split()
                pattern = r"\b" + r"[\s\-]+".join(
                    re.escape(p) for p in parts
                ) + r"\b"
                if re.search(pattern, text_lower):
                    found_skills.append(normalized)
                # Otherwise only include if it's a recognized skill
                # (from static dictionary OR seen across multiple JDs)
                elif normalized in valid_skills:
                    found_skills.append(normalized)

    # 3. Deduplicate, preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for skill in found_skills:
        if skill not in seen:
            seen.add(skill)
            unique.append(skill)

    # 4. Sort by frequency in text (more mentions = more relevant), then alpha
    def _relevance(skill: str) -> tuple[int, str]:
        parts = skill.split()
        pattern = r"\b" + r"[\s\-]+".join(re.escape(p) for p in parts) + r"\b"
        count = len(re.findall(pattern, text_lower))
        return (-count, skill)

    unique.sort(key=_relevance)

    return unique

def match_resume_skills_with_context(
    resume_text: str,
    jd_skills: list[str],
    jd_text: str = "",
) -> dict:
    """Compare resume text against JD skill phrases, with full context.

    Args:
        resume_text: The full resume text.
        jd_skills: List of skill phrases extracted from the JD.
        jd_text: Original JD text (for context snippets on missing skills).

    Returns:
        {
            "matched": [{"skill": "...", "resume_context": "..."}],
            "missing": [{"skill": "...", "jd_context": "..."}],
            "match_percent": int
        }
    """
    if not jd_skills:
        return {"matched": [], "missing": [], "match_percent": 0}

    resume_lower = resume_text.lower()
    jd_lower = jd_text.lower() if jd_text else ""

    matched: list[dict] = []
    missing: list[dict] = []

    for skill in jd_skills:
        skill_lower = skill.lower()
        parts = skill_lower.split()

        # Build flexible pattern for matching
        if len(parts) >= 2:
            pattern = r"\b" + r"[\s\-]+".join(
                re.escape(p) for p in parts
            ) + r"\b"
        else:
            pattern = r"\b" + re.escape(skill_lower) + r"\b"

        found_in_resume = re.search(pattern, resume_lower)

        if found_in_resume:
            context = _find_context(resume_text, skill)
            matched.append({
                "skill": skill,
                "resume_context": context,
            })
        else:
            entry: dict = {"skill": skill}
            if jd_lower:
                context = _find_context(jd_text, skill)
                if context:
                    entry["jd_context"] = context
            missing.append(entry)

    total = len(jd_skills)
    match_count = len(matched)
    match_percent = round(match_count / total * 100) if total > 0 else 0

    return {
        "matched": matched,
        "missing": missing,
        "match_percent": match_percent,
    }



# Stop words to ignore when extracting n-grams
_STOP_WORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "was", "are", "were", "be",
    "been", "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "shall", "can", "need",
    "must", "that", "this", "these", "those", "it", "its", "not", "no",
    "nor", "so", "if", "then", "than", "too", "very", "just", "also",
    "such", "like", "only", "more", "most", "other", "some", "any", "all",
    "each", "every", "both", "few", "many", "much", "own", "same", "well",
    "about", "into", "through", "during", "before", "after", "above",
    "below", "between", "under", "over", "up", "out", "off", "down",
    "while", "where", "when", "what", "which", "who", "whom", "how",
    "there", "here", "their", "they", "them", "we", "us", "our", "you",
    "your", "he", "she", "his", "her", "my", "me", "i",
    # Common JD filler words
    "able", "ensure", "include", "including", "required", "preferred",
    "responsible", "experience", "work", "working", "role", "position",
    "candidate", "strong", "good", "excellent", "minimum", "least",
    "years", "year", "related", "relevant", "knowledge", "understanding",
    "ability", "skills", "skill", "using", "used", "use",
    "new", "etc", "e.g", "eg", "ie", "i.e",
}

# Minimum number of JDs a phrase must appear in to be considered a real skill
_MIN_JD_FREQUENCY = 3

# Cache for the dynamic dictionary
_dynamic_cache: dict = {
    "skills": {},       # skill -> count of JDs containing it
    "built_at": 0,      # timestamp
    "job_count": 0,     # number of JDs analyzed
}
_dynamic_cache_lock = threading.Lock()


def _tokenize_for_ngrams(text: str) -> list[str]:
    """Tokenize text into lowercase words, stripping punctuation."""
    return re.findall(r"[a-z][a-z0-9+#/.'-]*", text.lower())


def _extract_ngrams(tokens: list[str], n: int) -> list[str]:
    """Extract n-grams from token list, filtering stop-word-heavy phrases."""
    ngrams = []
    for i in range(len(tokens) - n + 1):
        gram = tokens[i:i + n]
        # Skip if more than half are stop words
        stop_count = sum(1 for w in gram if w in _STOP_WORDS)
        if stop_count > n // 2:
            continue
        # Skip if first or last word is a stop word
        if gram[0] in _STOP_WORDS or gram[-1] in _STOP_WORDS:
            continue
        # Skip very short words (single char except known ones like R, C)
        if any(len(w) < 2 and w not in {"r", "c", "ai"} for w in gram):
            continue
        phrase = " ".join(gram)
        ngrams.append(phrase)
    return ngrams


def build_dynamic_skills(db_session) -> dict[str, int]:
    """Analyze all scraped JDs and build a frequency-based skill dictionary.

    Returns dict of {skill_phrase: number_of_JDs_containing_it}.
    Results are cached for 6 hours.
    """
    # Return cache if fresh (< 6 hours old)
    cache_age = time.time() - _dynamic_cache["built_at"]
    if _dynamic_cache["built_at"] > 0 and cache_age < 6 * 3600:
        return _dynamic_cache["skills"]

    if not _dynamic_cache_lock.acquire(blocking=False):
        return _dynamic_cache["skills"]

    try:
        return _build_dynamic_skills(db_session)
    finally:
        _dynamic_cache_lock.release()


def _build_dynamic_skills(db_session) -> dict[str, int]:
    from models import ScrapedJob

    cache_age = time.time() - _dynamic_cache["built_at"]
    if _dynamic_cache["built_at"] > 0 and cache_age < 6 * 3600:
        return _dynamic_cache["skills"]

    log.info("Building dynamic skill dictionary from scraped JDs...")
    start = time.time()

    # Count how many JDs each phrase appears in (document frequency)
    phrase_df: Counter = Counter()
    job_count = 0

    query = (
        db_session.query(ScrapedJob.description, ScrapedJob.skills)
        .filter(ScrapedJob.description != "")
        .limit(ANALYTICS_MAX_ROWS)
        .yield_per(500)
    )
    for desc, job_skills in query:
        if not desc:
            continue
        job_count += 1

        # Extract n-grams from description
        tokens = _tokenize_for_ngrams(desc)
        phrases_in_this_jd: set[str] = set()

        for n in (2, 3):
            for phrase in _extract_ngrams(tokens, n):
                phrases_in_this_jd.add(phrase)

        # Also add multi-word skills from job metadata
        if job_skills:
            skills_list = job_skills if isinstance(job_skills, list) else []
            for raw in skills_list:
                if isinstance(raw, str):
                    normalized = _normalize_skill(raw)
                    if normalized and len(normalized.split()) >= 2:
                        phrases_in_this_jd.add(normalized)

        # Increment document frequency for each unique phrase in this JD
        for phrase in phrases_in_this_jd:
            phrase_df[phrase] += 1

    if job_count == 0:
        return {}

    # Filter: keep phrases that appear in enough JDs
    min_freq = max(_MIN_JD_FREQUENCY, job_count // 100)  # At least 1% of jobs
    real_skills = {
        phrase: count
        for phrase, count in phrase_df.items()
        if count >= min_freq
    }

    # Also merge in our static KNOWN_SKILLS (they're always valid)
    for skill in KNOWN_SKILLS:
        if skill not in real_skills:
            # Check if it appears in any JDs
            if skill in phrase_df:
                real_skills[skill] = phrase_df[skill]

    # Update cache
    _dynamic_cache["skills"] = real_skills
    _dynamic_cache["built_at"] = time.time()
    _dynamic_cache["job_count"] = job_count

    elapsed = time.time() - start
    log.info(
        f"Dynamic skill dictionary built: {len(real_skills)} phrases "
        f"from {job_count} JDs in {elapsed:.1f}s"
    )

    return real_skills


def get_trending_skills(
    db_session,
    limit: int = 50,
    category: Optional[str] = None,
) -> list[dict]:
    """Get the most common skill phrases across all scraped JDs.

    Returns a ranked list of {skill, count, percent} dicts.
    """
    skills = build_dynamic_skills(db_session)
    if not skills:
        return []

    job_count = _dynamic_cache["job_count"] or 1

    # Sort by frequency
    ranked = sorted(skills.items(), key=lambda x: -x[1])

    results = []
    for phrase, count in ranked[:limit]:
        results.append({
            "skill": phrase,
            "count": count,
            "percent": round(count / job_count * 100, 1),
        })

    return results
