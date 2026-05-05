"""End-to-end offline test of the scripted reference pipeline.

Runs the full workflow without Bedrock: tools → classifier → report → put_file.
Verifies that the produced classification matches plan.md §5 exactly.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent.rule_optimizer import _classify, run_scripted_analysis
from tools.cloudwatch_mock import get_alarm_statistics


_EXPECTED_CLASSIFICATION = {
    "payment-api-5xx-rate": "NORMAL",
    "ec2-cpu-high-web-fleet": "THRESHOLD_UP",
    "rds-prod-cpu": "NORMAL",
    "lambda-checkout-errors": "THRESHOLD_UP",
    "alb-target-5xx": "CONDITION_AND",
    "nightly-batch-cpu-spike": "TIME_WINDOW_SUPPRESS",
    "deploy-time-5xx": "TIME_WINDOW_SUPPRESS",
    "dynamodb-throttle-orders": "NORMAL",
    "sqs-queue-depth-legacy-v1": "RULE_RETIRE",
    "old-ec2-status-check": "RULE_RETIRE",
    "api-latency-p99": "NORMAL",
    "ecs-memory-web": "THRESHOLD_UP",
    "s3-4xx-public-bucket": "CONDITION_AND",
    "rds-connections-high": "TIME_WINDOW_SUPPRESS",
    "waf-blocked-requests": "RULE_RETIRE",
}


def test_classifier_matches_plan_expectation():
    stats = get_alarm_statistics()["alarms"]
    for s in stats:
        assert _classify(s) == _EXPECTED_CLASSIFICATION[s["AlarmName"]], (
            f"{s['AlarmName']}: expected {_EXPECTED_CLASSIFICATION[s['AlarmName']]}, got {_classify(s)}"
        )


def test_end_to_end_summary_counts():
    os.environ["OFFLINE_MODE"] = "1"
    summary = run_scripted_analysis()
    assert summary["total_alarms"] == 15
    assert summary["noise_candidates"] == 11
    assert summary["genuine"] == 4
    assert summary["noise_breakdown"] == {
        "THRESHOLD_UP": 3,
        "CONDITION_AND": 2,
        "TIME_WINDOW_SUPPRESS": 3,
        "RULE_RETIRE": 3,
    }


def test_report_file_created(tmp_path, monkeypatch):
    os.environ["OFFLINE_MODE"] = "1"
    summary = run_scripted_analysis()
    path = Path("diagnosis") / Path(summary["path"]).name
    assert path.is_file(), f"report file missing: {path}"
    body = path.read_text(encoding="utf-8")
    # Sanity: report contains all 11 noise alarm names
    noise_names = [n for n, cls in _EXPECTED_CLASSIFICATION.items() if cls != "NORMAL"]
    for name in noise_names:
        assert name in body, f"expected {name} to appear in the report"
    # Link section is present
    assert "Report commit:" in body


def test_report_reduction_reasonable():
    summary = run_scripted_analysis()
    assert 70 <= summary["reduction_pct"] <= 95
