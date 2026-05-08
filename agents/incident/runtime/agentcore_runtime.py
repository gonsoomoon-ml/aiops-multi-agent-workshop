#!/usr/bin/env python3
"""
agentcore_runtime.py — Phase 4 Incident Agent Runtime 진입점

Monitor (`agents/monitor/runtime/agentcore_runtime.py`) 와 동일 골격 — `@app.entrypoint`
+ OAuth2CredentialProvider 자동 inject + MCPClient → Gateway 호출. 차이점:
  - agent_name = ``aiops_demo_${DEMO_USER}_incident``
  - tool filter = ``github-storage___`` prefix (Incident 는 runbook lookup 만)
  - payload = ``{"alarm_name": "..."}`` (Monitor 의 mode/query 와 다름)
  - Single mode (past/live 분기 없음)

helper (auth_local, mcp_client, env_utils) 는 monitor/shared 직접 import (D1) — Incident
deploy_runtime.py 가 빌드 컨텍스트에 monitor/shared + incident/shared 모두 copy
(phase4.md §3-6 Option A).

사용법:
    Runtime 컨테이너 안에서 ``python -m agentcore_runtime`` 으로 실행 (Dockerfile CMD).

사전 조건 (Runtime 환경변수, deploy_runtime.py 가 launch 시 주입):
    - GATEWAY_URL: Phase 2 Gateway endpoint
    - OAUTH_PROVIDER_NAME: Incident OAuth provider 이름
    - COGNITO_GATEWAY_SCOPE: Cognito Resource Server scope
    - INCIDENT_MODEL_ID: Bedrock model ID
    - DEMO_USER: alarm name prefix 정렬용
    - OTEL_RESOURCE_ATTRIBUTES, AGENT_OBSERVABILITY_ENABLED: CW GenAI Observability

payload 스키마:
    {"alarm_name": "<full alarm name>"}

yield 스키마 (SSE):
    - ``agent_text_stream`` — LLM streaming chunk (final JSON)
    - ``token_usage`` — usage 누적 metrics
    - ``workflow_complete`` — SSE 종료 sentinel

reference:
    - phase3.md §3-4 (호출 흐름) + §5 (OAuth provider 자동 inject)
    - phase4.md §3 (Incident Agent 상세) + §3-6 (build context Option A)
"""
import os
import sys
from pathlib import Path
from typing import Any, AsyncGenerator

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from bedrock_agentcore.identity.auth import requires_access_token

SCRIPT_DIR = Path(__file__).resolve().parent

# 로컬 dev 시 sibling 디렉토리 (../../shared = monitor/shared, ../shared = incident/shared)
# 둘 다 sys.path 에 추가. 컨테이너에선 cwd (/app) 자동, 별도 insert 불필요.
# - 컨테이너: /app/shared (monitor helper) + /app/incident_shared (incident agent.py + prompts)
# - 로컬: agents/monitor/shared (helper) + agents/incident/shared (agent.py + prompts)
if (SCRIPT_DIR.parent / "shared").is_dir():
    # 로컬 dev — incident/runtime/agentcore_runtime.py 직접 실행 시
    sys.path.insert(0, str(SCRIPT_DIR.parents[2]))   # PROJECT_ROOT for `agents.monitor.shared.X`

# Runtime 환경변수는 Runtime.launch(env_vars=...) 가 OS env 로 직접 주입.

# import — 컨테이너 vs 로컬 구분
try:
    # 컨테이너 (build context flatten 후): /app/shared + /app/incident_shared
    from shared.mcp_client import create_mcp_client                   # monitor helper
    from incident_shared.agent import create_agent                    # incident truth
except ModuleNotFoundError:
    # 로컬 dev — sys.path 에 PROJECT_ROOT 가 추가됨
    from agents.monitor.shared.mcp_client import create_mcp_client    # noqa: E402
    from agents.incident.shared.agent import create_agent             # noqa: E402

OAUTH_PROVIDER_NAME = os.environ["OAUTH_PROVIDER_NAME"]
COGNITO_GATEWAY_SCOPE = os.environ["COGNITO_GATEWAY_SCOPE"]

# Incident 는 single mode — github-storage Target 만 (phase4.md §3-5)
TOOL_TARGET_PREFIX = "github-storage___"
SYSTEM_PROMPT_FILENAME = "system_prompt.md"


@requires_access_token(
    provider_name=OAUTH_PROVIDER_NAME,
    scopes=[COGNITO_GATEWAY_SCOPE],
    auth_flow="M2M",
    into="access_token",
)
async def _fetch_gateway_token(*, access_token: str = "") -> str:
    """OAuth2CredentialProvider 가 자동 inject 한 access_token 반환.

    데코레이터가 workload identity → Cognito M2M 교환 (``GetResourceOauth2Token``) 후
    ``access_token`` kwarg 로 주입.
    """
    return access_token


app = BedrockAgentCoreApp()


@app.entrypoint
async def incident_agent(payload: dict, context: Any) -> AsyncGenerator[dict, None]:
    """Runtime invoke 진입점 — payload {alarm_name} → SSE yield 3종."""
    alarm_name = payload.get("alarm_name")
    if not alarm_name:
        yield {
            "type": "agent_text_stream",
            "text": '[error] payload 에 "alarm_name" 누락',
        }
        yield {"type": "workflow_complete", "text": ""}
        return

    query = f'{{"alarm_name": "{alarm_name}"}}'      # LLM 입력 — system_prompt 의 schema 와 일치

    gateway_token = await _fetch_gateway_token()
    mcp_client = create_mcp_client(gateway_token=gateway_token)
    with mcp_client:
        all_tools = mcp_client.list_tools_sync()
        tools = [t for t in all_tools if t.tool_name.startswith(TOOL_TARGET_PREFIX)]
        if not tools:
            received = [t.tool_name for t in all_tools]
            yield {
                "type": "agent_text_stream",
                "text": f"[error] 도구 0개. prefix '{TOOL_TARGET_PREFIX}' 매칭 실패. 받음: {received}",
            }
            yield {"type": "workflow_complete", "text": ""}
            return

        agent = create_agent(tools=tools, system_prompt_filename=SYSTEM_PROMPT_FILENAME)
        usage_totals = {
            "inputTokens": 0, "outputTokens": 0, "totalTokens": 0,
            "cacheReadInputTokens": 0, "cacheWriteInputTokens": 0,
        }
        async for event in agent.stream_async(query):
            data = event.get("data", "")
            if data:
                yield {"type": "agent_text_stream", "text": data}
            metadata = event.get("event", {}).get("metadata", {})
            if "usage" in metadata:
                usage = metadata["usage"]
                for key in usage_totals:
                    usage_totals[key] += usage.get(key, 0)

    yield {"type": "token_usage", "usage": usage_totals}
    yield {"type": "workflow_complete", "text": ""}


if __name__ == "__main__":
    app.run()
