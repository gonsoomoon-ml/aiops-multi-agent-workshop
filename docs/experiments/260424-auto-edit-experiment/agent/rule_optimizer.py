"""Rule Optimization Agent — the Strands Agent that drives noise detection.

Two execution paths:

- `build_agent()` returns a Strands `Agent` bound to Bedrock + our 6 tools,
  driven by natural-language prompts. This is the main demo path.
- `run_scripted_analysis()` reproduces the same workflow *without* an LLM by
  applying the classification heuristics as Python code. Useful for offline
  CI, smoke tests, and as a reference implementation for the system prompt.
  The two paths produce compatible markdown reports for identical mock input.
"""
from __future__ import annotations

import json
import os
from datetime import date
from typing import Any

from tools.cloudwatch_mock import describe_alarms, describe_alarm_history, get_alarm_statistics
from tools.github_tool import get_file, list_files, put_file

SYSTEM_PROMPT = """\
You are the Rule Optimization Agent for a Cloud Operation team.
Your job: detect noisy CloudWatch alarms, propose concrete rule improvements,
then commit a markdown report to the team's GitHub repository.

TOOLS YOU HAVE:
- describe_alarms(alarm_names=None): current alarm definitions
- describe_alarm_history(alarm_name=None, start_time=None, end_time=None, max_records=1000):
    raw StateUpdate events (use sparingly — prefer get_alarm_statistics)
- get_alarm_statistics(alarm_name=None, period_days=7): pre-aggregated 7-day stats
    per alarm (fires, auto_resolve_rate, avg_duration_minutes, ack_ratio_7d,
    last_ack_days_ago, hour_of_day_distribution, peak_hours, weekday_vs_weekend)
- list_files(path="rules/"): list of rule YAML files in the repo
- get_file(path): read a file's contents from the repo
- put_file(path, content, commit_message): commit a file (used to publish the report)

WORKFLOW (execute in order):
1) describe_alarms() → get definitions.
2) get_alarm_statistics(period_days=7) → get aggregated per-alarm metrics.
3) list_files("rules/") and get_file for each rule to cite current YAML.
4) Classify EACH alarm into exactly ONE bucket:
     NORMAL — real actionable incident (keep as-is, do NOT propose changes)
     THRESHOLD_UP — over-sensitive; raise threshold or EvaluationPeriods
     CONDITION_AND — single-metric false positives; correlate with another metric
     TIME_WINDOW_SUPPRESS — predictable-time burst; suppress that window
     RULE_RETIRE — no acks, long idle; propose deletion
5) Write a markdown report following FORMAT below.
6) put_file("diagnosis/<YYYY-MM-DD>-noise.md", report,
       commit_message="diagnosis: weekly noise review")
7) Return a short terminal summary: counts + commit URL.

CLASSIFICATION HEURISTICS (apply in order — first match wins):
- NORMAL: fires ≤ 10 AND ack_ratio_7d ≥ 0.5
- RULE_RETIRE: last_ack_days_ago ≥ 60, OR
               (ack_ratio_7d == 0 AND fires ≥ 150 AND auto_resolve_rate ≥ 0.99
                AND top-3 hours carry < 40% of fires)
- TIME_WINDOW_SUPPRESS: peak_hours where top-3 hours carry ≥ 60% of fires
- THRESHOLD_UP: fires ≥ 50 AND auto_resolve_rate ≥ 0.9 AND ack_ratio_7d < 0.1
- CONDITION_AND: fires 30-100 AND auto_resolve_rate between 0.6 and 0.95
                 AND ack_ratio_7d < 0.2 AND NOT time-clustered

MARKDOWN REPORT FORMAT:

# Noise Alarm Diagnosis — <ISO-DATE>

## Summary
- Total alarms analyzed: N
- Noise candidates: N (Threshold N / Condition N / TimeWindow N / Retire N)
- Genuine incidents: N
- Expected weekly fire reduction if all proposals applied: ~X%

## Noise candidates

### ⚠️ <AlarmName> — <classification label>
**Current definition** (from `rules/<AlarmName>.yaml`):
- <namespace/metric statistic> <comparison> <threshold>
- Period <n>s, EvaluationPeriods <n>

**7-day pattern**
- Fires: <n> / Auto-resolve: <pct>% / Avg duration: <m>m / Ack: <pct>%
- <time clustering note, or omit>

**Inference**: <1-2 sentences>

**Proposal**
- <concrete change line 1>
- <concrete change line 2 (optional)>
- Expected fires after change: ~<n>/week (−<y>%)

(repeat per candidate)

## Genuine incidents (keep as-is)
- `<AlarmName>` — <1 line reason>

## Links
- Report commit: <commit_url returned by put_file>

RULES:
- Use exact numbers from get_alarm_statistics. Round to 1 decimal.
- Each candidate section ≤ 12 lines.
- Do not invent data. If you lack a field, say "n/a".
- Always finish by calling put_file, then print the commit URL.
- Respond in the same language as the user's request (Korean or English).
"""


def build_agent(model_id: str | None = None, region: str | None = None):
    """Create a Strands Agent wired to Bedrock with our 6 tools bound.

    Raises ImportError if Strands / BedrockModel are unavailable.
    """
    from strands import Agent
    from strands.models import BedrockModel

    model = BedrockModel(
        model_id=model_id or os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-5-20250929-v1:0"),
        region_name=region or os.environ.get("AWS_REGION", "us-west-2"),
    )
    return Agent(
        model=model,
        tools=[
            describe_alarms,
            describe_alarm_history,
            get_alarm_statistics,
            list_files,
            get_file,
            put_file,
        ],
        system_prompt=SYSTEM_PROMPT,
    )


# ---------------------------------------------------------------------------
# Scripted (no-LLM) reference implementation — mirrors the heuristics above.
# Used for offline smoke tests and as a correctness benchmark.
# ---------------------------------------------------------------------------

def _classify(stats: dict) -> str:
    fires = stats["fires"]
    auto = stats["auto_resolve_rate"]
    ack = stats["ack_ratio_7d"]
    last_ack = stats.get("last_ack_days_ago")
    peaks = stats.get("peak_hours", [])
    top3_pct = sum(p["pct"] for p in peaks[:3])

    # NORMAL: low-frequency with real acks
    if fires <= 10 and ack >= 0.5:
        return "NORMAL"
    # RULE_RETIRE: explicit long-idle ownership, OR very-high-volume 0-ack drone
    if last_ack is not None and last_ack >= 60:
        return "RULE_RETIRE"
    if ack == 0 and fires >= 150 and auto >= 0.99 and top3_pct < 40:
        return "RULE_RETIRE"
    # TIME_WINDOW_SUPPRESS: strong top-3 hour clustering
    if peaks and top3_pct >= 60:
        return "TIME_WINDOW_SUPPRESS"
    # THRESHOLD_UP: noisy, mostly self-resolving, never ack'd
    if fires >= 50 and auto >= 0.9 and ack < 0.1:
        return "THRESHOLD_UP"
    # CONDITION_AND: mid-frequency with partial auto-resolve and low ack
    if 30 <= fires <= 100 and 0.6 <= auto <= 0.95 and ack < 0.2:
        return "CONDITION_AND"
    # Fallback
    if fires >= 50 and ack < 0.2:
        return "THRESHOLD_UP"
    return "NORMAL"


_LABEL_KR = {
    "NORMAL": "정상",
    "THRESHOLD_UP": "Threshold 상향",
    "CONDITION_AND": "조건 결합 (AND)",
    "TIME_WINDOW_SUPPRESS": "Time window 제외",
    "RULE_RETIRE": "Rule 폐기",
}


def _proposal(stats: dict, cls: str, alarm_def: dict) -> tuple[list[str], int]:
    """Return (proposal_lines, estimated_fires_after)."""
    fires = stats["fires"]
    threshold = stats["threshold"]
    if cls == "THRESHOLD_UP":
        new_th = round(threshold * 1.2, 1) if threshold > 1 else max(threshold + 4, 5)
        lines = [
            f"Threshold: {threshold} → **{new_th}** (~P90 + margin)",
            f"EvaluationPeriods: {alarm_def.get('EvaluationPeriods')} → **{(alarm_def.get('EvaluationPeriods') or 1) + 1}** (absorb single-spike)",
        ]
        after = max(1, int(fires * 0.06))
        return lines, after
    if cls == "CONDITION_AND":
        lines = [
            "Combine with a second signal (e.g., request rate or error rate) using AND",
            "Keep threshold unchanged; fire only when both metrics breach within 5 minutes",
        ]
        after = max(1, int(fires * 0.15))
        return lines, after
    if cls == "TIME_WINDOW_SUPPRESS":
        hours = [p["hour_kst"] for p in stats.get("peak_hours", [])[:3]]
        range_txt = f"{min(hours):02d}:00-{max(hours)+1:02d}:00 KST" if hours else "predictable window"
        lines = [
            f"Suppress alarm during {range_txt} (batch/deploy/commute window)",
            "Keep threshold unchanged outside that window",
        ]
        after = max(1, int(fires * 0.25))
        return lines, after
    if cls == "RULE_RETIRE":
        lines = [
            "Delete this rule — no ack or action recorded in >= 60 days",
            "If needed later, re-create with stricter threshold and ownership",
        ]
        after = 0
        return lines, after
    return [], fires


def run_scripted_analysis(as_of: date | None = None) -> dict[str, Any]:
    """Run the full pipeline without any LLM — deterministic reference flow.

    Returns a summary dict plus writes the markdown report via put_file.
    """
    today = as_of or date.today()

    alarms_resp = describe_alarms()
    alarm_defs = {a["AlarmName"]: a for a in alarms_resp["MetricAlarms"]}
    stats_resp = get_alarm_statistics(period_days=7)

    classified = []
    genuine = []
    noise_buckets = {"THRESHOLD_UP": 0, "CONDITION_AND": 0, "TIME_WINDOW_SUPPRESS": 0, "RULE_RETIRE": 0}
    total_before = 0
    total_after = 0

    for s in stats_resp["alarms"]:
        cls = _classify(s)
        total_before += s["fires"]
        if cls == "NORMAL":
            genuine.append((s, cls))
            total_after += s["fires"]
            continue
        prop_lines, after = _proposal(s, cls, alarm_defs[s["AlarmName"]])
        classified.append((s, cls, prop_lines, after))
        noise_buckets[cls] += 1
        total_after += after

    # Build markdown
    date_iso = today.isoformat()
    reduction_pct = 0 if total_before == 0 else round((1 - total_after / total_before) * 100, 1)
    lines: list[str] = []
    lines.append(f"# Noise Alarm Diagnosis — {date_iso}")
    lines.append("")
    lines.append("## Summary")
    lines.append(f"- Total alarms analyzed: {len(stats_resp['alarms'])}")
    noise_count = sum(noise_buckets.values())
    lines.append(
        f"- Noise candidates: {noise_count} "
        f"(Threshold {noise_buckets['THRESHOLD_UP']} / Condition {noise_buckets['CONDITION_AND']} / "
        f"TimeWindow {noise_buckets['TIME_WINDOW_SUPPRESS']} / Retire {noise_buckets['RULE_RETIRE']})"
    )
    lines.append(f"- Genuine incidents: {len(genuine)}")
    lines.append(f"- Expected weekly fire reduction if all proposals applied: ~{reduction_pct}%")
    lines.append("")
    lines.append("## Noise candidates")
    lines.append("")

    for s, cls, prop_lines, after in classified:
        fires = s["fires"]
        reduction = 100 if fires == 0 else round((1 - after / fires) * 100, 1)
        alarm = alarm_defs[s["AlarmName"]]
        lines.append(f"### ⚠️ {s['AlarmName']} — {_LABEL_KR[cls]} ({cls})")
        lines.append("")
        lines.append(f"**Current definition** (from `rules/{s['AlarmName']}.yaml`):")
        stat = alarm.get("Statistic") or alarm.get("ExtendedStatistic")
        lines.append(
            f"- {alarm['Namespace']} `{alarm['MetricName']}` ({stat}) "
            f"{alarm['ComparisonOperator']} {alarm['Threshold']}"
        )
        lines.append(f"- Period {alarm['Period']}s, EvaluationPeriods {alarm['EvaluationPeriods']}")
        lines.append("")
        lines.append("**7-day pattern**")
        dur = s["avg_duration_minutes"]
        lines.append(
            f"- Fires: {fires} / Auto-resolve: {round(s['auto_resolve_rate']*100,1)}% / "
            f"Avg duration: {dur:.1f}m / Ack: {round(s['ack_ratio_7d']*100,1)}%"
        )
        if s.get("peak_hours"):
            top = ", ".join(f"{p['hour_kst']:02d}h ({p['pct']}%)" for p in s["peak_hours"][:3])
            lines.append(f"- Peak hours: {top}")
        lines.append("")
        lines.append("**Inference**")
        lines.append(_inference_line(s, cls))
        lines.append("")
        lines.append("**Proposal**")
        for p in prop_lines:
            lines.append(f"- {p}")
        lines.append(f"- Expected fires after change: ~{after}/week (−{reduction}%)")
        lines.append("")

    lines.append("## Genuine incidents (keep as-is)")
    for s, _cls in genuine:
        lines.append(f"- `{s['AlarmName']}` — {s['fires']} fires, ack {round(s['ack_ratio_7d']*100)}%, real signal")
    lines.append("")

    body = "\n".join(lines)
    path = f"diagnosis/{date_iso}-noise.md"
    commit = put_file(path, body, commit_message=f"diagnosis: weekly noise review {date_iso}")
    body_with_link = body + f"\n## Links\n- Report commit: {commit.get('commit_url')}\n"
    # Re-commit with link filled in
    commit2 = put_file(path, body_with_link, commit_message=f"diagnosis: weekly noise review {date_iso}")

    return {
        "total_alarms": len(stats_resp["alarms"]),
        "noise_candidates": noise_count,
        "noise_breakdown": noise_buckets,
        "genuine": len(genuine),
        "total_fires_before": total_before,
        "total_fires_after": total_after,
        "reduction_pct": reduction_pct,
        "commit_url": commit2.get("commit_url"),
        "path": path,
    }


def _inference_line(stats: dict, cls: str) -> str:
    fires = stats["fires"]
    auto = round(stats["auto_resolve_rate"] * 100)
    ack = round(stats["ack_ratio_7d"] * 100)
    if cls == "THRESHOLD_UP":
        return (
            f"Fires {fires}x with {auto}% auto-resolving and only {ack}% ack'd. "
            "Normal traffic already crosses the current threshold."
        )
    if cls == "CONDITION_AND":
        return (
            f"Mid-frequency ({fires}) with only {ack}% ack — the single metric "
            "isn't a reliable incident signal by itself."
        )
    if cls == "TIME_WINDOW_SUPPRESS":
        peaks = stats.get("peak_hours", [])
        top_pct = sum(p["pct"] for p in peaks[:3])
        return (
            f"{top_pct:.0f}% of fires cluster in a predictable time band — suppress that window."
        )
    if cls == "RULE_RETIRE":
        last_ack = stats.get("last_ack_days_ago")
        if last_ack:
            return f"No ack in {last_ack}+ days; this rule has no operational value."
        return f"{fires} fires this week, 0 acked, all auto-resolved — nobody owns this rule."
    return "n/a"
