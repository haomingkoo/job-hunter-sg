"""
AI phrase blacklist -- detects and replaces overly polished AI-generated phrasing.

Phrases that appear in the actual job description are PROTECTED (not replaced),
since those are legitimate terms the employer uses.
"""

from __future__ import annotations

import re

# Map of AI-sounding phrases -> simpler replacements
# Keys are lowercase for case-insensitive matching.
AI_PHRASE_REPLACEMENTS: dict[str, str] = {
    # ── Truly AI-generated / cringeworthy verbs ─────────────────────────
    "spearheaded": "led",
    "synergized": "collaborated",
    "catalyzed": "started",
    "galvanized": "motivated",
    "masterminded": "planned",
    "instrumentalized": "used",
    "effectuated": "carried out",
    "endeavored": "worked",
    "galvanised": "motivated",
    "ideated": "brainstormed",

    # ── Corporate buzzwords ──────────────────────────────────────────────
    "synergy": "collaboration",
    "paradigm shift": "change",
    "cutting-edge": "modern",
    "state-of-the-art": "modern",
    "best-in-class": "top",
    "world-class": "strong",
    "bleeding-edge": "latest",
    "game-changing": "significant",
    "groundbreaking": "new",
    # NOTE: "transformative", "end-to-end", "thought leadership",
    # "core competencies", "mission-critical" are legitimate professional
    # terms used in real JDs. Do NOT replace them.
    "holistic approach": "broad approach",
    "actionable insights": "useful findings",
    "scalable solutions": "solutions",
    "robust framework": "framework",
    "strategic alignment": "alignment",
    "cross-functional synergies": "cross-team collaboration",
    "disruptive innovation": "new approach",
    "north star metric": "key metric",
    "move the needle": "make an impact",
    "low-hanging fruit": "quick win",
    "deep dive": "analysis",

    # ── AI resume filler ─────────────────────────────────────────────────
    "seasoned professional": "experienced",
    "passionate about": "interested in",
    "driven individual": "motivated",
    "results-oriented": "practical",
    "results-driven": "effective",
    "detail-oriented individual": "thorough",
    "highly motivated": "motivated",
    "self-starter": "independent",
    "dynamic individual": "adaptable",
    "proven track record": "track record",
    "strong communicator": "clear communicator",
    "team player": "collaborative",
    "go-getter": "proactive",
    "think outside the box": "find creative solutions",
    "wear many hats": "handle multiple roles",
    "hit the ground running": "start quickly",
    "proactive problem-solver": "problem-solver",
    "adept at": "skilled in",
    "well-versed in": "experienced with",
    "instrumental in": "contributed to",
    "played a pivotal role": "contributed",
    "extensive experience": "experience",
    "demonstrated expertise": "expertise",

    # ── Wordy phrases -> simpler ─────────────────────────────────────────
    "in order to": "to",
    "utilize": "use",
    "utilization": "use",
    "utilized": "used",
    "utilizing": "using",
    "utilise": "use",
    "utilisation": "use",
    "utilised": "used",
    "utilising": "using",
    "leverage": "use",
    "leveraging": "using",
    "endeavor": "try",
    "commence": "start",
    "commenced": "started",
    "terminate": "end",
    "terminated": "ended",
    "subsequently": "then",
    "aforementioned": "this",
    "in conjunction with": "with",
    "with respect to": "about",
    "in the event that": "if",
    "at this point in time": "now",
    "due to the fact that": "because",
    "for the purpose of": "to",
    "on a daily basis": "daily",
    "in a timely manner": "on time",
    "prior to": "before",
    "subsequent to": "after",
    "in excess of": "over",
    "a significant number of": "many",
    "the vast majority of": "most",
    "in close collaboration with": "with",
    "with the aim of": "to",
    "it is worth noting that": "",
    "it goes without saying": "",
    "needless to say": "",
}


def clean_ai_phrases(
    text: str, jd_text: str = ""
) -> tuple[str, list[dict[str, str | bool]]]:
    """Replace AI-sounding phrases with simpler alternatives.

    Phrases present in jd_text are protected (not replaced).
    Returns (cleaned_text, list of changes made).

    Each change dict contains:
        - original_phrase: the phrase matched in text
        - replacement: the simpler alternative (or "PROTECTED")
        - protected: True if the phrase was skipped because it appears in the JD
    """
    if not text:
        return text, []

    jd_lower = jd_text.lower()
    changes: list[dict[str, str | bool]] = []

    # Sort by length descending so longer phrases are matched first
    # (e.g., "in order to" before "in")
    sorted_phrases = sorted(
        AI_PHRASE_REPLACEMENTS.items(), key=lambda p: len(p[0]), reverse=True
    )

    for phrase, replacement in sorted_phrases:
        # Case-insensitive search using word boundaries where sensible
        # For multi-word phrases, use escaped literal match
        pattern = re.compile(re.escape(phrase), re.IGNORECASE)

        if not pattern.search(text):
            continue

        # Phrase exists in text -- check if JD protects it
        if jd_lower and phrase.lower() in jd_lower:
            changes.append(
                {
                    "original_phrase": phrase,
                    "replacement": "PROTECTED",
                    "protected": True,
                }
            )
            continue

        # Replace all occurrences, preserving surrounding text
        text = pattern.sub(replacement, text)
        changes.append(
            {
                "original_phrase": phrase,
                "replacement": replacement,
                "protected": False,
            }
        )

    return text, changes
