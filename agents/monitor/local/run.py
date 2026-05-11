"""Phase 2 current — Gateway MCP demo (Cognito + 4 도구).

mode 분기:
    --mode past  : 과거 mock 도구 (P2-A3 — Phase 1 baseline 출력 동일성 검증)
    --mode live  : 라이브 CloudWatch 도구 (P2-A4/A5 — Phase 0 알람 분류)

본 파일은 Phase 2 local 진입점으로 **영구 보존** — Phase 3+ Runtime 은 별 entry
(`agents/{monitor,incident,...}/runtime/agentcore_runtime.py`) 로 신설. 같은
4 helper (agent / auth_local / mcp_client / modes) 를 재사용.
"""
import argparse
import asyncio
import os

from dotenv import load_dotenv

from _shared_debug import dprint, dump_stream_event, is_debug
from agents.monitor.shared.agent import create_agent
from agents.monitor.shared.auth_local import get_local_gateway_token
from agents.monitor.shared.mcp_client import create_mcp_client
from agents.monitor.shared.modes import MODE_CONFIG

QUERY_PAST = "지난 7일 alarm history를 분석해 3가지 진단 유형으로 제안하고, real alarm은 따로 나열해줘."
QUERY_LIVE_TEMPLATE = (
    "현재 라이브 알람 (payment-{user}-* prefix) 의 상태와 classification 을 분석해, "
    "실제로 봐야 할 알람만 알려줘."
)

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
        dump_stream_event(event)
    print()
    _print_token_usage(usage_totals)


async def _amain(mode: str, query: str) -> None:
    target_prefix, prompt_filename = MODE_CONFIG[mode]
    gateway_token = get_local_gateway_token()
    mcp_client = create_mcp_client(gateway_token=gateway_token)
    with mcp_client:  # Strands MCPClient 는 sync context manager
        all_tools = mcp_client.list_tools_sync()
        tools = [t for t in all_tools if t.tool_name.startswith(target_prefix)]
        if is_debug():
            dprint(
                "MCP tools",
                f"prefix='{target_prefix}' matched {len(tools)}/{len(all_tools)}: "
                f"{[t.tool_name for t in tools]} (all={[t.tool_name for t in all_tools]})",
                color="cyan",
            )
        if not tools:
            received = [t.tool_name for t in all_tools]
            raise SystemExit(
                f"[error] mode={mode} 도구 0개. Gateway target prefix '{target_prefix}' "
                f"매칭 실패. 받음: {received}"
            )
        agent = create_agent(tools=tools, system_prompt_filename=prompt_filename)
        await _stream_response(agent, query)


def main() -> None:
    load_dotenv()
    if not os.environ.get("GATEWAY_URL"):
        raise SystemExit("[error] GATEWAY_URL 미설정. infra/cognito-gateway/deploy.sh 실행 후 .env 갱신 필요.")

    parser = argparse.ArgumentParser(description="Monitor Agent — Phase 2 current (Gateway MCP)")
    parser.add_argument(
        "--mode", choices=["past", "live"], required=True,
        help="past = mock 분석 (P2-A3) | live = 라이브 분류 (P2-A4/A5)",
    )
    parser.add_argument("--query", default=None, help="기본: mode 별 default query")
    args = parser.parse_args()

    demo_user = os.environ.get("DEMO_USER") or os.environ.get("USER") or "ubuntu"
    default = QUERY_PAST if args.mode == "past" else QUERY_LIVE_TEMPLATE.format(user=demo_user)
    query = args.query or default

    print("=" * 60)
    print(f"Monitor Agent — Phase 2 current (mode={args.mode})")
    print(f"Model:   {os.environ.get('MONITOR_MODEL_ID', 'global.anthropic.claude-sonnet-4-6')}")
    print(f"Gateway: {os.environ['GATEWAY_URL']}")
    print(f"Query:   {query}")
    print("=" * 60)
    print("\n분석 중... (Gateway 호출 + LLM 추론)\n")

    asyncio.run(_amain(args.mode, query))


if __name__ == "__main__":
    main()
