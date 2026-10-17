"""An OpenAI-compatible chat model: Groq, OpenAI, OpenRouter, Together, Ollama, vLLM.

They share one wire format (``POST {base}/chat/completions`` with ``tools``), so one adapter
serves them all; only the base URL, the key and the model name differ.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

import httpx

from mandate.llm.base import LlmError, Message, Reply, ToolCall, ToolDef

RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_WAIT_SECONDS = 30.0  # the longest pause between attempts, even if the server asks for more
STOPS = {"stop": "end", "tool_calls": "tool_use", "length": "length"}


class OpenAIChat:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        model: str,
        client: httpx.Client | None = None,
        attempts: int = 5,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.name = model
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = client or httpx.Client(timeout=60.0)
        self._attempts = attempts
        self._sleep = sleep

    def complete(
        self,
        system: str,
        messages: list[Message],
        tools: list[ToolDef] | None = None,
        *,
        max_tokens: int = 1024,
    ) -> Reply:
        body: dict[str, Any] = {
            "model": self.name,
            "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, *map(_wire, messages)],
        }
        if tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.schema,
                    },
                }
                for t in tools
            ]
        data = self._post(body)
        try:
            choice = data["choices"][0]
            message = choice["message"]
            calls = tuple(
                ToolCall(
                    id=str(call["id"]),
                    name=str(call["function"]["name"]),
                    args=_arguments(call["function"].get("arguments")),
                )
                for call in message.get("tool_calls") or []
            )
            usage = data.get("usage") or {}
            return Reply(
                text=message.get("content") or "",
                tool_calls=calls,
                stop="tool_use" if calls else STOPS.get(choice.get("finish_reason"), "end"),
                usage={
                    "input": int(usage.get("prompt_tokens", 0)),
                    "output": int(usage.get("completion_tokens", 0)),
                },
            )
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise LlmError(f"the model's answer was not understood: {error}") from error

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        last = "no attempt was made"
        for attempt in range(self._attempts):
            wait = 2.0**attempt
            try:
                response = self._client.post(self._url, json=body, headers=self._headers)
            except httpx.HTTPError as error:
                last = f"the model could not be reached: {type(error).__name__}"
            else:
                if response.status_code == 200:
                    try:
                        return dict(response.json())
                    except ValueError as error:
                        raise LlmError("the model's answer was not JSON") from error
                last = f"HTTP {response.status_code}: {response.text[:200]}"
                if response.status_code not in RETRY_STATUSES:
                    raise LlmError(last)
                wait = _retry_after(response) or wait
            if attempt + 1 < self._attempts:
                self._sleep(min(wait, MAX_WAIT_SECONDS))
        raise LlmError(last)


def _retry_after(response: httpx.Response) -> float | None:
    """How long the server asks us to wait, in seconds (a plain number of seconds only)."""
    try:
        return max(0.0, float(response.headers["retry-after"]))
    except (KeyError, ValueError):
        return None


def _arguments(raw: Any) -> dict[str, Any]:
    if raw in (None, ""):
        return {}
    value = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(value, dict):
        raise ValueError("tool arguments were not an object")
    return value


def _wire(message: Message) -> dict[str, Any]:
    if message.role == "tool":
        return {"role": "tool", "tool_call_id": message.tool_call_id, "content": message.text}
    if message.role == "assistant" and message.tool_calls:
        return {
            "role": "assistant",
            "content": message.text or None,
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": json.dumps(call.args)},
                }
                for call in message.tool_calls
            ],
        }
    return {"role": message.role, "content": message.text}
