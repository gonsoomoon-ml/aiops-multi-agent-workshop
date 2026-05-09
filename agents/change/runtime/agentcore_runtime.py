#!/usr/bin/env python3
"""
agentcore_runtime.py — Phase 6a Change Agent Runtime 진입점 (A2A protocol)

Phase 4 incident `agentcore_runtime.py` 와 다른 점:
  - **A2A protocol** — `BedrockAgentCoreApp` + `@app.entrypoint` 미사용. 대신 Strands
    `A2AServer.to_fastapi_app()` 가 FastAPI app 을 생성, uvicorn 으로 port 9000 root
    path 에 expose. AgentCore Runtime 의 `protocolConfiguration: A2A` 와 정합.
  - **두 Target prefix 필터** — `deployments-storage___` (read) + `github-storage___`
    (incidents append) 두 Target 의 tool 만 caller 에 전달.
  - **Inbound Authorizer** — Cognito Client C (Phase 2 재사용, Option X) Bearer JWT 가
    AgentCore 측에서 검증된 후 도달. 본 코드는 직접 검증 안 함.
  - **payload schema** — A2A `message/send` 의 user message text 가 그대로 입력. JSON
    str 또는 plain text 둘 다 허용 — system_prompt 가 JSON parsing.

사용법:
    Runtime 컨테이너 안에서 `python -m agentcore_runtime` (Dockerfile CMD) — uvicorn
    이 :9000 에서 listen. AgentCore 가 inbound JWT 검증 + path prefix strip 후 forward.

사전 조건 (Runtime 환경변수, deploy_runtime.py 가 launch 시 주입):
    - GATEWAY_URL: Phase 2 Gateway endpoint
    - OAUTH_PROVIDER_NAME: Change OAuth provider 이름 (Gateway 호출용 Client C M2M)
    - COGNITO_GATEWAY_SCOPE: Cognito Resource Server scope
    - CHANGE_MODEL_ID: Bedrock model ID (default Haiku 4.5)
    - DEMO_USER: alarm name prefix 정렬용
    - AGENTCORE_RUNTIME_URL: AgentCore 자동 주입 — AgentCard `url` 필드에 사용
    - OTEL_RESOURCE_ATTRIBUTES, AGENT_OBSERVABILITY_ENABLED: CW GenAI Observability

A2A wire:
    - `POST /` — message/send (JSON-RPC). body parts[0].text 가 LLM 입력.
    - `GET /.well-known/agent-card.json` — AgentCard discovery (skills 자동 도출).

reference:
    - phase4.md §3 (Incident Agent 패턴 — tools 주입 시그니처 carry-over)
    - phase6a.md §4 (Change Agent 권한 범위)
    - 02-a2a-agent-sigv4/agent.py (Strands A2AServer 최소 예제)
"""
import os
import sys
from pathlib import Path

import uvicorn
from bedrock_agentcore.identity.auth import requires_access_token
from fastapi import FastAPI
from strands.multiagent.a2a import A2AServer

SCRIPT_DIR = Path(__file__).resolve().parent

# 로컬 dev 시 sibling 디렉토리 sys.path 추가. 컨테이너에선 cwd (/app) 자동 — 별도 insert 불필요.
# - 컨테이너: /app/shared (helper from monitor_a2a) + /app/change_shared (truth)
# - 로컬: agents/monitor_a2a/shared (helper) + agents/change/shared (truth)
if (SCRIPT_DIR.parent / "shared").is_dir():
    sys.path.insert(0, str(SCRIPT_DIR.parents[2]))   # PROJECT_ROOT for `agents.X.shared.Y`

# import — 컨테이너 vs 로컬 구분
try:
    # 컨테이너 (build context flatten 후): /app/shared + /app/change_shared
    from shared.mcp_client import create_mcp_client                   # monitor_a2a helper
    from change_shared.agent import create_agent                       # change truth
except ModuleNotFoundError:
    # 로컬 dev — sys.path 에 PROJECT_ROOT 가 추가됨
    from agents.monitor_a2a.shared.mcp_client import create_mcp_client  # noqa: E402
    from agents.change.shared.agent import create_agent                 # noqa: E402

OAUTH_PROVIDER_NAME = os.environ["OAUTH_PROVIDER_NAME"]
COGNITO_GATEWAY_SCOPE = os.environ["COGNITO_GATEWAY_SCOPE"]
RUNTIME_URL = os.environ.get("AGENTCORE_RUNTIME_URL", "http://127.0.0.1:9000/")
DEMO_USER = os.environ.get("DEMO_USER", "ubuntu")
AGENT_NAME = f"aiops_demo_{DEMO_USER}_change"

# Change 는 두 Target 의 도구 모두 사용 (deployments read + incidents append)
TOOL_TARGET_PREFIXES = ("deployments-storage___", "github-storage___")
SYSTEM_PROMPT_FILENAME = "system_prompt.md"


@requires_access_token(
    provider_name=OAUTH_PROVIDER_NAME,
    scopes=[COGNITO_GATEWAY_SCOPE],
    auth_flow="M2M",
    into="access_token",
)
async def _fetch_gateway_token(*, access_token: str = "") -> str:
    """Gateway 호출용 token (Client C M2M) — Phase 3/4 와 동일 패턴."""
    return access_token


def _build_change_agent():
    """Strands Agent — Gateway tool 의 두 Target 만 필터해 주입.

    A2A server 가 init 시점에 1회 호출. session 별 재구성 안 함 (AgentCore 의
    workload-accesstoken 은 outbound 에 사용되지 않으므로 본 패턴은 OAuth provider 의
    `access_token` 으로 일관 — Phase 3/4 패턴 동일).
    """
    import asyncio

    gateway_token = asyncio.run(_fetch_gateway_token())
    mcp_client = create_mcp_client(gateway_token=gateway_token)
    mcp_client.start()
    all_tools = mcp_client.list_tools_sync()
    tools = [
        t for t in all_tools
        if t.tool_name.startswith(TOOL_TARGET_PREFIXES)
    ]
    if not tools:
        received = [t.tool_name for t in all_tools]
        raise RuntimeError(
            f"Change tool 0개 — prefix {TOOL_TARGET_PREFIXES} 매칭 실패. 받음: {received}. "
            f"Phase 6a Step C (deployments-storage Target 등록) 가 선행되어야 함."
        )
    return create_agent(tools=tools, system_prompt_filename=SYSTEM_PROMPT_FILENAME)


# Strands Agent 1회 init — A2AServer 가 그대로 wrap
agent = _build_change_agent()
agent.name = AGENT_NAME
agent.description = "Change Agent — 24h 배포 이력 lookup + incident log append"

# A2A server — AgentCore Runtime 의 path prefix `/runtimes/{arn}/invocations/` 를
# strip 한 root path 에 마운트해야 함 → `serve_at_root=True`.
a2a_server = A2AServer(
    agent=agent,
    http_url=RUNTIME_URL,
    serve_at_root=True,
)

app = FastAPI()
app.mount("/", a2a_server.to_fastapi_app())


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9000)
