"""Merge content-free execution evidence across resumable stages."""


def merge_execution_metrics(current: dict | None, update: dict | None) -> dict:
    current = dict(current or {})
    update = dict(update or {})
    models = list(dict.fromkeys([*(current.get("models") or []), *(update.get("models") or [])]))
    return {
        "logical_run_id": str(update.get("logical_run_id") or current.get("logical_run_id") or ""),
        "trace_key": str(update.get("trace_key") or current.get("trace_key") or ""),
        "stage": str(update.get("stage") or current.get("stage") or ""),
        "model_call_count": int(current.get("model_call_count") or 0)
        + int(update.get("model_call_count") or 0),
        "checkpoint_hit_count": int(current.get("checkpoint_hit_count") or 0)
        + int(update.get("checkpoint_hit_count") or 0),
        "input_tokens": int(current.get("input_tokens") or 0) + int(update.get("input_tokens") or 0),
        "output_tokens": int(current.get("output_tokens") or 0) + int(update.get("output_tokens") or 0),
        "latency_ms": round(
            float(current.get("latency_ms") or 0) + float(update.get("latency_ms") or 0),
            3,
        ),
        "validation_codes": [
            *(current.get("validation_codes") or []),
            *(update.get("validation_codes") or []),
        ],
        "models": models,
        "attempts": [*(current.get("attempts") or []), *(update.get("attempts") or [])],
        "terminal_status": str(update.get("terminal_status") or current.get("terminal_status") or ""),
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
    })
