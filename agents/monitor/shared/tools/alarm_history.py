"""Strands @tool wrappers — Phase 1 frozen baseline path.

mock_data 의 두 단위 함수를 1:1 매핑하는 두 개의 @tool. Phase 2 mode=past
Gateway 도구와 도구 명·응답 shape 가 동일 — `run_local_import.py` (baseline) 와
Phase 2 mode=past 가 같은 system_prompt 를 공유 가능.
"""
from typing import Dict, List

from strands import tool

from mock_data.phase1.alarm_history import (
    get_past_alarm_history as _mock_get_past_alarm_history,
    get_past_alarms_metadata as _mock_get_past_alarms_metadata,
)


@tool
def get_past_alarms_metadata() -> Dict[str, List[Dict]]:
    """과거 5개 mock 알람의 metadata 를 반환한다.

    응답 shape: ``{"alarms": [...]}`` — Phase 2 mode=past Gateway 의 동일 도구와
    byte-level 동일. 각 entry 는 CloudWatch DescribeAlarms PascalCase 필드 +
    ``Tags.Classification`` 합성 필드 (ground truth ``_*`` 필드는 strip 됨).
    """
    return {"alarms": _mock_get_past_alarms_metadata()}


@tool
def get_past_alarm_history(days: int = 7) -> Dict[str, List[Dict]]:
    """과거 mock history 이벤트 (시간 윈도우 필터) 를 반환한다.

    Args:
        days: 최근 며칠 분 history 반환. 7 이상이면 전체.

    Returns:
        ``{"events": [...]}`` — 각 event 는 ``AlarmName``/``Timestamp``/
        ``HistoryItemType``/``HistorySummary`` 와 합성 필드 ``ack``/``action_taken``
        포함. Phase 2 mode=past Gateway 의 동일 도구와 byte-level 동일.
    """
    return {"events": _mock_get_past_alarm_history(days=days)}
