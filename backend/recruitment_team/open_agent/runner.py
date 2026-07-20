"""Open-ended orchestrator over the target-assessment tool set, with a
mandatory independent judge as the one non-optional step regardless of the
reasoning path the orchestrator took to get there, and real-time progress
reporting built on Task 9's verified streaming mechanism."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from types import SimpleNamespace
from typing import Iterator

from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.errors import GraphRecursionError

import config
from resume_agent.agent import create_resume_agent
from resume_agent.tools import search_jobs

from ..assessment_contracts import (
    JUDGE_TOOL,
    SPECIALIST_TOOL,
    TargetAssessmentProgress,
    TargetAssessmentRequest,
    TargetAssessmentResult,
    TargetAssessmentUpdate,
    invoke_structured,
    target_assessment_execution_policy,
)
from ..persona_packs import PersonaPackRegistry, load_persona_pack_registry
from ..telemetry import OpenTelemetryRecorder, RecruitmentTelemetry
from . import context
from .guardrails import has_repeated_call
from .streaming import iter_progress_events
from .subagents import create_target_persona_subagents
from .tools import ask_candidate, propose_resume_edit, read_candidate_evidence, read_target_job


@tool
def guarded_search_jobs(query: str, n: int | None = None, detail: bool = False) -> dict:
    """Search the current internal Singapore job corpus by role or responsibility.

    Same contract as the underlying search_jobs tool; rejects a materially
    identical repeat within this run instead of re-querying.
    """
    args = {"query": query, "n": n, "detail": detail}
    history = context.tool_call_history()
    if history is not None and has_repeated_call(history, "search_jobs", args):
        return {
            "ok": False,
            "failure_type": "validation",
            "reason": "identical_call_no_new_information",
        }
    result = search_jobs.invoke(args)
    if history is not None:
        history.append(SimpleNamespace(tool_calls=[{"name": "search_jobs", "args": args}]))
    return result


class OpenAgentTargetAssessmentRunner:
    """Open-ended replacement for NativeTargetAssessmentRunner."""

    def __init__(
        self,
        model_factory=None,
        judge_model_factory=None,
        telemetry: RecruitmentTelemetry | None = None,
        persona_registry: PersonaPackRegistry | None = None,
    ):
        if model_factory is None:
            from resume_agent.models import create_agent_model

            model_factory = lambda: create_agent_model(
                timeout=config.RECRUITMENT_MODEL_HTTP_TIMEOUT_SECONDS,
                max_retries=config.RECRUITMENT_MODEL_TRANSPORT_RETRIES,
            )
        self._model_factory = model_factory
        self._judge_model_factory = judge_model_factory or model_factory
        self._telemetry = telemetry or OpenTelemetryRecorder()
        self._registry = persona_registry or load_persona_pack_registry()

    def run(self, request: TargetAssessmentRequest) -> Iterator[TargetAssessmentUpdate]:
        yield TargetAssessmentProgress(
            team_member="coordinator", status="running", summary="Open-agent run started.", detail={}
        )

        orchestrator_model = self._model_factory()
        persona_subagents = create_target_persona_subagents(self._registry, orchestrator_model)
        agent = create_resume_agent(
            model=orchestrator_model,
            tools=[read_candidate_evidence, read_target_job, guarded_search_jobs, propose_resume_edit, ask_candidate],
            subagents=persona_subagents,
            checkpointer=MemorySaver(),
            interrupt_on={"ask_candidate": True},
        )
        payload = {"messages": [{
            "role": "user",
            "content": (
                "Assess this candidate against the target job. Consult whichever "
                "personas you judge useful, however many times you judge useful. "
                "Propose resume edits only where you have real evidence or an answer "
                "the candidate gave you. Ask the candidate directly if you hit a real "
                "evidence gap."
            ),
        }]}
        run_config = {
            "recursion_limit": config.AGENT_MAX_TOOL_ITERATIONS,
            "configurable": {"thread_id": str(uuid.uuid4())},
        }

        specialist_runs: list[dict] = []
        synthesis = ""
        pending_question: str | None = None
        with context.assessment_context(request):
            try:
                for event in iter_progress_events(agent, payload, run_config):
                    if event["kind"] == "tool_call":
                        if event["tool_name"] == ask_candidate.name:
                            pending_question = (event.get("args") or {}).get("question")
                        yield TargetAssessmentProgress(
                            team_member=event["team_member"],
                            status="running",
                            summary=f"{event['team_member']} called {event['tool_name']}.",
                            detail={"tool_name": event["tool_name"]},
                        )
                    elif (
                        event["kind"] == "tool_result"
                        and event["team_member"] != "coordinator"
                        and event["tool_name"] == SPECIALIST_TOOL.name
                    ):
                        submission = self._parse_specialist_submission(event["content"])
                        if submission is not None:
                            specialist_runs.append(
                                {"persona_id": event["team_member"], "status": "completed", "submission": submission}
                            )
                            yield TargetAssessmentProgress(
                                team_member=event["team_member"],
                                status="completed",
                                summary=f"{event['team_member']} submitted its assessment.",
                                detail={},
                            )
                    elif event["kind"] == "message" and event["team_member"] == "coordinator":
                        synthesis = str(event["content"])
            except GraphRecursionError:
                # The orchestrator hit its recursion_limit before reaching a
                # natural stopping point. Per the design spec's "Mandatory
                # final judge" section, whatever specialist_runs/synthesis
                # were accumulated so far must still go through the judge
                # rather than being discarded -- so just stop consuming
                # events and fall through to the same judge-calling path a
                # normal completion takes.
                pass
            edits = context.proposed_edits() or []

            # iter_progress_events (Task 9) only forwards dict-shaped node
            # updates (see streaming.py's `isinstance(node_update, dict)`
            # check), so the raw `{"__interrupt__": (...)}` chunk LangGraph
            # emits when the HumanInTheLoopMiddleware pauses the graph is
            # silently dropped -- the stream loop above just ends with no
            # explicit signal. Confirmed empirically (see
            # tests/test_open_agent_runner.py's interrupt test): with a
            # checkpointer + thread_id wired, agent.get_state(run_config)
            # after the loop still exposes the pending interrupt via
            # `state.interrupts`, because the checkpointer persisted it.
            if agent.get_state(run_config).interrupts:
                yield TargetAssessmentProgress(
                    team_member="coordinator",
                    status="paused",
                    summary="Run paused: waiting on the candidate to answer a question.",
                    detail={"question": pending_question},
                )
                return

        judge_model = self._judge_model_factory()
        judge = self._run_judge(judge_model, request, specialist_runs, synthesis)
        status = "completed" if judge["disposition"] == "pass" else "quality_blocked"

        yield TargetAssessmentResult(
            status=status,
            specialist_runs=tuple(specialist_runs),
            synthesis=synthesis,
            judge=judge,
            correction=None,
            error=None,
            execution_policy=target_assessment_execution_policy(),
            proposed_edits=tuple(edits),
        )

    @staticmethod
    def _parse_specialist_submission(content) -> dict | None:
        if isinstance(content, dict):
            return content
        if not isinstance(content, str):
            return None
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return None

    def _run_judge(self, model, request: TargetAssessmentRequest, specialist_runs: list[dict], synthesis: str) -> dict:
        from ..prompts.target_assessment import TARGET_JUDGE_SYSTEM_PROMPT

        data = {
            "target_job": asdict(request.target_job),
            "role_success_profile": asdict(request.role_profile),
            "specialist_runs": specialist_runs,
            "synthesis": synthesis,
        }
        payload, failure, input_tokens, output_tokens, model_name = invoke_structured(
            model,
            JUDGE_TOOL,
            TARGET_JUDGE_SYSTEM_PROMPT,
            "open_agent_judge_data",
            data,
            telemetry=self._telemetry,
            operation="open_agent_assessment.judge_attempt",
            attempt=1,
            max_attempts=1,
            attributes={"trace_key": request.trace_key},
        )
        if payload is None:
            return {
                "disposition": "block",
                "strengths": [], "weaknesses": [f"Judge call failed: {failure}"],
                "deductions": [], "evidence_gaps": [], "score": 0, "score_reason": failure,
                "confidence": 0, "confidence_reason": failure,
                "rubric_scores": {"evidence_grounding": 0, "role_coverage": 0, "decision_usefulness": 0, "fairness_and_boundaries": 0},
            }
        return {**payload, "model_name": model_name, "input_tokens": input_tokens, "output_tokens": output_tokens}
