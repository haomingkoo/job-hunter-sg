from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from recruitment_team.provider_compatibility import (
    alternating_provider_messages,
    provider_message_compatibility,
    require_tool_call,
)


def test_tool_results_become_one_user_turn_without_changing_assistant_call():
    assistant = AIMessage(
        content="",
        tool_calls=[
            {"name": "first_tool", "args": {}, "id": "call-1", "type": "tool_call"},
            {"name": "second_tool", "args": {}, "id": "call-2", "type": "tool_call"},
        ],
    )
    original = [
        HumanMessage(content="request"),
        assistant,
        ToolMessage(content="first result", name="first_tool", tool_call_id="call-1"),
        ToolMessage(content={"ok": True}, name="second_tool", tool_call_id="call-2"),
    ]

    adapted = alternating_provider_messages(original)

    assert [message.type for message in adapted] == ["human", "ai", "human"]
    assert adapted[1] is assistant
    assert "first_tool" in adapted[2].content
    assert "second_tool" in adapted[2].content
    assert original[2].type == "tool"


def test_middleware_adapts_sea_lion_but_preserves_native_provider_messages():
    messages = [
        HumanMessage(content="request"),
        AIMessage(content="", tool_calls=[
            {"name": "tool", "args": {}, "id": "call-1", "type": "tool_call"},
        ]),
        ToolMessage(content="result", name="tool", tool_call_id="call-1"),
    ]
    observed = []

    def handler(request):
        observed.append(request.messages)
        return AIMessage(content="done")

    sea_lion_request = SimpleNamespace(
        model=SimpleNamespace(model_name="aisingapore/Gemma-SEA-LION-v4-27B-IT"),
        messages=messages,
        override=lambda **changes: SimpleNamespace(
            model=SimpleNamespace(model_name="aisingapore/Gemma-SEA-LION-v4-27B-IT"),
            messages=changes["messages"],
        ),
    )
    native_request = SimpleNamespace(
        model=SimpleNamespace(model_name="gpt-native"),
        messages=messages,
    )

    provider_message_compatibility.wrap_model_call(sea_lion_request, handler)
    provider_message_compatibility.wrap_model_call(native_request, handler)

    assert [message.type for message in observed[0]] == ["human", "ai", "human"]
    assert observed[1] is messages


def test_rejected_duplicate_is_rendered_as_a_clear_provider_instruction():
    adapted = alternating_provider_messages([
        ToolMessage(
            content='{"reason":"identical_call_no_new_information: already called"}',
            name="read_shortlist",
            tool_call_id="call-1",
        )
    ])

    assert adapted[0].content.startswith("Application instruction:")
    assert "Do not call that tool again" in adapted[0].content


def test_required_tool_middleware_sets_explicit_tool_choice():
    observed = []
    request = SimpleNamespace(
        override=lambda **changes: SimpleNamespace(tool_choice=changes["tool_choice"]),
    )

    require_tool_call.wrap_model_call(
        request,
        lambda updated: observed.append(updated.tool_choice) or AIMessage(content="done"),
    )

    assert observed == ["required"]
