"""Conversational coordinator with structured replies and resumable pauses."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import replace
from typing import Any

from langchain.agents.structured_output import ToolStrategy
from langchain_core.messages import HumanMessage, convert_to_messages
from langgraph.errors import GraphRecursionError
from langgraph.types import Command

import config
from prompt_safety import xml_data_block

from ..conversation_model import ConversationReply, ModelReply
from ..errors import ConversationUnavailable, InvalidCommand
from ..fair_hiring import mentions_protected_status
from ..interface import Message, PreferenceFact
from ..open_agent import context as open_agent_context
from ..open_agent.streaming import format_questions, iter_progress_events, rejected_tool_result
from ..open_agent.tools import (
    ask_candidate,
    propose_resume_edit,
    read_candidate_evidence,
    read_shortlist,
    read_target_job,
    search_jobs,
    write_plan,
    write_shortlist,
)
from ..prompts import COORDINATOR_PROMPT_VERSION, COORDINATOR_SYSTEM_PROMPT
from ..model_transport_observer import create_observed_agent_model
from ..provider_compatibility import provider_message_compatibility, require_tool_call
from ..recovery import classify_failure
from ..telemetry import OpenTelemetryRecorder, RecruitmentTelemetry
from ..tool_call_guard import ToolCallGuardMiddleware
from .context import ConversationContext


REPLY_TOOL_NAME = ConversationReply.__name__

_QUESTION_LIMIT_SENTENCE = (
    "[System: you have reached this conversation's question limit. Do not call "
    "ask_candidate again. Answer now with the evidence you already have.]"
)


def _latest_user_message(messages: list[Message]) -> str:
    return next(
        (message.content for message in reversed(messages) if message.role == "user"),
        "",
    )


def _pending_ask_call_id(state) -> str | None:
    """The id of the `ask_candidate` call the graph is paused on.

    Read off the checkpoint rather than carried on `case_facts`: the pause and
    its call id live in the same durable place, so they cannot go out of sync.
    """
    for message in reversed(state.values.get("messages") or []):
        for call in getattr(message, "tool_calls", None) or []:
            if call.get("name") == ask_candidate.name:
                return call.get("id")
    return None


def _ask_rounds_so_far(state) -> int:
    return sum(
        1
        for message in state.values.get("messages") or []
        for call in (getattr(message, "tool_calls", None) or [])
        if call.get("name") == ask_candidate.name
    )


def _delete_terminal_checkpoint(run_config: dict) -> bool:
    """Delete a terminal coordinator checkpoint and report whether it is gone."""
    thread_id = str(run_config.get("configurable", {}).get("thread_id") or "")
    if not thread_id:
        return True
    try:
        from ..open_agent.checkpoint_store import delete_checkpoint

        delete_checkpoint(thread_id)
    except Exception:
        return False
    return True


def _model_name(state) -> str:
    for message in reversed(state.values.get("messages") or []):
        name = (getattr(message, "response_metadata", None) or {}).get("model_name")
        if name:
            return str(name)
    return "coordinator-deep-agent"


def _unsubmitted_text_for_validation(state) -> str:
    """Read rejected model prose only to classify a safe terminal failure."""
    for message in reversed(state.values.get("messages") or []):
        if getattr(message, "type", "") != "ai":
            continue
        content = getattr(message, "content", "")
        return content if isinstance(content, str) else ""
    return ""


def _resume_edit_reply(edits: list[dict], reply: ConversationReply) -> str:
    count = len(edits)
    if count:
        noun = "edit is" if count == 1 else "edits are"
        paragraphs = [f"{count} evidence-supported resume {noun} pending below for your approval."]
    else:
        paragraphs = [
            "No resume edit became pending. The attempted rewrites did not stay within your confirmed evidence."
        ]
    # Accepted tool results own edit state. Keep the model's useful explanation,
    # but suppress any paragraph in which it tries to narrate pending, accepted,
    # or rejected edit state itself.
    paragraphs.extend(
        paragraph.strip()
        for paragraph in re.split(r"\n\s*\n", reply.reply.strip())
        if paragraph.strip()
        and not (
            re.search(r"\b(?:edit|edits|rewrite|rewrites|draft|drafts)\b", paragraph, re.I)
            and re.search(r"\b(?:pending|accepted|rejected)\b", paragraph, re.I)
        )
    )
    assumptions = [item.strip() for item in reply.assumptions if item.strip()]
    missing = [item.strip() for item in reply.missing_information if item.strip()]
    if assumptions:
        paragraphs.append(f"Assumptions, not resume claims: {'; '.join(assumptions)}.")
    if missing:
        paragraphs.append(f"Missing or unverified: {'; '.join(missing)}.")
    question = reply.follow_up_question.strip()
    if question:
        paragraphs.append(question)
    return "\n\n".join(paragraphs)


def _has_job_result_evidence(context: ConversationContext) -> bool:
    if context.search_results:
        return any(result.jobs for result in context.search_results)
    return bool(context.recommendations or context.shortlisted_jobs)


_TOOL_CLAIM_RULES = (
    (
        re.compile(
            r"\b(?:found|identified|located|returned)\b.{0,30}"
            r"\b(?:match(?:es)?|roles?|jobs?|postings?)\b",
            re.I,
        ),
        "search_jobs",
        _has_job_result_evidence,
    ),
    (
        re.compile(
            r"\bthere (?:are|is)\s+(?!(?:no|not|zero)\b).{0,35}"
            r"\b(?:match(?:es)?|roles?|jobs?|postings?)\b"
            r"|\b(?:one|two|three|four|five|six|seven|eight|nine|ten|\d+|"
            r"some|several|multiple)\s+.{0,25}\b(?:match(?:es)?|roles?|jobs?|postings?)\b"
            r".{0,25}\b(?:available|ready|found|identified|located|returned)\b",
            re.I,
        ),
        "search_jobs",
        _has_job_result_evidence,
    ),
    (re.compile(r"\b(?:searched|ran (?:a )?search)\b", re.I), "search_jobs", lambda c: bool(c.search_results)),
    (
        re.compile(r"\b(?:shortlisted|added .{0,40} to (?:the |your )?shortlist|published .{0,20}shortlist)\b", re.I),
        "write_shortlist",
        lambda c: bool(c.drafted_matches),
    ),
    (
        re.compile(r"\b(?:created|updated|wrote) .{0,30}\bplan\b", re.I),
        "write_plan",
        lambda c: bool(c.drafted_plan),
    ),
    (
        re.compile(r"\b(?:rewrote|edited|updated) .{0,40}\b(?:resume|bullet)\b", re.I),
        "propose_resume_edit",
        lambda c: bool(c.proposed_edits),
    ),
)


def _unverified_tool_claim(content: str, context: ConversationContext) -> str:
    """Return the named tool when prose claims work absent from its result sink."""
    return next(
        (
            tool_name
            for pattern, tool_name, evidence in _TOOL_CLAIM_RULES
            if pattern.search(content) and not evidence(context)
        ),
        "",
    )


def _thread_state_block(context: ConversationContext, preferences: tuple[PreferenceFact, ...]) -> str:
    """Serialize thread state without duplicating posting content."""
    state = {
        "recommendation_count": len(context.recommendations),
        "shortlisted_count": len(context.shortlisted_jobs),
        "latest_search_query": context.latest_search_query,
        "target_job_selected": context.target_job is not None,
        "selected_target_job_id": context.target_job.job_id if context.target_job else None,
        "candidate_profile_available": context.candidate_profile is not None,
        "preferences": [
            {"field": fact.field, "value": fact.value} for fact in preferences
        ],
        "plan": list(context.plan),
    }
    return xml_data_block(
        "thread_state", json.dumps(state, ensure_ascii=False, separators=(",", ":"))
    )


class DeepAgentConversationModel:
    """Conversation adapter that runs a real tool loop for every turn."""

    def __init__(self, *, model_factory=None, telemetry: RecruitmentTelemetry | None = None):
        # `model_factory` is for tests and nothing else.
        self._model_factory = model_factory
        self._telemetry = telemetry or OpenTelemetryRecorder()

    def _build_model(self):
        """Always explicit: model=None inherits a 60s timeout and no retries."""
        if self._model_factory:
            return self._model_factory()
        return create_observed_agent_model(
            self._telemetry,
            role="coordinator",
            timeout=config.RECRUITMENT_MODEL_HTTP_TIMEOUT_SECONDS,
            max_retries=config.RECRUITMENT_MODEL_TRANSPORT_RETRIES,
            model=config.COORDINATOR_MODEL,
            max_completion_tokens=config.RECRUITMENT_CONVERSATION_MAX_TOKENS,
        )

    def _cleanup_terminal_checkpoint(self, run_config: dict) -> bool:
        """Observe cleanup outcome without recording the private checkpoint id."""
        with self._telemetry.operation(
            "checkpoint_cleanup",
            {"role": "coordinator"},
        ) as span:
            cleaned = _delete_terminal_checkpoint(run_config)
            span.set_attribute("cleanup_succeeded", cleaned)
            if not cleaned:
                span.mark_error("CheckpointCleanupFailed")
            return cleaned

    def _build_agent(self, context: ConversationContext):
        from langchain.agents import create_agent
        from langchain.agents.middleware import HumanInTheLoopMiddleware

        # The assessment runner's module-level SqliteSaver, not a second store:
        # one checkpoint file, one durability story. Imported here so that
        # importing this module does not open a sqlite connection.
        from ..open_agent.runner import _CHECKPOINTER

        if context.candidate_profile is None:
            raise RuntimeError("coordinator requires a current candidate evidence profile")

        # Not create_deep_agent: its base stack binds eight more tools and its
        # `middleware` argument only appends, so they cannot be declined.
        tools = [
            read_shortlist,
            search_jobs,
            write_plan,
            write_shortlist,
            propose_resume_edit,
            ask_candidate,
        ]
        if context.target_job is not None:
            tools.append(read_target_job)
        tools.append(read_candidate_evidence)

        return create_agent(
            model=self._build_model(),
            tools=tools,
            middleware=[
                provider_message_compatibility,
                require_tool_call,
                ToolCallGuardMiddleware(
                    one_shot_tools={search_jobs.name},
                    terminal_tool=REPLY_TOOL_NAME,
                    required_tools={search_jobs.name: read_candidate_evidence.name},
                ),
                HumanInTheLoopMiddleware(interrupt_on={"ask_candidate": True}),
            ],
            system_prompt=COORDINATOR_SYSTEM_PROMPT,
            response_format=ToolStrategy(ConversationReply),
            checkpointer=_CHECKPOINTER,
        )

    @staticmethod
    def _run_config(graph_thread_id: str) -> dict:
        return {
            "recursion_limit": config.COORDINATOR_MAX_TOOL_ITERATIONS,
            "configurable": {"thread_id": graph_thread_id},
        }

    def _new_turn_payload(
        self,
        context: ConversationContext,
        messages: list[Message],
        current_preferences: tuple[PreferenceFact, ...],
    ) -> dict:
        """The DB transcript, then the compact thread state, then this message.

        The resume text is deliberately absent. Block IDs reach the agent through
        `read_candidate_evidence`, exactly as they do on the assessment path.
        """
        request: list[Any] = []
        latest_index = next(
            (
                index
                for index in range(len(messages) - 1, -1, -1)
                if messages[index].role == "user"
            ),
            None,
        )
        prior_messages = [
            message
            for index, message in enumerate(messages)
            if index != latest_index
        ][-(config.RECRUITMENT_MODEL_HISTORY_TURNS * 2):]
        request.extend(
            convert_to_messages(
                [
                    {"role": message.role, "content": message.content}
                    for message in prior_messages
                ]
            )
        )
        turn = _thread_state_block(context, current_preferences)
        if latest_index is not None:
            turn = f"{turn}\n\n{messages[latest_index].content}"
        request.append(HumanMessage(content=turn))
        return {"messages": request}

    def respond(
        self,
        messages: list[Message],
        resume_text: str,
        current_preferences: tuple[PreferenceFact, ...] = (),
        context: ConversationContext | None = None,
    ) -> ModelReply:
        del resume_text
        if context is None:
            # A guard clause, not a quiet degradation back into the blind
            # coordinator this adapter exists to replace.
            raise InvalidCommand("DeepAgentConversationModel requires a ConversationContext")

        agent = self._build_agent(context)
        run_config, payload, skip_tool_call_ids, question_limit_enforced = self._turn(
            agent, context, messages, current_preferences
        )

        try:
            reply = self._respond(
                agent,
                context,
                run_config,
                payload,
                skip_tool_call_ids,
                question_limit_enforced,
            )
        except BaseException as error:
            if not self._cleanup_terminal_checkpoint(run_config):
                error.checkpoint_cleanup_token = run_config["configurable"]["thread_id"]
            raise
        if reply.pause_token:
            return reply
        if self._cleanup_terminal_checkpoint(run_config):
            return reply
        return replace(
            reply,
            checkpoint_cleanup_token=run_config["configurable"]["thread_id"],
        )

    def _respond(
        self,
        agent,
        context: ConversationContext,
        run_config: dict,
        payload,
        skip_tool_call_ids: set[str] | None,
        question_limit_enforced: bool,
    ) -> ModelReply:
        pending_question = ""
        submitted = False
        edit_attempted = False
        tool_call_count = 0
        rejected_tool_name = ""
        consecutive_tool_rejections = 0
        with self._telemetry.operation(
            "conversation.loop",
            {
                "trace_key": context.trace_key,
                "resumed": skip_tool_call_ids is not None,
                "recursion_limit": run_config["recursion_limit"],
            },
        ) as span:
            with open_agent_context.assessment_context(
                context, initial_edits=context.proposed_edits
            ):
                try:
                    for event in iter_progress_events(
                        agent, payload, run_config, skip_tool_call_ids=skip_tool_call_ids
                    ):
                        if (
                            event.get("kind") == "model_attempt"
                            and event.get("team_member") == "coordinator"
                            and int(event.get("attempt") or 0)
                            > config.COORDINATOR_MAX_MODEL_STEPS
                        ):
                            if context.on_event is not None:
                                context.on_event(event)
                            span.set_attribute("failure_type", "business")
                            span.set_attribute("failure_code", "attempt_budget_exhausted")
                            span.set_attribute(
                                "model_step_limit", config.COORDINATOR_MAX_MODEL_STEPS
                            )
                            raise ConversationUnavailable(
                                "coordinator reached its model step limit",
                                decision=classify_failure("attempt_budget_exhausted"),
                            )
                        if event.get("kind") == "tool_call":
                            tool_call_count += 1
                            if tool_call_count > config.COORDINATOR_MAX_TOOL_CALLS:
                                if context.on_event is not None:
                                    context.on_event(event)
                                span.set_attribute("failure_type", "business")
                                span.set_attribute(
                                    "failure_code", "attempt_budget_exhausted"
                                )
                                span.set_attribute(
                                    "tool_call_limit", config.COORDINATOR_MAX_TOOL_CALLS
                                )
                                raise ConversationUnavailable(
                                    "coordinator reached its tool call limit",
                                    decision=classify_failure(
                                        "attempt_budget_exhausted"
                                    ),
                                )
                        if event.get("tool_name") == REPLY_TOOL_NAME:
                            # The turn's reply, not a tool the coordinator
                            # called. Publishing it would put "coordinator
                            # called ConversationReply" in the activity stream.
                            submitted = submitted or event["kind"] == "tool_call"
                            continue
                        if event.get("kind") == "tool_result":
                            tool_name = str(event.get("tool_name") or "")
                            if rejected_tool_result(event):
                                if tool_name == rejected_tool_name:
                                    consecutive_tool_rejections += 1
                                else:
                                    rejected_tool_name = tool_name
                                    consecutive_tool_rejections = 1
                                if (
                                    consecutive_tool_rejections
                                    >= config.COORDINATOR_MAX_CONSECUTIVE_TOOL_REJECTIONS
                                ):
                                    span.set_attribute("failure_type", "business")
                                    span.set_attribute(
                                        "failure_code", "attempt_budget_exhausted"
                                    )
                                    span.set_attribute("rejected_tool_name", tool_name)
                                    span.set_attribute(
                                        "consecutive_tool_rejections",
                                        consecutive_tool_rejections,
                                    )
                                    raise ConversationUnavailable(
                                        "coordinator repeatedly retried a rejected tool call",
                                        decision=classify_failure("attempt_budget_exhausted"),
                                    )
                            else:
                                rejected_tool_name = ""
                                consecutive_tool_rejections = 0
                        if (
                            event["kind"] == "tool_call"
                            and event["tool_name"] == propose_resume_edit.name
                        ):
                            edit_attempted = True
                        if (
                            event["kind"] == "tool_call"
                            and event["tool_name"] == ask_candidate.name
                        ):
                            pending_question = format_questions(event.get("args") or {})
                        if context.on_event is not None:
                            context.on_event(event)
                except GraphRecursionError as error:
                    span.set_attribute("failure_type", "business")
                    span.set_attribute("failure_code", "attempt_budget_exhausted")
                    raise ConversationUnavailable(
                        "coordinator loop hit its tool iteration cap",
                        decision=classify_failure("attempt_budget_exhausted"),
                    ) from error

            state = agent.get_state(run_config)
            executed_query = (
                context.search_results[-1].query if context.search_results else ""
            )
            span.set_attribute("search_count", len(context.search_results))
            span.set_attribute("proposed_edit_count", len(context.proposed_edits))

            latest_search = context.search_results[-1] if context.search_results else None
            if latest_search is not None and (
                latest_search.failure_type or latest_search.failure_code
            ):
                failure_code = latest_search.failure_code or "connection_failure"
                span.set_attribute("failure_type", latest_search.failure_type or "transient")
                span.set_attribute("failure_code", failure_code)
                span.set_attribute("failed_tool_name", "search_jobs")
                raise ConversationUnavailable(
                    "job search did not complete",
                    decision=classify_failure(failure_code),
                    detail={
                        "validation_code": "search_result_unavailable",
                        "tool_name": "search_jobs",
                    },
                )

            if state.interrupts:
                if mentions_protected_status(pending_question):
                    span.set_attribute("failure_type", "safety")
                    span.set_attribute("failure_code", "protected_candidate_question")
                    raise ConversationUnavailable(
                        "coordinator rejected a protected-status question",
                        decision=classify_failure("protected_candidate_question"),
                    )
                if question_limit_enforced:
                    span.set_attribute("failure_type", "business")
                    span.set_attribute("failure_code", "attempt_budget_exhausted")
                    raise ConversationUnavailable(
                        "coordinator continued asking after the candidate question limit",
                        decision=classify_failure("attempt_budget_exhausted"),
                    )
                span.set_attribute("outcome", "paused")
                return ModelReply(
                    prompt_version=COORDINATOR_PROMPT_VERSION,
                    content=pending_question,
                    model_name=_model_name(state),
                    search_query=executed_query,
                    pause_token=run_config["configurable"]["thread_id"],
                    reply_mode="paused",
                )

            reply = state.values.get("structured_response")
            if not submitted or not isinstance(reply, ConversationReply):
                span.set_attribute("failure_type", "validation")
                span.set_attribute("failure_code", "structured_output_invalid")
                unverified_tool = _unverified_tool_claim(
                    _unsubmitted_text_for_validation(state), context
                )
                detail = None
                if unverified_tool:
                    span.set_attribute("unverified_tool_claim", unverified_tool)
                    detail = {
                        "validation_code": "unverified_tool_claim",
                        "tool_name": unverified_tool,
                    }
                raise ConversationUnavailable(
                    "coordinator did not submit the required structured reply",
                    decision=classify_failure("structured_output_invalid"),
                    detail=detail,
                )
            content = (
                _resume_edit_reply(context.proposed_edits, reply)
                if edit_attempted
                else reply.reply.strip()
            )
            unverified_tool = _unverified_tool_claim(content, context)
            if unverified_tool:
                span.set_attribute("failure_type", "validation")
                span.set_attribute("failure_code", "structured_output_invalid")
                span.set_attribute("unverified_tool_claim", unverified_tool)
                raise ConversationUnavailable(
                    "coordinator reply claimed tool work that did not complete",
                    decision=classify_failure("structured_output_invalid"),
                    detail={
                        "validation_code": "unverified_tool_claim",
                        "tool_name": unverified_tool,
                    },
                )
            span.set_attribute("outcome", "submitted")
            return ModelReply(
                prompt_version=COORDINATOR_PROMPT_VERSION,
                content=content,
                model_name=_model_name(state),
                # An observation, not a request: what ran, not what was wished
                # for. `_query_from_candidate` reads this on the next
                # SearchJobs command.
                search_query=executed_query,
                reply_mode="structured",
            )

    def _turn(
        self,
        agent,
        context: ConversationContext,
        messages: list[Message],
        current_preferences: tuple[PreferenceFact, ...],
    ) -> tuple[dict, Any, set[str] | None, bool]:
        """Resume the paused graph if there is one, otherwise start a fresh one."""
        if context.pause_token:
            run_config = self._run_config(context.pause_token)
            state = agent.get_state(run_config)
            if state.interrupts:
                answer = _latest_user_message(messages)
                question_limit_enforced = (
                    _ask_rounds_so_far(state) >= config.OPEN_AGENT_MAX_CANDIDATE_QUESTION_ROUNDS
                )
                if question_limit_enforced:
                    answer = f"{answer}\n\n{_QUESTION_LIMIT_SENTENCE}"
                call_id = _pending_ask_call_id(state)
                return (
                    run_config,
                    Command(resume={"decisions": [{"type": "respond", "message": answer}]}),
                    {call_id} if call_id else None,
                    question_limit_enforced,
                )

        run_config = self._run_config(f"coordinator-{context.thread_id}-{uuid.uuid4()}")
        return (
            run_config,
            self._new_turn_payload(context, messages, current_preferences),
            None,
            False,
        )
