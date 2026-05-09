"""history-mock Lambda — Phase 1 data/mock 를 Gateway Target 으로 노출.

AgentCore Gateway 호출 패턴 (boto3 ParamValidationError 발견 + 실측):
- tool 식별자: ``context.client_context.custom["bedrockAgentCoreToolName"]``
  (event 가 아닌 Lambda invoke metadata 에 들어옴, 형식 ``<target>___<tool>``)
- input: ``event`` 자체가 inputSchema.properties 의 값 dict (parameters/input wrapper 없음)

vendoring (deploy.sh 가 처리):
    cp -r data/mock/phase1 infra/cognito-gateway/lambda/history_mock/data/mock/phase1
    + infra/cognito-gateway/lambda/history_mock/data/mock/__init__.py 생성

import path 는 Phase 1 unit test 와 동일 — 단일 진실 원천 유지.
"""
from data.mock.phase1.alarm_history import (
    get_past_alarm_history,
    get_past_alarms_metadata,
)


def _tool_name(context) -> str:
    cc = getattr(context, "client_context", None)
    custom = getattr(cc, "custom", None) if cc else None
    return (custom or {}).get("bedrockAgentCoreToolName", "")


def lambda_handler(event, context):
    tool = _tool_name(context)
    params = event or {}

    if tool.endswith("get_past_alarms_metadata"):
        return {"alarms": get_past_alarms_metadata()}

    if tool.endswith("get_past_alarm_history"):
        days = int(params.get("days", 7))
        return {"events": get_past_alarm_history(days=days)}

    return {"error": f"unknown tool: {tool!r}"}
