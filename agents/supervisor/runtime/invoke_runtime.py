#!/usr/bin/env python3
"""
invoke_runtime.py — Phase 6a Supervisor admin invoke (단독 디버깅용 SIGV4 호출)

Supervisor Runtime 의 customJWTAuthorizer 가 Cognito Client A user JWT 만 통과시키는데,
admin 디버깅 시 (예: 배포 직후 health check) Cognito 인증 없이 호출하고 싶으면 별 문제.
**본 스크립트는 SIGV4 호출이라 customJWTAuthorizer 가 활성화된 상태에선 401 반환** —
admin 용도로는 임시로 authorizer 제거 후 사용 또는 Phase 4 invoke_runtime.py 와 동일한
패턴이 필요할 때 reference.

정상 경로:
    Operator CLI (Phase 6a Step D) — Cognito Client A USER_PASSWORD_AUTH → JWT → HTTPS POST.

사용법 (admin 디버깅 only — authorizer 비활성화 상태에서):
    uv run agents/supervisor/runtime/invoke_runtime.py --query "현재 상황 진단해줘"

사전 조건:
    - deploy_runtime.py 실행 완료 (runtime/.env 에 RUNTIME_ARN)
    - Runtime authorizer 임시 제거 (또는 IAM 호출 권한 있는 admin user)
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
    parser = argparse.ArgumentParser(description="Phase 6a Supervisor admin invoke")
    parser.add_argument(
        "--query",
        default="현재 상황 진단해줘",
        help="자연어 운영자 질의 (default: '현재 상황 진단해줘')",
    )
    return parser.parse_args()


def parse_sse_event(line_bytes: bytes) -> dict | None:
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
    if not RUNTIME_ARN:
        print(f"{RED}❌ RUNTIME_ARN 미설정 — deploy_runtime.py 먼저 실행{NC}")
        sys.exit(1)

    print(f"{BLUE}{'=' * 60}{NC}")
    print(f"  Phase 6a Supervisor invoke")
    print(f"  Query: {args.query}")
    print(f"  Runtime ARN: {RUNTIME_ARN}")
    print(f"{BLUE}{'=' * 60}{NC}")
    print(f"{YELLOW}⚠️  본 스크립트는 SIGV4 — Runtime 의 customJWTAuthorizer 가 활성화된 상태에선{NC}")
    print(f"{YELLOW}    401 반환. 정상 경로는 Operator CLI (Phase 6a Step D).{NC}\n")

    config = Config(connect_timeout=300, read_timeout=600, retries={"max_attempts": 0})
    client = boto3.client("bedrock-agentcore", region_name=REGION, config=config)

    payload = {"query": args.query}

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
                f"Output: {usage_summary.get('outputTokens', 0):,}{NC}"
            )
    else:
        body = response["response"].read().decode("utf-8")
        print(body)

    elapsed = (datetime.now() - start).total_seconds()
    print(f"\n{GREEN}✅ 완료 ({elapsed:.1f}초){NC}\n")


if __name__ == "__main__":
    main()
