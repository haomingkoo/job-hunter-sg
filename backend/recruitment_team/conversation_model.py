"""Conversation-model port and concrete production/test adapters."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal, Protocol

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool
from pydantic import BaseModel, Field, ValidationError
from prompt_safety import xml_data_block

import config

from .interface import Message, PreferenceFact, PreferenceUpdate
from .prompts import CONVERSATION_SYSTEM_PROMPT
from .telemetry import OpenTelemetryRecorder, RecruitmentTelemetry


class _PreferenceUpdatePayload(BaseModel):
    field: Literal["role", "location", "seniority", "salary", "constraints"]
    value: str = Field(min_length=1)
    evidence_quote: str = Field(min_length=1)


class _ConversationPayload(BaseModel):
    reply: str = Field(min_length=1)
    preference_updates: list[_PreferenceUpdatePayload] = Field(default_factory=list)


@tool(args_schema=_ConversationPayload)
def submit_recruitment_conversation(
    reply: str,
    preference_updates: list[_PreferenceUpdatePayload],
) -> str:
    """Submit one recruitment-team reply and any durable candidate preferences.

    Use after every conversational turn. Each preference update must be explicitly
    stated in the latest user message and include an exact supporting quote. Do not
    use this tool to infer preferences from a resume or an earlier message.
    """
    return "submitted"


@dataclass(frozen=True)
class ModelReply:
    content: str
    model_name: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    preference_updates: tuple[PreferenceUpdate, ...] = ()


class ConversationModel(Protocol):
    def respond(
        self,
        messages: list[Message],
        resume_text: str,
        current_preferences: tuple[PreferenceFact, ...] = (),
    ) -> ModelReply: ...


def preference_update_error(
    updates: tuple[PreferenceUpdate, ...],
    latest_user_message: str,
) -> str:
    for index, update in enumerate(updates):
        if not update.value.strip():
            return f"preference_updates[{index}].value is required"
        quote = update.evidence_quote.strip()
        if not quote:
            return f"preference_updates[{index}].evidence_quote is required"
        if quote not in latest_user_message:
            return f"preference_updates[{index}].evidence_quote must occur exactly in the latest user message"
    return ""


def _submission(response: AIMessage) -> tuple[_ConversationPayload | None, dict, str]:
    calls = [call for call in response.tool_calls if call.get("name") == submit_recruitment_conversation.name]
    failed = {
        "content": response.content,
        "tool_calls": response.tool_calls,
    }
    if len(response.tool_calls) != 1 or len(calls) != 1:
        return None, failed, "exactly one submit_recruitment_conversation tool call is required"
    try:
        return _ConversationPayload.model_validate(calls[0].get("args") or {}), failed, ""
    except ValidationError as error:
        return None, failed, str(error)


class LangChainConversationModel:
    """Production adapter over the existing provider-neutral LangChain factory."""

    def __init__(
        self,
        model=None,
        *,
        telemetry: RecruitmentTelemetry | None = None,
    ):
        if model is None:
            from resume_agent.models import create_agent_model

            model = create_agent_model(
                timeout=config.RECRUITMENT_MODEL_HTTP_TIMEOUT_SECONDS,
                max_retries=config.RECRUITMENT_MODEL_TRANSPORT_RETRIES,
            )
        self._model = model
        self._telemetry = telemetry or OpenTelemetryRecorder()

    def respond(
        self,
        messages: list[Message],
        resume_text: str,
        current_preferences: tuple[PreferenceFact, ...] = (),
    ) -> ModelReply:
        request = [
            SystemMessage(content=CONVERSATION_SYSTEM_PROMPT),
            HumanMessage(content=xml_data_block("resume_data", resume_text)),
        ]
        if current_preferences:
            request.append(
                HumanMessage(
                    content=xml_data_block(
                        "current_preference_facts",
                        json.dumps(
                            [
                                {
                                    "field": fact.field,
                                    "value": fact.value,
                                    "evidence_quote": fact.evidence_quote,
                                }
                                for fact in current_preferences
                            ],
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                    )
                )
            )
        for message in messages:
            if message.role == "user":
                request.append(HumanMessage(content=message.content))
            else:
                request.append(AIMessage(content=message.content))
        latest_user_message = next(
            (message.content for message in reversed(messages) if message.role == "user"),
            "",
        )
        input_tokens = 0
        output_tokens = 0
        bound_model = self._model.bind_tools(
            [submit_recruitment_conversation],
            tool_choice=submit_recruitment_conversation.name,
        )
        failed_output: dict = {}
        failure = ""
        for attempt in range(config.RECRUITMENT_CONVERSATION_VALIDATION_ATTEMPTS):
            attempt_request = list(request)
            if failure:
                attempt_request.append(
                    HumanMessage(
                        content=(
                            "Correct the failed structured submission. Return exactly one tool call.\n\n"
                            + xml_data_block(
                                "failed_conversation_output",
                                json.dumps(failed_output, ensure_ascii=False, separators=(",", ":")),
                            )
                            + "\n\n"
                            + xml_data_block("validation_error", failure)
                        )
                    )
                )
            with self._telemetry.operation(
                "conversation.model_attempt",
                {
                    "attempt": attempt + 1,
                    "max_attempts": config.RECRUITMENT_CONVERSATION_VALIDATION_ATTEMPTS,
                    "configured_timeout_seconds": config.RECRUITMENT_MODEL_HTTP_TIMEOUT_SECONDS,
                    "transport_retries": config.RECRUITMENT_MODEL_TRANSPORT_RETRIES,
                },
            ) as span:
                response = bound_model.invoke(attempt_request)
                usage = getattr(response, "usage_metadata", None) or {}
                attempt_input_tokens = int(usage.get("input_tokens") or 0)
                attempt_output_tokens = int(usage.get("output_tokens") or 0)
                input_tokens += attempt_input_tokens
                output_tokens += attempt_output_tokens
                span.set_attribute("input_tokens", attempt_input_tokens)
                span.set_attribute("output_tokens", attempt_output_tokens)
                model_name = str(
                    getattr(response, "response_metadata", {}).get("model_name") or type(self._model).__name__
                )
                span.set_attribute("model", model_name)
                payload, failed_output, failure = _submission(response)
                updates = (
                    tuple(
                        PreferenceUpdate(
                            field=item.field,
                            value=item.value.strip(),
                            evidence_quote=item.evidence_quote.strip(),
                        )
                        for item in payload.preference_updates
                    )
                    if payload is not None
                    else ()
                )
                if payload is not None:
                    failure = preference_update_error(updates, latest_user_message)
                span.set_attribute("validation_code", failure)
                span.set_attribute("accepted", payload is not None and not failure)
            if payload is None or failure:
                continue
            return ModelReply(
                content=payload.reply.strip(),
                model_name=model_name,
                input_tokens=input_tokens or None,
                output_tokens=output_tokens or None,
                preference_updates=updates,
            )
        raise ValueError(f"conversation structured output failed validation: {failure}")


class ScriptedConversationModel:
    """Deterministic adapter that exercises production orchestration in E2E tests."""

    def __init__(self, replies: list[str | ModelReply]):
        self._replies = iter(replies)
        self.call_count = 0

    def respond(
        self,
        messages: list[Message],
        resume_text: str,
        current_preferences: tuple[PreferenceFact, ...] = (),
    ) -> ModelReply:
        self.call_count += 1
        reply = next(self._replies)
        if isinstance(reply, ModelReply):
            return reply
        return ModelReply(
            content=reply,
            model_name="scripted-conversation-model",
        )
