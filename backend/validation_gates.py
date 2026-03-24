"""
Validation gates -- local checks on every AI-generated resume change.

All gates are pure functions. No LLM calls. Run in <10ms each.
Inspired by Resume-Matcher's 4-gate validation system.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from ai_phrases import clean_ai_phrases

log = logging.getLogger("jobhunter.gates")

# ── Result type ─────────────────────────────────────────────────────────────


@dataclass
class GateResult:
    passed: bool
    gate_name: str
    message: str
    auto_fixed: bool = False
    fixed_text: str | None = None


# ── Extraction helpers ──────────────────────────────────────────────────────

_NUMBER_RE = re.compile(
    r"\$[\d,.]+[kKmMbB]?"
    r"|\d+(?:\.\d+)?%"
    r"|\d{1,3}(?:,\d{3})+"
    r"|\d+[kKmMbB]\b"
    r"|\d+\s*(?:team|users|people|projects|systems|clients|engineers"
    r"|members|staff|reports|sites|regions|countries)"
)

_DOMAIN_TERM_RE = re.compile(r"\b[A-Z][A-Za-z0-9+#./-]{2,}\b")

_TECH_TERMS = {
    "python", "java", "javascript", "typescript", "react", "angular",
    "vue", "docker", "kubernetes", "aws", "azure", "gcp", "sql",
    "nosql", "mongodb", "postgresql", "redis", "kafka", "spark",
    "hadoop", "airflow", "pytorch", "tensorflow", "scikit-learn",
    "django", "flask", "fastapi", "spring", "node", "graphql",
    "linux", "git", "jira", "tableau", "powerbi", "figma",
    "terraform", "ansible", "jenkins", "ci/cd",
}


def _extract_numbers(text: str) -> set[str]:
    """Extract all numeric facts from text."""
    return {m.strip().lower() for m in _NUMBER_RE.findall(text)}


def _extract_domain_terms(text: str) -> set[str]:
    """Extract capitalized domain terms and known tech terms."""
    terms = {m.lower() for m in _DOMAIN_TERM_RE.findall(text)}
    words = set(re.findall(r"[a-z][a-z0-9+#./-]+", text.lower()))
    terms |= words & _TECH_TERMS
    return terms


# ── Gate 1: Fact Preservation ───────────────────────────────────────────────


def gate_fact_preservation(original: str, tailored: str) -> GateResult:
    """Ensure all numbers and metrics from the original appear in the tailored version."""
    orig_numbers = _extract_numbers(original)
    tail_numbers = _extract_numbers(tailored)
    missing = orig_numbers - tail_numbers

    if missing:
        return GateResult(
            passed=False,
            gate_name="fact_preservation",
            message=f"Missing facts from original: {', '.join(sorted(missing))}",
        )
    return GateResult(
        passed=True,
        gate_name="fact_preservation",
        message="All original facts preserved.",
    )


# ── Gate 2: AI Phrase Detection ─────────────────────────────────────────────


def gate_ai_phrases(tailored: str, jd_text: str = "") -> GateResult:
    """Check for AI-sounding phrases and auto-replace them."""
    cleaned, changes = clean_ai_phrases(tailored, jd_text)

    if not changes:
        return GateResult(
            passed=True,
            gate_name="ai_phrases",
            message="No AI-sounding phrases detected.",
        )

    replaced = [c for c in changes if not c.get("protected", False)]
    if not replaced:
        return GateResult(
            passed=True,
            gate_name="ai_phrases",
            message="AI phrases found but all are protected by JD context.",
        )

    phrase_list = ", ".join(
        f'"{c["original_phrase"]}"->"{c["replacement"]}"' for c in replaced[:3]
    )
    return GateResult(
        passed=True,
        gate_name="ai_phrases",
        message=f"Auto-replaced {len(replaced)} AI phrase(s): {phrase_list}",
        auto_fixed=True,
        fixed_text=cleaned,
    )


# ── Gate 3: Keyword Verbatim Check ──────────────────────────────────────────


def gate_keyword_verbatim(
    tailored: str,
    required_keywords: list[str] | None = None,
) -> GateResult:
    """Verify that required keywords appear verbatim in the tailored text."""
    if not required_keywords:
        return GateResult(
            passed=True,
            gate_name="keyword_verbatim",
            message="No keywords to verify.",
        )

    tail_lower = tailored.lower()
    missing = [kw for kw in required_keywords if kw.lower() not in tail_lower]

    if missing:
        return GateResult(
            passed=False,
            gate_name="keyword_verbatim",
            message=f"Missing keywords: {', '.join(missing[:5])}",
        )
    return GateResult(
        passed=True,
        gate_name="keyword_verbatim",
        message=f"All {len(required_keywords)} required keyword(s) present.",
    )


# ── Gate 4: Length Sanity ───────────────────────────────────────────────────


def gate_length_sanity(original: str, tailored: str) -> GateResult:
    """Check that the rewrite is not too long, too short, or bloated."""
    orig_words = len(original.split())
    tail_words = len(tailored.split())

    if tail_words > 40:
        return GateResult(
            passed=False,
            gate_name="length_sanity",
            message=f"Rewrite is {tail_words} words (max 40).",
        )

    if tail_words < 8:
        return GateResult(
            passed=True,  # warning, not failure
            gate_name="length_sanity",
            message=f"Rewrite is very short ({tail_words} words).",
        )

    if orig_words > 0 and tail_words / orig_words > 1.8:
        return GateResult(
            passed=False,
            gate_name="length_sanity",
            message=(
                f"Rewrite is {tail_words / orig_words:.1f}x longer than "
                f"original ({orig_words} -> {tail_words} words). Max 1.8x."
            ),
        )

    return GateResult(
        passed=True,
        gate_name="length_sanity",
        message=f"Length OK ({tail_words} words).",
    )


# ── Gate 5: Hallucination Detection ────────────────────────────────────────


def gate_hallucination(
    original: str,
    tailored: str,
    injectable_keywords: set[str] | None = None,
) -> GateResult:
    """Detect if the AI invented domain terms not in the original or injectable set."""
    safe_terms = injectable_keywords or set()
    safe_lower = {t.lower() for t in safe_terms}

    orig_terms = _extract_domain_terms(original)
    tail_terms = _extract_domain_terms(tailored)
    new_terms = tail_terms - orig_terms - safe_lower

    if len(new_terms) > 3:
        examples = sorted(new_terms)[:5]
        return GateResult(
            passed=False,
            gate_name="hallucination",
            message=f"Possible hallucination: {len(new_terms)} new terms ({', '.join(examples)})",
        )
    return GateResult(
        passed=True,
        gate_name="hallucination",
        message="No hallucinated terms detected.",
    )


# ── Runners ─────────────────────────────────────────────────────────────────


def run_all_gates(
    original: str,
    tailored: str,
    jd_text: str = "",
    required_keywords: list[str] | None = None,
    injectable_keywords: set[str] | None = None,
) -> list[GateResult]:
    """Run all 5 validation gates. Returns list of results."""
    return [
        gate_fact_preservation(original, tailored),
        gate_ai_phrases(tailored, jd_text),
        gate_keyword_verbatim(tailored, required_keywords),
        gate_length_sanity(original, tailored),
        gate_hallucination(original, tailored, injectable_keywords),
    ]


def validate_and_fix(
    original: str,
    tailored: str,
    jd_text: str = "",
    required_keywords: list[str] | None = None,
    injectable_keywords: set[str] | None = None,
) -> tuple[str, list[GateResult]]:
    """Run all gates, apply auto-fixes, return (final_text, gate_results).

    If a critical gate fails (fact_preservation, hallucination),
    returns the ORIGINAL text unchanged.
    """
    results = run_all_gates(
        original, tailored, jd_text, required_keywords, injectable_keywords,
    )

    final_text = tailored

    # Check for critical failures -- revert to original
    critical_gates = {"fact_preservation", "hallucination"}
    for result in results:
        if not result.passed and result.gate_name in critical_gates:
            log.info(
                f"[GATE] Critical failure ({result.gate_name}): "
                f"{result.message}. Reverting to original."
            )
            return original, results

    # Apply auto-fixes from non-critical gates
    for result in results:
        if result.auto_fixed and result.fixed_text:
            final_text = result.fixed_text

    # Check length failure -- revert to original
    for result in results:
        if not result.passed and result.gate_name == "length_sanity":
            log.info(f"[GATE] Length failure: {result.message}. Reverting.")
            return original, results

    return final_text, results
