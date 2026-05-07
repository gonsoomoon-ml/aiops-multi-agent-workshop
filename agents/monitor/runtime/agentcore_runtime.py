#!/usr/bin/env python3
"""
agentcore_runtime.py — Phase 3 Monitor Agent Runtime 진입점

Phase 2 ``local/run.py`` 의 9-step 호출 시퀀스 (mcp_client → list_tools → filter →
create_agent → stream_async) 를 그대로 보존하면서, stdout print 를 SSE yield 로 evolve.
C1 (single source of truth) 시연 — create_agent / mcp_client / MODE_CONFIG 모두
Phase 2 와 같은 ``shared/`` 모듈에서 import.

사용법:
    Runtime 컨테이너 안에서 ``python -m agentcore_runtime`` 으로 실행 (Dockerfile CMD).
    AgentCore 가 invoke 시 자동으로 ``@app.entrypoint`` 함수 호출.

사전 조건 (Runtime 환경변수, deploy_runtime.py 가 launch 시 주입):
    - GATEWAY_URL: Phase 2 Gateway endpoint (mcp_client.py 에서 read)
    - OAUTH_PROVIDER_NAME: Cognito OAuth provider 이름 (SDK 자동 token inject 에 사용)
    - MONITOR_MODEL_ID: Bedrock model ID (shared/agent.py 에서 read)
    - DEMO_USER: live mode query 의 ``payment-{user}-*`` prefix 채움
    - OTEL_RESOURCE_ATTRIBUTES, AGENT_OBSERVABILITY_ENABLED: CW GenAI Observability 자동 통합

payload 스키마 (D4):
    {"mode": "past" | "live", "query": "..."}  — query 생략 시 mode 별 default 템플릿

yield 스키마 (D4, SSE):
    - ``agent_text_stream`` — LLM streaming chunk
    - ``token_usage`` — usage 누적 metrics (마지막)
    - ``workflow_complete`` — SSE 종료 sentinel

reference:
    - phase3.md §3-4 (호출 흐름) + §5 (OAuth provider 자동 inject 매커니즘)
    - developer-briefing-agent/managed-agentcore/agentcore_runtime.py (BedrockAgentCoreApp 패턴)
"""
import os
import sys
from pathlib import Path
from typing import Any, AsyncGenerator

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from bedrock_agentcore.identity.auth import requires_access_token

SCRIPT_DIR = Path(__file__).resolve().parent

# 로컬 dev 시 shared/ 가 ``agents/monitor/shared/`` (sibling) — sys.path 에 parent 추가.
# 컨테이너 안에서는 build context 평탄화로 ``/app/shared/`` 가 직접 cwd 의 sibling →
# ``-m agentcore_runtime`` 가 cwd 를 sys.path 에 자동 추가하므로 insert 불필요.
if (SCRIPT_DIR.parent / "shared").is_dir():
    sys.path.insert(0, str(SCRIPT_DIR.parent))

# Runtime 환경변수는 ``Runtime.launch(env_vars=...)`` 가 OS env 로 직접 주입 —
# .env 로딩 불필요 (python-dotenv 의존 제거). 로컬 dev 시는 호출 측에서 .env 로딩.

from shared.agent import create_agent          # noqa: E402 — sys.path 조정 후 import
from shared.mcp_client import create_mcp_client  # noqa: E402
from shared.modes import MODE_CONFIG             # noqa: E402

OAUTH_PROVIDER_NAME = os.environ["OAUTH_PROVIDER_NAME"]
COGNITO_GATEWAY_SCOPE = os.environ["COGNITO_GATEWAY_SCOPE"]  # 예: aiops-demo-ubuntu-resource-server/invoke


@requires_access_token(
    provider_name=OAUTH_PROVIDER_NAME,
    scopes=[COGNITO_GATEWAY_SCOPE],
    auth_flow="M2M",
    into="access_token",
)
async def _fetch_gateway_token(*, access_token: str = "") -> str:
    """OAuth2CredentialProvider 가 자동 inject 한 access_token 을 반환.

    데코레이터가 workload identity → Cognito M2M 교환 (``GetResourceOauth2Token``) 후
    ``access_token`` kwarg 로 주입. 함수는 그대로 반환만 한다.
    """
    return access_token

QUERY_PAST = "지난 7일 alarm history를 분석해 3가지 진단 유형으로 제안하고, real alarm은 따로 나열해줘."
QUERY_LIVE_TEMPLATE = (
    "현재 라이브 알람 (payment-{user}-* prefix) 의 상태와 classification 을 분석해, "
    "실제로 봐야 할 알람만 알려줘."
)

app = BedrockAgentCoreApp()


@app.entrypoint
async def monitor_agent(payload: dict, context: Any) -> AsyncGenerator[dict, None]:
    """Runtime invoke 진입점 — payload {mode, query} → SSE yield 3종."""
    mode = payload.get("mode", "live")
    target_prefix, prompt_filename = MODE_CONFIG[mode]
    demo_user = os.environ.get("DEMO_USER", "ubuntu")
    query = payload.get("query") or (
        QUERY_PAST if mode == "past"
        else QUERY_LIVE_TEMPLATE.format(user=demo_user)
    )

    gateway_token = await _fetch_gateway_token()
    mcp_client = create_mcp_client(gateway_token=gateway_token)
    with mcp_client:
        all_tools = mcp_client.list_tools_sync()
        tools = [t for t in all_tools if t.tool_name.startswith(target_prefix)]
        if not tools:
            received = [t.tool_name for t in all_tools]
            yield {
                "type": "agent_text_stream",
                "text": f"[error] mode={mode} 도구 0개. prefix '{target_prefix}' 매칭 실패. 받음: {received}",
            }
            yield {"type": "workflow_complete", "text": ""}
            return

        agent = create_agent(tools=tools, system_prompt_filename=prompt_filename)
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
