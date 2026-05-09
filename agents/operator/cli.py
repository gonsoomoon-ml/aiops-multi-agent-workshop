#!/usr/bin/env python3
"""
Operator CLI — Phase 6a end-to-end 진입점 (Option X — SigV4 IAM).

워크샵 청중 (운영자) 가 Supervisor Runtime 을 호출하는 정상 경로:
  1. AWS 자격증명 (`aws configure` 로 설정한 IAM credentials)
  2. boto3 `bedrock-agentcore.invoke_agent_runtime` (SigV4 자동 서명)
  3. SSE 스트림 stdout — Supervisor 가 sub-agent 들 호출하며 stream

Phase 6a Option X 에서 Cognito Client A + OperatorUser 신규 자원 추가 0 — Operator
도 Phase 4 invoke 와 동일한 SigV4 IAM 사용. Cognito 는 Supervisor 의 outbound (Phase 2
Client C 재사용) 에만 등장.

Phase 4 의 ``agents/{monitor,incident}/runtime/invoke_runtime.py`` 와 다른 점:
  - **payload 스키마**: ``{"query": "<자연어 운영자 질의>"}`` (Monitor 의 mode + Incident 의 alarm_name 통합)
  - **응답 형식**: Supervisor 가 만든 통합 JSON (system_prompt schema) — 코드 측 해석 불필요

사용법:
    python agents/operator/cli.py --query "현재 상황 진단해줘"
    python agents/operator/cli.py --query "alarm payment-ubuntu-status-check 진단"

사전 조건:
    - Phase 6a Step C 완료 (`bash infra/phase6a/deploy.sh`) — deployments-storage Lambda + Target
    - Supervisor Runtime 배포 완료 (`agents/supervisor/runtime/.env` 에 SUPERVISOR_RUNTIME_ARN)
    - AWS 자격증명 + 사용자 IAM Role 에 ``bedrock-agentcore:InvokeAgentRuntime`` 권한

reference:
    - docs/design/phase6a.md §8 (Operator CLI) — Option X refactor 후
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

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(PROJECT_ROOT / "agents" / "supervisor" / "runtime" / ".env", override=False)

REGION = os.getenv("AWS_REGION", "us-west-2")
SUPERVISOR_RUNTIME_ARN = (
    os.getenv("SUPERVISOR_RUNTIME_ARN")
    or os.getenv("RUNTIME_ARN")          # supervisor/runtime/.env 의 generic key
    or ""
)

GREEN, YELLOW, BLUE, RED, DIM, NC = (
    "\033[0;32m", "\033[1;33m", "\033[0;34m", "\033[0;31m", "\033[2m", "\033[0m"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Phase 6a Operator CLI — Supervisor Runtime 호출 (SigV4 IAM)"
    )
    parser.add_argument(
        "--query",
        default="현재 상황 진단해줘",
        help="자연어 운영자 질의 (default: '현재 상황 진단해줘')",
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
    args = parse_args()
    if not SUPERVISOR_RUNTIME_ARN:
        print(f"{RED}❌ SUPERVISOR_RUNTIME_ARN 미설정{NC}", file=sys.stderr)
        print(
            "  agents/supervisor/runtime/deploy_runtime.py 먼저 실행 — runtime/.env 에 ARN 작성됨.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"{BLUE}{'=' * 60}{NC}")
    print(f"  Phase 6a Operator → Supervisor")
    print(f"  Query: {args.query}")
    print(f"  Runtime ARN: {SUPERVISOR_RUNTIME_ARN}")
    print(f"{BLUE}{'=' * 60}{NC}\n")

    config = Config(connect_timeout=300, read_timeout=600, retries={"max_attempts": 0})
    client = boto3.client("bedrock-agentcore", region_name=REGION, config=config)

    payload = {"query": args.query}
    runtime_user_id = os.getenv("DEMO_USER", "ubuntu")

    start = datetime.now()
    response = client.invoke_agent_runtime(
        agentRuntimeArn=SUPERVISOR_RUNTIME_ARN,
        qualifier="DEFAULT",
        runtimeUserId=runtime_user_id,
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
