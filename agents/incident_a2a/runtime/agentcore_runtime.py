#!/usr/bin/env python3
"""
agentcore_runtime.py — Phase 6a Incident A2A Runtime 진입점

Phase 4 ``agents/incident/runtime/agentcore_runtime.py`` (HTTP) 의 **A2A 변형**.
preservation rule 에 따라 Phase 4 incident 코드는 미터치 — 본 디렉토리는 신규 사본 +
A2A protocol wrap.

Phase 4 incident 와의 차이:
  - **A2A protocol** — `BedrockAgentCoreApp` + `@app.entrypoint` 미사용. Strands
    `A2AServer.to_fastapi_app()` 가 FastAPI 로 wrap, uvicorn 으로 :9000 listen.
  - **Inbound auth** — Cognito Client C Bearer JWT (Phase 2 재사용, allowedClients=[C]).
  - **AgentCard 자동 생성** — `agent.tool_registry` 의 github-storage tool 들이 skill 로 export.
  - **payload schema** — A2A `message/send` 의 user message text 가 그대로 입력.
    Phase 4 의 `{"alarm_name": "..."}` 와 호환되도록 system_prompt 가 처리.

helper (auth_local, mcp_client, env_utils) 는 **Phase 4 monitor/shared** 직접 재사용 +
truth (`agent.py + prompts/`) 는 **Phase 4 incident/shared** 직접 재사용 (Option G —
2026-05-09 review). incident_a2a 자체에 shared/ 없음, runtime/ 만 보유. caller 측 build
context Option A 로 deploy 시 두 Phase 4 디렉토리 모두 copy.

reference:
    - phase4.md §3 (Incident Agent — payload + tool 흐름 carry-over)
    - phase6a.md §5 (A2A 활성화)
"""
import os
import sys
from pathlib import Path

import uvicorn
from bedrock_agentcore.identity.auth import requires_access_token
from fastapi import FastAPI
from strands.multiagent.a2a import A2AServer

SCRIPT_DIR = Path(__file__).resolve().parent

# Phase 4 monitor/shared (helper) + incident/shared (truth) 를 직접 재사용 (Option G).
# 컨테이너: deploy_runtime.py 가 두 디렉토리를 runtime/ 에 copy.
# 로컬 dev: agents.monitor.shared + agents.incident.shared 직접 import (Phase 4).
if (SCRIPT_DIR / "shared").is_dir():
    sys.path.insert(0, str(SCRIPT_DIR))                # /app/shared + /app/incident_shared
else:
    sys.path.insert(0, str(SCRIPT_DIR.parents[2]))     # PROJECT_ROOT for agents.* import

try:
    # 컨테이너 (build context flatten 후): /app/shared + /app/incident_shared
    from shared.mcp_client import create_mcp_client                       # Phase 4 monitor helper
    from incident_shared.agent import create_agent                         # Phase 4 incident truth
except ModuleNotFoundError:
    # 로컬 dev — Phase 4 디렉토리 직접 사용
    from agents.monitor.shared.mcp_client import create_mcp_client         # noqa: E402
    from agents.incident.shared.agent import create_agent                  # noqa: E402

OAUTH_PROVIDER_NAME = os.environ["OAUTH_PROVIDER_NAME"]
COGNITO_GATEWAY_SCOPE = os.environ["COGNITO_GATEWAY_SCOPE"]
RUNTIME_URL = os.environ.get("AGENTCORE_RUNTIME_URL", "http://127.0.0.1:9000/")
DEMO_USER = os.environ.get("DEMO_USER", "ubuntu")
AGENT_NAME = f"aiops_demo_{DEMO_USER}_incident_a2a"

# Phase 4 와 동일 — github-storage Target 만 (runbook lookup)
TOOL_TARGET_PREFIX = "github-storage___"
SYSTEM_PROMPT_FILENAME = "system_prompt.md"


@requires_access_token(
    provider_name=OAUTH_PROVIDER_NAME,
    scopes=[COGNITO_GATEWAY_SCOPE],
    auth_flow="M2M",
    into="access_token",
)
async def _fetch_gateway_token(*, access_token: str = "") -> str:
    """Gateway 호출용 token (Client C M2M)."""
    return access_token


def _build_incident_agent():
    """Strands Agent — Gateway 의 github-storage Target tool 만 필터해 주입."""
    import asyncio

    gateway_token = asyncio.run(_fetch_gateway_token())
    mcp_client = create_mcp_client(gateway_token=gateway_token)
    mcp_client.start()
    all_tools = mcp_client.list_tools_sync()
    tools = [t for t in all_tools if t.tool_name.startswith(TOOL_TARGET_PREFIX)]
    if not tools:
        received = [t.tool_name for t in all_tools]
        raise RuntimeError(
            f"Incident tool 0개 — prefix '{TOOL_TARGET_PREFIX}' 매칭 실패. 받음: {received}"
        )
    return create_agent(tools=tools, system_prompt_filename=SYSTEM_PROMPT_FILENAME)


agent = _build_incident_agent()
agent.name = AGENT_NAME
agent.description = (
    "Incident Agent — alarm 1건 → runbook 조회 → 진단 + 권장 조치 JSON 반환"
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
