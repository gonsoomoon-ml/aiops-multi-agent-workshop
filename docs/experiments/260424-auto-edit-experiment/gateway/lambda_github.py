"""Lambda handler that exposes the GitHub tool to AgentCore Gateway.

Same event conventions as `lambda_cloudwatch.py`. For Lab 2, this Lambda
needs PyGithub installed and `GITHUB_TOKEN` / `GITHUB_REPO` set as function
environment variables (not baked into the code).
"""
from __future__ import annotations

import json
import logging
from typing import Any

from tools.github_tool import get_file, list_files, put_file

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_DISPATCH = {
    "list_files": list_files,
    "get_file": get_file,
    "put_file": put_file,
}


def _unwrap(event: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if isinstance(event, str):
        event = json.loads(event)
    if "body" in event and isinstance(event["body"], str):
        try:
            event = {**event, **json.loads(event["body"])}
        except json.JSONDecodeError:
            pass
    name = (
        event.get("toolName")
        or event.get("tool_name")
        or event.get("action")
        or event.get("name")
    )
    args = event.get("arguments") or event.get("parameters") or event.get("args") or {}
    if not name:
        raise ValueError(f"event missing tool name; keys={list(event.keys())}")
    return name, args


def lambda_handler(event: Any, context: Any) -> dict[str, Any]:
    try:
        tool_name, arguments = _unwrap(event)
        logger.info("GitHub tool invocation: %s(%s)", tool_name, list(arguments.keys()))
        fn = _DISPATCH.get(tool_name)
        if fn is None:
            raise KeyError(f"unknown tool: {tool_name}. Available: {list(_DISPATCH)}")
        result = fn(**arguments)
        return {"statusCode": 200, "body": json.dumps(result, default=str)}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Invocation failed")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(exc), "type": type(exc).__name__}),
        }


if __name__ == "__main__":
    import os

    os.environ.setdefault("OFFLINE_MODE", "1")
    out = lambda_handler({"toolName": "list_files", "arguments": {"path": "rules/"}}, None)
    print(out["statusCode"])
    parsed = json.loads(out["body"])
    print(f"files under rules/: {len(parsed['files'])}")
