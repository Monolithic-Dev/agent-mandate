"""Run a live agent against a running gateway.

    python -m mandate.agents "Archive the newsletters, then delete m-1" --tenant demo
    python -m mandate.agents "..." --provider groq --model openai/gpt-oss-120b

The API address and key come from MANDATE_API_URL and MANDATE_API_KEY; the model from the
LLM settings in .env (see .env.example). Nothing here is scored: it shows what a real model
does at the gateway, and what the gateway does about it.
"""

from __future__ import annotations

import argparse
import os
import sys

import httpx

from mandate.agents.live import GatewayClient, run_agent
from mandate.config import Settings
from mandate.errors import ConfigError
from mandate.llm import LlmError, build_chat_model


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m mandate.agents", description=__doc__)
    parser.add_argument("task", help="what to ask the agent to do")
    parser.add_argument("--tenant", default="demo")
    parser.add_argument("--agent", default="assistant", help="the agent's name or id")
    parser.add_argument("--provider", help="anthropic, groq, openai or openai-compatible")
    parser.add_argument("--model")
    parser.add_argument("--max-steps", type=int, default=10)
    args = parser.parse_args(argv)
    # A model's reply can hold any character; a Windows console's code page cannot print them all.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")

    settings = Settings()
    api_url = os.environ.get("MANDATE_API_URL", "http://127.0.0.1:8000")
    try:
        key = settings.require_api_key()
        model = build_chat_model(settings, provider=args.provider, model=args.model)
        listing = httpx.get(
            f"{api_url}/v1/tenants/{args.tenant}/agents", headers={"X-Mandate-Key": key}, timeout=15
        )
        listing.raise_for_status()
    except (ConfigError, httpx.HTTPError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    agents = {a["name"]: a["id"] for a in listing.json()} | {
        a["id"]: a["id"] for a in listing.json()
    }
    if args.agent not in agents:
        print(
            f"error: no agent {args.agent!r} in {args.tenant!r}: {sorted(agents)}", file=sys.stderr
        )
        return 2

    gateway = GatewayClient(api_url, key, args.tenant, agents[args.agent])
    print(f"{model.name} as {args.agent} in {args.tenant}: {args.task}\n")
    try:
        run = run_agent(model, gateway, args.task, max_steps=args.max_steps)
    except LlmError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    for step in run.steps:
        status = step.result.get("status")
        why = step.result.get("reason") or step.result.get("message") or ""
        print(f"  {step.tool}({step.args}) -> {status} {why}".rstrip())
    print(f"\n{run.answer}")
    print(
        f"\n{len(run.executed)} ran, {len(run.held)} held for the owner, {len(run.denied)} denied"
        f" · {run.tokens['input']} tokens in, {run.tokens['output']} out · stopped: {run.stopped}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
