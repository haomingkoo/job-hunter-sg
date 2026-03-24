"""
Skill phrase extractor -- extracts multi-word skill phrases from job descriptions.

Uses a combination of:
1. Known skills dictionary (common multi-word tech/business terms)
2. The job's existing skills array from the database
3. Pattern matching for noun phrases

No external dependencies -- pure stdlib + re.
"""

from __future__ import annotations

import re

# ── Known multi-word skill phrases ──────────────────────────────────────────
# 200+ common multi-word skills in tech, business, and SG-specific domains.
# All stored lowercase for case-insensitive matching.

KNOWN_SKILLS: set[str] = {
    # --- Programming & Software ---
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
    # --- AI / ML / Data ---
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
    # --- Cloud & DevOps ---
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
    # --- Cybersecurity ---
    "information security", "network security",
    "application security", "cyber security",
    "penetration testing", "vulnerability assessment",
    "threat modeling", "security audit",
    "identity and access management", "access control",
    "security operations", "security compliance",
    "security architecture", "endpoint security",
    "zero trust", "zero trust architecture",
    # --- Databases ---
    "database administration", "database design",
    "database management", "database optimization",
    "relational database", "graph database",
    "nosql database",
    # --- Networking ---
    "network administration", "network engineering",
    "network architecture", "network monitoring",
    "software-defined networking",
    # --- Management & Leadership ---
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
    # --- Agile & Process ---
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
    # --- Business & Strategy ---
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
    # --- Sales & Marketing ---
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
    # --- Supply Chain & Operations ---
    "supply chain management", "supply chain optimization",
    "logistics management", "inventory management",
    "procurement management", "warehouse management",
    "operations management", "operational excellence",
    "facilities management", "fleet management",
    # --- HR & Training ---
    "human resources", "talent acquisition",
    "employee engagement", "employee relations",
    "learning and development", "training and development",
    "organizational development", "succession planning",
    "workforce planning", "compensation and benefits",
    "performance review", "onboarding process",
    # --- Compliance & Governance ---
    "regulatory compliance", "corporate governance",
    "internal audit", "external audit",
    "legal compliance", "policy development",
    "data protection", "privacy compliance",
    # --- UX / UI / Design ---
    "user experience", "user interface",
    "ux design", "ui design", "ux/ui design",
    "user research", "usability testing",
    "interaction design", "visual design",
    "information architecture", "wireframing and prototyping",
    "design systems", "responsive design",
    "accessibility compliance", "human-centered design",
    "graphic design", "motion design",
    # --- Singapore-specific ---
    "skills framework",
    "digital transformation", "smart nation",
    "industry transformation",
    "government technology",
    "public sector", "civil service",
    "singapore standards",
    # --- Emerging / Specialized ---
    "blockchain technology", "distributed ledger",
    "internet of things", "edge computing",
    "quantum computing", "augmented reality",
    "virtual reality", "mixed reality",
    "digital twin", "3d printing",
    "autonomous systems", "computer-aided design",
    # --- Additional common terms ---
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


# ── Sentence splitting ──────────────────────────────────────────────────────

_SENTENCE_RE = re.compile(
    r"(?<=[.!?;])\s+|(?<=\n)\s*"
)


def _split_sentences(text: str) -> list[str]:
    """Split text into rough sentence-like chunks."""
    raw = _SENTENCE_RE.split(text)
    return [s.strip() for s in raw if s.strip()]


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


# ── Core extraction ─────────────────────────────────────────────────────────

def _normalize_skill(raw: str) -> str:
    """Lowercase and collapse whitespace."""
    return re.sub(r"\s+", " ", raw.strip().lower())


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

    # 1. Match against known skills dictionary
    found_skills: list[str] = _find_known_skills_in_text(text_lower)

    # 2. Add job_skills from the database that are multi-word
    if job_skills:
        for raw_skill in job_skills:
            normalized = _normalize_skill(raw_skill)
            if not normalized:
                continue
            # Only add multi-word skills (single words handled elsewhere)
            word_count = len(normalized.split())
            if word_count >= 2 and normalized not in found_skills:
                # Verify the phrase actually appears in the JD text
                parts = normalized.split()
                pattern = r"\b" + r"[\s\-]+".join(
                    re.escape(p) for p in parts
                ) + r"\b"
                if re.search(pattern, text_lower):
                    found_skills.append(normalized)
                # Only include metadata skills that are in our known dictionary
                # to avoid noise like "Medical Study" from job source data
                elif normalized in KNOWN_SKILLS:
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


# ── Resume matching ─────────────────────────────────────────────────────────

def match_resume_skills(
    resume_text: str,
    jd_skills: list[str],
) -> dict:
    """Compare resume text against JD skill phrases.

    For each matched skill, shows WHERE in the resume it appears.
    For each missing skill, shows WHERE in the JD it would need to be
    (looked up from the original JD text is not available here, so we
    use the skill name as the context hint -- callers can supply
    jd_text separately via match_resume_skills_with_context).

    Args:
        resume_text: The full resume text.
        jd_skills: List of skill phrases extracted from the JD.

    Returns:
        {
            "matched": [{"skill": "...", "resume_context": "..."}],
            "missing": [{"skill": "..."}],
            "match_percent": int
        }
    """
    return match_resume_skills_with_context(
        resume_text=resume_text,
        jd_skills=jd_skills,
        jd_text="",
    )


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
