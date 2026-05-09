#!/usr/bin/env python3
"""
agentcore_runtime.py — Phase 6a Monitor A2A Runtime 진입점

Phase 4 ``agents/monitor/runtime/agentcore_runtime.py`` (HTTP) 의 **A2A 변형**.
preservation rule (2026-05-09) 에 따라 Phase 4 monitor 코드는 미터치 — 본 디렉토리는
신규 사본 + A2A protocol wrap. workshop 청중이 두 디렉토리를 line-by-line 비교 가능.

Phase 4 monitor 와의 차이:
  - **A2A protocol** — `BedrockAgentCoreApp` + `@app.entrypoint` 미사용. Strands
    `A2AServer.to_fastapi_app()` 가 FastAPI 로 wrap, uvicorn 으로 :9000 listen.
  - **Live mode 전용** — Phase 4 monitor 의 dual mode (past/live) 중 live 만 노출.
    Past mode 는 Phase 4 monitor (HTTP) 가 그대로 처리. Phase 6a 의 Supervisor flow
    가 "현재 alarm 상황" → "alarm 별 incident" 인 것에 정합.
  - **AgentCard 자동 생성** — `agent.tool_registry` 의 Gateway tool 들이 skill 로
    자동 export. caller 가 `.well-known/agent-card.json` 으로 발견.

사전 조건 (Runtime 환경변수):
    - GATEWAY_URL: Phase 2 Gateway endpoint
    - OAUTH_PROVIDER_NAME: Monitor A2A OAuth provider 이름 (Gateway 호출용 Client C M2M)
    - COGNITO_GATEWAY_SCOPE: Cognito Resource Server scope
    - MONITOR_MODEL_ID: Bedrock model ID
    - DEMO_USER: live mode query 의 ``payment-{user}-*`` prefix 채움
    - AGENTCORE_RUNTIME_URL: AgentCore 자동 주입 — AgentCard `url` 필드에 사용
    - OTEL_RESOURCE_ATTRIBUTES, AGENT_OBSERVABILITY_ENABLED

A2A wire:
    - `POST /` — message/send. body parts[0].text 가 LLM 입력.
    - `GET /.well-known/agent-card.json` — AgentCard discovery.

reference:
    - phase3.md §3-4 (호출 흐름) — Phase 4 monitor 와 도구/Agent 흐름 동일
    - phase6a.md §5 (A2A 활성화), §10-2 (02-a2a-agent-sigv4 reference)
"""
import os
import sys
from pathlib import Path

import uvicorn
from bedrock_agentcore.identity.auth import requires_access_token
from fastapi import FastAPI
from strands.multiagent.a2a import A2AServer

SCRIPT_DIR = Path(__file__).resolve().parent

# 로컬 dev 시 sibling shared/ — sys.path 에 parent 추가. 컨테이너에선 cwd (/app) 자동.
if (SCRIPT_DIR.parent / "shared").is_dir():
    sys.path.insert(0, str(SCRIPT_DIR.parent))

from shared.agent import create_agent          # noqa: E402
from shared.mcp_client import create_mcp_client  # noqa: E402
from shared.modes import MODE_CONFIG             # noqa: E402

OAUTH_PROVIDER_NAME = os.environ["OAUTH_PROVIDER_NAME"]
COGNITO_GATEWAY_SCOPE = os.environ["COGNITO_GATEWAY_SCOPE"]
RUNTIME_URL = os.environ.get("AGENTCORE_RUNTIME_URL", "http://127.0.0.1:9000/")
DEMO_USER = os.environ.get("DEMO_USER", "ubuntu")
AGENT_NAME = f"aiops_demo_{DEMO_USER}_monitor_a2a"

# Phase 6a Monitor A2A = live mode 전용. past mode 는 Phase 4 monitor (HTTP) 가 처리.
MODE = "live"
TARGET_PREFIX, PROMPT_FILENAME = MODE_CONFIG[MODE]


@requires_access_token(
    provider_name=OAUTH_PROVIDER_NAME,
    scopes=[COGNITO_GATEWAY_SCOPE],
    auth_flow="M2M",
    into="access_token",
)
async def _fetch_gateway_token(*, access_token: str = "") -> str:
    """Gateway 호출용 token (Client C M2M) — Phase 3/4 와 동일 패턴."""
    return access_token


def _build_monitor_agent():
    """Strands Agent — Gateway 의 cloudwatch-wrapper Target tool 만 필터해 주입."""
    import asyncio

    gateway_token = asyncio.run(_fetch_gateway_token())
    mcp_client = create_mcp_client(gateway_token=gateway_token)
    mcp_client.start()
    all_tools = mcp_client.list_tools_sync()
    tools = [t for t in all_tools if t.tool_name.startswith(TARGET_PREFIX)]
    if not tools:
        received = [t.tool_name for t in all_tools]
        raise RuntimeError(
            f"Monitor live tool 0개 — prefix '{TARGET_PREFIX}' 매칭 실패. 받음: {received}"
        )
    return create_agent(tools=tools, system_prompt_filename=PROMPT_FILENAME)


# Strands Agent 1회 init — A2AServer 가 wrap
agent = _build_monitor_agent()
agent.name = AGENT_NAME
agent.description = (
    "Monitor Agent (live mode) — 현재 라이브 CloudWatch 알람 분류, "
    "real (유효) vs noise (개선) 식별"
)

a2a_server = A2AServer(
    agent=agent,
    http_url=RUNTIME_URL,
    serve_at_root=True,
)

app = FastAPI()
app.mount("/", a2a_server.to_fastapi_app())


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9000)
