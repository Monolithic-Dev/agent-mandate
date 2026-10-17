"""The model layer and the live agent, with the network replaced by fakes."""

import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from mandate.agents.live import GatewayClient, run_agent, tool_defs
from mandate.config import Settings
from mandate.errors import ConfigError
from mandate.llm import LlmError, Message, Reply, ToolCall, build_chat_model
from mandate.llm.anthropic_chat import AnthropicChat
from mandate.llm.openai_chat import OpenAIChat

ENV = [
    "MANDATE_LLM_PROVIDER",
    "MANDATE_MODEL",
    "MANDATE_LLM_MODEL",
    "MANDATE_LLM_BASE_URL",
    "MANDATE_LLM_API_KEY",
    "ANTHROPIC_API_KEY",
    "GROQ_API_KEY",
    "OPENAI_API_KEY",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV:
        monkeypatch.delenv(name, raising=False)


def settings(**values: Any) -> Settings:
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


# --- choosing a provider ----------------------------------------------------------------------


def test_groq_is_an_openai_compatible_provider_with_its_own_key_and_url() -> None:
    model = build_chat_model(settings(mandate_llm_provider="groq", groq_api_key="gsk-test"))
    assert isinstance(model, OpenAIChat)
    assert model._url == "https://api.groq.com/openai/v1/chat/completions"  # noqa: SLF001
    assert model.name == "openai/gpt-oss-120b"


def test_anthropic_needs_its_key_and_uses_the_configured_model() -> None:
    with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
        build_chat_model(settings())
    model = build_chat_model(settings(anthropic_api_key="sk-ant-test", mandate_model="claude-x"))
    assert isinstance(model, AnthropicChat) and model.name == "claude-x"


def test_a_local_server_needs_no_key_but_a_hosted_one_does() -> None:
    local = build_chat_model(
        settings(
            mandate_llm_provider="openai-compatible",
            mandate_llm_base_url="http://localhost:11434/v1",
            mandate_llm_model="llama3.2",
        )
    )
    assert isinstance(local, OpenAIChat)
    with pytest.raises(ConfigError, match="API key"):
        build_chat_model(settings(mandate_llm_provider="openai"))
    with pytest.raises(ConfigError, match="BASE_URL"):
        build_chat_model(settings(mandate_llm_provider="openai-compatible", mandate_llm_model="m"))
    with pytest.raises(ConfigError, match="unknown LLM provider"):
        build_chat_model(settings(mandate_llm_provider="nope"))


# --- the OpenAI-compatible adapter ------------------------------------------------------------


def chat(handler: Any, **extra: Any) -> OpenAIChat:
    return OpenAIChat(
        base_url="https://llm.test/v1",
        api_key="k",
        model="m",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: None,
        **extra,
    )


def test_it_sends_tools_and_reads_tool_calls_back() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "c1",
                                    "type": "function",
                                    "function": {
                                        "name": "email_delete",
                                        "arguments": '{"message_id": "m-1"}',
                                    },
                                }
                            ],
                        },
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 5},
            },
        )

    reply = chat(handler).complete("sys", [Message("user", "hi")], tool_defs()[:1])
    assert reply.tool_calls == (ToolCall("c1", "email_delete", {"message_id": "m-1"}),)
    assert reply.stop == "tool_use" and reply.usage == {"input": 12, "output": 5}
    assert seen["auth"] == "Bearer k"
    assert seen["body"]["messages"][0] == {"role": "system", "content": "sys"}
    assert seen["body"]["tools"][0]["function"]["name"] == "email_list"


def test_a_tool_turn_is_sent_back_as_a_tool_message() -> None:
    sent: list[Any] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content)["messages"])
        return httpx.Response(200, json={"choices": [{"message": {"content": "done"}}]})

    call = ToolCall("c1", "email_list", {})
    chat(handler).complete(
        "s",
        [
            Message("user", "go"),
            Message("assistant", "", (call,)),
            Message("tool", "{}", tool_call_id="c1"),
        ],
    )
    assistant, tool = sent[0][2], sent[0][3]
    assert assistant["tool_calls"][0]["function"]["arguments"] == "{}"
    assert tool == {"role": "tool", "tool_call_id": "c1", "content": "{}"}


def test_it_retries_a_busy_server_but_not_a_refusal() -> None:
    answers = iter([429, 503, 200])

    def busy(request: httpx.Request) -> httpx.Response:
        status = next(answers)
        if status == 200:
            return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
        return httpx.Response(status, text="slow down")

    assert chat(busy).complete("s", [Message("user", "x")]).text == "ok"
    with pytest.raises(LlmError, match="HTTP 401"):
        chat(lambda r: httpx.Response(401, text="bad key")).complete("s", [Message("user", "x")])
    with pytest.raises(LlmError, match="HTTP 500"):
        chat(lambda r: httpx.Response(500, text="boom")).complete("s", [Message("user", "x")])


def test_garbled_answers_are_errors_not_crashes() -> None:
    with pytest.raises(LlmError, match="not understood"):
        chat(lambda r: httpx.Response(200, json={"choices": []})).complete(
            "s", [Message("user", "x")]
        )
    bad = {
        "choices": [
            {
                "message": {
                    "tool_calls": [{"id": "1", "function": {"name": "t", "arguments": "[1]"}}]
                }
            }
        ]
    }
    with pytest.raises(LlmError, match="not understood"):
        chat(lambda r: httpx.Response(200, json=bad)).complete("s", [Message("user", "x")])


# --- the Anthropic adapter --------------------------------------------------------------------


class FakeClaude:
    def __init__(self, content: list[Any], stop: str = "end_turn") -> None:
        self.sent: dict[str, Any] = {}
        self._response = SimpleNamespace(
            content=content,
            stop_reason=stop,
            usage=SimpleNamespace(input_tokens=7, output_tokens=3),
        )
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs: Any) -> Any:
        self.sent = kwargs
        return self._response


def test_claude_tool_results_are_folded_into_one_user_turn() -> None:
    client = FakeClaude(
        [
            SimpleNamespace(type="text", text="Done."),
            SimpleNamespace(type="tool_use", id="t9", name="email_list", input={"folder": "inbox"}),
        ],
        stop="tool_use",
    )
    model = AnthropicChat(api_key="x", model="claude-x", client=client)
    calls = (
        ToolCall("a", "email_read", {"message_id": "m-1"}),
        ToolCall("b", "email_read", {"message_id": "m-2"}),
    )
    reply = model.complete(
        "sys",
        [
            Message("user", "read both"),
            Message("assistant", "reading", calls),
            Message("tool", "one", tool_call_id="a"),
            Message("tool", "two", tool_call_id="b"),
        ],
        tool_defs()[:1],
    )
    wire = client.sent["messages"]
    assert [m["role"] for m in wire] == ["user", "assistant", "user"]
    assert [b["tool_use_id"] for b in wire[2]["content"]] == ["a", "b"]
    assert wire[1]["content"][0] == {"type": "text", "text": "reading"}
    assert client.sent["tools"][0]["input_schema"]["type"] == "object"
    assert reply.text == "Done." and reply.stop == "tool_use"
    assert reply.tool_calls == (ToolCall("t9", "email_list", {"folder": "inbox"}),)
    assert reply.usage == {"input": 7, "output": 3}


def test_a_failing_claude_call_is_an_llm_error() -> None:
    client = SimpleNamespace(
        messages=SimpleNamespace(create=lambda **k: (_ for _ in ()).throw(RuntimeError("x")))
    )
    with pytest.raises(LlmError, match="could not be reached"):
        AnthropicChat(api_key="x", model="m", client=client).complete("s", [Message("user", "x")])


# --- the live agent ---------------------------------------------------------------------------


class Scripted:
    """A model that answers from a list, and records what it was shown."""

    name = "scripted"

    def __init__(self, replies: list[Reply]) -> None:
        self.replies = iter(replies)
        self.seen: list[list[Message]] = []

    def complete(
        self, system: str, messages: list[Message], tools: Any = None, *, max_tokens: int = 1024
    ) -> Reply:
        self.seen.append(list(messages))
        return next(self.replies)


def test_the_tools_given_to_a_model_are_the_gateways_tools() -> None:
    names = [t.name for t in tool_defs()]
    assert {"email_delete", "refund_issue", "file_write"} <= set(names)
    refund = next(t for t in tool_defs() if t.name == "refund_issue")
    assert set(refund.schema["properties"]) == {"order_id", "amount"}


def test_held_and_denied_results_go_back_to_the_model_and_are_counted() -> None:
    model = Scripted(
        [
            Reply(
                "",
                (ToolCall("1", "email_archive", {"message_id": "m-3"}),),
                "tool_use",
                {"input": 5, "output": 2},
            ),
            Reply("", (ToolCall("2", "email_delete", {"message_id": "m-1"}),), "tool_use"),
            Reply(
                "Archived m-3; deleting m-1 needs your approval.",
                (),
                "end",
                {"input": 9, "output": 8},
            ),
        ]
    )
    answers = {
        "email_archive": {"status": "ok"},
        "email_delete": {
            "status": "confirmation_required",
            "reason": "confirm_rule",
            "approval_id": "act_1",
        },
    }
    run = run_agent(model, lambda tool, args: answers[tool], "tidy up")
    assert [s.tool for s in run.executed] == ["email_archive"]
    assert [s.tool for s in run.held] == ["email_delete"] and run.denied == []
    assert run.answer.startswith("Archived") and run.stopped == "end"
    assert run.tokens == {"input": 14, "output": 10}
    # The model was told what happened, so it can report it.
    last = model.seen[-1][-1]
    assert last.role == "tool" and "confirmation_required" in last.text


def test_an_agent_that_never_stops_is_cut_off() -> None:
    looping = Scripted(
        [Reply("", (ToolCall(str(i), "email_list", {}),), "tool_use") for i in range(5)]
    )
    run = run_agent(looping, lambda tool, args: {"status": "ok"}, "go", max_steps=3)
    assert run.stopped == "max_steps" and len(run.steps) == 3


def test_the_gateway_client_posts_the_call_with_the_key_and_survives_failures() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["key"] = request.headers["x-mandate-key"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"status": "denied", "reason": "no_authority_path"})

    client = GatewayClient(
        "http://api:8000/",
        "key",
        "acme",
        "agt_1",
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert client("file_delete", {"path": "a.txt"}) == {
        "status": "denied",
        "reason": "no_authority_path",
    }
    assert seen["url"] == "http://api:8000/v1/tenants/acme/tool-calls" and seen["key"] == "key"
    assert seen["body"] == {"agent_id": "agt_1", "tool": "file_delete", "args": {"path": "a.txt"}}

    down = GatewayClient(
        "http://api",
        "k",
        "t",
        "a",
        httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(502))),
    )
    assert down("email_list", {})["status"] == "error"


def test_a_live_agent_through_the_real_api_is_held_where_the_owner_said_to_ask() -> None:
    """The model proposes a delete and an archive; the gateway holds one and runs the other."""
    from fakes.memory_backend import MemoryTenantBackend
    from fastapi.testclient import TestClient

    from mandate.api.app import create_app
    from mandate.clock import FixedClock

    key = "k" * 24
    api = TestClient(
        create_app(
            Settings(mandate_api_key=key, _env_file=None),  # type: ignore[call-arg]
            MemoryTenantBackend(),
            FixedClock(),
        )
    )
    h = {"X-Mandate-Key": key}
    assert (
        api.post("/v1/tenants", json={"tenant_id": "acme", "name": "Acme"}, headers=h).status_code
        == 201
    )
    owner = api.post(
        "/v1/tenants/acme/principals", json={"name": "Dana", "role": "owner"}, headers=h
    ).json()["id"]
    agent = api.post(
        "/v1/tenants/acme/agents", json={"name": "main", "kind": "primary"}, headers=h
    ).json()["id"]
    said = api.post(
        "/v1/tenants/acme/utterances",
        json={
            "principal_id": owner,
            "channel": "owner_direct",
            "text": (
                "You may read and archive my email, but confirm with me before deleting anything."
            ),
        },
        headers=h,
    ).json()
    for item in said["instructions"]:
        if item["needs_confirmation"]:
            api.post(
                f"/v1/tenants/acme/instructions/{item['instruction']['id']}/confirm",
                json={"by": owner},
                headers=h,
            )

    model = Scripted(
        [
            Reply("", (ToolCall("1", "email_archive", {"message_id": "m-3"}),), "tool_use"),
            Reply("", (ToolCall("2", "email_delete", {"message_id": "m-1"}),), "tool_use"),
            Reply("Archived m-3. Deleting m-1 is waiting for your approval.", (), "end"),
        ]
    )
    run = run_agent(
        model, GatewayClient("http://testserver", key, "acme", agent, api), "tidy my inbox"
    )
    assert [s.tool for s in run.executed] == ["email_archive"]
    assert [s.tool for s in run.held] == ["email_delete"]
    assert run.held[0].result["reason"] == "confirm_rule"
    assert api.get(
        "/v1/tenants/acme/actions?status=pending", headers=h
    ).json()  # waiting for the owner


def test_it_waits_as_long_as_a_busy_server_asks_but_not_forever() -> None:
    waits: list[float] = []
    answers = iter([("12", 429), ("500", 429), (None, 200)])

    def handler(request: httpx.Request) -> httpx.Response:
        retry, status = next(answers)
        if status == 200:
            return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
        return httpx.Response(
            status, headers={"retry-after": retry or "0"}, text="tokens per minute"
        )

    model = OpenAIChat(
        base_url="https://llm.test/v1",
        api_key="k",
        model="m",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=waits.append,
    )
    assert model.complete("s", [Message("user", "x")]).text == "ok"
    assert waits == [12.0, 30.0]
