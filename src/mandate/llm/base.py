"""A language model, as the live agents see it: provider-neutral, and nothing more.

The authority engine never calls a model (a decision must be reproducible), so this is used
only by live agents and the planned planner. Adapters turn these types into one provider's wire
format and back: ``anthropic_chat`` (Claude) and ``openai_chat`` (any OpenAI-compatible API,
which covers Groq, OpenAI, OpenRouter, Together, and local servers such as Ollama and vLLM).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol


class LlmError(Exception):
    """The model could not be reached or answered something unusable."""


@dataclass(frozen=True)
class ToolDef:
    """A tool the model may call: a name, what it does, and a JSON Schema for its arguments."""

    name: str
    description: str
    schema: dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    args: dict[str, Any]


@dataclass(frozen=True)
class Message:
    """One turn. ``user`` and ``assistant`` carry text; an assistant turn may also carry the
    tool calls it made; a ``tool`` turn answers one call (``tool_call_id``) with ``text``."""

    role: Literal["user", "assistant", "tool"]
    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None


@dataclass(frozen=True)
class Reply:
    text: str
    tool_calls: tuple[ToolCall, ...] = ()
    # Why the model stopped, in one provider-neutral word: "end", "tool_use" or "length".
    stop: str = "end"
    usage: dict[str, int] = field(default_factory=dict)


class ChatModel(Protocol):
    name: str

    def complete(
        self,
        system: str,
        messages: list[Message],
        tools: list[ToolDef] | None = None,
        *,
        max_tokens: int = 1024,
    ) -> Reply: ...
