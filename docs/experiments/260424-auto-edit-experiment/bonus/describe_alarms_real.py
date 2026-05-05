"""Bonus — real `DescribeAlarms` via boto3, adapted to the Mock schema.

Demonstrates the "불변 계약" principle from plan.md §5: the Agent does not
know whether it's talking to Mock or Real data because the response shape
is identical. All Mock-only fields (`_tags`, `_ack_ratio_7d`,
`_last_ack_days_ago`) are stripped from real responses, so the Agent must
degrade gracefully when they're missing — which `tools/cloudwatch_mock.py`
and `agent/rule_optimizer.py` already do by using `.get(...)` with defaults.

Usage:
    # Requires AWS creds with `cloudwatch:DescribeAlarms` permission
    python -m bonus.describe_alarms_real demo-cpu-high --region us-west-2

Comparison with Mock:
    python -m bonus.describe_alarms_real --compare <alarm-name>
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any

import boto3


def _to_mock_shape(alarm: dict[str, Any]) -> dict[str, Any]:
    """Coerce boto3 alarm dict into the same shape the Mock returns.

    boto3 already returns the canonical CloudWatch schema; we just normalize
    datetime → ISO string and drop keys the Mock does not emit. Importantly
    we do NOT fabricate Mock-only fields (`_tags`, `_ack_ratio_7d`, …) — they
    are simply absent in real data.
    """
    out = {}
    for k, v in alarm.items():
        if isinstance(v, datetime):
            out[k] = v.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        else:
            out[k] = v
    return out


def describe_alarms_real(alarm_names: list[str] | None = None, region: str = "us-west-2") -> dict[str, Any]:
    client = boto3.client("cloudwatch", region_name=region)
    kwargs = {}
    if alarm_names:
        kwargs["AlarmNames"] = alarm_names
    resp = client.describe_alarms(**kwargs)
    return {
        "MetricAlarms": [_to_mock_shape(a) for a in resp.get("MetricAlarms", [])],
        "CompositeAlarms": [_to_mock_shape(a) for a in resp.get("CompositeAlarms", [])],
    }


def _compare_with_mock(name: str) -> int:
    from tools.cloudwatch_mock import describe_alarms as mock_describe

    real = describe_alarms_real([name])
    mock = mock_describe([name])

    print("REAL keys:", sorted(real["MetricAlarms"][0].keys()) if real["MetricAlarms"] else "<empty>")
    print("MOCK keys:", sorted(mock["MetricAlarms"][0].keys()) if mock["MetricAlarms"] else "<empty>")

    real_set = set(real["MetricAlarms"][0].keys()) if real["MetricAlarms"] else set()
    mock_set = set(mock["MetricAlarms"][0].keys()) if mock["MetricAlarms"] else set()

    only_real = real_set - mock_set
    only_mock = mock_set - real_set
    shared = real_set & mock_set
    print(f"\n shared ({len(shared)}): {sorted(shared)}")
    print(f"\n only in REAL ({len(only_real)}): {sorted(only_real)}")
    print(f"\n only in MOCK ({len(only_mock)}): {sorted(only_mock)}  <-- Mock-only helper fields")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("alarm_name", nargs="?", default=os.environ.get("BONUS_ALARM_NAME", "demo-cpu-high"))
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "us-west-2"))
    parser.add_argument("--compare", action="store_true", help="compare schemas with Mock")
    args = parser.parse_args()

    if args.compare:
        return _compare_with_mock(args.alarm_name)
    out = describe_alarms_real([args.alarm_name], region=args.region)
    print(json.dumps(out, indent=2, default=str, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
