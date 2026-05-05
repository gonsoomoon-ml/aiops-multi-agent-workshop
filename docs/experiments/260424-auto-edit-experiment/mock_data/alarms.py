"""Synthetic CloudWatch Alarm dataset backing the Noise Alarm demo.

Matches plan.md §5 exactly: 15 alarms whose per-alarm fire counts, ack ratios,
time-of-day distribution, and expected classifications are fixed and deterministic
(seeded random). Consumed by tools/cloudwatch_mock.py which exposes it through
CloudWatch-compatible method names (`describe_alarms`, `describe_alarm_history`).

Mock-only auxiliary fields (prefixed with `_`) carry metadata that AWS CloudWatch
does not provide natively (`_ack_ratio_7d`, `_tags`, `_last_ack_days_ago`).
Bonus lab replaces this module with real AWS data and must strip these fields.
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from typing import Any

# "현재 시각" 을 고정하여 데모 재현성 확보. plan.md 상의 today = 2026-04-23.
NOW = datetime(2026, 4, 23, 9, 0, 0, tzinfo=timezone.utc)
WINDOW_START = NOW - timedelta(days=7)

_KST = timezone(timedelta(hours=9))

# ---------------------------------------------------------------------------
# Alarm definitions (mirror plan.md §5 table)
# ---------------------------------------------------------------------------

_ALARM_SPECS: list[dict[str, Any]] = [
    {
        "AlarmName": "payment-api-5xx-rate",
        "AlarmDescription": "Payment APIGW 5XX rate > 10/min for 5 minutes",
        "Namespace": "AWS/ApiGateway",
        "MetricName": "5XXError",
        "Statistic": "Sum",
        "Dimensions": [{"Name": "ApiName", "Value": "payment-api"}],
        "Period": 60,
        "EvaluationPeriods": 5,
        "Threshold": 10.0,
        "ComparisonOperator": "GreaterThanThreshold",
        "fires": 3,
        "auto_resolve_rate": 0.0,
        "avg_duration_min": 22,
        "ack_ratio": 1.00,
        "pattern": "uniform",
        "tags": {"service": "payment", "env": "prod", "team": "payments"},
    },
    {
        "AlarmName": "ec2-cpu-high-web-fleet",
        "AlarmDescription": "Web fleet CPU > 70% for 5 minutes",
        "Namespace": "AWS/EC2",
        "MetricName": "CPUUtilization",
        "Statistic": "Average",
        "Dimensions": [{"Name": "AutoScalingGroupName", "Value": "web-asg"}],
        "Period": 300,
        "EvaluationPeriods": 1,
        "Threshold": 70.0,
        "ComparisonOperator": "GreaterThanThreshold",
        "fires": 142,
        "auto_resolve_rate": 0.96,
        "avg_duration_min": 4,
        "ack_ratio": 0.02,
        "pattern": "business_peaks",
        "tags": {"service": "web", "env": "prod", "team": "platform"},
    },
    {
        "AlarmName": "rds-prod-cpu",
        "AlarmDescription": "RDS instance CPU > 90% for 5 minutes",
        "Namespace": "AWS/RDS",
        "MetricName": "CPUUtilization",
        "Statistic": "Average",
        "Dimensions": [{"Name": "DBInstanceIdentifier", "Value": "prod-primary"}],
        "Period": 300,
        "EvaluationPeriods": 1,
        "Threshold": 90.0,
        "ComparisonOperator": "GreaterThanThreshold",
        "fires": 5,
        "auto_resolve_rate": 0.40,
        "avg_duration_min": 18,
        "ack_ratio": 1.00,
        "pattern": "uniform",
        "tags": {"service": "rds-prod", "env": "prod", "team": "data"},
    },
    {
        "AlarmName": "lambda-checkout-errors",
        "AlarmDescription": "Checkout Lambda Errors >= 1 per minute",
        "Namespace": "AWS/Lambda",
        "MetricName": "Errors",
        "Statistic": "Sum",
        "Dimensions": [{"Name": "FunctionName", "Value": "checkout-handler"}],
        "Period": 60,
        "EvaluationPeriods": 1,
        "Threshold": 1.0,
        "ComparisonOperator": "GreaterThanOrEqualToThreshold",
        "fires": 87,
        "auto_resolve_rate": 1.00,
        "avg_duration_min": 1,
        "ack_ratio": 0.00,
        "pattern": "uniform",
        "tags": {"service": "checkout", "env": "prod", "team": "payments"},
    },
    {
        "AlarmName": "alb-target-5xx",
        "AlarmDescription": "ALB target 5XX > 5 per 5 minutes",
        "Namespace": "AWS/ApplicationELB",
        "MetricName": "HTTPCode_Target_5XX_Count",
        "Statistic": "Sum",
        "Dimensions": [{"Name": "LoadBalancer", "Value": "app/web-alb/abc123"}],
        "Period": 300,
        "EvaluationPeriods": 1,
        "Threshold": 5.0,
        "ComparisonOperator": "GreaterThanThreshold",
        "fires": 56,
        "auto_resolve_rate": 0.89,
        "avg_duration_min": 3,
        "ack_ratio": 0.05,
        "pattern": "business_peaks",
        "tags": {"service": "web", "env": "prod", "team": "platform"},
    },
    {
        "AlarmName": "nightly-batch-cpu-spike",
        "AlarmDescription": "Batch fleet CPU > 80% for 5 minutes",
        "Namespace": "AWS/EC2",
        "MetricName": "CPUUtilization",
        "Statistic": "Average",
        "Dimensions": [{"Name": "AutoScalingGroupName", "Value": "batch-asg"}],
        "Period": 300,
        "EvaluationPeriods": 1,
        "Threshold": 80.0,
        "ComparisonOperator": "GreaterThanThreshold",
        "fires": 49,
        "auto_resolve_rate": 1.00,
        "avg_duration_min": 12,
        "ack_ratio": 0.00,
        "pattern": "nightly_batch",
        "tags": {"service": "batch", "env": "prod", "team": "data"},
    },
    {
        "AlarmName": "deploy-time-5xx",
        "AlarmDescription": "ALB 5XX > 3 per minute (deploy sensitivity)",
        "Namespace": "AWS/ApplicationELB",
        "MetricName": "HTTPCode_ELB_5XX_Count",
        "Statistic": "Sum",
        "Dimensions": [{"Name": "LoadBalancer", "Value": "app/api-alb/def456"}],
        "Period": 60,
        "EvaluationPeriods": 1,
        "Threshold": 3.0,
        "ComparisonOperator": "GreaterThanThreshold",
        "fires": 34,
        "auto_resolve_rate": 1.00,
        "avg_duration_min": 2,
        "ack_ratio": 0.00,
        "pattern": "deploy_windows",
        "tags": {"service": "api", "env": "prod", "team": "platform"},
    },
    {
        "AlarmName": "dynamodb-throttle-orders",
        "AlarmDescription": "DynamoDB orders table throttled > 0",
        "Namespace": "AWS/DynamoDB",
        "MetricName": "ThrottledRequests",
        "Statistic": "Sum",
        "Dimensions": [{"Name": "TableName", "Value": "orders"}],
        "Period": 60,
        "EvaluationPeriods": 1,
        "Threshold": 0.0,
        "ComparisonOperator": "GreaterThanThreshold",
        "fires": 8,
        "auto_resolve_rate": 0.50,
        "avg_duration_min": 9,
        "ack_ratio": 0.87,
        "pattern": "uniform",
        "tags": {"service": "orders", "env": "prod", "team": "orders"},
    },
    {
        "AlarmName": "sqs-queue-depth-legacy-v1",
        "AlarmDescription": "Legacy v1 SQS depth > 100",
        "Namespace": "AWS/SQS",
        "MetricName": "ApproximateNumberOfMessagesVisible",
        "Statistic": "Maximum",
        "Dimensions": [{"Name": "QueueName", "Value": "legacy-v1-events"}],
        "Period": 300,
        "EvaluationPeriods": 1,
        "Threshold": 100.0,
        "ComparisonOperator": "GreaterThanThreshold",
        "fires": 21,
        "auto_resolve_rate": 1.00,
        "avg_duration_min": 7,
        "ack_ratio": 0.00,
        "last_ack_days_ago": 90,
        "pattern": "uniform",
        "tags": {"service": "legacy-v1", "env": "prod", "team": "unknown"},
    },
    {
        "AlarmName": "old-ec2-status-check",
        "AlarmDescription": "Deprecated EC2 status check failure",
        "Namespace": "AWS/EC2",
        "MetricName": "StatusCheckFailed",
        "Statistic": "Sum",
        "Dimensions": [{"Name": "InstanceId", "Value": "i-0deadbeef0000001"}],
        "Period": 60,
        "EvaluationPeriods": 1,
        "Threshold": 0.0,
        "ComparisonOperator": "GreaterThanThreshold",
        "fires": 18,
        "auto_resolve_rate": 1.00,
        "avg_duration_min": 2,
        "ack_ratio": 0.00,
        "last_ack_days_ago": 120,
        "pattern": "uniform",
        "tags": {"service": "legacy-ec2", "env": "prod", "team": "unknown"},
    },
    {
        "AlarmName": "api-latency-p99",
        "AlarmDescription": "APIGW p99 latency > 2000ms",
        "Namespace": "AWS/ApiGateway",
        "MetricName": "Latency",
        "Statistic": "p99",
        "Dimensions": [{"Name": "ApiName", "Value": "public-api"}],
        "Period": 300,
        "EvaluationPeriods": 2,
        "Threshold": 2000.0,
        "ComparisonOperator": "GreaterThanThreshold",
        "fires": 7,
        "auto_resolve_rate": 0.57,
        "avg_duration_min": 14,
        "ack_ratio": 1.00,
        "pattern": "uniform",
        "tags": {"service": "api", "env": "prod", "team": "platform"},
    },
    {
        "AlarmName": "ecs-memory-web",
        "AlarmDescription": "ECS web service memory > 60%",
        "Namespace": "AWS/ECS",
        "MetricName": "MemoryUtilization",
        "Statistic": "Average",
        "Dimensions": [{"Name": "ServiceName", "Value": "web"}, {"Name": "ClusterName", "Value": "prod"}],
        "Period": 300,
        "EvaluationPeriods": 1,
        "Threshold": 60.0,
        "ComparisonOperator": "GreaterThanThreshold",
        "fires": 98,
        "auto_resolve_rate": 0.94,
        "avg_duration_min": 2,
        "ack_ratio": 0.03,
        "pattern": "business_peaks",
        "tags": {"service": "web", "env": "prod", "team": "platform"},
    },
    {
        "AlarmName": "s3-4xx-public-bucket",
        "AlarmDescription": "Public bucket 4XX > 20 / 5m",
        "Namespace": "AWS/S3",
        "MetricName": "4xxErrors",
        "Statistic": "Sum",
        "Dimensions": [
            {"Name": "BucketName", "Value": "public-assets"},
            {"Name": "FilterId", "Value": "EntireBucket"},
        ],
        "Period": 300,
        "EvaluationPeriods": 1,
        "Threshold": 20.0,
        "ComparisonOperator": "GreaterThanThreshold",
        "fires": 41,
        "auto_resolve_rate": 0.76,
        "avg_duration_min": 5,
        "ack_ratio": 0.12,
        "pattern": "uniform",
        "tags": {"service": "assets", "env": "prod", "team": "web"},
    },
    {
        "AlarmName": "rds-connections-high",
        "AlarmDescription": "RDS connections > 80",
        "Namespace": "AWS/RDS",
        "MetricName": "DatabaseConnections",
        "Statistic": "Average",
        "Dimensions": [{"Name": "DBInstanceIdentifier", "Value": "prod-primary"}],
        "Period": 300,
        "EvaluationPeriods": 1,
        "Threshold": 80.0,
        "ComparisonOperator": "GreaterThanThreshold",
        "fires": 63,
        "auto_resolve_rate": 1.00,
        "avg_duration_min": 8,
        "ack_ratio": 0.00,
        "pattern": "commute_peaks",
        "tags": {"service": "rds-prod", "env": "prod", "team": "data"},
    },
    {
        "AlarmName": "waf-blocked-requests",
        "AlarmDescription": "WAF blocked > 0",
        "Namespace": "AWS/WAFV2",
        "MetricName": "BlockedRequests",
        "Statistic": "Sum",
        "Dimensions": [{"Name": "WebACL", "Value": "prod-acl"}, {"Name": "Region", "Value": "us-west-2"}],
        "Period": 60,
        "EvaluationPeriods": 1,
        "Threshold": 0.0,
        "ComparisonOperator": "GreaterThanThreshold",
        "fires": 204,
        "auto_resolve_rate": 1.00,
        "avg_duration_min": 1,
        "ack_ratio": 0.00,
        "pattern": "constant_drizzle",
        "tags": {"service": "security", "env": "prod", "team": "security"},
    },
]


def _arn_for(name: str) -> str:
    return f"arn:aws:cloudwatch:us-west-2:123456789012:alarm:{name}"


def _in_window(dt: datetime) -> bool:
    return WINDOW_START <= dt <= NOW


def _pick_fire_times(pattern: str, count: int, rng: random.Random) -> list[datetime]:
    """Generate `count` fire start times within the 7-day window, shaped by pattern."""
    out: list[datetime] = []
    attempts = 0
    max_attempts = count * 50
    while len(out) < count and attempts < max_attempts:
        attempts += 1
        # pick a candidate time in KST for easier semantics, convert to UTC
        day_offset = rng.uniform(0, 7)
        ts_kst = WINDOW_START.astimezone(_KST) + timedelta(days=day_offset)

        if pattern == "uniform":
            candidate = ts_kst
        elif pattern == "business_peaks":
            # 60% in 09-11 or 14-16 weekdays, 40% random
            if rng.random() < 0.6:
                hour = rng.choice([9, 10, 14, 15])
                minute = rng.randint(0, 59)
                candidate = ts_kst.replace(hour=hour, minute=minute, second=rng.randint(0, 59))
                if candidate.weekday() >= 5:  # skip weekend
                    continue
            else:
                candidate = ts_kst
        elif pattern == "nightly_batch":
            # 02:00-04:00 KST, every night
            hour = rng.choice([2, 3])
            minute = rng.randint(0, 59)
            candidate = ts_kst.replace(hour=hour, minute=minute, second=rng.randint(0, 59))
        elif pattern == "deploy_windows":
            # Tue/Thu 14:00-15:00
            day = ts_kst.date()
            target_weekday = rng.choice([1, 3])  # Tue=1, Thu=3
            delta_days = (target_weekday - ts_kst.weekday()) % 7
            candidate = (ts_kst + timedelta(days=delta_days)).replace(
                hour=14, minute=rng.randint(0, 59), second=rng.randint(0, 59)
            )
        elif pattern == "commute_peaks":
            # 07-09 or 18-20 weekdays
            hour = rng.choice([7, 8, 18, 19])
            minute = rng.randint(0, 59)
            candidate = ts_kst.replace(hour=hour, minute=minute, second=rng.randint(0, 59))
            if candidate.weekday() >= 5:
                continue
        elif pattern == "constant_drizzle":
            # WAF: ~uniform with slight day-hour bias
            candidate = ts_kst
        else:
            candidate = ts_kst

        candidate_utc = candidate.astimezone(timezone.utc)
        if _in_window(candidate_utc):
            out.append(candidate_utc)

    out.sort()
    return out


def _state_reason(alarm: dict[str, Any], crossed: bool, value: float) -> str:
    op = alarm["ComparisonOperator"]
    th = alarm["Threshold"]
    if crossed:
        return (
            f"Threshold Crossed: 1 datapoint [{value:.2f}] was "
            f"{'greater than' if 'Greater' in op else 'less than'} the threshold ({th:.2f})."
        )
    return (
        f"Threshold Crossed: 1 datapoint [{value:.2f}] was not "
        f"{'greater than' if 'Greater' in op else 'less than'} the threshold ({th:.2f})."
    )


def _history_data(state: str, reason: str, value: float) -> str:
    return json.dumps(
        {
            "version": "1.0",
            "oldState": {"stateValue": "OK" if state == "ALARM" else "ALARM"},
            "newState": {"stateValue": state, "stateReason": reason},
            "dataPoints": [{"value": value}],
        }
    )


def generate_history(seed: int = 20260423) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Generate ALARMS (describe_alarms response items) and HISTORY (StateUpdate events).

    Deterministic given fixed seed. Returns the pair expected by the mock tool.
    """
    rng = random.Random(seed)
    alarms_out: list[dict[str, Any]] = []
    history_out: list[dict[str, Any]] = []

    for spec in _ALARM_SPECS:
        fires = spec["fires"]
        fire_times = _pick_fire_times(spec["pattern"], fires, rng)
        avg = spec["avg_duration_min"]
        auto_rate = spec["auto_resolve_rate"]

        last_state = "OK"
        last_ts = WINDOW_START - timedelta(hours=1)
        last_value_over = spec["Threshold"] * 1.1

        for fire_ts in fire_times:
            duration = max(1, int(rng.gauss(avg, max(1.0, avg * 0.4))))
            end_ts = fire_ts + timedelta(minutes=duration)
            if end_ts > NOW:
                end_ts = NOW - timedelta(seconds=1)

            over_val = spec["Threshold"] + abs(rng.gauss(spec["Threshold"] * 0.15, max(1.0, spec["Threshold"] * 0.1)))
            under_val = max(0.0, spec["Threshold"] - abs(rng.gauss(spec["Threshold"] * 0.2, max(1.0, spec["Threshold"] * 0.1))))

            history_out.append(
                {
                    "AlarmName": spec["AlarmName"],
                    "AlarmType": "MetricAlarm",
                    "Timestamp": fire_ts,
                    "HistoryItemType": "StateUpdate",
                    "HistorySummary": f"Alarm updated from OK to ALARM",
                    "HistoryData": _history_data("ALARM", _state_reason(spec, True, over_val), over_val),
                }
            )
            # ALARM → OK transition (auto or manual)
            auto = rng.random() < auto_rate
            history_out.append(
                {
                    "AlarmName": spec["AlarmName"],
                    "AlarmType": "MetricAlarm",
                    "Timestamp": end_ts,
                    "HistoryItemType": "StateUpdate",
                    "HistorySummary": f"Alarm updated from ALARM to OK",
                    "HistoryData": _history_data("OK", _state_reason(spec, False, under_val), under_val),
                    "_auto_resolved": auto,  # Mock-only convenience flag
                }
            )
            last_ts = end_ts
            last_state = "OK"
            last_value_over = over_val

        alarm_doc = {
            "AlarmName": spec["AlarmName"],
            "AlarmArn": _arn_for(spec["AlarmName"]),
            "AlarmDescription": spec["AlarmDescription"],
            "ActionsEnabled": True,
            "OKActions": [],
            "AlarmActions": [],
            "InsufficientDataActions": [],
            "StateValue": last_state,
            "StateReason": _state_reason(spec, False, last_value_over * 0.7),
            "StateUpdatedTimestamp": last_ts,
            "MetricName": spec["MetricName"],
            "Namespace": spec["Namespace"],
            "Statistic": spec["Statistic"] if spec["Statistic"] not in {"p99", "p95", "p90"} else None,
            "ExtendedStatistic": spec["Statistic"] if spec["Statistic"] in {"p99", "p95", "p90"} else None,
            "Dimensions": spec["Dimensions"],
            "Period": spec["Period"],
            "EvaluationPeriods": spec["EvaluationPeriods"],
            "DatapointsToAlarm": spec["EvaluationPeriods"],
            "Threshold": spec["Threshold"],
            "ComparisonOperator": spec["ComparisonOperator"],
            "TreatMissingData": "missing",
            # Mock-only
            "_tags": spec["tags"],
            "_ack_ratio_7d": spec["ack_ratio"],
        }
        # Drop None keys so consumers don't see ExtendedStatistic=None for Average alarms
        alarm_doc = {k: v for k, v in alarm_doc.items() if v is not None}
        if "last_ack_days_ago" in spec:
            alarm_doc["_last_ack_days_ago"] = spec["last_ack_days_ago"]
        alarms_out.append(alarm_doc)

    # chronological order for history
    history_out.sort(key=lambda e: e["Timestamp"])
    return alarms_out, history_out


ALARMS, HISTORY = generate_history()


if __name__ == "__main__":
    # CLI peek: prints counts + a sample alarm to help humans sanity-check
    print(f"ALARMS: {len(ALARMS)} entries")
    print(f"HISTORY: {len(HISTORY)} StateUpdate events")
    print()
    print("Sample alarm:")
    sample = ALARMS[1]  # ec2-cpu-high-web-fleet
    for k, v in sample.items():
        print(f"  {k}: {v}")
