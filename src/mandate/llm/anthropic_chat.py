"""Claude, through the Anthropic SDK."""

from __future__ import annotations

from typing import Any

from mandate.llm.base import LlmError, Message, Reply, ToolCall, ToolDef

STOPS = {"end_turn": "end", "stop_sequence": "end", "tool_use": "tool_use", "max_tokens": "length"}


class AnthropicChat:
    def __init__(self, *, api_key: str, model: str, client: Any = None) -> None:
        self.name = model
        if client is None:
            import anthropic  # imported here: nothing else in the product needs the SDK

            client = anthropic.Anthropic(api_key=api_key)
        self._client = client

    def complete(
        self,
        system: str,
        messages: list[Message],
        tools: list[ToolDef] | None = None,
        *,
        max_tokens: int = 1024,
    ) -> Reply:
        kwargs: dict[str, Any] = {
            "model": self.name,
            "max_tokens": max_tokens,
            "system": system,
            "messages": _wire(messages),
        }
        if tools:
            kwargs["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.schema}
                for t in tools
            ]
        try:
            response = self._client.messages.create(**kwargs)
        except Exception as error:  # noqa: BLE001 - the SDK has many error types; all mean "no answer"
            raise LlmError(f"the model could not be reached: {type(error).__name__}") from error
        text: list[str] = []
        calls: list[ToolCall] = []
        for block in response.content:
            if block.type == "text":
                text.append(block.text)
            elif block.type == "tool_use":
                calls.append(ToolCall(id=block.id, name=block.name, args=dict(block.input)))
        usage = getattr(response, "usage", None)
        return Reply(
            text="".join(text),
            tool_calls=tuple(calls),
            stop="tool_use" if calls else STOPS.get(str(response.stop_reason), "end"),
            usage={
                "input": int(getattr(usage, "input_tokens", 0) or 0),
                "output": int(getattr(usage, "output_tokens", 0) or 0),
            },
        )


def _wire(messages: list[Message]) -> list[dict[str, Any]]:
    """Claude wants tool results as blocks inside a user turn, so consecutive ``tool`` turns
    are folded into one."""
    wire: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "tool":
            block = {
                "type": "tool_result",
                "tool_use_id": message.tool_call_id,
                "content": message.text,
            }
            if wire and wire[-1]["role"] == "user" and wire[-1].get("_results"):
                wire[-1]["content"].append(block)
            else:
                wire.append({"role": "user", "content": [block], "_results": True})
        elif message.role == "assistant" and message.tool_calls:
            content: list[dict[str, Any]] = []
            if message.text:
                content.append({"type": "text", "text": message.text})
            content += [
                {"type": "tool_use", "id": c.id, "name": c.name, "input": c.args}
                for c in message.tool_calls
            ]
            wire.append({"role": "assistant", "content": content})
        else:
            wire.append({"role": message.role, "content": message.text})
    for turn in wire:
        turn.pop("_results", None)
    return wire
