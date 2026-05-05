#!/usr/bin/env python3
"""Terminal entrypoint for the Rule Optimization Agent.

Usage:

    python invoke_cli.py "최근 1주 noise alarm 진단하고 diagnosis/에 리포트 올려줘"
    python invoke_cli.py --dry-run            # scripted reference (no Bedrock)
    python invoke_cli.py --dry-run -q "..."    # accept custom prompt anyway

Environment variables read (see .env.example):
    AWS_REGION, BEDROCK_MODEL_ID — Bedrock routing
    OFFLINE_MODE — 1 for local-fs GitHub fallback, 0 for real GitHub
    GITHUB_TOKEN, GITHUB_REPO — real GitHub mode
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _load_env() -> None:
    """Load .env or .env.local if present. Uses stdlib only (no python-dotenv dep)."""
    for name in (".env.local", ".env"):
        p = Path(__file__).resolve().parent / name
        if not p.is_file():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def run_agent(query: str) -> None:
    """Invoke the Strands Agent with `query` and stream tool calls to stdout."""
    from agent.rule_optimizer import build_agent

    print(f"→ [agent] invoking Strands Agent via Bedrock model "
          f"{os.environ.get('BEDROCK_MODEL_ID', '(default)')} ...")
    agent = build_agent()
    result = agent(query)
    # `result` is Strands AgentResult; print the final assistant message
    print()
    print("=" * 60)
    print("Agent response:")
    print("=" * 60)
    print(str(result))


def run_dry(query: str | None = None) -> None:
    """Run the scripted reference pipeline — no Bedrock required."""
    from agent.rule_optimizer import run_scripted_analysis

    if query:
        print(f"→ [dry-run] query: {query}")
    print("→ cloudwatch.describe_alarms()")
    print("→ cloudwatch.get_alarm_statistics(period_days=7)")
    print("→ github.list_files('rules/')")
    print("→ [analysis] classifying 15 alarms ...")
    summary = run_scripted_analysis()
    print(f"→ github.put_file('{summary['path']}') — committed")
    print()
    print("=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"  Alarms analyzed     : {summary['total_alarms']}")
    print(f"  Noise candidates    : {summary['noise_candidates']}"
          f"  (TH={summary['noise_breakdown']['THRESHOLD_UP']}"
          f" / AND={summary['noise_breakdown']['CONDITION_AND']}"
          f" / TW={summary['noise_breakdown']['TIME_WINDOW_SUPPRESS']}"
          f" / RET={summary['noise_breakdown']['RULE_RETIRE']})")
    print(f"  Genuine incidents   : {summary['genuine']}")
    print(f"  Fires before / after: {summary['total_fires_before']} / {summary['total_fires_after']}"
          f"  (−{summary['reduction_pct']}%)")
    print(f"  Report              : {summary['commit_url']}")
    print()


def main(argv: list[str] | None = None) -> int:
    _load_env()
    parser = argparse.ArgumentParser(description="Rule Optimization Agent CLI")
    parser.add_argument(
        "query",
        nargs="?",
        default="최근 1주 noise alarm 진단하고 diagnosis/에 리포트 올려줘",
        help="Natural language request to the Agent",
    )
    parser.add_argument(
        "-q", "--query",
        dest="query_opt",
        help="Explicit --query form (equivalent to positional)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip Bedrock; run the scripted reference pipeline (useful offline)",
    )
    args = parser.parse_args(argv)

    query = args.query_opt or args.query

    if args.dry_run:
        run_dry(query)
        return 0
    try:
        run_agent(query)
    except Exception as exc:  # noqa: BLE001 — surface any Bedrock/config issue to stderr
        print(f"error: {exc}", file=sys.stderr)
        print(
            "hint: set AWS_REGION + BEDROCK_MODEL_ID and ensure your AWS credentials "
            "have Bedrock invoke access. Or re-run with --dry-run.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
