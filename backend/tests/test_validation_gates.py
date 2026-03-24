from validation_gates import (
    gate_ai_phrases,
    gate_fact_preservation,
    gate_hallucination,
    gate_keyword_verbatim,
    gate_length_sanity,
    validate_and_fix,
)


def test_fact_preserved():
    result = gate_fact_preservation(
        "Led team of 12 engineers saving $3M",
        "Directed team of 12 engineers achieving $3M in cost savings",
    )
    assert result.passed


def test_fact_altered():
    result = gate_fact_preservation(
        "Led team of 12 engineers saving $3M",
        "Directed team of 15 engineers achieving $5M in cost savings",
    )
    assert not result.passed


def test_fact_removed():
    result = gate_fact_preservation(
        "Reduced costs by 25%",
        "Significantly reduced operational costs",
    )
    assert not result.passed


def test_ai_phrase_replaced():
    result = gate_ai_phrases("Spearheaded a transformative initiative")
    assert result.auto_fixed
    assert result.fixed_text is not None
    assert "spearheaded" not in result.fixed_text.lower()


def test_ai_phrase_protected_by_jd():
    result = gate_ai_phrases(
        "Spearheaded the cloud migration",
        jd_text="Looking for someone who has spearheaded large migrations",
    )
    assert not result.auto_fixed
    assert "protected" in result.message.lower()


def test_keyword_present():
    result = gate_keyword_verbatim(
        "Built machine learning pipeline for real-time data",
        ["machine learning"],
    )
    assert result.passed


def test_keyword_missing():
    result = gate_keyword_verbatim(
        "Built ML pipeline for real-time data",
        ["machine learning"],
    )
    assert not result.passed


def test_length_too_long():
    original = "Led a team"
    tailored = " ".join(["word"] * 45)
    result = gate_length_sanity(original, tailored)
    assert not result.passed


def test_length_bloated():
    original = "Led team of 5"
    tailored = " ".join(["word"] * 30)
    result = gate_length_sanity(original, tailored)
    assert not result.passed


def test_no_hallucination():
    result = gate_hallucination(
        "Led Python team to deploy ML models",
        "Directed Python team to deploy ML models on AWS",
        injectable_keywords={"AWS"},
    )
    assert result.passed


def test_hallucination_detected():
    result = gate_hallucination(
        "Managed team schedule",
        "Managed Kubernetes Docker Terraform CI/CD pipeline orchestration",
        injectable_keywords=set(),
    )
    assert not result.passed


def test_critical_failure_reverts():
    original = "Saved $3M through process optimization"
    tailored = "Revolutionized process optimization achieving unprecedented results"
    final_text, results = validate_and_fix(original, tailored)
    assert final_text == original
    assert any(not result.passed for result in results)


def test_auto_fix_applied():
    original = "Led team"
    tailored = "Spearheaded a cutting-edge team"
    final_text, _results = validate_and_fix(original, tailored, jd_text="")
    assert "spearheaded" not in final_text.lower()
    assert final_text != original
