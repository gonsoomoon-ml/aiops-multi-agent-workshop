"""CloudWatch Alarm mock tool — Tool #1 of the Rule Optimization Agent.

Exposes three entry points:

- describe_alarms(alarm_names=None) — CloudWatch `DescribeAlarms` compatible.
- describe_alarm_history(alarm_name=None, start_time=None, end_time=None)
    — CloudWatch `DescribeAlarmHistory` compatible, narrowed to StateUpdate events.
- get_alarm_statistics(alarm_name=None, period_days=7)
    — Analysis helper (not a real CloudWatch API). Pre-aggregates per-alarm metrics
      so the Agent can reason about patterns without crunching ~1700 events.
      Bonus lab's real-data path implements the exact same shape on top of boto3.

All three are Strands-compatible tools via the `@tool` decorator.
"""
from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

try:
    from strands import tool
except Exception:  # pragma: no cover — allow import outside Strands env
    def tool(fn):  # type: ignore
        return fn

from mock_data.alarms import ALARMS, HISTORY, NOW


_DATETIME_FIELDS = {"Timestamp", "StateUpdatedTimestamp"}


def _serialize(obj: Any) -> Any:
    """Recursively convert datetimes to ISO strings so responses are JSON-safe."""
    if isinstance(obj, datetime):
        return obj.isoformat().replace("+00:00", "Z")
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize(v) for v in obj]
    return obj


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# Canonical CloudWatch-compatible methods
# ---------------------------------------------------------------------------

@tool
def describe_alarms(alarm_names: list[str] | None = None) -> dict[str, Any]:
    """Return metric alarm definitions, mirroring `cloudwatch:DescribeAlarms`.

    Args:
        alarm_names: Optional list of AlarmName strings to filter by. If None,
            all alarms are returned.

    Returns:
        Dict with key `MetricAlarms` (list of alarm docs). Schema matches AWS
        CloudWatch, plus Mock-only auxiliary fields prefixed `_` (`_tags`,
        `_ack_ratio_7d`, `_last_ack_days_ago`). The Bonus lab's real-data
        version drops these aux fields.
    """
    if alarm_names:
        wanted = set(alarm_names)
        metric_alarms = [a for a in ALARMS if a["AlarmName"] in wanted]
    else:
        metric_alarms = list(ALARMS)
    return _serialize({"MetricAlarms": metric_alarms, "CompositeAlarms": []})


@tool
def describe_alarm_history(
    alarm_name: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    max_records: int = 1000,
) -> dict[str, Any]:
    """Return alarm state-change history, mirroring `cloudwatch:DescribeAlarmHistory`.

    Args:
        alarm_name: Optional AlarmName to filter by. If None, events for all
            15 alarms are returned.
        start_time: ISO-8601 string. Defaults to 7 days before "now".
        end_time: ISO-8601 string. Defaults to "now".
        max_records: Cap on returned events (default 1000).

    Returns:
        Dict with `AlarmHistoryItems` (list) matching AWS schema:
        `AlarmName`, `AlarmType`, `Timestamp`, `HistoryItemType`,
        `HistorySummary`, `HistoryData`.
    """
    start_dt = _parse_ts(start_time) or (NOW - timedelta(days=7))
    end_dt = _parse_ts(end_time) or NOW

    items = [
        e for e in HISTORY
        if (alarm_name is None or e["AlarmName"] == alarm_name)
        and start_dt <= e["Timestamp"] <= end_dt
    ]
    items = items[:max_records]
    # Strip Mock-only `_auto_resolved` flag from wire response to mirror AWS
    clean = [
        {k: v for k, v in e.items() if not k.startswith("_")}
        for e in items
    ]
    return _serialize({"AlarmHistoryItems": clean})


# ---------------------------------------------------------------------------
# Analysis helper (not a real CloudWatch API)
# ---------------------------------------------------------------------------

def _bucket_hour(ts: datetime) -> int:
    kst = timezone(timedelta(hours=9))
    return ts.astimezone(kst).hour


def _is_weekend(ts: datetime) -> bool:
    kst = timezone(timedelta(hours=9))
    return ts.astimezone(kst).weekday() >= 5


@tool
def get_alarm_statistics(alarm_name: str | None = None, period_days: int = 7) -> dict[str, Any]:
    """Pre-aggregated per-alarm metrics over the last `period_days`.

    NOTE: This is NOT a CloudWatch API — it's a Mock/Lambda-provided helper so
    the Agent can reason about noise patterns without counting ~1700 events in
    context. The Bonus lab implements identical shape on top of boto3.

    Returns for each alarm:

        {
            "AlarmName": str,
            "fires": int,
            "auto_resolve_rate": float,
            "avg_duration_minutes": float,
            "ack_ratio_7d": float,
            "last_ack_days_ago": int | None,
            "hour_of_day_distribution": {0: n, 1: n, ... 23: n},
            "weekday_vs_weekend": {"weekday": n, "weekend": n},
            "peak_hours": [list of hour buckets with >= 30% of fires],
            "threshold": float,
            "comparison_operator": str,
            "metric": str,
            "namespace": str,
            "tags": dict,
            "state_value": str,
        }
    """
    cutoff = NOW - timedelta(days=period_days)
    alarms_by_name = {a["AlarmName"]: a for a in ALARMS}
    fires_by_alarm: dict[str, list[dict]] = defaultdict(list)

    # pair ALARM -> OK events to compute duration
    alarm_events: dict[str, dict | None] = defaultdict(lambda: None)
    pairs_by_alarm: dict[str, list[tuple[dict, dict | None]]] = defaultdict(list)

    for ev in HISTORY:
        if ev["Timestamp"] < cutoff:
            continue
        summary = ev.get("HistorySummary", "")
        if "from OK to ALARM" in summary:
            alarm_events[ev["AlarmName"]] = ev
        elif "from ALARM to OK" in summary:
            start = alarm_events[ev["AlarmName"]]
            alarm_events[ev["AlarmName"]] = None
            pairs_by_alarm[ev["AlarmName"]].append((start, ev))
        fires_by_alarm  # noqa: B018

    target_names = [alarm_name] if alarm_name else [a["AlarmName"] for a in ALARMS]

    result_list = []
    for name in target_names:
        spec = alarms_by_name.get(name)
        if not spec:
            continue
        pairs = pairs_by_alarm.get(name, [])
        fires = len(pairs)
        auto_count = sum(1 for _, ok_ev in pairs if ok_ev and ok_ev.get("_auto_resolved"))
        auto_rate = (auto_count / fires) if fires else 0.0

        durations: list[float] = []
        hours = Counter()
        weekday_count = 0
        weekend_count = 0
        for start_ev, ok_ev in pairs:
            if not start_ev or not ok_ev:
                continue
            delta = (ok_ev["Timestamp"] - start_ev["Timestamp"]).total_seconds() / 60.0
            if delta > 0:
                durations.append(delta)
            hours[_bucket_hour(start_ev["Timestamp"])] += 1
            if _is_weekend(start_ev["Timestamp"]):
                weekend_count += 1
            else:
                weekday_count += 1

        avg_duration = (sum(durations) / len(durations)) if durations else 0.0
        peak_hours = []
        if fires:
            threshold_cnt = max(1, int(fires * 0.25))  # "peak" = hours holding ≥25% of fires? — use relative threshold
            for h, cnt in hours.most_common():
                if cnt >= fires * 0.10:  # include hours with ≥10% of fires
                    peak_hours.append({"hour_kst": h, "fires": cnt, "pct": round(cnt / fires * 100, 1)})

        result_list.append(
            {
                "AlarmName": name,
                "fires": fires,
                "auto_resolve_rate": round(auto_rate, 3),
                "avg_duration_minutes": round(avg_duration, 2),
                "ack_ratio_7d": spec.get("_ack_ratio_7d", 0.0),
                "last_ack_days_ago": spec.get("_last_ack_days_ago"),
                "hour_of_day_distribution": dict(sorted(hours.items())),
                "weekday_vs_weekend": {"weekday": weekday_count, "weekend": weekend_count},
                "peak_hours": peak_hours,
                "threshold": spec["Threshold"],
                "comparison_operator": spec["ComparisonOperator"],
                "metric": spec["MetricName"],
                "namespace": spec["Namespace"],
                "tags": spec.get("_tags", {}),
                "state_value": spec.get("StateValue"),
            }
        )

    return {"alarms": result_list, "period_days": period_days, "generated_at": _serialize(NOW)}


if __name__ == "__main__":
    alarms = describe_alarms()
    print(f"describe_alarms: {len(alarms['MetricAlarms'])} alarms")
    hist = describe_alarm_history()
    print(f"describe_alarm_history: {len(hist['AlarmHistoryItems'])} events")
    stats = get_alarm_statistics()
    print(f"get_alarm_statistics: {len(stats['alarms'])} aggregated entries")
    # Show stats for the noisy web alarm
    for s in stats["alarms"]:
        if s["AlarmName"] == "ec2-cpu-high-web-fleet":
            print(json.dumps(s, indent=2, default=str))
            break
