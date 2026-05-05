"""cloudwatch-wrapper Lambda — Intent shape (Smithy 폐기, Section 4).

AgentCore Gateway 호출 패턴 (실측):
- tool 식별자: ``context.client_context.custom["bedrockAgentCoreToolName"]``
  (event 가 아닌 Lambda invoke metadata, 형식 ``<target>___<tool>``)
- input: ``event`` 자체가 inputSchema.properties 의 값 dict (wrapper 없음)

LLM 친화적 응답 — verbose 필드 제거, classification 을 top-level 로.
Tags 는 describe_alarms 응답에 포함되지 않으므로 list_tags_for_resource 별도 호출.
"""
import os

import boto3

cw = boto3.client("cloudwatch")
DEMO_USER = os.environ["DEMO_USER"]
ALARM_PREFIX = f"payment-{DEMO_USER}-"


def _tool_name(context) -> str:
    cc = getattr(context, "client_context", None)
    custom = getattr(cc, "custom", None) if cc else None
    return (custom or {}).get("bedrockAgentCoreToolName", "")


def _classification(alarm_arn: str) -> str | None:
    resp = cw.list_tags_for_resource(ResourceARN=alarm_arn)
    for tag in resp.get("Tags", []):
        if tag["Key"] == "Classification":
            return tag["Value"]
    return None


def _ts(value) -> str | None:
    return value.isoformat() if value else None


def lambda_handler(event, context):
    tool = _tool_name(context)
    params = event or {}

    if tool.endswith("list_live_alarms"):
        resp = cw.describe_alarms(AlarmNamePrefix=ALARM_PREFIX)
        alarms = []
        for a in resp.get("MetricAlarms", []):
            alarms.append({
                "name": a["AlarmName"],
                "state": a["StateValue"],
                "state_reason": a.get("StateReason", ""),
                "metric_name": a.get("MetricName"),
                "namespace": a.get("Namespace"),
                "threshold": a.get("Threshold"),
                "classification": _classification(a["AlarmArn"]),
                "updated": _ts(a.get("StateUpdatedTimestamp")),
            })
        return {"alarms": alarms}

    if tool.endswith("get_live_alarm_history"):
        if "alarm_name" not in params:
            return {"error": "alarm_name is required"}
        resp = cw.describe_alarm_history(
            AlarmName=params["alarm_name"],
            HistoryItemType=params.get("type", "StateUpdate"),
            MaxRecords=int(params.get("max", 20)),
        )
        return {
            "history": [{
                "ts": _ts(h["Timestamp"]),
                "summary": h["HistorySummary"],
                "type": h["HistoryItemType"],
            } for h in resp.get("AlarmHistoryItems", [])]
        }

    return {"error": f"unknown tool: {tool!r}"}
