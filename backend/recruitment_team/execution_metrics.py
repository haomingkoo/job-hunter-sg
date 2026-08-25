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


def merge_execution_metrics(current: dict | None, update: dict | None) -> dict:
    current = dict(current or {})
    update = dict(update or {})
    attempts = _merge_attempts(current, update)
    semantic_outcomes = _merge_semantic_outcomes(current, update)
    attempts_are_identifiable = bool(attempts) and all(item.get("attempt_id") for item in attempts)
    models = list(dict.fromkeys([*(current.get("models") or []), *(update.get("models") or [])]))
    transport_by_role: dict[str, dict] = {}
    for source in (current.get("transport_by_role") or {}, update.get("transport_by_role") or {}):
        for role, values in source.items():
            totals = transport_by_role.setdefault(
                str(role),
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
            for key in (
                "call_count",
                "attempt_count",
                "retry_count",
                "error_count",
                "input_tokens",
                "output_tokens",
            ):
                totals[key] += int((values or {}).get(key) or 0)
            totals["latency_ms"] = round(
                float(totals["latency_ms"])
                + float((values or {}).get("latency_ms") or 0),
                3,
            )
            totals["models"] = list(dict.fromkeys([
                *totals["models"],
                *((values or {}).get("models") or []),
            ]))
            if int((values or {}).get("call_count") or 0) > 0:
                totals["token_usage_available"] = bool(
                    totals["token_usage_available"]
                    and (values or {}).get("token_usage_available") is True
                )
    transport_sources = [
        source
        for source in (current, update)
        if int(source.get("transport_call_count") or 0) > 0
    ]
    return {
        "logical_run_id": str(current.get("logical_run_id") or update.get("logical_run_id") or ""),
        "trace_key": str(current.get("trace_key") or update.get("trace_key") or ""),
        "command_run_id": str(update.get("command_run_id") or current.get("command_run_id") or ""),
        "command_trace_key": str(
            update.get("command_trace_key") or current.get("command_trace_key") or ""
        ),
        "stage": str(update.get("stage") or current.get("stage") or ""),
        "model_call_count": (
            sum(int(item.get("attempt_count") or 1) for item in attempts)
            if attempts_are_identifiable
            else int(current.get("model_call_count") or 0) + int(update.get("model_call_count") or 0)
        ),
        "checkpoint_hit_count": int(current.get("checkpoint_hit_count") or 0)
        + int(update.get("checkpoint_hit_count") or 0),
        "input_tokens": (
            sum(int(item.get("input_tokens") or 0) for item in attempts)
            if attempts_are_identifiable
            else int(current.get("input_tokens") or 0) + int(update.get("input_tokens") or 0)
        ),
        "output_tokens": (
            sum(int(item.get("output_tokens") or 0) for item in attempts)
            if attempts_are_identifiable
            else int(current.get("output_tokens") or 0) + int(update.get("output_tokens") or 0)
        ),
        "latency_ms": round(
            float(current.get("latency_ms") or 0) + float(update.get("latency_ms") or 0),
            3,
        ),
        "validation_codes": [
            *(current.get("validation_codes") or []),
            *(update.get("validation_codes") or []),
        ],
        "models": models,
        "attempts": attempts,
        "semantic_outcomes": semantic_outcomes,
        "semantic_by_role": summarize_semantic_outcomes(semantic_outcomes),
        "terminal_status": str(update.get("terminal_status") or current.get("terminal_status") or ""),
        "transport_call_count": int(current.get("transport_call_count") or 0)
        + int(update.get("transport_call_count") or 0),
        "transport_attempt_count": int(current.get("transport_attempt_count") or 0)
        + int(update.get("transport_attempt_count") or 0),
        "transport_retry_count": int(current.get("transport_retry_count") or 0)
        + int(update.get("transport_retry_count") or 0),
        "transport_error_count": int(current.get("transport_error_count") or 0)
        + int(update.get("transport_error_count") or 0),
        "transport_token_usage_available": bool(transport_sources) and all(
            source.get("transport_token_usage_available") is True
            for source in transport_sources
        ),
        "transport_latency_ms": round(
            float(current.get("transport_latency_ms") or 0)
            + float(update.get("transport_latency_ms") or 0),
            3,
        ),
        "transport_models": list(dict.fromkeys([
            *(current.get("transport_models") or []),
            *(update.get("transport_models") or []),
        ])),
        "transport_by_role": transport_by_role,
    }


def merge_execution_event(current: dict | None, event: dict) -> dict:
    validation_code = str(event.get("validation_code") or "")
    model = str(event.get("model") or "")
    return merge_execution_metrics(current, {
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
        "transport_call_count": event.get("transport_call_count") or 0,
        "transport_attempt_count": event.get("transport_attempt_count") or 0,
        "transport_retry_count": event.get("transport_retry_count") or 0,
        "transport_error_count": event.get("transport_error_count") or 0,
        "transport_token_usage_available": event.get(
            "transport_token_usage_available"
        ) is True,
        "transport_latency_ms": event.get("transport_latency_ms") or 0,
        "transport_models": event.get("transport_models") or [],
        "transport_by_role": event.get("transport_by_role") or {},
    })
