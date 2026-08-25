"""Merge content-free execution evidence across resumable stages."""


def _merge_attempts(current: dict, update: dict) -> list[dict]:
    merged: list[dict] = []
    seen_ids: set[str] = set()
    for attempt in [
        *(current.get("attempts") or []),
        *(current.get("nested_model_attempts") or []),
        *(update.get("attempts") or []),
        *(update.get("nested_model_attempts") or []),
    ]:
        attempt = dict(attempt or {})
        attempt_id = str(attempt.get("attempt_id") or "")
        if attempt_id and attempt_id in seen_ids:
            continue
        if attempt_id:
            seen_ids.add(attempt_id)
        merged.append(attempt)
    return merged


def _merge_semantic_outcomes(current: dict, update: dict) -> list[dict]:
    merged: list[dict] = []
    seen_ids: set[str] = set()
    for outcome in [
        *(current.get("semantic_outcomes") or []),
        *(update.get("semantic_outcomes") or []),
    ]:
        outcome = dict(outcome or {})
        outcome_id = str(outcome.get("outcome_id") or "")
        if outcome_id and outcome_id in seen_ids:
            continue
        if outcome_id:
            seen_ids.add(outcome_id)
        merged.append(outcome)
    return merged


def summarize_semantic_outcomes(outcomes: list[dict]) -> dict[str, dict[str, int]]:
    """Count content-free contract outcomes by the role that submitted them."""
    by_role: dict[str, dict[str, int]] = {}
    for outcome in outcomes:
        role = str(outcome.get("role") or "")
        if not role:
            continue
        totals = by_role.setdefault(
            role,
            {
                "submission_count": 0,
                "accepted_count": 0,
                "rejected_count": 0,
                "correction_attempt_count": 0,
            },
        )
        totals["submission_count"] += 1
        if outcome.get("accepted") is True:
            totals["accepted_count"] += 1
        else:
            totals["rejected_count"] += 1
        if int(outcome.get("submission_attempt") or 1) > 1:
            totals["correction_attempt_count"] += 1
    return by_role


def _merged_reported_total(
    sources: tuple[dict, dict],
    attempts: list[dict],
    *,
    reported_key: str,
    legacy_key: str,
    attempt_key: str,
    overlapping_observations: bool,
) -> int:
    """Merge attempt-backed totals while retaining unattributed legacy scalars."""
    if not attempts or not all(item.get("attempt_id") for item in attempts):
        return sum(int(source.get(reported_key, source.get(legacy_key, 0)) or 0) for source in sources)

    def attempt_value(item: dict) -> int:
        if attempt_key != "attempt_count":
            return int(item.get(attempt_key) or 0)
        explicit = item.get(attempt_key)
        if explicit is not None:
            return int(explicit or 0)
        return int(item.get("event") in (None, "model_attempt"))

    total = sum(attempt_value(item) for item in attempts)
    residuals = []
    for source in sources:
        source_attempts = _merge_attempts({}, source)
        source_attempt_total = sum(attempt_value(item) for item in source_attempts)
        source_reported_total = int(source.get(reported_key, source.get(legacy_key, 0)) or 0)
        residuals.append(max(0, source_reported_total - source_attempt_total))
    return total + (max(residuals, default=0) if overlapping_observations else sum(residuals))


def _execution_observation_ids(metrics: dict) -> list[str]:
    ids = [str(value) for value in metrics.get("execution_observation_ids") or [] if value]
    command_id = str(metrics.get("command_run_id") or metrics.get("command_trace_key") or "")
    if command_id and command_id not in ids:
        ids.append(command_id)
    if not command_id:
        for attempt in [
            *(metrics.get("attempts") or []),
            *(metrics.get("nested_model_attempts") or []),
        ]:
            attempt_id = str((attempt or {}).get("attempt_id") or "")
            observation_id = f"attempt:{attempt_id}" if attempt_id else ""
            if observation_id and observation_id not in ids:
                ids.append(observation_id)
    return ids


def _merge_transport_observations(current: dict, update: dict) -> list[dict]:
    merged: list[dict] = []
    seen: set[str] = set()
    for item in [
        *(current.get("transport_observations") or []),
        *(update.get("transport_observations") or []),
    ]:
        observation = dict(item or {})
        observation_id = str(observation.get("observation_id") or "")
        if not observation_id or observation_id in seen:
            continue
        seen.add(observation_id)
        merged.append(observation)
    return merged


def _transport_observation_ids(metrics: dict) -> set[str]:
    return {
        str(item.get("observation_id"))
        for item in metrics.get("transport_observations") or []
        if (item or {}).get("observation_id")
    }


def _transport_from_observations(observations: list[dict]) -> dict:
    by_role: dict[str, dict] = {}
    for observation in observations:
        role = str(observation.get("role") or "unclassified")
        totals = by_role.setdefault(
            role,
            {
                "call_count": 0,
                "attempt_count": 0,
                "retry_count": 0,
                "error_count": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "token_usage_available": True,
                "latency_ms": 0.0,
                "models": [],
            },
        )
        attempts = int(observation.get("attempts") or 0)
        totals["call_count"] += 1
        totals["attempt_count"] += attempts
        totals["retry_count"] += max(0, attempts - 1)
        totals["error_count"] += int(observation.get("outcome") == "error")
        totals["input_tokens"] += int(observation.get("input_tokens") or 0)
        totals["output_tokens"] += int(observation.get("output_tokens") or 0)
        totals["token_usage_available"] = bool(
            totals["token_usage_available"]
            and observation.get("token_usage_available") is True
        )
        totals["latency_ms"] += float(observation.get("latency_ms") or 0)
        model = str(observation.get("model") or "")
        if model and model not in totals["models"]:
            totals["models"].append(model)
    for totals in by_role.values():
        totals["latency_ms"] = round(float(totals["latency_ms"]), 3)
    return {
        "transport_call_count": len(observations),
        "transport_attempt_count": sum(int(item.get("attempts") or 0) for item in observations),
        "transport_retry_count": sum(max(0, int(item.get("attempts") or 0) - 1) for item in observations),
        "transport_error_count": sum(item.get("outcome") == "error" for item in observations),
        "transport_input_tokens": sum(int(item.get("input_tokens") or 0) for item in observations),
        "transport_output_tokens": sum(int(item.get("output_tokens") or 0) for item in observations),
        "transport_token_usage_available": bool(observations)
        and all(item.get("token_usage_available") is True for item in observations),
        "transport_latency_ms": round(
            sum(float(item.get("latency_ms") or 0) for item in observations),
            3,
        ),
        "transport_models": list(
            dict.fromkeys(str(item.get("model") or "") for item in observations if item.get("model"))
        ),
        "transport_by_role": by_role,
    }


_TRANSPORT_TOTAL_KEYS = (
    "transport_call_count",
    "transport_attempt_count",
    "transport_retry_count",
    "transport_error_count",
    "transport_input_tokens",
    "transport_output_tokens",
)
_ROLE_TOTAL_KEYS = (
    "call_count",
    "attempt_count",
    "retry_count",
    "error_count",
    "input_tokens",
    "output_tokens",
)


def _merge_transport_metrics(
    current: dict,
    update: dict,
    residual_sources: tuple[dict, dict],
    overlapping_observations: bool,
) -> dict:
    transport_keys = {
        *_TRANSPORT_TOTAL_KEYS,
        "transport_token_usage_available",
        "transport_latency_ms",
        "transport_models",
        "transport_by_role",
        "transport_observations",
    }
    if not any(transport_keys.intersection(source) for source in (current, update)):
        return {}

    observations = _merge_transport_observations(current, update)
    totals = _transport_from_observations(observations)
    availability = [
        all(item.get("token_usage_available") is True for item in observations)
    ] if observations else []
    maximum_residuals: dict[str, float] = {}
    maximum_role_residuals: dict[tuple[str, str], float] = {}

    def residual_increment(key: str, value: float) -> float:
        if not overlapping_observations:
            return value
        previous = maximum_residuals.get(key, 0.0)
        maximum_residuals[key] = max(previous, value)
        return max(0.0, value - previous)

    def role_residual_increment(role: str, key: str, value: float) -> float:
        if not overlapping_observations:
            return value
        identity = (role, key)
        previous = maximum_role_residuals.get(identity, 0.0)
        maximum_role_residuals[identity] = max(previous, value)
        return max(0.0, value - previous)

    for source in residual_sources:
        source_observations = [dict(item or {}) for item in source.get("transport_observations") or []]
        represented = _transport_from_observations(source_observations)
        for key in _TRANSPORT_TOTAL_KEYS:
            residual = max(0, int(source.get(key) or 0) - int(represented.get(key) or 0))
            totals[key] += int(residual_increment(key, residual))
        residual_latency = max(
            0.0,
            float(source.get("transport_latency_ms") or 0)
            - float(represented.get("transport_latency_ms") or 0),
        )
        totals["transport_latency_ms"] = round(
            float(totals["transport_latency_ms"])
            + residual_increment("transport_latency_ms", residual_latency),
            3,
        )
        residual_calls = max(
            0,
            int(source.get("transport_call_count") or 0)
            - int(represented.get("transport_call_count") or 0),
        )
        if residual_calls:
            availability.append(source.get("transport_token_usage_available") is True)
        totals["transport_models"] = list(
            dict.fromkeys([*totals["transport_models"], *(source.get("transport_models") or [])])
        )

        represented_roles = represented.get("transport_by_role") or {}
        for role, values in (source.get("transport_by_role") or {}).items():
            role = str(role)
            role_totals = totals["transport_by_role"].setdefault(
                role,
                {
                    "call_count": 0,
                    "attempt_count": 0,
                    "retry_count": 0,
                    "error_count": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "token_usage_available": True,
                    "latency_ms": 0.0,
                    "models": [],
                },
            )
            represented_role = represented_roles.get(role) or {}
            for key in _ROLE_TOTAL_KEYS:
                residual = max(
                    0,
                    int((values or {}).get(key) or 0)
                    - int(represented_role.get(key) or 0),
                )
                role_totals[key] += int(role_residual_increment(role, key, residual))
            residual_role_calls = max(
                0,
                int((values or {}).get("call_count") or 0)
                - int(represented_role.get("call_count") or 0),
            )
            if residual_role_calls:
                role_totals["token_usage_available"] = bool(
                    role_totals["token_usage_available"]
                    and (values or {}).get("token_usage_available") is True
                )
            role_totals["latency_ms"] = round(
                float(role_totals["latency_ms"])
                + role_residual_increment(
                    role,
                    "latency_ms",
                    max(
                        0.0,
                        float((values or {}).get("latency_ms") or 0)
                        - float(represented_role.get("latency_ms") or 0),
                    ),
                ),
                3,
            )
            role_totals["models"] = list(
                dict.fromkeys([*role_totals["models"], *((values or {}).get("models") or [])])
            )

    totals["transport_token_usage_available"] = bool(availability) and all(availability)
    totals["transport_observations"] = observations
    return totals


def merge_execution_metrics(current: dict | None, update: dict | None) -> dict:
    current = dict(current or {})
    update = dict(update or {})
    current_observation_ids = _execution_observation_ids(current)
    update_observation_ids = _execution_observation_ids(update)
    overlapping_observations = bool(
        set(current_observation_ids).intersection(update_observation_ids)
    )
    overlapping_transport_observations = bool(
        _transport_observation_ids(current).intersection(
            _transport_observation_ids(update)
        )
    )
    replayed_update = bool(update_observation_ids) and all(
        observation_id in current_observation_ids
        for observation_id in update_observation_ids
    )
    effective_update = {} if replayed_update else update
    attempts = _merge_attempts(current, effective_update)
    semantic_outcomes = _merge_semantic_outcomes(current, effective_update)
    residual_sources = (current, {} if replayed_update else update)
    execution_observation_ids = list(
        dict.fromkeys([*current_observation_ids, *update_observation_ids])
    )
    models = list(dict.fromkeys([*(current.get("models") or []), *(update.get("models") or [])]))
    reported_model_call_count = _merged_reported_total(
        residual_sources,
        attempts,
        reported_key="reported_model_call_count",
        legacy_key="model_call_count",
        attempt_key="attempt_count",
        overlapping_observations=overlapping_observations,
    )
    reported_input_tokens = _merged_reported_total(
        residual_sources,
        attempts,
        reported_key="reported_input_tokens",
        legacy_key="input_tokens",
        attempt_key="input_tokens",
        overlapping_observations=overlapping_observations,
    )
    reported_output_tokens = _merged_reported_total(
        residual_sources,
        attempts,
        reported_key="reported_output_tokens",
        legacy_key="output_tokens",
        attempt_key="output_tokens",
        overlapping_observations=overlapping_observations,
    )
    transport_metrics = _merge_transport_metrics(
        current,
        update,
        residual_sources,
        overlapping_transport_observations,
    )
    expose_separate_observations = any(
        any(
            key in source
            for key in (
                "reported_model_call_count",
                "reported_input_tokens",
                "reported_output_tokens",
                "transport_input_tokens",
                "transport_output_tokens",
            )
        )
        for source in (current, update)
    )
    return {
        "logical_run_id": str(current.get("logical_run_id") or update.get("logical_run_id") or ""),
        "trace_key": str(current.get("trace_key") or update.get("trace_key") or ""),
        "command_run_id": str(update.get("command_run_id") or current.get("command_run_id") or ""),
        "command_trace_key": str(update.get("command_trace_key") or current.get("command_trace_key") or ""),
        "execution_observation_ids": execution_observation_ids,
        "stage": str(update.get("stage") or current.get("stage") or ""),
        "model_call_count": reported_model_call_count,
        "checkpoint_hit_count": (
            max(
                int(current.get("checkpoint_hit_count") or 0),
                int(update.get("checkpoint_hit_count") or 0),
            )
            if overlapping_observations
            else int(current.get("checkpoint_hit_count") or 0)
            + (0 if replayed_update else int(update.get("checkpoint_hit_count") or 0))
        ),
        "input_tokens": reported_input_tokens,
        "output_tokens": reported_output_tokens,
        "latency_ms": round(
            max(
                float(current.get("latency_ms") or 0),
                float(update.get("latency_ms") or 0),
            )
            if overlapping_observations
            else float(current.get("latency_ms") or 0)
            + (0 if replayed_update else float(update.get("latency_ms") or 0)),
            3,
        ),
        "validation_codes": list(
            dict.fromkeys(
                [
                    *(current.get("validation_codes") or []),
                    *(update.get("validation_codes") or []),
                ]
            )
        ),
        "models": models,
        "attempts": attempts,
        "semantic_outcomes": semantic_outcomes,
        "semantic_by_role": summarize_semantic_outcomes(semantic_outcomes),
        "terminal_status": str(update.get("terminal_status") or current.get("terminal_status") or ""),
        **transport_metrics,
        **(
            {
                "reported_model_call_count": reported_model_call_count,
                "reported_input_tokens": reported_input_tokens,
                "reported_output_tokens": reported_output_tokens,
                **(
                    {
                        "transport_input_tokens": transport_metrics["transport_input_tokens"],
                        "transport_output_tokens": transport_metrics["transport_output_tokens"],
                    }
                    if transport_metrics
                    else {}
                ),
            }
            if expose_separate_observations
            else {}
        ),
    }


def merge_execution_event(current: dict | None, event: dict) -> dict:
    validation_code = str(event.get("validation_code") or "")
    model = str(event.get("model") or "")
    metrics = {
        "logical_run_id": event.get("logical_run_id"),
        "stage": "candidate_profile",
        "model_call_count": 1 if event.get("event") == "model_attempt" else 0,
        "checkpoint_hit_count": 1 if event.get("event") == "checkpoint_hit" else 0,
        "input_tokens": event.get("input_tokens") or 0,
        "output_tokens": event.get("output_tokens") or 0,
        "latency_ms": event.get("latency_ms") or 0,
        "validation_codes": [validation_code] if validation_code else [],
        "models": [model] if model else [],
        "attempts": [event],
        "terminal_status": event.get("status") or "",
    }
    for key in (
        "transport_observations",
        "transport_call_count",
        "transport_attempt_count",
        "transport_retry_count",
        "transport_error_count",
        "transport_token_usage_available",
        "transport_latency_ms",
        "transport_models",
        "transport_by_role",
    ):
        if key in event:
            metrics[key] = event[key]
    return merge_execution_metrics(current, metrics)
