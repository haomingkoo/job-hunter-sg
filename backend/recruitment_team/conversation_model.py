"""Conversation-model port and concrete production/test adapters."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

from pydantic import BaseModel, Field, field_validator

from .interface import Message, PreferenceFact, PreferenceUpdate

if TYPE_CHECKING:  # pragma: no cover - import cycle guard, annotations are strings
    from .coordinator.context import ConversationContext


class ConversationReply(BaseModel):
    """Submit one recruitment-team reply.

    The class name is load-bearing: the coordinator loop terminates on
    `ToolStrategy(ConversationReply)`, and ToolStrategy derives the tool name
    the model sees from `__name__`.
    """

    reply: str = Field(min_length=1)
    assumptions: list[str] = Field(
        default_factory=list,
        description="Interpretations that must stay outside resume edits.",
    )
    missing_information: list[str] = Field(
        default_factory=list,
        description="Material candidate facts that remain unknown or unverified.",
    )
    follow_up_question: str = Field(
        default="",
        description="One optional question whose answer would materially improve the work.",
    )

    @field_validator("reply")
    @classmethod
    def require_complete_sentence(cls, value: str) -> str:
        """Reject visibly cut-off prose while ToolStrategy can still repair it."""
        if not reply_is_complete(value):
            raise ValueError("reply must end with a complete sentence")
        return value


_SENTENCE_END = re.compile(r"[.!?](?:[\"'\u201d\u2019)\]])?\s*$")


def reply_is_complete(value: str) -> bool:
    """Whether candidate-facing prose has an explicit sentence ending."""
    return bool(_SENTENCE_END.search(value))


@dataclass(frozen=True)
class ModelReply:
    content: str
    model_name: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    reply_mode: Literal["adapter", "paused", "structured"] = "adapter"
    preference_updates: tuple[PreferenceUpdate, ...] = ()
    # Which prompt produced this turn. A trace that always stamps the same
    # constant cannot tell you which one ran.
    prompt_version: str = ""
    search_query: str = ""
    # Set only when a turn ended paused on ask_candidate: the LangGraph thread id
    # holding the pending interrupt. RecruitmentTeam persists it so the next
    # message resumes that graph instead of starting a new one.
    pause_token: str = ""
    # A terminal graph whose checkpoint deletion failed. The recruitment team
    # persists this opaque local identifier so later privacy cleanup can retry.
    checkpoint_cleanup_token: str = ""


def paragraph_reply(content: str) -> str:
    """Add readable paragraph breaks when a model returns one prose wall."""
    text = content.strip()
    if "\n" in text:
        return text
    sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z0-9"“])', text)
    if len(sentences) < 2:
        return text
    paragraphs = [" ".join(sentences[index:index + 2]) for index in range(0, len(sentences), 2)]
    if len(paragraphs) > 4:
        paragraphs = paragraphs[:3] + [" ".join(paragraphs[3:])]
    return "\n\n".join(paragraphs)


class ConversationModel(Protocol):
    def respond(
        self,
        messages: list[Message],
        resume_text: str,
        current_preferences: tuple[PreferenceFact, ...] = (),
        context: "ConversationContext | None" = None,
    ) -> ModelReply: ...


def evidenced_preference_updates(
    updates: tuple[PreferenceUpdate, ...],
    latest_user_message: str,
) -> tuple[tuple[PreferenceUpdate, ...], tuple[str, ...]]:
    """Keep exact-quote preference updates and report rejected ones."""
    kept: list[PreferenceUpdate] = []
    rejected: list[str] = []
    for index, update in enumerate(updates):
        reason = preference_update_error((update,), latest_user_message)
        if reason:
            rejected.append(reason.replace("preference_updates[0]", f"preference_updates[{index}]"))
            continue
        kept.append(update)
    return tuple(kept), tuple(rejected)


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
        context: "ConversationContext | None" = None,
    ) -> ModelReply:
        self.call_count += 1
        reply = next(self._replies)
        if isinstance(reply, ModelReply):
            return reply
        return ModelReply(
            content=reply,
            model_name="scripted-conversation-model",
        )
