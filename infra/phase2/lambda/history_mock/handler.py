"""history-mock Lambda — Phase 1 mock_data 를 Gateway Target 으로 노출.

vendoring (deploy.sh 가 처리):
    cp -r mock_data/phase1 infra/phase2/lambda/history_mock/mock_data/phase1
    + infra/phase2/lambda/history_mock/mock_data/__init__.py 생성

import path 는 Phase 1 unit test 와 동일 — 단일 진실 원천 유지.
"""
from mock_data.phase1.alarm_history import (
    get_past_alarm_history,
    get_past_alarms_metadata,
)


def lambda_handler(event, context):
    tool = event.get("tool_name")
    params = event.get("input", {})

    if tool == "get_past_alarms_metadata":
        return {"alarms": get_past_alarms_metadata()}

    if tool == "get_past_alarm_history":
        days = int(params.get("days", 7))
        return {"events": get_past_alarm_history(days=days)}

    return {"error": f"unknown tool: {tool}"}
