"""
Phase 1 — Monitor Agent 로컬 실행 (스트리밍).

Usage:
    uv run python -m agents.monitor.local.run
    uv run python -m agents.monitor.local.run --query "최근 7일 알람 진단해줘"

검증:
    mock 데이터(5 alarms, 24 history events)에서
    Monitor가 3 noise / 2 real 분류 + 3가지 진단 유형 제안하는지 확인.

스트리밍 패턴은 developer-briefing-agent/local-agent/chat.py 차용.
"""
import argparse
import asyncio
import os

from dotenv import load_dotenv

from agents.monitor.shared.agent import create_agent

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
    agent = create_agent()
    await _stream_response(agent, query)


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(description="Monitor Agent local runner (Phase 1)")
    parser.add_argument("--query", default=DEFAULT_QUERY, help="Query to send to the agent")
    args = parser.parse_args()

    if not os.environ.get("AWS_REGION"):
        print("[warn] AWS_REGION 미설정. .env 또는 export로 설정하세요. 기본값 us-west-2 사용.")

    print("=" * 60)
    print("Monitor Agent (Phase 1, local mock)")
    print(f"Model: {os.environ.get('MONITOR_MODEL_ID', 'global.anthropic.claude-sonnet-4-6')}")
    print(f"Query: {args.query}")
    print("=" * 60)
    print("\n분석 중... (도구 호출 + LLM 추론, 약 5~15초)\n")

    asyncio.run(_amain(args.query))


if __name__ == "__main__":
    main()
