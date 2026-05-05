"""AgentCore Runtime-compatible entrypoint (Lab 3).

Wraps the same Strands Agent as Lab 1/2 in a BedrockAgentCoreApp so that
`bedrock-agentcore-starter-toolkit` can deploy it as a managed Runtime.

The contract:
  - Runtime invokes `handler(payload)` with the user's prompt as
    `payload["prompt"]`.
  - Handler returns a JSON-serializable dict — here, the Agent's final text
    plus a thin summary.

Local test:
    python -m runtime.agent_runtime --local "최근 1주 noise alarm 진단해줘"
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from bedrock_agentcore.runtime import BedrockAgentCoreApp

app = BedrockAgentCoreApp()


@app.entrypoint
def handler(payload: dict):
    """AgentCore Runtime entrypoint.

    Payload shape:
        {"prompt": "<natural language request>"}
    """
    from agent.rule_optimizer import build_agent

    prompt = payload.get("prompt") or payload.get("input") or payload.get("query")
    if not prompt:
        return {"error": "missing 'prompt' in payload"}
    agent = build_agent()
    result = agent(prompt)
    return {"response": str(result)}


def _local(prompt: str) -> int:
    """Run the handler locally without deploying — useful for smoke tests."""
    out = handler({"prompt": prompt})
    print(json.dumps(out, default=str, indent=2, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local", action="store_true", help="Invoke handler once locally")
    parser.add_argument("prompt", nargs="?", default="최근 1주 noise alarm 진단해줘")
    args = parser.parse_args()
    if args.local:
        return _local(args.prompt)
    app.run()  # start the HTTP server that Runtime expects
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
