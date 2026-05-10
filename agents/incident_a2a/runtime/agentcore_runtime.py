#!/usr/bin/env python3
"""
agentcore_runtime.py — Phase 6a Incident A2A Runtime 진입점 (AWS canonical pattern)

AWS docs 의 `serve_a2a(StrandsA2AExecutor(agent))` 패턴 정확 차용. monitor_a2a 와 동일
LazyExecutor 패턴 — module init 시 placeholder agent, 첫 request 시 real agent 빌드.

핵심: AgentCore SDK 의 `serve_a2a` 가 `BedrockCallContextBuilder` 자동 부착 →
workload-token 헤더 → `BedrockAgentCoreContext` ContextVar → `requires_access_token`
decorator 가 작동. Strands `A2AServer.to_fastapi_app()` 단독은 이 builder 미부착.

Phase 4 helper (auth_local, mcp_client, env_utils) + truth (agent.py + prompts/) 직접
재사용 (Option G):
  - 컨테이너: shared/ (Phase 4 monitor) + incident_shared/ (Phase 4 incident)
  - 로컬: agents.monitor.shared (helper) + agents.incident.shared (truth)

reference:
    - https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-a2a.html
    - bedrock_agentcore/runtime/a2a.py (BedrockCallContextBuilder)
    - phase4.md §3 (Incident Agent — payload + tool 흐름 carry-over)
"""
import os
import sys
from pathlib import Path

from bedrock_agentcore.runtime import serve_a2a
from bedrock_agentcore.identity.auth import requires_access_token
from strands import Agent
from strands.multiagent.a2a.executor import StrandsA2AExecutor

SCRIPT_DIR = Path(__file__).resolve().parent

# Phase 4 monitor/shared (helper) + incident/shared (truth) 직접 재사용 (Option G).
# 컨테이너: deploy_runtime.py 가 두 디렉토리를 runtime/ 에 copy.
# 로컬 dev: agents.monitor.shared (helper) + agents.incident.shared (truth) 직접 import.
if (SCRIPT_DIR / "shared").is_dir():
    sys.path.insert(0, str(SCRIPT_DIR))                # /app/shared + /app/incident_shared
else:
    sys.path.insert(0, str(SCRIPT_DIR.parents[2]))     # PROJECT_ROOT for agents.* import

try:
    from shared.mcp_client import create_mcp_client                       # Phase 4 monitor helper
    from incident_shared.agent import create_agent                         # Phase 4 incident truth
except ModuleNotFoundError:
    from agents.monitor.shared.mcp_client import create_mcp_client         # noqa: E402
    from agents.incident.shared.agent import create_agent                  # noqa: E402

OAUTH_PROVIDER_NAME = os.environ["OAUTH_PROVIDER_NAME"]
COGNITO_GATEWAY_SCOPE = os.environ["COGNITO_GATEWAY_SCOPE"]
DEMO_USER = os.environ.get("DEMO_USER", "ubuntu")
AGENT_NAME = f"aiops_demo_{DEMO_USER}_incident_a2a"
AGENT_DESC = "Incident Agent — alarm 1건 → runbook 조회 → 진단 + 권장 조치 JSON 반환"

# Phase 4 와 동일 — storage Target 만 (runbook lookup).
# Backend 선택은 env STORAGE_BACKEND 로 (s3 default / github 선택). Lambda 응답 shape 동형.
TOOL_TARGET_PREFIX = f"{os.environ.get('STORAGE_BACKEND', 's3')}-storage___"
SYSTEM_PROMPT_FILENAME = "system_prompt.md"


@requires_access_token(
    provider_name=OAUTH_PROVIDER_NAME,
    scopes=[COGNITO_GATEWAY_SCOPE],
    auth_flow="M2M",
    into="access_token",
)
async def _fetch_gateway_token(*, access_token: str = "") -> str:
    """Gateway 호출용 token (Client M2M)."""
    return access_token


async def _build_real_incident_agent() -> Agent:
    """Real agent 빌드 — request 시점에 호출 (workload-token ContextVar 채워진 후)."""
    gateway_token = await _fetch_gateway_token()
    mcp_client = create_mcp_client(gateway_token=gateway_token)
    mcp_client.start()
    all_tools = mcp_client.list_tools_sync()
    tools = [t for t in all_tools if t.tool_name.startswith(TOOL_TARGET_PREFIX)]
    if not tools:
        received = [t.tool_name for t in all_tools]
        raise RuntimeError(
            f"Incident tool 0개 — prefix '{TOOL_TARGET_PREFIX}' 매칭 실패. 받음: {received}"
        )
    agent = create_agent(tools=tools, system_prompt_filename=SYSTEM_PROMPT_FILENAME)
    agent.name = AGENT_NAME
    agent.description = AGENT_DESC
    return agent


class LazyIncidentExecutor(StrandsA2AExecutor):
    """첫 request 시 real agent build — module init 시점 workload-token 없음 회피."""

    def __init__(self):
        placeholder = Agent(name=AGENT_NAME, description=AGENT_DESC, tools=[])
        super().__init__(agent=placeholder)
        self._built = False

    async def execute(self, context, event_queue):
        if not self._built:
            self.agent = await _build_real_incident_agent()
            self._built = True
        await super().execute(context, event_queue)


if __name__ == "__main__":
    serve_a2a(LazyIncidentExecutor(), port=9000)
