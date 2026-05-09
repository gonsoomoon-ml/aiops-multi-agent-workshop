#!/usr/bin/env python3
"""
Operator CLI — Phase 6a end-to-end 진입점.

워크샵 청중 (운영자) 가 Supervisor Runtime 을 호출하는 정상 경로:
  1. Cognito Client A 로 USER_PASSWORD_AUTH → IdToken (Bearer JWT)
  2. AgentCore Runtime endpoint 에 HTTPS POST (Authorization: Bearer)
  3. SSE 스트림 stdout 출력 — Supervisor 가 sub-agent 들 호출하며 stream

Phase 4 의 ``invoke_runtime.py`` (boto3 SIGV4) 와의 차이:
  - **인증 방식**: SIGV4 → **Cognito JWT Bearer** (Supervisor 의 customJWTAuthorizer 가
    allowedClients=[ClientA] 로 검증).
  - **HTTP client**: boto3 `invoke_agent_runtime` → **httpx 직접 POST** (boto3 가 자동
    SIGV4 signing 하므로 Bearer 사용 불가).
  - **endpoint URL**: 동일 (`https://bedrock-agentcore.{region}.amazonaws.com/runtimes/
    {quote(arn)}/invocations`).

사용법:
    python agents/operator/cli.py --query "현재 상황 진단해줘"
    python agents/operator/cli.py --query "alarm payment-ubuntu-status-check 진단"

사전 조건:
    - Phase 6a Step C 완료 (`bash infra/phase6a/deploy.sh`)
        → repo `.env` 에 COGNITO_USER_POOL_ID / COGNITO_CLIENT_A_ID / OPERATOR_USERNAME
        → repo `.env.operator` 에 OPERATOR_PASSWORD
    - Supervisor Runtime 배포 완료 (`agents/supervisor/runtime/.env` 에 RUNTIME_ARN)

reference:
    - docs/design/phase6a.md §8 (Operator CLI 상세)
    - 02-use-cases/A2A-multi-agent-incident-response/host_adk_agent (Web UI 변형)
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import boto3
import httpx
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(PROJECT_ROOT / ".env.operator", override=True)
load_dotenv(PROJECT_ROOT / "agents" / "supervisor" / "runtime" / ".env", override=False)

REGION = os.getenv("AWS_REGION", "us-west-2")
COGNITO_CLIENT_A_ID = os.getenv("COGNITO_CLIENT_A_ID", "")
OPERATOR_USERNAME = os.getenv("OPERATOR_USERNAME", "")
OPERATOR_PASSWORD = os.getenv("OPERATOR_PASSWORD", "")
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
        description="Phase 6a Operator CLI — Supervisor 호출 (Cognito JWT)"
    )
    parser.add_argument(
        "--query",
        default="현재 상황 진단해줘",
        help="자연어 운영자 질의 (default: '현재 상황 진단해줘')",
    )
    parser.add_argument(
        "--session-id",
        default=None,
        help="X-Amzn-Bedrock-AgentCore-Runtime-Session-Id (default: 자동 생성)",
    )
    return parser.parse_args()


def check_prereqs() -> None:
    """필수 env / .env 항목 검증 — 미설정 시 명시적 메시지 후 종료."""
    missing = []
    if not COGNITO_CLIENT_A_ID:
        missing.append("COGNITO_CLIENT_A_ID (.env — Phase 6a Step C 산출물)")
    if not OPERATOR_USERNAME:
        missing.append("OPERATOR_USERNAME (.env)")
    if not OPERATOR_PASSWORD:
        missing.append("OPERATOR_PASSWORD (.env.operator)")
    if not SUPERVISOR_RUNTIME_ARN:
        missing.append(
            "SUPERVISOR_RUNTIME_ARN or RUNTIME_ARN "
            "(agents/supervisor/runtime/.env — Step B Supervisor deploy 산출물)"
        )
    if missing:
        print(f"{RED}❌ 필수 설정 미존재:{NC}", file=sys.stderr)
        for item in missing:
            print(f"  - {item}", file=sys.stderr)
        print(file=sys.stderr)
        print(
            "Phase 6a 의 Step C (`bash infra/phase6a/deploy.sh`) 와 Step B "
            "(`agents/supervisor/runtime/deploy_runtime.py`) 둘 다 통과한 상태인지 확인.",
            file=sys.stderr,
        )
        sys.exit(1)


def get_id_token() -> str:
    """Cognito Client A 로 USER_PASSWORD_AUTH → IdToken (JWT)."""
    cognito = boto3.client("cognito-idp", region_name=REGION)
    try:
        resp = cognito.initiate_auth(
            ClientId=COGNITO_CLIENT_A_ID,
            AuthFlow="USER_PASSWORD_AUTH",
            AuthParameters={
                "USERNAME": OPERATOR_USERNAME,
                "PASSWORD": OPERATOR_PASSWORD,
            },
        )
    except cognito.exceptions.NotAuthorizedException as e:
        print(f"{RED}❌ Cognito 인증 실패: {e}{NC}", file=sys.stderr)
        print(
            "  username / password 확인. Phase 6a deploy.sh 가 .env.operator 에 작성한 값.",
            file=sys.stderr,
        )
        sys.exit(2)
    except Exception as e:
        print(f"{RED}❌ Cognito initiate_auth 에러: {e}{NC}", file=sys.stderr)
        sys.exit(2)

    auth_result = resp.get("AuthenticationResult") or {}
    id_token = auth_result.get("IdToken")
    if not id_token:
        # Cognito 가 challenge 반환 (예: NEW_PASSWORD_REQUIRED) 시 처리
        challenge = resp.get("ChallengeName")
        print(
            f"{RED}❌ IdToken 미반환. ChallengeName: {challenge!r}{NC}",
            file=sys.stderr,
        )
        sys.exit(2)
    return id_token


def parse_sse_event(line: str) -> dict | None:
    """SSE `data: {...}` 라인을 dict 로 파싱."""
    line = line.strip()
    if not line or not line.startswith("data: "):
        return None
    payload = line[6:].strip()
    if not payload:
        return None
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return None


def stream_supervisor(id_token: str, query: str, session_id: str | None) -> int:
    """Supervisor Runtime 에 HTTPS POST → SSE 스트림 stdout.

    Returns: HTTP status code (200 정상). 비정상 시 본문 dump.
    """
    url = (
        f"https://bedrock-agentcore.{REGION}.amazonaws.com/runtimes/"
        f"{quote(SUPERVISOR_RUNTIME_ARN, safe='')}/invocations?qualifier=DEFAULT"
    )
    headers = {
        "Authorization": f"Bearer {id_token}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    if session_id:
        # 32+ chars 권장 (AgentCore docs)
        headers["X-Amzn-Bedrock-AgentCore-Runtime-Session-Id"] = session_id

    body = {"query": query}
    usage_summary: dict | None = None

    print(f"{BLUE}{'=' * 60}{NC}")
    print(f"  Phase 6a Operator → Supervisor")
    print(f"  Query: {query}")
    print(f"  Runtime ARN: {SUPERVISOR_RUNTIME_ARN}")
    print(f"{BLUE}{'=' * 60}{NC}\n")

    start = datetime.now()
    try:
        with httpx.stream(
            "POST", url,
            json=body, headers=headers,
            timeout=httpx.Timeout(connect=30, read=600, write=30, pool=30),
        ) as resp:
            if resp.status_code != 200:
                err = resp.read().decode("utf-8", errors="replace")
                print(f"{RED}❌ HTTP {resp.status_code}{NC}", file=sys.stderr)
                print(err, file=sys.stderr)
                return resp.status_code

            content_type = resp.headers.get("content-type", "")
            if "text/event-stream" in content_type:
                for line in resp.iter_lines():
                    event = parse_sse_event(line)
                    if event is None:
                        continue
                    etype = event.get("type")
                    if etype == "agent_text_stream":
                        print(event.get("text", ""), end="", flush=True)
                    elif etype == "token_usage":
                        usage_summary = event.get("usage", {})
            else:
                # SSE 가 아닐 경우 본문 그대로 출력
                body_text = resp.read().decode("utf-8", errors="replace")
                print(body_text)
    except httpx.HTTPError as e:
        print(f"{RED}❌ HTTP 에러: {e}{NC}", file=sys.stderr)
        return -1

    if usage_summary:
        print()
        print(
            f"{DIM}📊 Tokens — Total: {usage_summary.get('totalTokens', 0):,} | "
            f"Input: {usage_summary.get('inputTokens', 0):,} | "
            f"Output: {usage_summary.get('outputTokens', 0):,} | "
            f"Cache R/W: {usage_summary.get('cacheReadInputTokens', 0):,}/"
            f"{usage_summary.get('cacheWriteInputTokens', 0):,}{NC}"
        )

    elapsed = (datetime.now() - start).total_seconds()
    print(f"\n{GREEN}✅ 완료 ({elapsed:.1f}초){NC}\n")
    return 0


def main() -> None:
    args = parse_args()
    check_prereqs()
    id_token = get_id_token()
    print(f"{GREEN}✓ Cognito Client A 인증 통과{NC} (IdToken {len(id_token)} chars)\n")
    rc = stream_supervisor(id_token, args.query, args.session_id)
    sys.exit(rc if rc < 0 else 0)


if __name__ == "__main__":
    main()
