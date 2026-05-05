"""Contract tests for tools/cloudwatch_mock.py.

Guarantees the tool response shape matches what agent/rule_optimizer.py and
the Gateway OpenAPI schema expect.
"""
from __future__ import annotations

from tools.cloudwatch_mock import (
    describe_alarm_history,
    describe_alarms,
    get_alarm_statistics,
)


def test_describe_alarms_returns_metric_alarms():
    resp = describe_alarms()
    assert "MetricAlarms" in resp
    assert len(resp["MetricAlarms"]) == 15
    # composite is always present in CloudWatch response
    assert resp.get("CompositeAlarms") == []


def test_describe_alarms_filter_by_name():
    resp = describe_alarms(alarm_names=["waf-blocked-requests"])
    assert len(resp["MetricAlarms"]) == 1
    assert resp["MetricAlarms"][0]["AlarmName"] == "waf-blocked-requests"


def test_history_strips_mock_only_fields():
    resp = describe_alarm_history()
    items = resp["AlarmHistoryItems"]
    assert items
    for it in items:
        assert all(not k.startswith("_") for k in it.keys()), f"leaked mock-only key in {it}"
        assert set(it.keys()) >= {"AlarmName", "Timestamp", "HistoryItemType", "HistorySummary"}


def test_history_filters_by_alarm_and_time():
    resp = describe_alarm_history(alarm_name="waf-blocked-requests", max_records=50)
    items = resp["AlarmHistoryItems"]
    assert items
    assert all(it["AlarmName"] == "waf-blocked-requests" for it in items)
    assert len(items) <= 50


def test_statistics_shape():
    resp = get_alarm_statistics()
    assert resp["period_days"] == 7
    assert len(resp["alarms"]) == 15
    for s in resp["alarms"]:
        assert {"AlarmName", "fires", "auto_resolve_rate", "avg_duration_minutes",
                "ack_ratio_7d", "hour_of_day_distribution", "peak_hours",
                "threshold", "comparison_operator"} <= s.keys()


def test_statistics_fire_counts_match_plan():
    """Plan §5 fire counts are the authoritative numbers."""
    resp = get_alarm_statistics()
    expected = {
        "payment-api-5xx-rate": 3,
        "ec2-cpu-high-web-fleet": 142,
        "rds-prod-cpu": 5,
        "lambda-checkout-errors": 87,
        "alb-target-5xx": 56,
        "nightly-batch-cpu-spike": 49,
        "deploy-time-5xx": 34,
        "dynamodb-throttle-orders": 8,
        "sqs-queue-depth-legacy-v1": 21,
        "old-ec2-status-check": 18,
        "api-latency-p99": 7,
        "ecs-memory-web": 98,
        "s3-4xx-public-bucket": 41,
        "rds-connections-high": 63,
        "waf-blocked-requests": 204,
    }
    got = {s["AlarmName"]: s["fires"] for s in resp["alarms"]}
    assert got == expected
