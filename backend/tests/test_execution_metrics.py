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

    merged = merge_execution_metrics(
        {},
        {
            "nested_model_attempts": [nested],
            "transport_call_count": 1,
        },
    )

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


def test_merge_keeps_partial_transport_totals_separate_from_reported_totals():
    merged = merge_execution_metrics(
        {},
        {
            "model_call_count": 2,
            "reported_model_call_count": 2,
            "input_tokens": 33,
            "output_tokens": 13,
            "reported_input_tokens": 33,
            "reported_output_tokens": 13,
            "transport_call_count": 1,
            "transport_input_tokens": 13,
            "transport_output_tokens": 5,
            "transport_token_usage_available": True,
        },
    )

    assert merged["reported_model_call_count"] == 2
    assert merged["transport_call_count"] == 1
    assert merged["model_call_count"] == 2
    assert merged["reported_input_tokens"] == 33
    assert merged["reported_output_tokens"] == 13
    assert merged["transport_input_tokens"] == 13
    assert merged["transport_output_tokens"] == 5
    assert merged["input_tokens"] == 33
    assert merged["output_tokens"] == 13


def test_merge_preserves_legacy_scalars_with_new_identifiable_attempts():
    merged = merge_execution_metrics(
        {
            "model_call_count": 3,
            "input_tokens": 100,
            "output_tokens": 40,
        },
        {
            "reported_model_call_count": 1,
            "reported_input_tokens": 11,
            "reported_output_tokens": 4,
            "attempts": [
                {
                    "attempt_id": "new-1",
                    "attempt_count": 1,
                    "input_tokens": 11,
                    "output_tokens": 4,
                }
            ],
        },
    )

    assert merged["reported_model_call_count"] == 4
    assert merged["reported_input_tokens"] == 111
    assert merged["reported_output_tokens"] == 44


def test_merge_preserves_paused_legacy_scalars_through_repeated_resumes():
    paused = {
        "terminal_status": "paused",
        "model_call_count": 2,
        "input_tokens": 20,
        "output_tokens": 8,
    }
    first_resume = merge_execution_metrics(
        paused,
        {
            "terminal_status": "paused",
            "reported_model_call_count": 1,
            "reported_input_tokens": 7,
            "reported_output_tokens": 3,
            "attempts": [
                {
                    "attempt_id": "resume-1",
                    "input_tokens": 7,
                    "output_tokens": 3,
                }
            ],
        },
    )
    completed = merge_execution_metrics(
        first_resume,
        {
            "terminal_status": "completed",
            "reported_model_call_count": 1,
            "reported_input_tokens": 5,
            "reported_output_tokens": 2,
            "attempts": [
                {
                    "attempt_id": "resume-2",
                    "input_tokens": 5,
                    "output_tokens": 2,
                }
            ],
        },
    )

    assert completed["terminal_status"] == "completed"
    assert completed["reported_model_call_count"] == 4
    assert completed["reported_input_tokens"] == 32
    assert completed["reported_output_tokens"] == 13


def test_merge_accumulates_new_format_paused_and_resumed_observations():
    paused = merge_execution_metrics(
        {},
        {
            "terminal_status": "paused",
            "reported_model_call_count": 1,
            "reported_input_tokens": 10,
            "reported_output_tokens": 4,
            "attempts": [
                {
                    "attempt_id": "pause-1",
                    "input_tokens": 10,
                    "output_tokens": 4,
                }
            ],
            "transport_call_count": 1,
            "transport_input_tokens": 10,
            "transport_output_tokens": 4,
            "transport_token_usage_available": True,
        },
    )
    completed = merge_execution_metrics(
        paused,
        {
            "terminal_status": "completed",
            "checkpoint_hit_count": 1,
            "reported_model_call_count": 1,
            "reported_input_tokens": 7,
            "reported_output_tokens": 3,
            "attempts": [
                {
                    "attempt_id": "resume-1",
                    "input_tokens": 7,
                    "output_tokens": 3,
                }
            ],
            "transport_call_count": 1,
            "transport_input_tokens": 7,
            "transport_output_tokens": 3,
            "transport_token_usage_available": True,
        },
    )

    assert completed["terminal_status"] == "completed"
    assert completed["checkpoint_hit_count"] == 1
    assert completed["reported_model_call_count"] == 2
    assert completed["reported_input_tokens"] == 17
    assert completed["reported_output_tokens"] == 7
    assert completed["transport_call_count"] == 2
    assert completed["transport_input_tokens"] == 17
    assert completed["transport_output_tokens"] == 7
    assert completed["transport_token_usage_available"] is True


def test_identical_execution_observation_replay_is_idempotent():
    observation = {
        "observation_id": "transport-call-1",
        "role": "coordinator",
        "attempts": 2,
        "outcome": "success",
        "input_tokens": 10,
        "output_tokens": 3,
        "token_usage_available": True,
        "latency_ms": 12.0,
        "model": "model-a",
    }
    snapshot = {
        "command_run_id": "command-1",
        "reported_model_call_count": 1,
        "reported_input_tokens": 10,
        "reported_output_tokens": 3,
        "attempts": [{"attempt_id": "reported-1", "input_tokens": 10, "output_tokens": 3}],
        "checkpoint_hit_count": 1,
        "latency_ms": 15.0,
        "transport_observations": [observation],
        "transport_call_count": 1,
        "transport_attempt_count": 2,
        "transport_retry_count": 1,
        "transport_error_count": 0,
        "transport_input_tokens": 10,
        "transport_output_tokens": 3,
        "transport_token_usage_available": True,
        "transport_latency_ms": 12.0,
        "transport_models": ["model-a"],
        "transport_by_role": {
            "coordinator": {
                "call_count": 1,
                "attempt_count": 2,
                "retry_count": 1,
                "error_count": 0,
                "input_tokens": 10,
                "output_tokens": 3,
                "token_usage_available": True,
                "latency_ms": 12.0,
                "models": ["model-a"],
            }
        },
    }

    first = merge_execution_metrics({}, snapshot)
    replayed = merge_execution_metrics(first, snapshot)

    assert replayed == first


def test_command_identity_makes_idless_reported_scalar_replay_idempotent():
    snapshot = {
        "command_run_id": "command-with-idless-attempt",
        "reported_model_call_count": 1,
        "reported_input_tokens": 9,
        "reported_output_tokens": 2,
        "attempts": [{"input_tokens": 9, "output_tokens": 2}],
    }

    first = merge_execution_metrics({}, snapshot)
    replayed = merge_execution_metrics(first, snapshot)

    assert replayed["reported_model_call_count"] == 1
    assert replayed["reported_input_tokens"] == 9
    assert replayed["reported_output_tokens"] == 2
    assert replayed["attempts"] == first["attempts"]


def test_distinct_execution_observations_accumulate_and_keep_legacy_residuals():
    legacy = {
        "model_call_count": 2,
        "input_tokens": 20,
        "output_tokens": 8,
        "transport_call_count": 1,
        "transport_attempt_count": 1,
        "transport_input_tokens": 4,
        "transport_output_tokens": 2,
        "transport_token_usage_available": True,
        "transport_latency_ms": 5.0,
    }
    first = merge_execution_metrics(
        legacy,
        {
            "command_run_id": "pause-command",
            "reported_model_call_count": 1,
            "reported_input_tokens": 7,
            "reported_output_tokens": 3,
            "attempts": [{"attempt_id": "pause-1", "input_tokens": 7, "output_tokens": 3}],
            "transport_observations": [{
                "observation_id": "pause-transport",
                "role": "coordinator",
                "attempts": 1,
                "outcome": "success",
                "input_tokens": 7,
                "output_tokens": 3,
                "token_usage_available": True,
                "latency_ms": 6.0,
            }],
        },
    )
    completed = merge_execution_metrics(
        first,
        {
            "command_run_id": "resume-command",
            "reported_model_call_count": 1,
            "reported_input_tokens": 5,
            "reported_output_tokens": 2,
            "attempts": [{"attempt_id": "resume-1", "input_tokens": 5, "output_tokens": 2}],
            "transport_observations": [{
                "observation_id": "resume-transport",
                "role": "coordinator",
                "attempts": 2,
                "outcome": "success",
                "input_tokens": 5,
                "output_tokens": 2,
                "token_usage_available": True,
                "latency_ms": 4.0,
            }],
        },
    )

    assert completed["reported_model_call_count"] == 4
    assert completed["reported_input_tokens"] == 32
    assert completed["reported_output_tokens"] == 13
    assert completed["transport_call_count"] == 3
    assert completed["transport_attempt_count"] == 4
    assert completed["transport_input_tokens"] == 16
    assert completed["transport_output_tokens"] == 7
    assert completed["transport_latency_ms"] == 15.0
    assert completed["transport_by_role"]["coordinator"]["call_count"] == 2


def test_reported_only_metrics_do_not_invent_transport_observations():
    merged = merge_execution_metrics(
        {},
        {
            "command_run_id": "reported-only",
            "reported_model_call_count": 2,
            "reported_input_tokens": 20,
            "reported_output_tokens": 5,
        },
    )

    assert not any(key.startswith("transport_") for key in merged)


def test_replayed_candidate_profile_event_is_idempotent_and_does_not_invent_transport():
    from recruitment_team.execution_metrics import merge_execution_event

    event = {
        "event": "model_attempt",
        "attempt_id": "candidate-profile-attempt-1",
        "logical_run_id": "profile-run",
        "input_tokens": 12,
        "output_tokens": 4,
        "latency_ms": 17.0,
    }

    first = merge_execution_event({}, event)
    replayed = merge_execution_event(first, event)

    assert replayed == first
    assert not any(key.startswith("transport_") for key in replayed)


def test_partially_overlapping_cumulative_snapshot_replaces_envelope_totals():
    first_attempt = {
        "attempt_id": "cumulative-1",
        "input_tokens": 10,
        "output_tokens": 3,
    }
    second_attempt = {
        "attempt_id": "cumulative-2",
        "input_tokens": 7,
        "output_tokens": 2,
    }
    current = merge_execution_metrics(
        {},
        {
            "reported_model_call_count": 1,
            "reported_input_tokens": 10,
            "reported_output_tokens": 3,
            "checkpoint_hit_count": 1,
            "latency_ms": 10,
            "attempts": [first_attempt],
        },
    )

    merged = merge_execution_metrics(
        current,
        {
            "reported_model_call_count": 2,
            "reported_input_tokens": 17,
            "reported_output_tokens": 5,
            "checkpoint_hit_count": 2,
            "latency_ms": 15,
            "attempts": [first_attempt, second_attempt],
        },
    )

    assert merged["reported_model_call_count"] == 2
    assert merged["reported_input_tokens"] == 17
    assert merged["reported_output_tokens"] == 5
    assert merged["checkpoint_hit_count"] == 2
    assert merged["latency_ms"] == 15


def test_partially_overlapping_snapshot_does_not_repeat_legacy_residuals():
    first_attempt = {
        "attempt_id": "legacy-cumulative-1",
        "input_tokens": 10,
        "output_tokens": 3,
    }
    second_attempt = {
        "attempt_id": "legacy-cumulative-2",
        "input_tokens": 7,
        "output_tokens": 2,
    }
    current = merge_execution_metrics(
        {},
        {
            "reported_model_call_count": 3,
            "reported_input_tokens": 30,
            "reported_output_tokens": 11,
            "attempts": [first_attempt],
        },
    )

    merged = merge_execution_metrics(
        current,
        {
            "reported_model_call_count": 4,
            "reported_input_tokens": 37,
            "reported_output_tokens": 13,
            "attempts": [first_attempt, second_attempt],
        },
    )

    assert merged["reported_model_call_count"] == 4
    assert merged["reported_input_tokens"] == 37
    assert merged["reported_output_tokens"] == 13


def test_partially_overlapping_transport_snapshot_does_not_repeat_legacy_residuals():
    first_observation = {
        "observation_id": "transport-cumulative-1",
        "role": "coordinator",
        "attempts": 1,
        "outcome": "success",
        "input_tokens": 10,
        "output_tokens": 3,
        "token_usage_available": True,
        "latency_ms": 5,
        "model": "model-a",
    }
    second_observation = {
        "observation_id": "transport-cumulative-2",
        "role": "coordinator",
        "attempts": 1,
        "outcome": "success",
        "input_tokens": 7,
        "output_tokens": 2,
        "token_usage_available": True,
        "latency_ms": 5,
        "model": "model-a",
    }
    current = merge_execution_metrics(
        {},
        {
            "transport_observations": [first_observation],
            "transport_call_count": 3,
            "transport_attempt_count": 3,
            "transport_input_tokens": 30,
            "transport_output_tokens": 11,
            "transport_latency_ms": 15,
            "transport_token_usage_available": True,
            "transport_by_role": {
                "coordinator": {
                    "call_count": 3,
                    "attempt_count": 3,
                    "input_tokens": 30,
                    "output_tokens": 11,
                    "latency_ms": 15,
                    "token_usage_available": True,
                }
            },
        },
    )

    merged = merge_execution_metrics(
        current,
        {
            "transport_observations": [first_observation, second_observation],
            "transport_call_count": 4,
            "transport_attempt_count": 4,
            "transport_input_tokens": 37,
            "transport_output_tokens": 13,
            "transport_latency_ms": 20,
            "transport_token_usage_available": True,
            "transport_by_role": {
                "coordinator": {
                    "call_count": 4,
                    "attempt_count": 4,
                    "input_tokens": 37,
                    "output_tokens": 13,
                    "latency_ms": 20,
                    "token_usage_available": True,
                }
            },
        },
    )

    assert merged["transport_call_count"] == 4
    assert merged["transport_attempt_count"] == 4
    assert merged["transport_input_tokens"] == 37
    assert merged["transport_output_tokens"] == 13
    assert merged["transport_latency_ms"] == 20
    assert merged["transport_by_role"]["coordinator"]["call_count"] == 4
    assert merged["transport_by_role"]["coordinator"]["input_tokens"] == 37
    assert merged["transport_by_role"]["coordinator"]["latency_ms"] == 20
