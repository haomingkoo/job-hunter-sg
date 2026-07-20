"""Run the labelled resume-agent reference case and print span-derived metrics."""

from __future__ import annotations

import json
import secrets
import sys
import time
from pathlib import Path

from dotenv import load_dotenv


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
load_dotenv(BACKEND_DIR / ".env")

from resume_agent import session  # noqa: E402


RESUME = """Jane Tan
jane@example.com

EXPERIENCE
GovTech | AI Project Lead | Jan 2022 - Present
- Led delivery of an internal document assistant for operations teams
- Coordinated engineers, policy users, and QA reviewers across rollout
"""
TARGET_JOB = {
    "title": "AI Project Lead",
    "company": "Example Agency",
    "description": "Own document automation delivery and stakeholder rollout.",
    "terms": ["document automation", "stakeholder rollout"],
    "location": "Singapore",
    "source": "reference-benchmark",
}


def main() -> None:
    session_id = f"reference-benchmark-{secrets.token_hex(4)}"
    owner_key = f"reference-benchmark-owner-{secrets.token_hex(4)}"
    started_at = time.perf_counter()
    events = list(session.stream_chat_events({
        "session_id": session_id,
        "message": "Run a concise, evidence-backed target-job review.",
        "resume_text": RESUME,
        "job_context": TARGET_JOB,
    }, owner_key=owner_key))
    state = session.get_state(session_id, owner_key=owner_key)
    spans = state.get("tool_spans") or []
    model_spans = [span for span in spans if span.get("kind") == "llm"]
    tool_spans = [span for span in spans if span.get("kind") == "tool"]
    response = next((
        str(event.get("content") or "")
        for event in reversed(events)
        if event.get("event") == "token" and str(event.get("content") or "").strip()
    ), "")
    output = {
        "elapsed_ms": round((time.perf_counter() - started_at) * 1000),
        "terminal_event": events[-1].get("event") if events else None,
        "review_status": state.get("review_status"),
        "response": response,
        "worker_scores": (state.get("multi_agent_assessment") or {}).get("scores_by_worker"),
        "median_score": (state.get("multi_agent_assessment") or {}).get("score"),
        "judge_status": (state.get("judge_run") or {}).get("status"),
        "judge_assessment": state.get("judge_assessment"),
        "synthesis_revision": state.get("synthesis_revision"),
        "presentation_violations": state.get("presentation_violations"),
        "model_call_count": len(model_spans),
        "total_tokens": sum(
            int((span.get("result") or {}).get("total_tokens") or 0)
            for span in model_spans
        ),
        "model_spans": [
            {
                "worker": span.get("worker"),
                "phase": span.get("phase"),
                "status": span.get("status"),
                "duration_ms": span.get("duration_ms"),
                "total_tokens": (span.get("result") or {}).get("total_tokens"),
            }
            for span in model_spans
        ],
        "tool_spans": [
            {
                "worker": span.get("worker"),
                "name": span.get("name"),
                "status": span.get("status"),
                "duration_ms": span.get("duration_ms"),
            }
            for span in tool_spans
        ],
    }
    output["quality_gate_passed"] = (
        output["terminal_event"] == "done"
        and output["review_status"] == "success"
        and output["judge_status"] == "success"
        and not (output["judge_assessment"] or {}).get("requires_revision", True)
        and not output["presentation_violations"]
        and bool(output["response"].strip())
    )
    print(json.dumps(output, indent=2, ensure_ascii=False))
    if not output["quality_gate_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
