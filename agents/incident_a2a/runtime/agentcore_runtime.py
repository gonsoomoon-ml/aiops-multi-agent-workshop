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

DEBUG mode (Phase 3/4 parity):
  - Phase 4 incident/shared/agent.py 가 ``FlowHook(agent_name="Incident")`` 를
    is_debug() 시점에 등록 — Option G 로 transitive 활성 (별도 코드 추가 0).
  - deploy_runtime.py 가 ``_shared_debug/`` 를 build context 로 copy + ``DEBUG`` env
    forward. ``DEBUG=1`` 재배포 시 CloudWatch logs 에 FlowHook + TTFT + usage trace.
  - dump_stream_event 직접 호출 부재 — A2A protocol 의 stream loop 는 StrandsA2AExecutor
    내부 (우리가 소유 X). FlowHook 의 BeforeModel + AfterModel + BeforeTool 만으로
    충분 (delta-based messages dump + LLM duration + tool 호출 가시화).

사전 조건 (Runtime 환경변수, deploy_runtime.py 가 launch 시 OS env 직접 주입):
    - GATEWAY_URL, OAUTH_PROVIDER_NAME, COGNITO_GATEWAY_SCOPE
    - INCIDENT_MODEL_ID, DEMO_USER, STORAGE_BACKEND (s3 / github)
    - DEBUG — '1' / 'true' 시 FlowHook trace 출력 (Phase 4 shared/agent.py 가 등록)
    - OTEL_RESOURCE_ATTRIBUTES, AGENT_OBSERVABILITY_ENABLED

Runtime 환경변수는 ``Runtime.launch(env_vars=...)`` 가 OS env 로 직접 주입 — .env
로딩 불필요 (python-dotenv 의존 제거). 로컬 dev 시는 호출 측에서 .env 로딩.

사용법:
    Runtime 컨테이너 안에서 ``python -m agentcore_runtime`` 으로 실행 (Dockerfile CMD).
    ``serve_a2a`` 가 port 9000 에 A2A protocol endpoint 노출 — caller (Supervisor) 가
    A2AClient 로 send_message. 로컬 단독 실행은 비대상 (A2A inbound = Supervisor 만).

payload 스키마 (A2A Message text part):
    alarm_name 문자열 또는 JSON ``{"alarm_name": "<full alarm name>"}`` — Supervisor
    가 후자 형식으로 호출. system_prompt 가 schema 명시. ``${STORAGE_BACKEND}-storage___``
    prefix tool 로 runbook 조회 후 진단.

response 스키마 (A2A Message artifact):
    runbook 기반 진단 + 권장 조치 (system_prompt 의 JSON schema 준수). caller 가
    ``artifact.parts[0].root.text`` 추출 → Supervisor LLM 이 sub-agent 응답으로 받음.
    token usage 별도 yield 없음 — A2A protocol 이 SSE event 모델 미사용
    (StrandsA2AExecutor 가 stream 내부 처리).

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
# - 컨테이너: deploy_runtime.py 가 두 디렉토리 + ``_shared_debug/`` 를 runtime/ 에 copy
#   (build context Option A 확장). build root = ``runtime/`` 가 통째로 ``/app/`` 으로
#   upload (flatten 아님 — ``shared/`` + ``incident_shared/`` + ``_shared_debug/`` 는
#   subdir 보존). ``-m agentcore_runtime`` 가 cwd (=/app/) 를 sys.path 에 자동 추가.
# - 로컬 dev: PROJECT_ROOT 를 sys.path 추가 → ``agents.monitor.shared`` (helper) +
#   ``agents.incident.shared`` (truth) 직접 import.
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
    """Gateway 호출용 token (Client M2M).

    `requires_access_token` 데코레이터가 `BedrockAgentCoreContext.get_workload_access_token()`
    에서 workload-token 읽어 Cognito M2M 교환 — 이 ContextVar 는 `serve_a2a` 의
    `BedrockCallContextBuilder` 가 per-request 채움.
    """
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
    """첫 request 시 real agent build — module init 시점 workload-token 없음 회피.

    AgentCard 는 init 시 placeholder agent (tools=[]) 에서 도출 — caller (Supervisor) 는
    AgentCard 의 url 만 필요 (skill 자세 정보 무관, send_message 가 protocol 통신).
    """

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
