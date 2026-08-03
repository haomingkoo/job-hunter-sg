"""A scripted brain for a real deep-agent graph.

This is a test double for the *model*, not for the graph. The graph, the tools,
the guardrails and the LangGraph interrupt all really run; only the sequence of
decisions is scripted. That is deliberate: a double that stands in for the graph
itself would assert that the test's own idea of a loop works, which is exactly
the class of green-suite evidence this repo has already been burned by.

It differs from `test_open_agent_runner.py`'s private `_ScriptedModel` in four
ways that matter for a conversational loop:

1. **Exhaustion raises.** `FakeMessagesListChatModel` wraps back to index 0 when
   its script runs out, so an under-scripted test silently loops forever or
   silently replays an old decision. Here that is an `AssertionError` naming the
   call number. `repeat_last=True` opts into looping, and only the iteration-cap
   test wants it.
2. **`consumed` and `calls` are different numbers.** `consumed` counts scripted
   responses used; `calls` counts model invocations. With `repeat_last=True` the
   first freezes and the second keeps climbing. A test that means to bound how
   far the loop ran must bound `calls` -- bounding `consumed` under `repeat_last`
   asserts nothing at all, because it is pinned at 1 whether the recursion limit
   is honoured or ignored.
3. **Every request is recorded.** `requests[n]` is the full message list the
   model was invoked with on call n, which is how a test proves the model
   actually *saw* a tool result instead of guessing from the transcript.
4. **Bound tool names are recorded**, so a test can assert the loop bound the
   tools it claims to bind.
"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field


# The terminal tool of the coordinator loop. `ToolStrategy` derives the tool name
# from the schema class name, so this string is `ConversationReply.__name__` and
# changes only if that class is renamed. See docs/v4-146-coordinator-loop.md §5.
CONVERSATION_REPLY_TOOL = "ConversationReply"


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

        Assert on this to prove a script was fully exercised. A test whose script
        is longer than the run silently asserted less than it looks like it did.
        Under `repeat_last` this stops advancing, so it is the wrong number for
        bounding a runaway loop -- use `calls`.
        """
        return self.i

    @property
    def calls(self) -> int:
        """How many times the model was really invoked, `repeat_last` included."""
        return len(self.requests)


def tool_call(name: str, args: dict, call_id: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


def submission(
    reply: str,
    *,
    preference_updates: list[dict] | None = None,
    search_query: str = "",
    pending_edit_block_ids: list[str] | None = None,
    call_id: str = "submit-1",
) -> AIMessage:
    """The structured-output call the coordinator loop terminates on.

    Reuses the existing conversation payload contract verbatim, so a scripted turn
    is validated by the same pydantic schema production uses. It does **not** by
    itself exercise the evidence-quote rule: `preference_updates` defaults to
    empty, and `preference_update_error` only has something to reject when a test
    passes one whose quote does or does not occur in the latest user message.
    """
    return tool_call(
        CONVERSATION_REPLY_TOOL,
        {
            "reply": reply,
            "preference_updates": list(preference_updates or []),
            "search_query": search_query,
            "pending_edit_block_ids": list(pending_edit_block_ids or []),
        },
        call_id,
    )


def preference(field: str, value: str, evidence_quote: str) -> dict:
    """One preference update for `submission(preference_updates=[...])`."""
    return {"field": field, "value": value, "evidence_quote": evidence_quote}


def final(text: str) -> AIMessage:
    """A plain reply with no tool call: how a graph without a response_format ends."""
    return AIMessage(content=text)
