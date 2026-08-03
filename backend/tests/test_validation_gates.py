from validation_gates import (
    gate_ai_phrases,
    gate_fact_preservation,
    gate_hallucination,
    gate_keyword_verbatim,
    gate_length_sanity,
    gate_unsupported_claims,
    numeric_metric_claims_verifiable,
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


def test_added_numeric_fact_rejected():
    result = gate_fact_preservation(
        "Led team of 8 to migrate legacy systems to cloud",
        "Led team of 8 to migrate legacy systems to cloud, handling 10M events daily",
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


def test_long_block_can_be_rewritten_without_an_absolute_word_cap():
    original = " ".join(["original"] * 45)
    tailored = " ".join(["rewrite"] * 45)
    result = gate_length_sanity(original, tailored)
    assert result.passed


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


def test_unsupported_outcome_claim_detected():
    result = gate_unsupported_claims(
        "Led team of 8 to migrate legacy systems to cloud",
        "Led 8-engineer team to migrate legacy systems with zero downtime and improved reliability",
    )
    assert not result.passed


def test_supported_outcome_claim_allowed():
    result = gate_unsupported_claims(
        "Led cloud migration with zero downtime",
        "Led 8-engineer cloud migration with zero downtime",
    )
    assert result.passed


def test_unsupported_scope_inflation_detected():
    original = (
        "Built the scaffold of a production multi-agent system, then reviewed "
        "its architecture and wrote the phased redesign plan."
    )

    for tailored in (
        "Led the architecture review and wrote the phased redesign plan.",
        "Designed and deployed the multi-agent system.",
        "Built a production-ready multi-agent system.",
    ):
        assert not gate_unsupported_claims(original, tailored).passed


def test_leadership_does_not_prove_ownership_or_manual_workflow_replacement():
    original = "Led delivery of an internal document assistant for operations teams"

    assert not gate_unsupported_claims(
        original,
        "Owned end-to-end document automation delivery for operations teams",
    ).passed
    assert not gate_unsupported_claims(
        original,
        "Led document automation delivery, replacing manual workflows",
    ).passed


def test_supported_scope_paraphrases_allowed():
    original = (
        "Led the architecture review, released the service, and delivered a "
        "production-ready system."
    )
    tailored = (
        "Directed the architecture review, deployed the service, and delivered "
        "a production-grade system."
    )

    assert gate_unsupported_claims(original, tailored).passed


def test_stronger_prevention_claim_is_rejected():
    result = gate_unsupported_claims(
        "Mitigated USD 100M+ in potential losses",
        "Avoided USD 100M+ in potential losses",
    )

    assert not result.passed


def test_scaffold_cannot_be_upgraded_to_full_production_implementation():
    result = gate_unsupported_claims(
        "Built the scaffold of a production multi-agent system.",
        "Designed and implemented a production multi-agent system.",
    )

    assert not result.passed


def test_scaffold_qualification_can_be_preserved():
    result = gate_unsupported_claims(
        "Built the scaffold of a production multi-agent system.",
        "Developed the scaffold for a production multi-agent system.",
    )

    assert result.passed


def test_numeric_metric_claims_reject_changed_meaning():
    assert not numeric_metric_claims_verifiable(
        "Built a platform targeting a ~90% reduction in investigation time.",
        "Built a platform that reduced investigation time by up to 90%.",
    )
    assert not numeric_metric_claims_verifiable(
        "USD 600M+ in opportunities identified; USD 50M+ realized.",
        "Delivered USD 50M+ in savings.",
    )
    assert not numeric_metric_claims_verifiable(
        "Mitigated USD 100M+ in potential losses.",
        "Prevented USD 100M+ in losses.",
    )


def test_numeric_metric_claims_allow_equivalent_meaning():
    assert numeric_metric_claims_verifiable(
        "Built a platform targeting a ~90% reduction in investigation time.",
        "Built a platform aiming for an approximately 90% reduction in investigation time.",
    )
    assert numeric_metric_claims_verifiable(
        "Realized USD 50M+ in savings.",
        "Delivered realised savings of USD 50M+.",
    )
    assert numeric_metric_claims_verifiable(
        "Avoided USD 10M in losses.",
        "Prevented losses totalling USD 10M.",
    )


def test_numeric_metric_context_is_attached_to_the_nearest_number():
    assert numeric_metric_claims_verifiable(
        "Identified USD 600M+ in opportunities and realized USD 50M+.",
        "Realised USD 50M+.",
    )


def test_numeric_metric_claims_preserve_currency_and_units():
    assert not numeric_metric_claims_verifiable(
        "Saved USD 50M.",
        "Saved SGD 50M.",
    )
    assert not numeric_metric_claims_verifiable(
        "Processed 50M records.",
        "Processed USD 50M.",
    )
    assert not numeric_metric_claims_verifiable(
        "8 years of experience with 6 direct reports.",
        "8 direct reports across 6 years.",
    )


def test_metric_meaning_drift_reverts_in_the_main_validation_runner():
    original = "Built a platform targeting a ~90% reduction in investigation time."
    tailored = "Built a platform that reduced investigation time by ~90%."

    final_text, results = validate_and_fix(original, tailored)

    assert final_text == original
    assert any(
        result.gate_name == "fact_preservation" and not result.passed
        for result in results
    )


def test_implementation_does_not_prove_deployment():
    result = gate_unsupported_claims(
        "Implemented a prototype for internal review.",
        "Deployed a prototype for internal review.",
    )

    assert not result.passed


def test_generated_list_number_is_removed_before_validation():
    original = "Selected and implemented SEMulator3D through A/B trials"
    tailored = "2. Selected and implemented SEMulator3D through A/B trials"

    final_text, _results = validate_and_fix(original, tailored)

    assert final_text == original


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


def test_unsupported_claim_reverts():
    original = "Led team of 8 to migrate legacy systems to cloud"
    tailored = (
        "Led 8-engineer team to migrate legacy systems to cloud infrastructure, "
        "ensuring zero downtime and improved system reliability."
    )
    final_text, results = validate_and_fix(original, tailored)
    assert final_text == original
    assert any(
        result.gate_name == "unsupported_claims" and not result.passed
        for result in results
    )
