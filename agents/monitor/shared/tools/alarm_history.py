"""
Strands tool: get_past_alarm_history.

Phase 1: mock_data/phase1/alarm_history.py를 직접 호출.
Phase 2: AgentCore Gateway의 history mock Lambda Target으로 외부화 — 응답 shape 동일.
"""
from typing import Dict, List
from strands import tool

from mock_data.phase1.alarm_history import (
    get_past_alarms_metadata,
    get_past_alarm_history as _mock_get_past_alarm_history,
)


@tool
def get_past_alarm_history(days: int = 7) -> Dict[str, List[Dict]]:
    """7일치 alarm 메타데이터와 상태 변경 history를 반환합니다.

    응답 shape는 AWS CloudWatch DescribeAlarms / DescribeAlarmHistory API 형식
    (PascalCase 필드)을 따른다. `ack` / `action_taken`은 CW에 없는 합성 필드로,
    실 운영에서는 PagerDuty 등 incident management 시스템에서 fused됨.

    Args:
        days: 몇 일치 history를 가져올지 (기본 7일).

    Returns:
        dict with keys:
            - alarms: [{AlarmName, AlarmDescription, MetricName, Namespace, Dimensions,
                        Statistic, Period, EvaluationPeriods, Threshold,
                        ComparisonOperator, AlarmConfigurationUpdatedTimestamp}, ...]
            - history: [{AlarmName, Timestamp, HistoryItemType, HistorySummary,
                         ack, action_taken}, ...]
    """
    return {
        "alarms": get_past_alarms_metadata(),
        "history": _mock_get_past_alarm_history(days=days),
    }
