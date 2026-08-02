"""Run one live coordinator turn and write a full trace.

Not a test. Hits the real model and writes JSON to backend/evals/live-runs/.

The loop's main failure mode is invisible to the unit suite: a ScriptedDeepAgent
returns a terminating response by construction, so it can never reproduce a model
that will not stop. On 2026-08-02 the coordinator called read_candidate_evidence
twelve times against a profile-less thread and died on the iteration cap. Nothing
in 914 green tests could have shown that.

    PYTHONPATH=backend python backend/scripts/trace_coordinator_turn.py \
        --resume path/to/resume.txt \
        --corpus /path/to/jobs.db \
        --message "Find me roles worth applying to."

Set LANGSMITH_TRACING=true and LANGSMITH_API_KEY to also stream the run to
LangSmith, which captures the full prompt and every model call without any
instrumentation here.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(REPO_ROOT))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume", required=True, help="Path to a resume text file")
    parser.add_argument("--corpus", required=True, help="SQLite job corpus to search")
    parser.add_argument(
        "--message",
        default="Read my resume and tell me what roles I should be targeting, then find them.",
    )
    parser.add_argument("--output", default="", help="Trace JSON path")
    parser.add_argument("--max-steps-shown", type=int, default=40)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    os.environ["DATABASE_URL"] = f"sqlite:///{args.corpus}"

    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / "backend" / ".env")

    import config
    from backend.tests.test_recruitment_team_module import _role_profiler
    from database import SessionLocal, init_db
    from models import ResumeVersion, User
    from recruitment_team import DeepAgentConversationModel, RecruitmentTeam
    from recruitment_team.activity_publisher import RecordedActivityPublisher
    from recruitment_team.coordinator import model as coordinator_model
    from recruitment_team.discovery import LangChainJobDiscovery
    from recruitment_team.interface import StartThread
    from recruitment_team.telemetry import RecordedTelemetry

    trace: dict = {
        "model": config.COORDINATOR_MODEL,
        "message": args.message,
        "steps": [],
    }
    started = time.time()

    # Wrap the stream rather than the tools: this records what the graph actually
    # emitted, including calls a tool never saw because a guardrail refused them.
    original = coordinator_model.iter_progress_events

    def recording(*call_args, **call_kwargs):
        for event in original(*call_args, **call_kwargs):
            trace["steps"].append(
                {
                    "at": round(time.time() - started, 2),
                    "kind": event.get("kind"),
                    "tool": event.get("tool_name"),
                    "member": event.get("team_member"),
                    # "content", not "result". Reading the wrong key is how a
                    # trace reports None for a tool that answered properly.
                    "content": str(event.get("content") or "")[:600],
                    "args": json.dumps(event.get("args") or {})[:400],
                }
            )
            yield event

    coordinator_model.iter_progress_events = recording

    init_db()
    db = SessionLocal()
    user = User(
        email=f"trace-{int(time.time())}@example.com",
        password_hash="unused",  # pragma: allowlist secret
        name="Coordinator trace",
    )
    db.add(user)
    db.commit()
    version = ResumeVersion(
        user_id=user.id,
        label="trace resume",
        resume_text=Path(args.resume).read_text(),
        is_master=True,
    )
    db.add(version)
    db.commit()

    team = RecruitmentTeam(
        db,
        DeepAgentConversationModel(),
        LangChainJobDiscovery(),
        _role_profiler(),
        RecordedTelemetry(),
        RecordedActivityPublisher(),
    )

    try:
        receipt = team.execute(
            user.id,
            StartThread(resume_version_id=version.id, message=args.message),
            idempotency_key=f"trace-{int(started)}",
        )
        snapshot = team.snapshot(user.id, receipt.thread_id)
        trace["outcome"] = "completed"
        trace["reply"] = snapshot.messages[-1].content if snapshot.messages else ""
        # recommendations are JobSnapshot dataclasses on the snapshot and dicts
        # in case_facts JSON, so read whichever this is rather than assuming.
        trace["shortlist"] = [
            {
                "title": job.get("title") if isinstance(job, dict) else getattr(job, "title", None),
                "company": job.get("company") if isinstance(job, dict) else getattr(job, "company", None),
            }
            for job in (getattr(snapshot.case_facts, "recommendations", None) or [])
        ]
    except Exception as error:  # noqa: BLE001 - the failure is the finding
        trace["outcome"] = f"{type(error).__name__}: {error}"

    trace["duration_seconds"] = round(time.time() - started, 1)
    trace["repeated_calls"] = _repeat_counts(trace["steps"])

    destination = Path(
        args.output or REPO_ROOT / "backend" / "evals" / "live-runs" / "coordinator-turn.json"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(trace, indent=2))

    print(f"outcome  : {trace['outcome']}")
    print(f"duration : {trace['duration_seconds']}s over {len(trace['steps'])} steps")
    print(f"trace    : {destination}")
    if trace["repeated_calls"]:
        print(f"REPEATS  : {trace['repeated_calls']}")
    for step in trace["steps"][: args.max_steps_shown]:
        detail = step["args"] if step["kind"] == "tool_call" else step["content"]
        print(f"  {step['at']:>7}s {step['kind']:<12} {str(step['tool'])[:26]:<26} {detail[:80]}")
    return 0


def _repeat_counts(steps: list[dict]) -> dict[str, int]:
    """Which tools were called with identical arguments more than once."""
    seen: dict[tuple[str, str], int] = {}
    for step in steps:
        if step["kind"] != "tool_call":
            continue
        key = (str(step["tool"]), step["args"])
        seen[key] = seen.get(key, 0) + 1
    return {f"{tool}{args}": count for (tool, args), count in seen.items() if count > 1}


if __name__ == "__main__":
    raise SystemExit(main())
