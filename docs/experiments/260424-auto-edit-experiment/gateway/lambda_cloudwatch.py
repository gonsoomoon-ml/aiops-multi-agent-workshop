"""Lambda handler that exposes the CloudWatch Mock tool to AgentCore Gateway.

Gateway invokes this Lambda once per tool call. Event payload arrives as either:

  (a) direct MCP-style dict:
       {"toolName": "describe_alarms", "arguments": {"alarm_names": ["foo"]}}

  (b) API-Gateway-wrapped dict with `body` as a JSON string:
       {"body": "{\\"toolName\\": \\"describe_alarms\\", ...}"}

We normalize both, dispatch to the Python tool in `tools/cloudwatch_mock.py`,
and return a JSON-serializable response. In Lab 3, the same handler is used
behind the AgentCore Runtime-deployed Gateway with no code changes.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from tools.cloudwatch_mock import (
    describe_alarm_history,
    describe_alarms,
    get_alarm_statistics,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_DISPATCH = {
    "describe_alarms": describe_alarms,
    "describe_alarm_history": describe_alarm_history,
    "get_alarm_statistics": get_alarm_statistics,
}


def _unwrap(event: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Return (tool_name, arguments) regardless of wrapping style."""
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
        logger.info("CloudWatch tool invocation: %s(%s)", tool_name, arguments)
        fn = _DISPATCH.get(tool_name)
        if fn is None:
            raise KeyError(f"unknown tool: {tool_name}. Available: {list(_DISPATCH)}")
        result = fn(**arguments)
        return {"statusCode": 200, "body": json.dumps(result, default=str)}
    except Exception as exc:  # noqa: BLE001 — always return a JSON error response
        logger.exception("Invocation failed")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(exc), "type": type(exc).__name__}),
        }


if __name__ == "__main__":
    # Local smoke: imitate Gateway invocation
    out = lambda_handler(
        {"toolName": "get_alarm_statistics", "arguments": {"period_days": 7}}, None
    )
    print(out["statusCode"])
    parsed = json.loads(out["body"])
    print(f"got {len(parsed['alarms'])} aggregated alarms")
