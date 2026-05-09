#!/usr/bin/env python3
"""
invoke_runtime.py — Phase 6a Supervisor admin invoke (단독 디버깅용 SIGV4 호출)

Phase 6a Option X 에서 Supervisor 는 **customJWTAuthorizer 미설정 = SigV4 default** —
본 스크립트도 정상 경로의 simplified version. agents/operator/cli.py 와 동일한 SigV4
인증을 admin 친화 형식으로 노출 (CLI args, 별 default query 등).

정상 경로:
    `python agents/operator/cli.py --query "..."` — Operator CLI (Phase 6a Step D).

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
