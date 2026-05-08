#!/usr/bin/env python3
"""
invoke_runtime.py — Phase 4 Incident Agent Runtime 단일 호출 (P4-A2 검증용)

배포된 Incident Runtime 에 invoke 1회 보내고 SSE 응답 stdout 출력. payload 는
``{"alarm_name": "<alarm full name>"}`` — Monitor 와 다른 schema (alarm 단위 진단).

사용법:
    uv run agents/incident/runtime/invoke_runtime.py --alarm payment-ubuntu-status-check
    uv run agents/incident/runtime/invoke_runtime.py --alarm payment-ubuntu-noisy-cpu

사전 조건:
    - deploy_runtime.py 실행 완료 (runtime/.env 에 RUNTIME_ARN 작성됨)
    - AWS 자격 증명 + 사용자 IAM Role 에 ``bedrock-agentcore:InvokeAgentRuntime`` 권한

reference:
    - phase3.md §8-1 (단일 호출 + SSE 파싱)
    - phase4.md §6-1 P4-A2
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
    """CLI 인자 — ``--alarm <full alarm name>`` 필수."""
    demo_user = os.getenv("DEMO_USER", "ubuntu")
    parser = argparse.ArgumentParser(
        description="Incident Agent AgentCore Runtime 호출 (P4-A2 검증)"
    )
    parser.add_argument(
        "--alarm",
        default=f"payment-{demo_user}-status-check",
        help=(
            "Full CloudWatch alarm name (e.g., 'payment-ubuntu-status-check'). "
            f"기본값: payment-{demo_user}-status-check"
        ),
    )
    return parser.parse_args()


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


def main() -> None:
    """invoke_agent_runtime 단일 호출 + SSE 스트림 stdout."""
    args = parse_args()
    if not RUNTIME_ARN:
        print(f"{RED}❌ RUNTIME_ARN 미설정 — deploy_runtime.py 먼저 실행{NC}")
        sys.exit(1)

    print(f"{BLUE}{'=' * 60}{NC}")
    print(f"  Phase 4 Incident invoke — alarm={args.alarm}")
    print(f"  Runtime ARN: {RUNTIME_ARN}")
    print(f"{BLUE}{'=' * 60}{NC}\n")

    config = Config(connect_timeout=300, read_timeout=600, retries={"max_attempts": 0})
    client = boto3.client("bedrock-agentcore", region_name=REGION, config=config)

    payload = {"alarm_name": args.alarm}

    start = datetime.now()
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
