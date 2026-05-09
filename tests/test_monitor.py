"""
Phase 1 — Monitor Agent mock 데이터 검증.

LLM 호출은 비용·비결정성 때문에 unit test에서 제외 — `agents/monitor/local/run.py` 수동 실행으로 검증.
이 파일은 mock 데이터의 ground truth + 통계 집계 결과가 3가지 진단 유형 정의와 일치하는지 검증.
"""
import datetime
from collections import Counter

import pytest

from data.mock.phase1.alarm_history import (
    ALARMS,
    HISTORY,
    get_past_alarms_metadata,
    get_past_alarm_history,
    get_past_ground_truth,
)


# ─── Mock 데이터 형식 / 분포 ────────────────────────

def test_alarm_count():
    assert len(ALARMS) == 5


def test_alarm_real_noise_split():
    gt = get_past_ground_truth()
    real = sum(1 for v in gt.values() if v["classification"] == "real")
    noise = sum(1 for v in gt.values() if v["classification"] == "noise")
    assert real == 2
    assert noise == 3


def test_diagnosis_type_distribution():
    gt = get_past_ground_truth()
    counts = Counter(v["diagnosis_type"] for v in gt.values() if v["diagnosis_type"])
    assert counts["threshold_uplift"] == 1
    assert counts["time_window_exclude"] == 1
    assert counts["rule_retirement"] == 1
    assert "conditional_combine" not in counts  # 유형 제거됨


def test_history_size():
    assert len(HISTORY) == 24


def test_public_metadata_strips_ground_truth():
    public = get_past_alarms_metadata()
    for entry in public:
        assert all(not k.startswith("_") for k in entry), f"private 키 노출: {entry}"


def test_pascalcase_fields():
    """CloudWatch API와 동일한 PascalCase 필드 보장."""
    public = get_past_alarms_metadata()
    required = {"AlarmName", "MetricName", "Namespace", "Threshold",
                "ComparisonOperator", "AlarmConfigurationUpdatedTimestamp"}
    for entry in public:
        assert required.issubset(entry.keys()), f"필드 누락: {entry}"


# ─── 진단 유형별 패턴 통계 검증 ────────────────────

def _stats_for(alarm_name: str, days: int = 7):
    """7일 history에서 alarm별 통계 집계 (PascalCase + HistorySummary 기반)."""
    events = [e for e in get_past_alarm_history(days=days) if e["AlarmName"] == alarm_name]
    fires = [e for e in events if e["HistorySummary"] == "Alarm updated from OK to ALARM"]
    n_fires = len(fires)
    if n_fires == 0:
        return None
    auto_resolve = sum(1 for f in fires if not f["ack"])
    ack = sum(1 for f in fires if f["ack"])
    action = sum(1 for f in fires if f["action_taken"])
    return {
        "n_fires": n_fires,
        "auto_resolve_rate": auto_resolve / n_fires,
        "ack_rate": ack / n_fires,
        "action_rate": action / n_fires,
    }


@pytest.mark.parametrize("alarm_name", ["web-server-memory-routine"])
def test_threshold_uplift_pattern(alarm_name):
    """auto_resolve > 90%, ack < 5%."""
    s = _stats_for(alarm_name)
    assert s is not None
    assert s["auto_resolve_rate"] > 0.90, f"{alarm_name} auto_resolve={s['auto_resolve_rate']}"
    assert s["ack_rate"] < 0.05, f"{alarm_name} ack_rate={s['ack_rate']}"


@pytest.mark.parametrize("alarm_name,window", [("nightly-batch-cpu", (2, 4))])
def test_time_window_pattern(alarm_name, window):
    """특정 UTC 시간대 fire 비율 > 80%."""
    fires = [
        e for e in get_past_alarm_history(days=7)
        if e["AlarmName"] == alarm_name and e["HistorySummary"] == "Alarm updated from OK to ALARM"
    ]
    in_window = sum(
        1 for e in fires
        if window[0] <= datetime.datetime.fromisoformat(e["Timestamp"].replace("Z", "+00:00")).hour < window[1]
    )
    ratio = in_window / len(fires) if fires else 0
    assert ratio > 0.80, f"{alarm_name} in-window={ratio} (fires {len(fires)})"


@pytest.mark.parametrize("alarm_name", ["legacy-2018-server-cpu"])
def test_rule_retirement_pattern(alarm_name):
    """ack 0건 AND action 0건. alarm 자체가 90일+ 전 생성."""
    s = _stats_for(alarm_name)
    if s is not None:
        assert s["ack_rate"] == 0.0, f"{alarm_name} ack_rate={s['ack_rate']}"
        assert s["action_rate"] == 0.0, f"{alarm_name} action_rate={s['action_rate']}"

    alarm_meta = next(a for a in ALARMS if a["AlarmName"] == alarm_name)
    created = datetime.datetime.fromisoformat(
        alarm_meta["AlarmConfigurationUpdatedTimestamp"].replace("Z", "+00:00")
    )
    now = datetime.datetime(2026, 5, 3, 12, 0, 0, tzinfo=datetime.timezone.utc)
    age_days = (now - created).days
    assert age_days >= 90, f"{alarm_name} age={age_days}"


@pytest.mark.parametrize("alarm_name", ["web-server-cpu-high", "payment-api-5xx-errors"])
def test_real_pattern(alarm_name):
    """real: 진단 유형 어디에도 매칭 안 됨. ack_rate 높고 action 동반."""
    s = _stats_for(alarm_name)
    assert s is not None
    assert s["ack_rate"] >= 0.05, f"{alarm_name} ack_rate={s['ack_rate']}"
    assert s["action_rate"] >= 0.5, f"{alarm_name} action_rate={s['action_rate']}"
