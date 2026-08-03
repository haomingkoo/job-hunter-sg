"""
Validation gates -- local checks on every AI-generated resume change.

All gates are pure functions. No LLM calls. Run in <10ms each.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from ai_phrases import clean_ai_phrases
from config import VALIDATION_REWRITE_MAX_EXPANSION_RATIO

log = logging.getLogger("jobhunter.gates")

@dataclass
class GateResult:
    passed: bool
    gate_name: str
    message: str
    auto_fixed: bool = False
    fixed_text: str | None = None



_NUMBER_RE = re.compile(
    r"\$[\d,.]+[kKmMbB]?"
    r"|\d+(?:\.\d+)?%"
    r"|\d{1,3}(?:,\d{3})+"
    r"|\d+[kKmMbB]\b"
    r"|\b\d+(?:\.\d+)?\+?\b"
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

_UNSUPPORTED_OUTCOME_PATTERNS = [
    re.compile(r"\bzero[- ]downtime\b", re.IGNORECASE),
    re.compile(r"\bno downtime\b", re.IGNORECASE),
    re.compile(r"\bwithout downtime\b", re.IGNORECASE),
    re.compile(r"\bimproved (?:system )?reliability\b", re.IGNORECASE),
    re.compile(r"\bseamless transition\b", re.IGNORECASE),
    re.compile(r"\boperational continuity\b", re.IGNORECASE),
    re.compile(r"\bensur(?:ed|ing)\b", re.IGNORECASE),
    re.compile(r"\breplac(?:e[ds]?|ing)\s+manual\b", re.IGNORECASE),
]

_UNSUPPORTED_SCOPE_CLAIMS = [
    (
        "ownership",
        re.compile(r"\b(?:owned|ownership)\b", re.IGNORECASE),
        re.compile(r"\b(?:owned|ownership)\b", re.IGNORECASE),
    ),
    (
        "leadership",
        re.compile(
            r"\b(?:led|leading|managed|managing|directed|supervised|headed|oversaw|"
            r"drove|spearheaded)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:led|leadership|leading|managed|managing|directed|supervised|"
            r"headed|oversaw|owned|drove|spearheaded)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "deployment",
        re.compile(
            r"\b(?:deployed|deploying|deployment)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:deployed|deploying|deployment|released|shipped|launched|"
            r"rolled out)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "production readiness",
        re.compile(r"\bproduction[- ](?:ready|grade)\b", re.IGNORECASE),
        re.compile(r"\bproduction[- ](?:ready|grade)\b", re.IGNORECASE),
    ),
    (
        "prevention",
        re.compile(r"\b(?:avoided|prevented)\b", re.IGNORECASE),
        re.compile(r"\b(?:avoided|prevented)\b", re.IGNORECASE),
    ),
]

_GENERATED_LIST_PREFIX_RE = re.compile(
    r"^\s*(?:[-*•]\s+|\d+[.)]\s+)"
)

_LIMITED_MATURITY_RE = re.compile(
    r"\b(?:scaffold|prototype|proof[- ]of[- ]concept|poc)\b",
    re.IGNORECASE,
)
_FULL_IMPLEMENTATION_RE = re.compile(
    r"\b(?:implemented|deployed|launched|released)\b",
    re.IGNORECASE,
)

_METRIC_NUMBER_RE = re.compile(
    r"(?<![\w.])(?:(?:USD|SGD|US\$|S\$|\$)\s*)?[~≈]?\s*"
    r"\d+(?:,\d{3})*(?:\.\d+)?\s*[kKmMbB]?\+?%?(?![\w%])",
    re.IGNORECASE,
)

_METRIC_CONTEXT_PATTERNS = (
    ("savings", re.compile(r"\bsav(?:e[ds]?|ings?)\b", re.IGNORECASE)),
    ("realised", re.compile(r"\breali[sz](?:e[ds]?|ing|ation)\b", re.IGNORECASE)),
    ("opportunities", re.compile(r"\bopportunit(?:y|ies)\b", re.IGNORECASE)),
    ("reduction", re.compile(r"\breduc(?:e[ds]?|ing|tions?)\b", re.IGNORECASE)),
    ("target", re.compile(r"\b(?:target|aim)(?:ed|ing|s)?\b", re.IGNORECASE)),
    ("projected", re.compile(r"\bproject(?:ed|ing|ions?)\b", re.IGNORECASE)),
    ("potential", re.compile(r"\bpotential(?:ly)?\b", re.IGNORECASE)),
    ("prevention", re.compile(r"\b(?:avoid|prevent)(?:ed|ing|s)?\b", re.IGNORECASE)),
    ("approximate", re.compile(r"\b(?:about|around|approximately|roughly)\b", re.IGNORECASE)),
    ("upper_bound", re.compile(r"\b(?:up to|at most)\b", re.IGNORECASE)),
)

_METRIC_UNIT_PATTERNS = (
    ("years", re.compile(r"\byears?\b", re.IGNORECASE)),
    ("months", re.compile(r"\bmonths?\b", re.IGNORECASE)),
    ("weeks", re.compile(r"\bweeks?\b", re.IGNORECASE)),
    ("days", re.compile(r"\bdays?\b", re.IGNORECASE)),
    ("reports", re.compile(r"\b(?:direct\s+)?reports?\b", re.IGNORECASE)),
    ("engineers", re.compile(r"\bengineers?\b", re.IGNORECASE)),
    ("people", re.compile(r"\b(?:people|persons?|staff|members?)\b", re.IGNORECASE)),
    ("users", re.compile(r"\busers?\b", re.IGNORECASE)),
    ("customers", re.compile(r"\bcustomers?\b", re.IGNORECASE)),
    ("clients", re.compile(r"\bclients?\b", re.IGNORECASE)),
    ("records", re.compile(r"\brecords?\b", re.IGNORECASE)),
    ("events", re.compile(r"\bevents?\b", re.IGNORECASE)),
    ("projects", re.compile(r"\bprojects?\b", re.IGNORECASE)),
    ("systems", re.compile(r"\bsystems?\b", re.IGNORECASE)),
    ("sites", re.compile(r"\bsites?\b", re.IGNORECASE)),
    ("countries", re.compile(r"\bcountr(?:y|ies)\b", re.IGNORECASE)),
    ("roles", re.compile(r"\broles?\b", re.IGNORECASE)),
    ("jobs", re.compile(r"\bjobs?\b", re.IGNORECASE)),
    ("listings", re.compile(r"\blistings?\b", re.IGNORECASE)),
)

_METRIC_CONTEXT_RADIUS = 80
_CLAIM_BOUNDARY_RE = re.compile(r"[;.!?\n]")


def _extract_numbers(text: str) -> set[str]:
    """Extract all numeric facts from text."""
    return {m.strip().lower() for m in _NUMBER_RE.findall(text)}


def _extract_domain_terms(text: str) -> set[str]:
    """Extract capitalized domain terms and known tech terms."""
    terms = {m.lower() for m in _DOMAIN_TERM_RE.findall(text)}
    words = set(re.findall(r"[a-z][a-z0-9+#./-]+", text.lower()))
    terms |= words & _TECH_TERMS
    return terms


def _normalize_metric_token(value: str) -> str:
    value = re.sub(r"^\s*(?:usd|sgd|us\$|s\$|\$)\s*", "", value, flags=re.IGNORECASE)
    return re.sub(r"[\s,~≈]", "", value).lower()


def _metric_currency(value: str) -> str:
    compact = re.sub(r"\s+", "", value).lower()
    if compact.startswith(("usd", "us$")):
        return "usd"
    if compact.startswith(("sgd", "s$")):
        return "sgd"
    if compact.startswith("$"):
        return "unspecified"
    return ""


def _metric_claim_signatures(text: str) -> list[tuple[str, frozenset[str]]]:
    metrics = [
        [match, _normalize_metric_token(match.group()), set()]
        for match in _METRIC_NUMBER_RE.finditer(text)
    ]
    for metric in metrics:
        if "~" in metric[0].group() or "≈" in metric[0].group():
            metric[2].add("approximate")
        currency = _metric_currency(metric[0].group())
        if currency:
            metric[2].add(f"currency:{currency}")

    labelled_patterns = _METRIC_CONTEXT_PATTERNS + tuple(
        (f"unit:{label}", pattern) for label, pattern in _METRIC_UNIT_PATTERNS
    )
    for label, pattern in labelled_patterns:
        for context_match in pattern.finditer(text):
            candidates = []
            for index, (metric_match, _token, _labels) in enumerate(metrics):
                is_unit = label.startswith("unit:")
                if is_unit and context_match.start() < metric_match.end():
                    continue
                distance = max(
                    metric_match.start() - context_match.end(),
                    context_match.start() - metric_match.end(),
                    0,
                )
                between = text[
                    min(metric_match.end(), context_match.end()):
                    max(metric_match.start(), context_match.start())
                ]
                max_distance = 18 if is_unit else _METRIC_CONTEXT_RADIUS
                if distance <= max_distance and not _CLAIM_BOUNDARY_RE.search(between):
                    candidates.append((distance, index))
            if candidates:
                metrics[min(candidates)[1]][2].add(label)

    return [(token, frozenset(labels)) for _match, token, labels in metrics]


def numeric_metric_claims_verifiable(source: str, generated: str) -> bool:
    """Return whether each generated numeric claim keeps its source meaning."""
    source_claims: dict[str, set[frozenset[str]]] = {}
    for token, labels in _metric_claim_signatures(source):
        source_claims.setdefault(token, set()).add(labels)

    return all(
        labels in source_claims.get(token, set())
        for token, labels in _metric_claim_signatures(generated)
    )


def gate_fact_preservation(original: str, tailored: str) -> GateResult:
    """Ensure numeric facts are preserved and not newly introduced."""
    orig_numbers = _extract_numbers(original)
    tail_numbers = _extract_numbers(tailored)
    missing = orig_numbers - tail_numbers
    added = tail_numbers - orig_numbers

    if missing:
        return GateResult(
            passed=False,
            gate_name="fact_preservation",
            message=f"Missing facts from original: {', '.join(sorted(missing))}",
        )
    if added:
        return GateResult(
            passed=False,
            gate_name="fact_preservation",
            message=f"Added unsupported numeric facts: {', '.join(sorted(added))}",
        )
    if not numeric_metric_claims_verifiable(original, tailored):
        return GateResult(
            passed=False,
            gate_name="fact_preservation",
            message="A numeric fact changed currency, unit, qualifier, or meaning.",
        )
    return GateResult(
        passed=True,
        gate_name="fact_preservation",
        message="All original facts preserved.",
    )


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

    if orig_words > 0 and tail_words / orig_words > VALIDATION_REWRITE_MAX_EXPANSION_RATIO:
        return GateResult(
            passed=False,
            gate_name="length_sanity",
            message=(
                f"Rewrite is {tail_words / orig_words:.1f}x longer than "
                f"original ({orig_words} -> {tail_words} words). "
                f"Max {VALIDATION_REWRITE_MAX_EXPANSION_RATIO:g}x."
            ),
        )

    return GateResult(
        passed=True,
        gate_name="length_sanity",
        message=f"Length OK ({tail_words} words).",
    )


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


def gate_unsupported_claims(original: str, tailored: str) -> GateResult:
    """Reject high-risk outcome or scope claims absent from the source bullet."""
    if (
        _LIMITED_MATURITY_RE.search(original)
        and not _LIMITED_MATURITY_RE.search(tailored)
        and _FULL_IMPLEMENTATION_RE.search(tailored)
    ):
        return GateResult(
            passed=False,
            gate_name="unsupported_claims",
            message="Rewrite removes a prototype or scaffold qualification.",
        )
    for pattern in _UNSUPPORTED_OUTCOME_PATTERNS:
        if pattern.search(tailored) and not pattern.search(original):
            return GateResult(
                passed=False,
                gate_name="unsupported_claims",
                message="Rewrite adds unsupported outcome claims.",
            )
    for claim, tailored_pattern, source_pattern in _UNSUPPORTED_SCOPE_CLAIMS:
        if tailored_pattern.search(tailored) and not source_pattern.search(original):
            return GateResult(
                passed=False,
                gate_name="unsupported_claims",
                message=f"Rewrite adds an unsupported {claim} claim.",
            )
    return GateResult(
        passed=True,
        gate_name="unsupported_claims",
        message="No unsupported claims detected.",
    )




def run_all_gates(
    original: str,
    tailored: str,
    jd_text: str = "",
    required_keywords: list[str] | None = None,
    injectable_keywords: set[str] | None = None,
    supporting_evidence: str = "",
) -> list[GateResult]:
    """Run all validation gates against source text and cited candidate evidence."""
    supported_source = "\n".join(part for part in (original, supporting_evidence) if part)
    return [
        gate_fact_preservation(supported_source, tailored),
        gate_ai_phrases(tailored, jd_text),
        gate_keyword_verbatim(tailored, required_keywords),
        gate_length_sanity(original, tailored),
        gate_hallucination(supported_source, tailored, injectable_keywords),
        gate_unsupported_claims(supported_source, tailored),
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
    normalized = tailored.strip()
    if not _GENERATED_LIST_PREFIX_RE.match(original):
        normalized = _GENERATED_LIST_PREFIX_RE.sub("", normalized, count=1)

    results = run_all_gates(
        original, normalized, jd_text, required_keywords, injectable_keywords,
    )

    final_text = normalized

    critical_gates = {"fact_preservation", "hallucination", "unsupported_claims"}
    for result in results:
        if not result.passed and result.gate_name in critical_gates:
            log.info(
                f"[GATE] Critical failure ({result.gate_name}): "
                f"{result.message}. Reverting to original."
            )
            return original, results

    for result in results:
        if result.auto_fixed and result.fixed_text:
            final_text = result.fixed_text

    for result in results:
        if not result.passed and result.gate_name == "length_sanity":
            log.info(f"[GATE] Length failure: {result.message}. Reverting.")
            return original, results

    return final_text, results
