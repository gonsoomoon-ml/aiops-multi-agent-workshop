#!/usr/bin/env python3
"""
agentcore_runtime.py — Phase 6a Supervisor Agent Runtime 진입점 (HTTP protocol)

Supervisor 는 운영자 (Operator CLI) 의 진입을 받음 → HTTP protocol Runtime 유지
(`BedrockAgentCoreApp` + `@app.entrypoint`). sub-agent 호출은 A2A protocol — `@tool`
함수 2개가 a2a.client.A2AClient 를 사용 (Strands `Agent` 의 `sub_agents` 미지원 →
*sub-agent 를 도구로 노출* 하는 패턴, research 확인).

inbound (operator → Supervisor):
  - HTTP entrypoint, port 8080
  - **SigV4 IAM** — Operator CLI 가 boto3 invoke_agent_runtime 사용 (Phase 4 패턴).
    customJWTAuthorizer 미설정 → AgentCore default = SigV4. Operator identity 는
    AWS IAM credential 로 검증.

outbound (Supervisor → 2 sub-agents):
  - A2A protocol over HTTPS — `https://bedrock-agentcore.{region}.amazonaws.com/runtimes/
    {quote(arn)}/invocations/`
  - **Cognito Client M2M token** (Bearer) — **Option X**: Phase 2 의 기존 Client 재사용,
    Phase 6a 가 추가하는 Cognito 자원 0. AgentCore customJWTAuthorizer 가 aud (= Client
    id) 만 검증 → Gateway scope 토큰이 sub-agent A2A inbound 에도 통과.
  - AgentCard discovery: `<base>/.well-known/agent-card.json`

사전 조건 (Runtime 환경변수, deploy_runtime.py 가 launch 시 OS env 직접 주입):
    - SUPERVISOR_MODEL_ID
    - OAUTH_PROVIDER_NAME — Cognito Client M2M provider (Phase 4 incident 와 동일 키)
    - COGNITO_GATEWAY_SCOPE — Phase 2 의 Gateway scope (sub-agent A2A inbound 통과)
    - MONITOR_A2A_RUNTIME_ARN, INCIDENT_A2A_RUNTIME_ARN — 2 sub-agents
      (Change Agent 는 후속 phase 로 연기 — Phase 6a 단순화)
    - DEMO_USER, AWS_REGION
    - DEBUG — '1' / 'true' 시 FlowHook + dump_stream_event trace 출력 (off 시 no-op)
    - OTEL_RESOURCE_ATTRIBUTES, AGENT_OBSERVABILITY_ENABLED

Runtime 환경변수는 ``Runtime.launch(env_vars=...)`` 가 OS env 로 직접 주입 — .env
로딩 불필요 (python-dotenv 의존 제거). 로컬 dev 시는 호출 측에서 .env 로딩.

사용법:
    Runtime 컨테이너 안에서 ``python -m agentcore_runtime`` 으로 실행 (Dockerfile CMD).
    AgentCore 가 invoke 시 자동으로 ``@app.entrypoint`` 함수 호출. Operator 진입점은
    ``invoke_runtime.py`` — boto3 ``invoke_agent_runtime`` (SigV4) 호출.

payload 스키마:
    {"query": "<자연어 운영자 질의>"}

yield 스키마 (SSE):
    - ``agent_text_stream`` — LLM streaming text chunk (sub-agent tool 호출 사이의
      Supervisor 자체 토큰 + 최종 통합 응답 — system_prompt 가 JSON 형식 요청 시 JSON)
    - ``token_usage`` — Supervisor LLM 자체의 usage 누적 (sub-agent 의 토큰은 별도
      집계 — CloudWatch metrics 참조)
    - ``workflow_complete`` — SSE 종료 sentinel

reference:
    - phase6a.md §3 (Supervisor + sub_agents 패턴)
    - docs/research/a2a_intro.md §6 (Supervisor 시나리오 다이어그램)
    - amazon-bedrock-agentcore-samples/02-use-cases/A2A-realestate-agentcore-multiagents
      /realestate_coordinator/agent.py:325-361 (가장 가까운 reference — Strands +
      Cognito M2M + @tool wrapping a2a.client)
"""
import os
import sys
from pathlib import Path
from typing import Any, AsyncGenerator
from urllib.parse import quote
from uuid import uuid4

import httpx
from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
from a2a.types import Message, Part, Role, TextPart
from bedrock_agentcore.identity.auth import requires_access_token
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import tool

SCRIPT_DIR = Path(__file__).resolve().parent

# 로컬 dev 시 ``shared/`` 는 ``agents/supervisor/shared/`` (sibling). sys.path 에
# parent 추가해야 ``from shared.X import ...`` 이 resolve. container 에서는 build
# root = ``runtime/`` 가 통째로 ``/app/`` 으로 upload (flatten 아님 — ``shared/`` 는
# subdir 로 보존; deploy script 가 ``project/agents/supervisor/shared/`` →
# ``runtime/shared/`` sibling copy 수행). ``-m agentcore_runtime`` 가 cwd 를
# sys.path 에 자동 추가하므로 container 에선 insert 불필요.
if (SCRIPT_DIR.parent / "shared").is_dir():
    sys.path.insert(0, str(SCRIPT_DIR.parent))

try:
    from shared.agent import create_supervisor_agent  # 컨테이너
except ModuleNotFoundError:
    from agents.supervisor.shared.agent import create_supervisor_agent  # 로컬 dev

# DEBUG=1 시 stream event trace (TTFT + message complete + usage).
# ``_shared_debug/`` 는 repo root sibling — deploy_runtime.py 가 build context 로 copy.
# 컨테이너에선 /app/_shared_debug/, 로컬에선 PROJECT_ROOT/_shared_debug/ (sys.path 위 양쪽 동일 import).
from _shared_debug import dump_stream_event  # noqa: E402

REGION = os.environ.get("AWS_REGION", "us-west-2")
# Option X — 단일 OAuth provider (Client 재사용, Phase 4 incident 와 동일 env 키)
OAUTH_PROVIDER_NAME = os.environ["OAUTH_PROVIDER_NAME"]
COGNITO_GATEWAY_SCOPE = os.environ["COGNITO_GATEWAY_SCOPE"]
DEMO_USER = os.environ.get("DEMO_USER", "ubuntu")
AGENT_NAME = f"aiops_demo_{DEMO_USER}_supervisor"

MONITOR_A2A_ARN = os.environ["MONITOR_A2A_RUNTIME_ARN"]
INCIDENT_A2A_ARN = os.environ["INCIDENT_A2A_RUNTIME_ARN"]
# Change Agent 는 후속 phase 로 연기 — Phase 6a 는 monitor + incident 두 sub-agent 만

DEFAULT_TIMEOUT = 300


def _runtime_url(arn: str) -> str:
    """AgentCore A2A endpoint URL — ARN → quoted URL.

    AgentCore Runtime A2A endpoint: `https://bedrock-agentcore.{region}.amazonaws.com/
    runtimes/{quote(arn)}/invocations/`. AgentCard discovery 는 그 base + `.well-known/
    agent-card.json` (research 확인).
    """
    return f"https://bedrock-agentcore.{REGION}.amazonaws.com/runtimes/{quote(arn, safe='')}/invocations/"


@requires_access_token(
    provider_name=OAUTH_PROVIDER_NAME,
    scopes=[COGNITO_GATEWAY_SCOPE],            # Phase 2 의 Gateway scope 동일
    auth_flow="M2M",
    into="access_token",                       # Phase 3/4 와 통일 (kwarg 이름)
    # NOTE: force_authentication 미사용 — 단일 entrypoint = 단일 event-loop → ContextVar
    # 격리 발생 안 함 (host_adk_agent reference 의 LazyClientFactory 이슈 회피). 기본
    # cache 활용 — AgentCore Identity 가 Cognito access_token 을 1시간 cache, 매
    # `@requires_access_token` 진입은 cache hit (Cognito 재호출 0).
)
async def _fetch_a2a_token(*, access_token: str = "") -> str:
    """A2A 호출용 Bearer JWT — Client M2M (Phase 2 재사용).

    AgentCore customJWTAuthorizer 가 aud (= Client id) 만 검증하므로 Gateway scope
    토큰이 sub-agent A2A inbound 에도 통과. scope `aiops-demo-${user}-resource-server/
    invoke` 가 다중 audience 에 사용되는 패턴 (Option X 의 핵심).
    """
    return access_token


async def _call_subagent(arn: str, query: str) -> str:
    """A2A 호출 1회 — Bearer JWT + AgentCard discovery + send_message → text 응답.

    1. Cognito Client M2M token 획득 (`@requires_access_token`, Phase 2 재사용)
    2. httpx.AsyncClient 에 Bearer 헤더 + Session-Id 헤더 주입
    3. A2ACardResolver 로 sub-agent 의 AgentCard fetch (`/.well-known/agent-card.json`)
    4. ClientFactory 로 A2AClient 생성, send_message — Task lifecycle (working → completed)
    5. artifact[0].parts[0].root.text 추출 — sub-agent 의 최종 응답
    """
    bearer = await _fetch_a2a_token()
    base_url = _runtime_url(arn)
    headers = {
        "Authorization": f"Bearer {bearer}",
        "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": str(uuid4()),
    }
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT, headers=headers) as h:
        resolver = A2ACardResolver(httpx_client=h, base_url=base_url)
        agent_card = await resolver.get_agent_card()
        config = ClientConfig(httpx_client=h, streaming=False)
        client = ClientFactory(config).create(agent_card)
        msg = Message(
            kind="message",
            role=Role.user,
            parts=[Part(TextPart(kind="text", text=query))],
            message_id=uuid4().hex,
        )
        async for event in client.send_message(msg):
            response = event[0] if isinstance(event, tuple) else event
            if hasattr(response, "artifacts") and response.artifacts:
                artifact = response.artifacts[0]
                if artifact.parts:
                    return artifact.parts[0].root.text
            # fallback: history 의 agent 메시지 모으기 (02-a2a-agent-sigv4/client.py 패턴)
            if hasattr(response, "history"):
                texts = [
                    m.parts[0].root.text for m in response.history
                    if m.role == Role.agent and m.parts
                ]
                if texts:
                    return "".join(texts)
        # 모든 event 통과 후에도 artifacts/history 없음 — Supervisor LLM 이 silent
        # failure 로 오해하지 않도록 sentinel 반환. system_prompt 가 sub-agent
        # 호출 실패 케이스 처리 정책 가짐 ("일부 sub-agent 응답 실패").
        return f"[sub-agent {arn.split('/')[-1]}: empty response]"


@tool
async def call_monitor_a2a(query: str) -> str:
    """Monitor A2A sub-agent 호출 — 라이브 CloudWatch alarm 분류 (real vs noise)."""
    return await _call_subagent(MONITOR_A2A_ARN, query)


@tool
async def call_incident_a2a(query: str) -> str:
    """Incident A2A sub-agent 호출 — 단일 alarm 의 runbook 진단. query 는 `{"alarm_name": "..."}` JSON str."""
    return await _call_subagent(INCIDENT_A2A_ARN, query)


app = BedrockAgentCoreApp()


@app.entrypoint
async def supervisor(payload: dict, context: Any) -> AsyncGenerator[dict, None]:
    """Operator → Supervisor 진입점. payload {query} → SSE yield 3종.

    Supervisor LLM 이 system_prompt 의 routing 정책 따라 sub-agent tool 들 호출 (LLM
    이 어떤 tool 을 부를지 결정 — Phase 4 의 hardcoded sequential CLI 와 다른 점).
    """
    query = payload.get("query") or ""
    if not query:
        yield {"type": "agent_text_stream", "text": '[error] payload 에 "query" 누락'}
        yield {"type": "workflow_complete", "text": ""}
        return

    agent = create_supervisor_agent(
        tools=[call_monitor_a2a, call_incident_a2a],
        system_prompt_filename="system_prompt.md",
    )
    usage_totals = {
        "inputTokens": 0, "outputTokens": 0, "totalTokens": 0,
        "cacheReadInputTokens": 0, "cacheWriteInputTokens": 0,
    }
    async for event in agent.stream_async(query):
        # dump_stream_event 가 먼저 — TTFT + message complete + usage trace
        # (DEBUG off 시 no-op). Phase 3 monitor / Phase 4 incident 와 동일 패턴.
        dump_stream_event(event, agent=agent)
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
