"""The conversational coordinator as a deep-agent tool loop (#146).

`LangChainConversationModel` is one `model.invoke()` binding one submission
tool. It cannot search, cannot read a posting, and never sees the results of a
search the thread ran. This adapter implements the same port and gives it the
loop the repo already has.

Two mechanisms are worth knowing before changing anything here.

**Termination is `response_format=ToolStrategy(ConversationReply)`.** LangChain
parses and validates the submission inside the loop, retries an invalid payload
without another round trip through this module, and ends the graph on the
structured call with no trailing completion. The parsed object arrives on
`state["structured_response"]`.

**Every turn gets its own LangGraph thread id.** That is not the obvious choice
and it is not cosmetic. `structured_response` is written into the checkpoint and
never cleared, and `factory._make_model_to_tools_edge` ends the run on
`"structured_response" in state` -- a key-presence check, so writing `None` over
it does not help (verified against langchain 1.3.11). On a stable per-thread
graph, the first completed turn therefore makes every later `ask_candidate`
resume terminate the instant the answer is injected, silently, with no reply.
So the DB transcript is replayed into a fresh graph each turn, and the
checkpointer is used for exactly what it is good at: holding one paused graph
between two HTTP requests. The pause's graph id travels back on
`ModelReply.pause_token` and is persisted on `case_facts`, the same way the
assessment runner persists its own pause token.

Two costs of that, stated rather than discovered later. The checkpoint file gains
a graph per chat turn and nothing prunes it, where the assessment runner adds one
per assessment. And LangGraph warns that deserializing `ConversationReply` from a
checkpoint will be blocked in a future version, which will need
`allowed_msgpack_modules` before that release lands.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from langchain.agents.structured_output import ToolStrategy
from langchain_core.messages import HumanMessage, convert_to_messages
from langgraph.errors import GraphRecursionError
from langgraph.types import Command

import config
from prompt_safety import xml_data_block

from ..conversation_model import ConversationReply, ModelReply
from ..errors import ConversationUnavailable, InvalidCommand
from ..interface import Message, PreferenceFact, PreferenceUpdate
from ..open_agent import context as open_agent_context
from ..open_agent.streaming import format_questions, iter_progress_events
from ..open_agent.tools import (
    ask_candidate,
    propose_resume_edit,
    read_candidate_evidence,
    read_shortlist,
    read_target_job,
    search_jobs,
)
from ..prompts import COORDINATOR_PROMPT_VERSION, COORDINATOR_SYSTEM_PROMPT
from .repeat_guard import RepeatedCallMiddleware
from ..telemetry import OpenTelemetryRecorder, RecruitmentTelemetry
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


def _model_name(state) -> str:
    for message in reversed(state.values.get("messages") or []):
        name = (getattr(message, "response_metadata", None) or {}).get("model_name")
        if name:
            return str(name)
    return "coordinator-deep-agent"


def _thread_state_block(context: ConversationContext, preferences: tuple[PreferenceFact, ...]) -> str:
    """Counts and preferences, never the postings themselves.

    Putting the shortlist here would make `read_shortlist` decorative and would
    put every posting into every turn's prompt. The agent asks for them.
    """
    state = {
        "recommendation_count": len(context.recommendations),
        "shortlisted_count": len(context.shortlisted_jobs),
        "latest_search_query": context.latest_search_query,
        "target_job_selected": context.target_job is not None,
        "selected_target_job_id": context.target_job.job_id if context.target_job else None,
        "candidate_profile_available": context.candidate_profile is not None,
        # The heuristic's answer, surfaced as evidence rather than applied as a
        # filter the agent cannot see. search_jobs takes exclude_junior as a
        # required argument and the agent decides it.
        "wants_experienced_roles": context.wants_experienced_roles,
        "preferences": [
            {"field": fact.field, "value": fact.value} for fact in preferences
        ],
    }
    return xml_data_block(
        "thread_state", json.dumps(state, ensure_ascii=False, separators=(",", ":"))
    )


def _resume_block(context: ConversationContext, resume_text: str) -> str:
    """The resume as blocks the agent can cite, not as prose it can only read.

    `propose_resume_edit` takes a canonical block ID, and those are opaque
    hashes. Handing over raw text gives the agent something to reason about and
    nothing to quote, so its first edit is always a guess. Emitting `id: text`
    per line costs about twenty characters a block and removes the guess.

    Falls back to the raw text when the document carries no blocks, because a
    resume the agent cannot see at all is the worse failure.
    """
    blocks = (context.resume_document or {}).get("blocks") or []
    if not blocks:
        return xml_data_block("resume", resume_text)
    lines = "\n".join(f"{block.get('id')}: {block.get('text', '')}" for block in blocks)
    return xml_data_block("resume", lines)


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
        from resume_agent.models import create_agent_model

        return create_agent_model(
            timeout=config.RECRUITMENT_MODEL_HTTP_TIMEOUT_SECONDS,
            max_retries=config.RECRUITMENT_MODEL_TRANSPORT_RETRIES,
            model=config.COORDINATOR_MODEL,
            max_completion_tokens=config.RECRUITMENT_CONVERSATION_MAX_TOKENS,
        )

    def _build_agent(self):
        from langchain.agents import create_agent
        from langchain.agents.middleware import HumanInTheLoopMiddleware

        # The assessment runner's module-level SqliteSaver, not a second store:
        # one checkpoint file, one durability story. Imported here so that
        # importing this module does not open a sqlite connection.
        from ..open_agent.runner import _CHECKPOINTER

        # Not create_deep_agent: its base stack binds eight more tools and its
        # `middleware` argument only appends, so they cannot be declined.
        return create_agent(
            model=self._build_model(),
            tools=[
                read_shortlist,
                search_jobs,
                read_target_job,
                read_candidate_evidence,
                propose_resume_edit,
                ask_candidate,
            ],
            middleware=[
                RepeatedCallMiddleware(),
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
        resume_text: str = "",
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
        request.extend(
            convert_to_messages(
                [
                    {"role": message.role, "content": message.content}
                    for index, message in enumerate(messages)
                    if index != latest_index
                ]
            )
        )
        turn = _thread_state_block(context, current_preferences)
        if context.candidate_profile is None and resume_text.strip():
            # Until the study has run there is no evidence profile, so
            # read_candidate_evidence returns nothing and the agent has no way to
            # learn who it is talking to. Live on 2026-08-02 it answered "please
            # share your resume" to a thread that already had one, then spun to
            # the iteration cap hunting for context it could never reach.
            turn = f"{turn}\n\n{_resume_block(context, resume_text)}"
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
        if context is None:
            # A guard clause, not a quiet degradation back into the blind
            # coordinator this adapter exists to replace.
            raise InvalidCommand("DeepAgentConversationModel requires a ConversationContext")

        agent = self._build_agent()
        run_config, payload, skip_tool_call_ids = self._turn(
            agent, context, messages, current_preferences, resume_text
        )

        pending_question = ""
        submitted = False
        with self._telemetry.operation(
            "conversation.loop",
            {
                "trace_key": context.trace_key,
                "graph_thread_id": run_config["configurable"]["thread_id"],
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
                        if event.get("tool_name") == REPLY_TOOL_NAME:
                            # The turn's reply, not a tool the coordinator
                            # called. Publishing it would put "coordinator
                            # called ConversationReply" in the activity stream.
                            submitted = submitted or event["kind"] == "tool_call"
                            continue
                        if (
                            event["kind"] == "tool_call"
                            and event["tool_name"] == ask_candidate.name
                        ):
                            pending_question = format_questions(event.get("args") or {})
                        if context.on_event is not None:
                            context.on_event(event)
                except GraphRecursionError as error:
                    span.set_attribute("failure_type", "tool_iteration_cap")
                    raise ConversationUnavailable(
                        "coordinator loop hit its tool iteration cap",
                        failure_type="tool_iteration_cap",
                        retryable=True,
                    ) from error

            state = agent.get_state(run_config)
            executed_query = (
                context.search_results[-1].query if context.search_results else ""
            )
            span.set_attribute("search_count", len(context.search_results))
            span.set_attribute("proposed_edit_count", len(context.proposed_edits))

            if state.interrupts:
                span.set_attribute("outcome", "paused")
                return ModelReply(
                    prompt_version=COORDINATOR_PROMPT_VERSION,
                    content=pending_question,
                    model_name=_model_name(state),
                    search_query=executed_query,
                    pause_token=run_config["configurable"]["thread_id"],
                )

            reply = state.values.get("structured_response")
            if not submitted or not isinstance(reply, ConversationReply):
                span.set_attribute("failure_type", "no_submission")
                raise ConversationUnavailable(
                    "coordinator loop ended without a reply",
                    failure_type="no_submission",
                    retryable=True,
                )
            span.set_attribute("outcome", "submitted")
            return ModelReply(
                prompt_version=COORDINATOR_PROMPT_VERSION,
                content=reply.reply.strip(),
                model_name=_model_name(state),
                preference_updates=tuple(
                    PreferenceUpdate(
                        field=item.field,
                        value=item.value.strip(),
                        evidence_quote=item.evidence_quote.strip(),
                    )
                    for item in reply.preference_updates
                ),
                # An observation, not a request: what ran, not what was wished
                # for. `_query_from_candidate` reads this on the next
                # SearchJobs command.
                search_query=executed_query,
            )

    def _turn(
        self,
        agent,
        context: ConversationContext,
        messages: list[Message],
        current_preferences: tuple[PreferenceFact, ...],
        resume_text: str,
    ) -> tuple[dict, Any, set[str] | None]:
        """Resume the paused graph if there is one, otherwise start a fresh one."""
        if context.pause_token:
            run_config = self._run_config(context.pause_token)
            state = agent.get_state(run_config)
            if state.interrupts:
                answer = _latest_user_message(messages)
                if _ask_rounds_so_far(state) >= config.OPEN_AGENT_MAX_CANDIDATE_QUESTION_ROUNDS:
                    # Prompt text, so it asks rather than enforces. Stated as a
                    # limitation: an extra question in a conversation costs one
                    # more turn, not a stuck run.
                    answer = f"{answer}\n\n{_QUESTION_LIMIT_SENTENCE}"
                call_id = _pending_ask_call_id(state)
                return (
                    run_config,
                    Command(resume={"decisions": [{"type": "respond", "message": answer}]}),
                    {call_id} if call_id else None,
                )

        run_config = self._run_config(f"coordinator-{context.thread_id}-{uuid.uuid4()}")
        return (
            run_config,
            self._new_turn_payload(context, messages, current_preferences, resume_text),
            None,
        )
