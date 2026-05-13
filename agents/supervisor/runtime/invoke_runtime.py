#!/usr/bin/env python3
"""
invoke_runtime.py — Phase 5 Supervisor 호출 진입점 (SigV4 IAM)

워크샵 청중 (운영자) + admin 통합 진입점. Phase 4 의 monitor/incident
``invoke_runtime.py`` 와 동일 패턴 — SigV4 IAM 자동 서명. Phase 5 Option X 에서
Supervisor 는 customJWTAuthorizer 미설정 → SigV4 default 로 정상 동작.

호출 흐름:
  1. AWS 자격증명 (`aws configure`)
  2. boto3 ``invoke_agent_runtime`` (SigV4 자동 서명)
  3. SSE 스트림 stdout — Supervisor 가 sub-agent 들 호출하며 stream

Phase 4 의 ``agents/{monitor,incident}/runtime/invoke_runtime.py`` 와 다른 점:
  - **payload 스키마**: ``{"query": "<자연어 운영자 질의>"}`` (Monitor 의 mode + Incident 의 alarm_name 통합)
  - **응답 형식**: Supervisor 가 만든 통합 JSON (system_prompt schema) — 코드 측 해석 불필요

사용법:
    uv run agents/supervisor/runtime/invoke_runtime.py --query "현재 상황 진단해줘"
    uv run agents/supervisor/runtime/invoke_runtime.py --query "alarm payment-ubuntu-status-check 진단"

사전 조건:
    - deploy_runtime.py 실행 완료 (repo root .env 에 ``SUPERVISOR_RUNTIME_ARN`` 등 작성됨)
    - AWS 자격증명 + 사용자 IAM Role 에 ``bedrock-agentcore:InvokeAgentRuntime`` 권한

reference:
    - docs/design/phase6a.md §8 (Operator 진입점)
    - agents/incident/runtime/invoke_runtime.py (Phase 4 SigV4 invoke 패턴)
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import boto3
from botocore.config import Config
from dotenv import load_dotenv

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[2]
load_dotenv(PROJECT_ROOT / ".env")

sys.path.insert(0, str(PROJECT_ROOT))
from _shared_debug import dprint  # noqa: E402

REGION = os.getenv("AWS_REGION", "us-west-2")
RUNTIME_ARN = os.getenv("SUPERVISOR_RUNTIME_ARN")

GREEN, YELLOW, BLUE, RED, DIM, NC = (
    "\033[0;32m", "\033[1;33m", "\033[0;34m", "\033[0;31m", "\033[2m", "\033[0m"
)


def parse_args() -> argparse.Namespace:
    """CLI 인자 — `--query <자연어 운영자 질의>` + `--session-id <UUID>`."""
    parser = argparse.ArgumentParser(description="Phase 5 Supervisor admin invoke (SigV4)")
    parser.add_argument(
        "--query",
        default="현재 상황 진단해줘",
        help="자연어 운영자 질의 (default: '현재 상황 진단해줘')",
    )
    parser.add_argument(
        "--session-id",
        default=None,
        help=(
            "동일 ID 로 재호출 시 Supervisor + sub-agent 모두 warm container 재사용 → TTFT 단축. "
            "AgentCore 제약: 최소 33자 (UUID hex 32자 + prefix 권장 — `workshop-$(uuidgen | tr -d -)`). "
            "생략 시 매 invoke 새 microVM (cold). Phase 3 monitor invoke_runtime 와 동일 패턴."
        ),
    )
    args = parser.parse_args()
    if args.session_id and len(args.session_id) < 33:
        parser.error(
            f"--session-id 길이 {len(args.session_id)} — AgentCore 제약 최소 33자. "
            f"예: workshop-$(uuidgen | tr -d -)  # → 41자"
        )
    return args


def parse_sse_event(line_bytes: bytes) -> dict | None:
    """SSE ``data: {...}`` 라인을 dict 로 파싱."""
    if not line_bytes:
        return None
    try:
        text = line_bytes.decode("utf-8").strip()
        if text.startswith("data: "):
            text = text[6:]
        return json.loads(text) if text else None
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


# Phase 5b — token usage 5 키 (cache R/W 포함). Combined 계산 + zero-fill 에 재사용.
_USAGE_KEYS = ["inputTokens", "outputTokens", "totalTokens",
               "cacheReadInputTokens", "cacheWriteInputTokens"]


def _format_usage_line(label: str, usage: dict, calls: int | None = None) -> str:
    """4-line summary 의 한 줄 — Monitor / Incident / Supervisor / Combined 공통.

    ``calls`` 가 2 이상이면 ``(N회)`` suffix 추가 — Incident 가 alarm N개 병렬 호출된
    경우 가시화. label 폭 14자 padding 으로 4 줄 시각적 정렬.
    """
    suffix = f" ({calls}회)" if calls and calls > 1 else ""
    head = f"{label}{suffix}"
    return (
        f"{DIM}📊 {head:<14} — "
        f"Total: {usage.get('totalTokens', 0):,} | "
        f"Input: {usage.get('inputTokens', 0):,} | "
        f"Output: {usage.get('outputTokens', 0):,} | "
        f"Cache R/W: {usage.get('cacheReadInputTokens', 0):,}/"
        f"{usage.get('cacheWriteInputTokens', 0):,}{NC}"
    )


def main() -> None:
    args = parse_args()
    if not RUNTIME_ARN:
        print(f"{RED}❌ SUPERVISOR_RUNTIME_ARN 미설정 — deploy_runtime.py 먼저 실행{NC}")
        sys.exit(1)

    print(f"{BLUE}{'=' * 60}{NC}")
    print(f"  Phase 5 Operator → Supervisor (SigV4)")
    print(f"  Query: {args.query}")
    print(f"  Runtime ARN: {RUNTIME_ARN}")
    if args.session_id:
        print(f"  Session ID:  {args.session_id} (warm container 재사용 시도)")
    print(f"{BLUE}{'=' * 60}{NC}\n")

    config = Config(connect_timeout=300, read_timeout=600, retries={"max_attempts": 0})
    client = boto3.client("bedrock-agentcore", region_name=REGION, config=config)

    payload = {"query": args.query}

    print(f"{YELLOW}📤 Supervisor 호출 중 — LLM 첫 토큰까지 ~10-15초 소요 가능{NC}\n")
    invoke_kwargs = {
        "agentRuntimeArn": RUNTIME_ARN,
        "qualifier": "DEFAULT",
        "runtimeUserId": os.getenv("DEMO_USER", "ubuntu"),
        "payload": json.dumps(payload),
    }
    if args.session_id:
        invoke_kwargs["runtimeSessionId"] = args.session_id

    start = datetime.now()
    response = client.invoke_agent_runtime(**invoke_kwargs)
    dprint("HTTP response 도착", f"{(datetime.now() - start).total_seconds():.2f}s", color="blue")

    content_type = response.get("contentType", "")
    if "text/event-stream" in content_type:
        usage_summary: dict | None = None
        # Phase 5b — sub-agent usage 누적 (Supervisor 가 ``subagent_usage`` SSE 로 yield).
        # 구조: {"monitor": {"usage": {...}, "calls": N}, "incident": {...}}
        subagent_usages: dict[str, dict] = {}
        first_byte_ts = first_text_ts = None
        for line in response["response"].iter_lines(chunk_size=1):
            if first_byte_ts is None:
                first_byte_ts = datetime.now()
                dprint("first SSE byte (TTFT)", f"{(first_byte_ts - start).total_seconds():.2f}s", color="cyan")
            event = parse_sse_event(line)
            if event is None:
                continue
            etype = event.get("type")
            if etype == "agent_text_stream":
                if first_text_ts is None:
                    first_text_ts = datetime.now()
                    dprint("first text token", f"{(first_text_ts - start).total_seconds():.2f}s", color="green")
                print(event.get("text", ""), end="", flush=True)
            elif etype == "tool_call_begin":
                tool = event.get("tool", "")
                inp_str = json.dumps(event.get("input", {}), ensure_ascii=False)
                inp_preview = inp_str if len(inp_str) <= 80 else inp_str[:77] + "..."
                elapsed = (datetime.now() - start).total_seconds()
                print(f"\n{DIM}  🔧 {tool}({inp_preview}) — {elapsed:.1f}s{NC}", flush=True)
            elif etype == "tool_call_end":
                elapsed = (datetime.now() - start).total_seconds()
                print(f"{DIM}  ✅ tool 응답 도착 — {elapsed:.1f}s{NC}", flush=True)
            elif etype == "subagent_usage":
                agent_type = event.get("agent", "")
                if agent_type:
                    subagent_usages[agent_type] = {
                        "usage": event.get("usage", {}),
                        "calls": event.get("calls", 1),
                    }
            elif etype == "token_usage":
                dprint("token_usage event", f"{(datetime.now() - start).total_seconds():.2f}s", color="magenta")
                usage_summary = event.get("usage", {})

        # Phase 5b — 4-line token usage summary (sub-agent + Supervisor + Combined).
        # Sub-agent 미호출 시 (단순 질의) Monitor/Incident + Combined 라인 skip — 그
        # 경우 Supervisor 한 줄만 출력 (이전 동작 유지).
        if subagent_usages or usage_summary:
            print()
            for atype, label in (("monitor", "Monitor"), ("incident", "Incident")):
                entry = subagent_usages.get(atype)
                if entry:
                    print(_format_usage_line(label, entry["usage"], calls=entry["calls"]))
            if usage_summary:
                print(_format_usage_line("Supervisor", usage_summary))
            if subagent_usages and usage_summary:
                combined = {k: usage_summary.get(k, 0) for k in _USAGE_KEYS}
                for entry in subagent_usages.values():
                    for k in _USAGE_KEYS:
                        combined[k] += entry["usage"].get(k, 0)
                print(_format_usage_line("Combined", combined))
    else:
        body = response["response"].read().decode("utf-8")
        print(body)

    elapsed = (datetime.now() - start).total_seconds()
    print(f"\n{GREEN}✅ 완료 ({elapsed:.1f}초){NC}\n")


if __name__ == "__main__":
    main()
