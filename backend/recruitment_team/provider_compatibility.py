"""Provider-specific message adaptation at the model request boundary."""

from __future__ import annotations

import json
from typing import Any

from langchain.agents.middleware import wrap_model_call
from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage

from prompt_safety import xml_data_block


def _requires_alternating_roles(model: Any) -> bool:
    name = str(
        getattr(model, "model_name", "")
        or getattr(model, "model", "")
        or ""
    ).casefold()
    return "sea-lion" in name or name.startswith("aisingapore/")


def _message_text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False, separators=(",", ":"), default=str)


def alternating_provider_messages(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Present tool results as one user turn for strict alternating providers.

    The graph state is not changed. Tool-call IDs, native ToolMessages, and
    durable receipts remain available to LangGraph and application validators.
    """
    adapted: list[BaseMessage] = []
    for message in messages:
        if isinstance(message, ToolMessage):
            result_text = _message_text(message)
            correction = ""
            if "identical_call_no_new_information" in result_text:
                correction = (
                    "Application instruction: the identical tool call was rejected. "
                    "Do not call that tool again with the same arguments in this turn. "
                    "Use its earlier result, choose a different tool, or finish the reply.\n\n"
                )
            text = xml_data_block(
                "tool_result",
                json.dumps(
                    {
                        "tool": message.name or "tool",
                        "tool_call_id": message.tool_call_id,
                        "result": result_text,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )
            message = HumanMessage(content=correction + text)
        if isinstance(message, HumanMessage) and adapted and isinstance(adapted[-1], HumanMessage):
            adapted[-1] = HumanMessage(
                content=f"{_message_text(adapted[-1])}\n\n{_message_text(message)}"
            )
        else:
            adapted.append(message)
    return adapted


@wrap_model_call
def provider_message_compatibility(request, handler):
    """Adapt only providers whose API rejects the standard tool role."""
    if not _requires_alternating_roles(request.model):
        return handler(request)
    messages = alternating_provider_messages(list(request.messages))
    return handler(request.override(messages=messages))


@wrap_model_call
def require_tool_call(request, handler):
    """Enforce workflows whose only valid progress is a tool result."""
    return handler(request.override(tool_choice="required"))
