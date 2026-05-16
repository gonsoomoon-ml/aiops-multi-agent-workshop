"""Phase 1 frozen baseline — mock 직접 import demo (offline, AWS 의존 0).

영구 보존 — 신규 audience 의 educational entry point + 회귀 격리 검증용.
어느 phase 가 와도 동작 가능 (shared/agent.py 시그니처 + shared/tools/alarm_history.py
보존되는 한). Phase 2 mode=past 와 같은 prompt + 같은 도구 명 사용 → 출력
동일성 검증 (P2-A3) 가능.

Usage:
    uv run python -m agents.monitor.local.run_local_import
    uv run python -m agents.monitor.local.run_local_import --query "..."
"""
import argparse
import asyncio
import os

from dotenv import load_dotenv

from agents.monitor.shared.agent import create_agent
from agents.monitor.shared.tools.alarm_history import (
    get_past_alarm_history,
    get_past_alarms_metadata,
)

DEFAULT_QUERY = "지난 7일 alarm history를 분석해 3가지 진단 유형으로 제안하고, real alarm은 따로 나열해줘."

DIM = "\033[2m"
NC = "\033[0m"


def _print_token_usage(usage_totals: dict) -> None:
    total = usage_totals.get("totalTokens", 0)
    input_t = usage_totals.get("inputTokens", 0)
    output_t = usage_totals.get("outputTokens", 0)
    cache_read = usage_totals.get("cacheReadInputTokens", 0)
    cache_write = usage_totals.get("cacheWriteInputTokens", 0)
    print(
        f"{DIM}📊 Tokens — Total: {total:,} | Input: {input_t:,} | "
        f"Output: {output_t:,} | Cache Read: {cache_read:,} | "
        f"Cache Write: {cache_write:,}{NC}"
    )


async def _stream_response(agent, prompt: str) -> None:
    usage_totals = {
        "inputTokens": 0,
        "outputTokens": 0,
        "totalTokens": 0,
        "cacheReadInputTokens": 0,
        "cacheWriteInputTokens": 0,
    }
    async for event in agent.stream_async(prompt):
        data = event.get("data", "")
        if data:
            print(data, end="", flush=True)
        metadata = event.get("event", {}).get("metadata", {})
        if "usage" in metadata:
            usage = metadata["usage"]
            for key in usage_totals:
                usage_totals[key] += usage.get(key, 0)
    print()
    _print_token_usage(usage_totals)


async def _amain(query: str) -> None:
    agent = create_agent(
        tools=[get_past_alarms_metadata, get_past_alarm_history],
        system_prompt_filename="system_prompt_past.md",
    )
    await _stream_response(agent, query)


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(description="Monitor Agent — Phase 1 frozen baseline (offline)")
    parser.add_argument("--query", default=DEFAULT_QUERY, help="Query to send to the agent")
    args = parser.parse_args()

    if not os.environ.get("AWS_REGION"):
        print("[warn] AWS_REGION 미설정. .env 또는 export로 설정하세요. 기본값 us-east-1 사용.")

    print("=" * 60)
    print("Monitor Agent — Phase 1 frozen baseline (mock 직접 import)")
    print(f"Model: {os.environ.get('MONITOR_MODEL_ID', 'global.anthropic.claude-sonnet-4-6')}")
    print(f"Query: {args.query}")
    print("=" * 60)
    print("\n분석 중... (도구 호출 + LLM 추론, 약 5~15초)\n")

    asyncio.run(_amain(args.query))


if __name__ == "__main__":
    main()
