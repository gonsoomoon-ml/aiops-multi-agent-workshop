"""Generate the `rules/` directory seed YAMLs from the mock alarm specs.

Each file in `rules/` is the GitOps-style "rule definition" that the Agent loads
to understand the current threshold/comparison and proposes changes against.

Run once to (re)populate rules/:

    python -m mock_data.seed_rules
"""
from __future__ import annotations

from pathlib import Path

import yaml

from mock_data.alarms import _ALARM_SPECS  # type: ignore[attr-defined]

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_RULES_DIR = _PROJECT_ROOT / "rules"


def _spec_to_rule(spec: dict) -> dict:
    return {
        "name": spec["AlarmName"],
        "description": spec["AlarmDescription"],
        "owner": spec["tags"].get("team", "unknown"),
        "service": spec["tags"].get("service", "unknown"),
        "metric": {
            "namespace": spec["Namespace"],
            "name": spec["MetricName"],
            "statistic": spec["Statistic"],
            "dimensions": spec["Dimensions"],
        },
        "evaluation": {
            "period_seconds": spec["Period"],
            "evaluation_periods": spec["EvaluationPeriods"],
            "threshold": spec["Threshold"],
            "comparison_operator": spec["ComparisonOperator"],
            "treat_missing_data": "missing",
        },
        "severity": "warning",
        "actions": {"ok": [], "alarm": ["sns:topic:cloud-ops-alerts"], "insufficient_data": []},
    }


def main() -> None:
    _RULES_DIR.mkdir(exist_ok=True)
    for spec in _ALARM_SPECS:
        rule = _spec_to_rule(spec)
        path = _RULES_DIR / f"{spec['AlarmName']}.yaml"
        path.write_text(yaml.safe_dump(rule, sort_keys=False, allow_unicode=True), encoding="utf-8")
        print(f"wrote {path.relative_to(_PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
