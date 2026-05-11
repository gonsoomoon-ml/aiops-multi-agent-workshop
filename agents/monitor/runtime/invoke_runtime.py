#!/usr/bin/env python3
"""
invoke_runtime.py — Phase 3 Monitor Agent Runtime 단일 호출 (배포 검증용)

배포된 AgentCore Runtime 에 invoke 1회 보내고 SSE 스트리밍 응답을 stdout 에 출력합니다.
P3-A4 (live mode 알람 분류 검증) 의 인터랙티브 도구. C1 (local == Runtime) 검증은
워크샵 청중이 두 출력을 직접 비교 — `local/run.py` 와 본 스크립트의 출력 대조.

사용법:
    uv run agents/monitor/runtime/invoke_runtime.py                          # default mode=live
    uv run agents/monitor/runtime/invoke_runtime.py --mode past
    uv run agents/monitor/runtime/invoke_runtime.py --mode past --query "특정 알람만 분석"

사전 조건:
    - deploy_runtime.py 실행 완료 (runtime/.env 에 RUNTIME_ARN 작성됨)
    - AWS 자격 증명 설정 (aws configure 또는 AWS_PROFILE)

reference:
    - phase3.md §8-1 (단일 호출 + SSE 파싱 패턴, payload schema D4)
    - developer-briefing-agent/managed-agentcore/example_invoke.py (한국어 docstring + argparse 패턴)
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
load_dotenv(SCRIPT_DIR / ".env", override=True)

REGION = os.getenv("AWS_REGION", "us-west-2")
RUNTIME_ARN = os.getenv("RUNTIME_ARN")

GREEN, YELLOW, BLUE, RED, DIM, NC = (
    "\033[0;32m", "\033[1;33m", "\033[0;34m", "\033[0;31m", "\033[2m", "\033[0m"
)


def parse_args() -> argparse.Namespace:
    """CLI 인자 파싱 — ``--mode`` (past|live) + ``--query`` (선택)."""
    parser = argparse.ArgumentParser(
        description="Monitor Agent AgentCore Runtime 호출 (P3-A3/A4 검증)"
    )
    parser.add_argument(
        "--mode",
        choices=["past", "live"],
        default="live",
        help="분석 모드 — past (7일 알람 history) | live (현재 알람) (기본값: live)",
    )
    parser.add_argument(
        "--query",
        default=None,
        help="LLM 에 전달할 질의 (생략 시 mode 별 default 템플릿 사용)",
    )
    return parser.parse_args()


def parse_sse_event(line_bytes: bytes) -> dict | None:
    """SSE ``data: {...}`` 라인을 dict 로 파싱. 빈 줄 / 비-JSON 은 None 반환."""
    if not line_bytes:
        return None
    try:
        text = line_bytes.decode("utf-8").strip()
        if text.startswith("data: "):
            text = text[6:]
        return json.loads(text) if text else None
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def main() -> None:
    """invoke_agent_runtime 단일 호출 + SSE 스트림 stdout 출력."""
    args = parse_args()
    if not RUNTIME_ARN:
        print(f"{RED}❌ RUNTIME_ARN 미설정 — deploy_runtime.py 먼저 실행{NC}")
        sys.exit(1)

    print(f"{BLUE}{'=' * 60}{NC}")
    print(f"  Phase 3 Runtime invoke — mode={args.mode}")
    print(f"  Runtime ARN: {RUNTIME_ARN}")
    print(f"{BLUE}{'=' * 60}{NC}\n")

    config = Config(connect_timeout=300, read_timeout=600, retries={"max_attempts": 0})
    client = boto3.client("bedrock-agentcore", region_name=REGION, config=config)

    payload = {"mode": args.mode}
    if args.query:
        payload["query"] = args.query

    start = datetime.now()
    # SIGV4 invoke 시 runtime 안에서 workload identity token 획득에 필수 (D2 OAuth 흐름 전제)
    response = client.invoke_agent_runtime(
        agentRuntimeArn=RUNTIME_ARN,
        qualifier="DEFAULT",
        runtimeUserId=os.getenv("DEMO_USER", "ubuntu"),
        payload=json.dumps(payload),
    )

    content_type = response.get("contentType", "")
    if "text/event-stream" in content_type:
        usage_summary = None
        for line in response["response"].iter_lines(chunk_size=1):
            event = parse_sse_event(line)
            if event is None:
                continue
            etype = event.get("type")
            if etype == "agent_text_stream":
                print(event.get("text", ""), end="", flush=True)
            elif etype == "token_usage":
                usage_summary = event.get("usage", {})
        if usage_summary:
            print()
            print(
                f"{DIM}📊 Tokens — Total: {usage_summary.get('totalTokens', 0):,} | "
                f"Input: {usage_summary.get('inputTokens', 0):,} | "
                f"Output: {usage_summary.get('outputTokens', 0):,} | "
                f"Cache R/W: {usage_summary.get('cacheReadInputTokens', 0):,}/"
                f"{usage_summary.get('cacheWriteInputTokens', 0):,}{NC}"
            )
    else:
        body = response["response"].read().decode("utf-8")
        print(body)

    elapsed = (datetime.now() - start).total_seconds()
    print(f"\n{GREEN}✅ 완료 ({elapsed:.1f}초){NC}\n")


if __name__ == "__main__":
    main()
