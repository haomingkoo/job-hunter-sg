from __future__ import annotations

import json


def _report(path, *, model, status="completed", duration=10.0):
    path.write_text(
        json.dumps(
            {
                "status": status,
                "parse_report": {"document_block_count": 4, "parse_quality": {"label": "good"}},
                "execution_policy": {"transport_retries": 0},
                "run": {"model_name": model, "model_call_count": 1, "input_tokens": 10, "output_tokens": 5},
                "error": None,
                "checkpoint": {"completed_scope_ids": ["summary_01"]},
                "spans": [
                    {"name": "candidate_profile.model_attempt", "duration_ms": duration, "attributes": {}},
                    {"name": "candidate_profile.validation", "attributes": {"validation_code": ""}},
                ],
            }
        ),
        encoding="utf-8",
    )


def test_comparison_records_model_latency_tokens_and_completion(tmp_path, capsys):
    from scripts.compare_candidate_profile_canaries import main

    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    output = tmp_path / "comparison.json"
    _report(first, model="model-a", duration=11.0)
    _report(second, model="model-b", duration=22.0)

    result = main([
        "--report", f"agent={first}",
        "--report", f"instruct={second}",
        "--output", str(output),
    ])

    comparison = json.loads(output.read_text(encoding="utf-8"))
    assert result == 0
    assert comparison["all_completed"] is True
    assert comparison["same_execution_policy"] is True
    assert [item["model_name"] for item in comparison["candidates"]] == ["model-a", "model-b"]
    assert comparison["candidates"][1]["model_attempt_duration_ms"] == [22.0]
    assert "all_completed" in capsys.readouterr().out
