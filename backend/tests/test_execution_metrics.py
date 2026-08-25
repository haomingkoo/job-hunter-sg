from recruitment_team.execution_metrics import merge_execution_metrics


def test_merge_deduplicates_replayed_attempts_and_preserves_assessment_lineage():
    attempt = {
        "attempt_id": "model-event-1",
        "attempt_count": 1,
        "input_tokens": 20,
        "output_tokens": 5,
    }

    merged = merge_execution_metrics(
        {
            "logical_run_id": "assessment-run",
            "trace_key": "assessment-trace",
            "model_call_count": 1,
            "input_tokens": 20,
            "output_tokens": 5,
            "attempts": [attempt],
        },
        {
            "logical_run_id": "assessment-run",
            "trace_key": "assessment-trace",
            "command_run_id": "answer-command",
            "command_trace_key": "answer-trace",
            "model_call_count": 1,
            "input_tokens": 20,
            "output_tokens": 5,
            "checkpoint_hit_count": 1,
            "attempts": [attempt],
        },
    )

    assert merged["attempts"] == [attempt]
    assert merged["model_call_count"] == 1
    assert merged["input_tokens"] == 20
    assert merged["output_tokens"] == 5
    assert merged["checkpoint_hit_count"] == 1
    assert merged["logical_run_id"] == "assessment-run"
    assert merged["trace_key"] == "assessment-trace"
    assert merged["command_run_id"] == "answer-command"
    assert merged["command_trace_key"] == "answer-trace"


def test_merge_deduplicates_content_free_semantic_outcomes_and_derives_role_counts():
    rejected = {
        "outcome_id": "specialist-call-1",
        "role": "recruiter",
        "stage": "specialist_submission",
        "accepted": False,
        "submission_attempt": 1,
        "validation_code": "unknown_criterion_citation",
    }
    accepted = {
        "outcome_id": "specialist-call-2",
        "role": "recruiter",
        "stage": "specialist_submission",
        "accepted": True,
        "submission_attempt": 2,
        "validation_code": "",
    }

    merged = merge_execution_metrics(
        {"semantic_outcomes": [rejected]},
        {"semantic_outcomes": [rejected, accepted]},
    )

    assert merged["semantic_outcomes"] == [rejected, accepted]
    assert merged["semantic_by_role"] == {
        "recruiter": {
            "submission_count": 2,
            "accepted_count": 1,
            "rejected_count": 1,
            "correction_attempt_count": 1,
        }
    }
    assert "submission" not in merged["semantic_outcomes"][0]


def test_merge_promotes_nested_validator_attempts_into_semantic_totals():
    nested = {
        "attempt_id": "resume_edit_evidence:validator-1",
        "attempt_count": 1,
        "input_tokens": 17,
        "output_tokens": 4,
        "stage": "resume_edit_evidence",
    }

    merged = merge_execution_metrics({}, {
        "nested_model_attempts": [nested],
        "transport_call_count": 1,
    })

    assert merged["attempts"] == [nested]
    assert merged["model_call_count"] == 1
    assert merged["input_tokens"] == 17
    assert merged["output_tokens"] == 4
    assert "nested_model_attempts" not in merged


def test_merge_preserves_per_role_cost_latency_and_model_identity():
    current = {
        "transport_call_count": 1,
        "transport_token_usage_available": True,
        "transport_latency_ms": 12.5,
        "transport_models": ["model-a"],
        "transport_by_role": {
            "specialist:recruiter": {
                "call_count": 1,
                "attempt_count": 1,
                "retry_count": 0,
                "error_count": 0,
                "input_tokens": 100,
                "output_tokens": 20,
                "token_usage_available": True,
                "latency_ms": 12.5,
                "models": ["model-a"],
            }
        },
    }
    update = {
        "transport_call_count": 1,
        "transport_token_usage_available": True,
        "transport_latency_ms": 7.25,
        "transport_models": ["model-a", "model-b"],
        "transport_by_role": {
            "specialist:recruiter": {
                "call_count": 1,
                "attempt_count": 2,
                "retry_count": 1,
                "error_count": 0,
                "input_tokens": 80,
                "output_tokens": 10,
                "token_usage_available": True,
                "latency_ms": 7.25,
                "models": ["model-b"],
            }
        },
    }

    merged = merge_execution_metrics(current, update)

    assert merged["transport_latency_ms"] == 19.75
    assert merged["transport_models"] == ["model-a", "model-b"]
    assert merged["transport_token_usage_available"] is True
    assert merged["transport_by_role"]["specialist:recruiter"] == {
        "call_count": 2,
        "attempt_count": 3,
        "retry_count": 1,
        "error_count": 0,
        "input_tokens": 180,
        "output_tokens": 30,
        "token_usage_available": True,
        "latency_ms": 19.75,
        "models": ["model-a", "model-b"],
    }


def test_merge_marks_token_usage_unavailable_when_any_nonempty_stage_lacks_it():
    merged = merge_execution_metrics(
        {
            "transport_call_count": 1,
            "transport_token_usage_available": True,
            "transport_by_role": {
                "coordinator": {
                    "call_count": 1,
                    "token_usage_available": True,
                }
            },
        },
        {
            "transport_call_count": 1,
            "transport_token_usage_available": False,
            "transport_by_role": {
                "coordinator": {
                    "call_count": 1,
                    "token_usage_available": False,
                }
            },
        },
    )

    assert merged["transport_token_usage_available"] is False
    assert merged["transport_by_role"]["coordinator"]["token_usage_available"] is False
