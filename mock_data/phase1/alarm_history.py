"""
Phase 1 mock — CloudWatch DescribeAlarms + DescribeAlarmHistory 샘플 데이터.

실제 CloudWatch API와 동일한 PascalCase 필드 구조로 작성. 5개 알람, 24개 이벤트
(전부 손으로 작성 — 처음 보는 사람이 위에서 아래로 한 번에 읽힘).

`ack` / `action_taken`은 CloudWatch에 없는 합성 필드. 실 운영에서는 PagerDuty 등
incident management 시스템에서 fused됨. Phase 2의 history mock Lambda Target은
동일 shape를 반환하도록 구현된다.

기준일(NOW) = 2026-05-03 12:00 UTC. 7일 cutoff = 2026-04-26 12:00 UTC.

분포: real 2 + noise 3 (threshold_uplift × 1, time_window_exclude × 1, rule_retirement × 1).

─── 알람 상태 머신 (CloudWatch) ─────────────────────────────
    [OK] ── 임계값 초과 ──> [ALARM] ── 임계값 회복 ──> [OK]
                            ↑                          ↑
                           fire                     recovery
HistorySummary 문자열로 표현됨:
  fire     = "Alarm updated from OK to ALARM"
  recovery = "Alarm updated from ALARM to OK"

─── auto-resolve 패턴 (noise 신호) ──────────────────────────
fire 발생 후 사람이 ack 하지 않은 채 메트릭이 다시 임계값 아래로 떨어져
ALARM→OK 로 돌아오는 경우. ack=False, action_taken=False 인 fire/recovery 쌍.

예: web-server-memory-routine
  04-30 11:05  OK→ALARM    ack=False    # 메모리 70% 초과 fire
  04-30 11:07  ALARM→OK    ack=False    # 2분 만에 70% 미만, 아무도 안 봄 = auto-resolved
  ... (7일간 4회 반복, 모두 동일 패턴)

자동 해소 비율이 매우 높다 = 임계값이 정상 운영 범위 안에 있다는 뜻 =
실제 문제가 아닌데 알람만 울림 = noise. 그래서 threshold_uplift 권고가 나옴.

─── ack / action_taken 은 어디서 오는가 ─────────────────────
실 운영 플로우 (mock에선 사전 라벨, Phase 2+ 에선 PD API ↔ CW history join):

  [CW Alarm fires] → SNS Topic → [PagerDuty/Opsgenie] → 엔지니어 휴대폰 page
                                                              │
                          ack=True ◀── PD 앱에서 "Acknowledge" 탭
                                                              │
                                              SSH/runbook 실행 (조치)
                                                              │
                action_taken=True ◀── PD "Resolved with action" 클릭
                                       또는 ChatOps `/resolve`
                                       또는 Jira/ServiceNow ticket close

필드 매핑:
  ack          ← PD incident.acknowledged_at (fire timestamp 윈도우와 join)
  action_taken ← PD incident.resolution == "manually_resolved" (vs "auto_resolved")
                 또는 runbook 실행 로그(Systems Manager Run Command, AWS Incident Manager)
                 또는 ticket resolution = "Done"

noise 알람은 page는 가지만 엔지니어가 "또 그 알람" 하며 무시 →
PD에서 auto_resolved 로 종료되어 ack=False, action_taken=False 로 기록됨.
"""
from typing import List, Dict, Optional


# ─── Alarms (CloudWatch DescribeAlarms 포맷) ───────────────

ALARMS: List[Dict] = [
    # ─ REAL: 사람이 ack + 조치한 진짜 알람 ────────────
    {
        "AlarmName": "web-server-cpu-high",
        "AlarmDescription": "Web server CPU > 90% — investigate scale-up",
        "MetricName": "CPUUtilization",
        "Namespace": "AWS/EC2",
        "Dimensions": [{"Name": "InstanceId", "Value": "i-0abc123web00"}],
        "Statistic": "Average",
        "Period": 60,
        "EvaluationPeriods": 5,
        "Threshold": 90.0,
        "ComparisonOperator": "GreaterThanThreshold",
        "AlarmConfigurationUpdatedTimestamp": "2026-04-26T00:00:00Z",  # 7d old
        "_classification": "real",
        "_diagnosis_type": None,
    },
    {
        "AlarmName": "payment-api-5xx-errors",
        "AlarmDescription": "Payment API 5XX error count spike",
        "MetricName": "HTTPCode_Target_5XX_Count",
        "Namespace": "AWS/ApplicationELB",
        "Dimensions": [{"Name": "LoadBalancer", "Value": "app/payment-api/abc"}],
        "Statistic": "Sum",
        "Period": 60,
        "EvaluationPeriods": 3,
        "Threshold": 10.0,
        "ComparisonOperator": "GreaterThanThreshold",
        "AlarmConfigurationUpdatedTimestamp": "2026-04-19T00:00:00Z",  # 14d old
        "_classification": "real",
        "_diagnosis_type": None,
    },

    # ─ NOISE/threshold_uplift: 임계값이 너무 낮아 자주 발화 ───
    # 시나리오: 메모리 70%는 이 워크로드의 정상 운영 범위 → 90%로 상향 필요
    {
        "AlarmName": "web-server-memory-routine",
        "AlarmDescription": "Web server memory > 70% (fires routinely)",
        "MetricName": "MemoryUtilization",
        "Namespace": "CWAgent",
        "Dimensions": [{"Name": "InstanceId", "Value": "i-0abc123web00"}],
        "Statistic": "Average",
        "Period": 60,
        "EvaluationPeriods": 1,
        "Threshold": 70.0,
        "ComparisonOperator": "GreaterThanThreshold",
        "AlarmConfigurationUpdatedTimestamp": "2026-03-04T00:00:00Z",  # 60d old
        "_classification": "noise",
        "_diagnosis_type": "threshold_uplift",
    },

    # ─ NOISE/time_window_exclude: 매일 같은 시간대만 발화 ────
    # 시나리오: 야간 배치(02-04 UTC)가 CPU 급등시키는 정상 패턴
    {
        "AlarmName": "nightly-batch-cpu",
        "AlarmDescription": "Batch instance CPU > 80%",
        "MetricName": "CPUUtilization",
        "Namespace": "AWS/EC2",
        "Dimensions": [{"Name": "InstanceId", "Value": "i-0batch00000000"}],
        "Statistic": "Average",
        "Period": 60,
        "EvaluationPeriods": 5,
        "Threshold": 80.0,
        "ComparisonOperator": "GreaterThanThreshold",
        "AlarmConfigurationUpdatedTimestamp": "2026-04-03T00:00:00Z",  # 30d old
        "_classification": "noise",
        "_diagnosis_type": "time_window_exclude",
        "_window_utc": (2, 4),
    },

    # ─ NOISE/rule_retirement: 100일째 거의 안 발화하고 아무도 안 봄 ─
    # 시나리오: 2018년 만든 알람, 해당 서버는 이미 폐기 직전
    {
        "AlarmName": "legacy-2018-server-cpu",
        "AlarmDescription": "Legacy 2018 server CPU > 70%",
        "MetricName": "CPUUtilization",
        "Namespace": "AWS/EC2",
        "Dimensions": [{"Name": "InstanceId", "Value": "i-0legacy0000000"}],
        "Statistic": "Average",
        "Period": 60,
        "EvaluationPeriods": 5,
        "Threshold": 70.0,
        "ComparisonOperator": "GreaterThanThreshold",
        "AlarmConfigurationUpdatedTimestamp": "2026-01-23T00:00:00Z",  # 100d old
        "_classification": "noise",
        "_diagnosis_type": "rule_retirement",
    },
]


# ─── History events (CloudWatch DescribeAlarmHistory 포맷) ────
#
# 각 fire = 2 events (OK→ALARM, ALARM→OK). 7일 윈도우 (04-26 ~ 05-03).
# real 알람은 ack=True+action_taken=True, noise는 ack=False+action_taken=False.

HISTORY: List[Dict] = [
    # web-server-cpu-high (real, 2 fires)
    {"AlarmName": "web-server-cpu-high", "Timestamp": "2026-04-29T09:15:00Z",
     "HistoryItemType": "StateUpdate", "HistorySummary": "Alarm updated from OK to ALARM",
     "ack": True, "action_taken": True},
    {"AlarmName": "web-server-cpu-high", "Timestamp": "2026-04-29T10:05:00Z",
     "HistoryItemType": "StateUpdate", "HistorySummary": "Alarm updated from ALARM to OK",
     "ack": True, "action_taken": True},
    {"AlarmName": "web-server-cpu-high", "Timestamp": "2026-05-02T14:30:00Z",
     "HistoryItemType": "StateUpdate", "HistorySummary": "Alarm updated from OK to ALARM",
     "ack": True, "action_taken": True},
    {"AlarmName": "web-server-cpu-high", "Timestamp": "2026-05-02T15:10:00Z",
     "HistoryItemType": "StateUpdate", "HistorySummary": "Alarm updated from ALARM to OK",
     "ack": True, "action_taken": True},

    # payment-api-5xx-errors (real, 2 fires)
    {"AlarmName": "payment-api-5xx-errors", "Timestamp": "2026-04-28T11:00:00Z",
     "HistoryItemType": "StateUpdate", "HistorySummary": "Alarm updated from OK to ALARM",
     "ack": True, "action_taken": True},
    {"AlarmName": "payment-api-5xx-errors", "Timestamp": "2026-04-28T11:50:00Z",
     "HistoryItemType": "StateUpdate", "HistorySummary": "Alarm updated from ALARM to OK",
     "ack": True, "action_taken": True},
    {"AlarmName": "payment-api-5xx-errors", "Timestamp": "2026-05-01T20:45:00Z",
     "HistoryItemType": "StateUpdate", "HistorySummary": "Alarm updated from OK to ALARM",
     "ack": True, "action_taken": True},
    {"AlarmName": "payment-api-5xx-errors", "Timestamp": "2026-05-01T21:30:00Z",
     "HistoryItemType": "StateUpdate", "HistorySummary": "Alarm updated from ALARM to OK",
     "ack": True, "action_taken": True},

    # web-server-memory-routine (threshold_uplift, 4 fires, 0 ack, auto-resolve in ~2min)
    {"AlarmName": "web-server-memory-routine", "Timestamp": "2026-04-30T11:05:00Z",
     "HistoryItemType": "StateUpdate", "HistorySummary": "Alarm updated from OK to ALARM",
     "ack": False, "action_taken": False},
    {"AlarmName": "web-server-memory-routine", "Timestamp": "2026-04-30T11:07:00Z",
     "HistoryItemType": "StateUpdate", "HistorySummary": "Alarm updated from ALARM to OK",
     "ack": False, "action_taken": False},
    {"AlarmName": "web-server-memory-routine", "Timestamp": "2026-05-01T16:20:00Z",
     "HistoryItemType": "StateUpdate", "HistorySummary": "Alarm updated from OK to ALARM",
     "ack": False, "action_taken": False},
    {"AlarmName": "web-server-memory-routine", "Timestamp": "2026-05-01T16:22:00Z",
     "HistoryItemType": "StateUpdate", "HistorySummary": "Alarm updated from ALARM to OK",
     "ack": False, "action_taken": False},
    {"AlarmName": "web-server-memory-routine", "Timestamp": "2026-05-02T13:45:00Z",
     "HistoryItemType": "StateUpdate", "HistorySummary": "Alarm updated from OK to ALARM",
     "ack": False, "action_taken": False},
    {"AlarmName": "web-server-memory-routine", "Timestamp": "2026-05-02T13:47:00Z",
     "HistoryItemType": "StateUpdate", "HistorySummary": "Alarm updated from ALARM to OK",
     "ack": False, "action_taken": False},
    {"AlarmName": "web-server-memory-routine", "Timestamp": "2026-05-03T08:12:00Z",
     "HistoryItemType": "StateUpdate", "HistorySummary": "Alarm updated from OK to ALARM",
     "ack": False, "action_taken": False},
    {"AlarmName": "web-server-memory-routine", "Timestamp": "2026-05-03T08:14:00Z",
     "HistoryItemType": "StateUpdate", "HistorySummary": "Alarm updated from ALARM to OK",
     "ack": False, "action_taken": False},

    # nightly-batch-cpu (time_window_exclude, 3 fires, all UTC 02-04)
    {"AlarmName": "nightly-batch-cpu", "Timestamp": "2026-04-30T02:45:00Z",
     "HistoryItemType": "StateUpdate", "HistorySummary": "Alarm updated from OK to ALARM",
     "ack": False, "action_taken": False},
    {"AlarmName": "nightly-batch-cpu", "Timestamp": "2026-04-30T03:50:00Z",
     "HistoryItemType": "StateUpdate", "HistorySummary": "Alarm updated from ALARM to OK",
     "ack": False, "action_taken": False},
    {"AlarmName": "nightly-batch-cpu", "Timestamp": "2026-05-01T02:15:00Z",
     "HistoryItemType": "StateUpdate", "HistorySummary": "Alarm updated from OK to ALARM",
     "ack": False, "action_taken": False},
    {"AlarmName": "nightly-batch-cpu", "Timestamp": "2026-05-01T03:30:00Z",
     "HistoryItemType": "StateUpdate", "HistorySummary": "Alarm updated from ALARM to OK",
     "ack": False, "action_taken": False},
    {"AlarmName": "nightly-batch-cpu", "Timestamp": "2026-05-02T02:30:00Z",
     "HistoryItemType": "StateUpdate", "HistorySummary": "Alarm updated from OK to ALARM",
     "ack": False, "action_taken": False},
    {"AlarmName": "nightly-batch-cpu", "Timestamp": "2026-05-02T03:45:00Z",
     "HistoryItemType": "StateUpdate", "HistorySummary": "Alarm updated from ALARM to OK",
     "ack": False, "action_taken": False},

    # legacy-2018-server-cpu (rule_retirement, 1 fire, 0 ack)
    {"AlarmName": "legacy-2018-server-cpu", "Timestamp": "2026-04-29T15:23:00Z",
     "HistoryItemType": "StateUpdate", "HistorySummary": "Alarm updated from OK to ALARM",
     "ack": False, "action_taken": False},
    {"AlarmName": "legacy-2018-server-cpu", "Timestamp": "2026-04-29T15:55:00Z",
     "HistoryItemType": "StateUpdate", "HistorySummary": "Alarm updated from ALARM to OK",
     "ack": False, "action_taken": False},
]


# ─── Public accessors ────────────────────────────────

def get_past_alarms_metadata() -> List[Dict]:
    """Public alarm metadata — ground truth(_*) 필드 제외."""
    return [
        {k: v for k, v in alarm.items() if not k.startswith("_")}
        for alarm in ALARMS
    ]


def get_past_alarm_history(days: int = 7) -> List[Dict]:
    """`days`일 이내 history 이벤트만 반환. 전체 데이터가 7일 이내라 days>=7이면 전체 반환."""
    if days >= 7:
        return list(HISTORY)
    # NOW = 2026-05-03 12:00 UTC. cutoff timestamp.
    import datetime
    now = datetime.datetime(2026, 5, 3, 12, 0, 0, tzinfo=datetime.timezone.utc)
    cutoff = (now - datetime.timedelta(days=days)).isoformat().replace("+00:00", "Z")
    return [e for e in HISTORY if e["Timestamp"] >= cutoff]


def get_past_ground_truth() -> Dict[str, Dict[str, Optional[str]]]:
    """테스트 전용 — 분류 라벨 (실 Agent 호출 시엔 노출 안 됨)."""
    return {
        alarm["AlarmName"]: {
            "classification": alarm["_classification"],
            "diagnosis_type": alarm["_diagnosis_type"],
        }
        for alarm in ALARMS
    }
