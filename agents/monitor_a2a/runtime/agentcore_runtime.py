#!/usr/bin/env python3
"""
agentcore_runtime.py — Phase 6a Monitor A2A Runtime 진입점 (AWS canonical pattern)

AWS docs 의 `agentcore create --protocol A2A` CLI 가 scaffolding 하는 정확한 패턴 차용:
**`serve_a2a(StrandsA2AExecutor(agent))`**. AgentCore SDK 의 `serve_a2a` 가:
  - `/ping` health endpoint
  - AgentCard auto-serve
  - **Bedrock header propagation** (`x-amzn-bedrock-agentcore-runtime-workload-accesstoken`
    → `BedrockAgentCoreContext` ContextVar) — `requires_access_token` decorator 가 작동하기
    위한 필수 조건
  - port 9000 default + Docker host detection
모두 자동 처리.

OAuth-dependent agent 의 핵심 — **lazy build**:
  - module init 시점엔 workload-token 없음 (incoming request 가 inject)
  - LazyMonitorExecutor 가 placeholder agent 로 init 후 첫 request 시 real agent 빌드
  - `requires_access_token` decorator 가 ContextVar 에서 workload-token 읽음 → Cognito
    M2M 교환 → Gateway 호출 token 획득

Phase 4 monitor/shared/ 직접 재사용 (Option G — 2026-05-09):
  - 컨테이너: deploy_runtime.py 가 agents/monitor/shared 를 runtime/shared 로 copy
  - 로컬 dev: agents.monitor.shared.* 직접 import

사전 조건 (Runtime 환경변수):
    - GATEWAY_URL: Phase 2 Gateway endpoint
    - OAUTH_PROVIDER_NAME: Monitor A2A OAuth provider 이름 (Gateway 호출용 Client C M2M)
    - COGNITO_GATEWAY_SCOPE: Cognito Resource Server scope
    - MONITOR_MODEL_ID: Bedrock model ID
    - DEMO_USER: live mode query 의 ``payment-{user}-*`` prefix 채움
    - AGENTCORE_RUNTIME_URL: AgentCore 자동 주입
    - OTEL_RESOURCE_ATTRIBUTES, AGENT_OBSERVABILITY_ENABLED

reference:
    - https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-a2a.html
      (Step 1: Create your A2A project — agentcore CLI scaffold)
    - bedrock_agentcore/runtime/a2a.py:97-168 (BedrockCallContextBuilder)
    - 02-use-cases/A2A-multi-agent-incident-response/monitoring_strands_agent (per-request
      build pattern reference — older A2AStarletteApplication 형식)
"""
import os
import sys
from pathlib import Path

from bedrock_agentcore.runtime import serve_a2a
from bedrock_agentcore.identity.auth import requires_access_token
from strands import Agent
from strands.multiagent.a2a.executor import StrandsA2AExecutor

SCRIPT_DIR = Path(__file__).resolve().parent

# Phase 4 monitor/shared/ 직접 재사용 (Option G).
# 컨테이너: deploy_runtime.py 가 agents/monitor/shared 를 runtime/shared 로 copy.
# 로컬 dev: agents.monitor.shared.* 직접 import.
if (SCRIPT_DIR / "shared").is_dir():
    sys.path.insert(0, str(SCRIPT_DIR))

try:
    from shared.agent import create_agent          # noqa: E402
    from shared.mcp_client import create_mcp_client  # noqa: E402
    from shared.modes import MODE_CONFIG             # noqa: E402
except ModuleNotFoundError:
    from agents.monitor.shared.agent import create_agent          # noqa: E402
    from agents.monitor.shared.mcp_client import create_mcp_client  # noqa: E402
    from agents.monitor.shared.modes import MODE_CONFIG             # noqa: E402

OAUTH_PROVIDER_NAME = os.environ["OAUTH_PROVIDER_NAME"]
COGNITO_GATEWAY_SCOPE = os.environ["COGNITO_GATEWAY_SCOPE"]
DEMO_USER = os.environ.get("DEMO_USER", "ubuntu")
AGENT_NAME = f"aiops_demo_{DEMO_USER}_monitor_a2a"
AGENT_DESC = (
    "Monitor Agent (live mode) — 현재 라이브 CloudWatch 알람 분류, "
    "real (유효) vs noise (개선) 식별"
)

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
    """Gateway 호출용 token (Client C M2M).

    `requires_access_token` 데코레이터가 `BedrockAgentCoreContext.get_workload_access_token()`
    에서 workload-token 읽어 Cognito M2M 교환 — 이 ContextVar 는 `serve_a2a` 의
    `BedrockCallContextBuilder` 가 per-request 채움.
    """
    return access_token


async def _build_real_monitor_agent() -> Agent:
    """Real agent 빌드 — request 시점에 호출 (workload-token ContextVar 채워진 후)."""
    gateway_token = await _fetch_gateway_token()
    mcp_client = create_mcp_client(gateway_token=gateway_token)
    mcp_client.start()
    all_tools = mcp_client.list_tools_sync()
    tools = [t for t in all_tools if t.tool_name.startswith(TARGET_PREFIX)]
    if not tools:
        received = [t.tool_name for t in all_tools]
        raise RuntimeError(
            f"Monitor live tool 0개 — prefix '{TARGET_PREFIX}' 매칭 실패. 받음: {received}"
        )
    agent = create_agent(tools=tools, system_prompt_filename=PROMPT_FILENAME)
    agent.name = AGENT_NAME
    agent.description = AGENT_DESC
    return agent


class LazyMonitorExecutor(StrandsA2AExecutor):
    """첫 request 시 real agent build — module init 시점 workload-token 없음 회피.

    AgentCard 는 init 시 placeholder agent (tools=[]) 에서 도출 — caller 는 AgentCard 의
    url 만 필요 (skill 자세 정보 무관, send_message 가 protocol 통신).
    """

    def __init__(self):
        placeholder = Agent(name=AGENT_NAME, description=AGENT_DESC, tools=[])
        super().__init__(agent=placeholder)
        self._built = False

    async def execute(self, context, event_queue):
        if not self._built:
            # request 시점 — `serve_a2a` 의 BedrockCallContextBuilder 가 workload-token
            # 을 ContextVar 에 채움 → `requires_access_token` decorator OK.
            self.agent = await _build_real_monitor_agent()
            self._built = True
        await super().execute(context, event_queue)


if __name__ == "__main__":
    # serve_a2a — port 9000, /ping health, AgentCard, header propagation 모두 자동
    serve_a2a(LazyMonitorExecutor(), port=9000)
