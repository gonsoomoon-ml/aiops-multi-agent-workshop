#!/usr/bin/env python3
"""
invoke_runtime.py — Phase 4 Incident Agent Runtime 단일 호출 (P4-A2 검증용)

배포된 Incident Runtime 에 invoke 1회 보내고 SSE 응답 stdout 출력. payload 는
``{"alarm_name": "<alarm full name>"}`` — Monitor 와 다른 schema (alarm 단위 진단).

사용법:
    uv run agents/incident/runtime/invoke_runtime.py --alarm payment-ubuntu-status-check
    uv run agents/incident/runtime/invoke_runtime.py --alarm payment-ubuntu-noisy-cpu
    uv run agents/incident/runtime/invoke_runtime.py --alarm ... --session-id workshop-<32hex>  # warm container

사전 조건:
    - deploy_runtime.py 실행 완료 (repo root .env 에 ``INCIDENT_RUNTIME_ARN`` 등 작성됨)
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
PROJECT_ROOT = SCRIPT_DIR.parents[2]
# 모든 metadata 가 repo root .env (INCIDENT_ prefix) — phase 3/5 와 namespace 분리
load_dotenv(PROJECT_ROOT / ".env")

REGION = os.getenv("AWS_REGION", "us-west-2")
RUNTIME_ARN = os.getenv("INCIDENT_RUNTIME_ARN")

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
    parser.add_argument(
        "--session-id",
        default=None,
        help=(
            "동일 ID 로 재호출 시 같은 warm container 재사용 → TTFT 단축 시연. "
            "AgentCore 제약: 최소 33자 (UUID hex 32자 + prefix 권장). "
            "생략 시 매 호출이 fresh microVM (cold 가능). dba chat.py 의 runtimeSessionId 패턴."
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


def main() -> None:
    """invoke_agent_runtime 단일 호출 + SSE 스트림 stdout."""
    args = parse_args()
    if not RUNTIME_ARN:
        print(f"{RED}❌ INCIDENT_RUNTIME_ARN 미설정 — deploy_runtime.py 먼저 실행{NC}")
        sys.exit(1)

    print(f"{BLUE}{'=' * 60}{NC}")
    print(f"  Phase 4 Incident invoke — alarm={args.alarm}")
    print(f"  Runtime ARN: {RUNTIME_ARN}")
    if args.session_id:
        print(f"  Session ID:  {args.session_id} (warm container 재사용 시도)")
    print(f"{BLUE}{'=' * 60}{NC}\n")

    config = Config(connect_timeout=300, read_timeout=600, retries={"max_attempts": 0})
    client = boto3.client("bedrock-agentcore", region_name=REGION, config=config)

    payload = {"alarm_name": args.alarm}

    # SIGV4 invoke — runtimeSessionId 명시 시 같은 microVM 의 warm container 재사용
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

    content_type = response.get("contentType", "")
    t_first_text = None  # client-side TTFT — 첫 agent_text_stream chunk 도착 시점
    if "text/event-stream" in content_type:
        usage_summary = None
        for line in response["response"].iter_lines(chunk_size=1):
            event = parse_sse_event(line)
            if event is None:
                continue
            etype = event.get("type")
            if etype == "agent_text_stream":
                if t_first_text is None:
                    t_first_text = datetime.now()
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
    if t_first_text is not None:
        ttft = (t_first_text - start).total_seconds()
        print(f"\n{GREEN}✅ 완료 — TTFT {ttft:.1f}초 / total {elapsed:.1f}초{NC}\n")
    else:
        print(f"\n{GREEN}✅ 완료 ({elapsed:.1f}초){NC}\n")


if __name__ == "__main__":
    main()
