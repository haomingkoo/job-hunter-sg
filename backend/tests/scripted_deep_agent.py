"""A scripted brain for a real deep-agent graph.

This is a test double for the *model*, not for the graph. The graph, the tools,
the guardrails and the LangGraph interrupt all really run; only the sequence of
decisions is scripted. That is deliberate: a double that stands in for the graph
itself would assert that the test's own idea of a loop works, which is exactly
the class of green-suite evidence this repo has already been burned by.

It differs from `test_open_agent_runner.py`'s private `_ScriptedModel` in three
ways that matter for a conversational loop:

1. **Exhaustion raises.** `FakeMessagesListChatModel` wraps back to index 0 when
   its script runs out, so an under-scripted test silently loops forever or
   silently replays an old decision. Here that is an `AssertionError` naming the
   call number. `repeat_last=True` opts into looping, and only the iteration-cap
   test wants it.
2. **Every request is recorded.** `requests[n]` is the full message list the
   model was invoked with on call n, which is how a test proves the model
   actually *saw* a tool result instead of guessing from the transcript.
3. **Bound tool names are recorded**, so a test can assert the loop bound the
   tools it claims to bind.
"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field


class ScriptedDeepAgent(FakeMessagesListChatModel):
    """Replays `responses` in order, one per model invocation, and records what it saw."""

    repeat_last: bool = False
    requests: list[list[Any]] = Field(default_factory=list)
    bound_tool_names: list[list[str]] = Field(default_factory=list)

    def bind_tools(self, tools, **kwargs):
        self.bound_tool_names.append([getattr(item, "name", str(item)) for item in tools])
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.requests.append(list(messages))
        if self.i >= len(self.responses):
            if not self.repeat_last:
                raise AssertionError(
                    f"ScriptedDeepAgent ran out of script on call {self.i + 1}: "
                    f"{len(self.responses)} responses were scripted. The graph made "
                    "more model calls than the test expected -- extend the script or "
                    "fix the loop, never let it wrap around."
                )
            response = self.responses[-1]
        else:
            response = self.responses[self.i]
            self.i += 1
        return ChatResult(generations=[ChatGeneration(message=response)])

    @property
    def consumed(self) -> int:
        """How many scripted responses were actually used.

        Assert on this. A test whose script is longer than the run silently
        asserted less than it looks like it did.
        """
        return self.i


def tool_call(name: str, args: dict, call_id: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


def submission(
    reply: str,
    *,
    preference_updates: list[dict] | None = None,
    search_query: str = "",
    call_id: str = "submit-1",
) -> AIMessage:
    """The terminal submission the coordinator loop ends on.

    Reuses the existing `submit_recruitment_conversation` contract verbatim, so a
    scripted turn exercises the same `_ConversationPayload` validation and the
    same evidence-quote rule as production.
    """
    return tool_call(
        "submit_recruitment_conversation",
        {
            "reply": reply,
            "preference_updates": list(preference_updates or []),
            "search_query": search_query,
        },
        call_id,
    )


def final(text: str) -> AIMessage:
    """The trailing plain reply the graph emits after the submission tool returns."""
    return AIMessage(content=text)
