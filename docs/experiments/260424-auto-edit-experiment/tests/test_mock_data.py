"""Shape and invariant tests for mock_data/alarms.py.

These guarantee that plan.md §5's expected data distribution is reproducible.
If the distribution drifts, the Agent's classification tests will also fail.
"""
from __future__ import annotations

from collections import Counter

from mock_data.alarms import ALARMS, HISTORY, _ALARM_SPECS  # type: ignore[attr-defined]


def test_fifteen_alarms():
    assert len(ALARMS) == 15


def test_history_events_per_alarm_matches_fires():
    """For every alarm, history should contain exactly fires * 2 StateUpdate events."""
    counts = Counter(e["AlarmName"] for e in HISTORY)
    for spec in _ALARM_SPECS:
        expected = spec["fires"] * 2
        assert counts[spec["AlarmName"]] == expected, (
            f"{spec['AlarmName']}: expected {expected} events, got {counts[spec['AlarmName']]}"
        )


def test_total_history_is_1672():
    assert len(HISTORY) == 1672


def test_alarm_documents_carry_required_keys():
    required = {
        "AlarmName",
        "AlarmArn",
        "Namespace",
        "MetricName",
        "Threshold",
        "ComparisonOperator",
        "EvaluationPeriods",
        "Period",
        "StateValue",
        "_tags",
        "_ack_ratio_7d",
    }
    for alarm in ALARMS:
        missing = required - alarm.keys()
        assert not missing, f"{alarm['AlarmName']} missing keys: {missing}"


def test_long_idle_rules_have_last_ack_marker():
    long_idle = {a["AlarmName"]: a for a in ALARMS if "_last_ack_days_ago" in a}
    assert set(long_idle) == {"sqs-queue-depth-legacy-v1", "old-ec2-status-check"}
    assert long_idle["sqs-queue-depth-legacy-v1"]["_last_ack_days_ago"] == 90
    assert long_idle["old-ec2-status-check"]["_last_ack_days_ago"] == 120


def test_history_is_sorted():
    prev = None
    for ev in HISTORY:
        if prev is not None:
            assert ev["Timestamp"] >= prev
        prev = ev["Timestamp"]


def test_deterministic_regeneration():
    from mock_data.alarms import generate_history

    a1, h1 = generate_history()
    a2, h2 = generate_history()
    assert [a["AlarmName"] for a in a1] == [a["AlarmName"] for a in a2]
    assert len(h1) == len(h2)
    # Spot-check a few timestamps are identical
    assert [e["Timestamp"] for e in h1[:10]] == [e["Timestamp"] for e in h2[:10]]
