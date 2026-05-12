# Phase 5 — Supervisor + A2A 프로토콜 활성화

> Phase 4 의 sequential CLI (boto3 SIGV4 로 Monitor → Incident 순차) 가 *caller 역할* 을 명시적으로 처리한 데 비해, Phase 5 는 **Supervisor Runtime** 이 *LLM-driven orchestrator* 가 되어 **A2A 프로토콜** 로 2 sub-agent (`monitor_a2a` + `incident_a2a`) 를 호출. routing 정책은 hardcoded 가 아니라 system_prompt 와 sub-agent `@tool` 시그니처 → LLM 이 어떤 sub-agent 를 언제 호출할지 결정.

설계 원본: [`docs/design/phase6a.md`](../design/phase6a.md) (D1~D6 + Option X / Option G / Change Agent 연기). 새 번호 = Phase 5, 옛 번호 = Phase 6a (파일/디렉토리 명은 `agents/*_a2a/` 그대로 — 역사 보존). A2A 프로토콜 직관: [`docs/research/a2a_intro.md`](../research/a2a_intro.md).

---

## 무엇을 만드나

| 산출물 | 위치 | 비고 |
|---|---|---|
| **Supervisor Runtime** (HTTP) | `agents/supervisor/runtime/agentcore_runtime.py` | `BedrockAgentCoreApp` + `@app.entrypoint` — Operator 진입. SigV4 IAM inbound. payload `{query}` → SSE yield 3종 |
| **Supervisor agent factory** | `agents/supervisor/shared/agent.py` | Strands Agent — caching Layer 1+2 + `FlowHook(agent_name="Supervisor")` if DEBUG=1 |
| **Supervisor system prompt** | `agents/supervisor/shared/prompts/system_prompt.md` | routing 정책 — LLM 이 어느 `@tool` 호출 결정 + 최종 통합 JSON schema |
| **Monitor A2A Runtime** | `agents/monitor_a2a/runtime/agentcore_runtime.py` | `serve_a2a(LazyMonitorExecutor())` — A2A 프로토콜 서버. JWT inbound (Phase 2 Client). Phase 4 `monitor/shared/` 직접 재사용 (Option G) |
| **Incident A2A Runtime** | `agents/incident_a2a/runtime/agentcore_runtime.py` | 동일 `serve_a2a` 패턴. Phase 4 `monitor/shared/` (helper) + `incident/shared/` (truth) 모두 import (Option G) |
| **3 deploy 스크립트** | `agents/{supervisor,monitor_a2a,incident_a2a}/runtime/deploy_runtime.py` | 5 또는 6 단계. shared/ + `_shared_debug/` build context copy → toolkit configure → launch → IAM extras + OAuth provider → READY → repo root `.env` 저장 (prefixed) |
| **Operator CLI 통합** | `agents/supervisor/runtime/invoke_runtime.py` | boto3 `invoke_agent_runtime` (SigV4) — Operator + admin 통합 진입점. Phase 4 invoke_runtime 패턴 carry-over. `--session-id` 옵션으로 3-layer warm container 재사용 (§3-4) |
| **3 teardown** | `agents/{supervisor,monitor_a2a,incident_a2a}/runtime/teardown.sh` | 6 step reverse + Phase 0/2/3/4 자원 + 다른 Phase 5 자원 보존 verify |

**Phase 5 가 새로 만드는 AWS 자원 (infra stack 0)**:
- AgentCore Runtime × 3 + ECR repo × 3 + IAM execution role × 3 (toolkit 자동 생성)
- `OAuth2CredentialProvider` × 3 — 각 Runtime 별 (모두 같은 Phase 2 Client M2M credentials — **Option X**)
- IAM inline policy × 3 (`SupervisorRuntimeExtras` / `MonitorA2aRuntimeExtras` / `IncidentA2aRuntimeExtras`)
- CloudWatch Log Group × 3 + transitive otel

**재사용 자원 (Phase 0/2/4)**:
- Cognito UserPool + Client (Phase 2 — Option X)
- Gateway + 3 Target (history-mock / cloudwatch-wrapper / s3-storage)
- S3 storage Lambda (Phase 4 — incident runbook 의존)
- EC2 + 2 alarm (Phase 0 — monitor 분류 대상)
- Phase 4 `monitor/shared/` + `incident/shared/` (Option G — *코드만 재사용*, deploy_runtime.py 가 build context 로 copy)

---

## 왜 필요한가

| 동기 | Phase 4 한계 | Phase 5 해결 |
|---|---|---|
| LLM-driven orchestration | sequential CLI = hardcoded routing (Monitor → Incident 고정) | Supervisor LLM 이 system_prompt 의 정책 따라 어떤 sub-agent 를 언제 호출할지 결정 — query 에 따라 routing 달라짐 |
| Multi-agent transport | CLI 가 boto3 SIGV4 로 각 Runtime 직접 호출 — caller 가 응답 통합 책임 | A2A 프로토콜 (JSON-RPC over HTTP + AgentCard discovery + Bearer JWT) — Supervisor 가 caller-as-LLM-tool 패턴 (Strands `@tool` wrapping `a2a.client`) |
| 자원 확장 비용 | Cognito Client 분리 시 보안 자원 +N | **Option X**: Phase 2 Client 재사용 (sub-agent JWT inbound 통과) — Cognito 추가 자원 0 |
| 코드 중복 | Phase 4 shared/ 가 sub-agent A2A 변형에 그대로 필요 | **Option G**: Phase 4 `monitor/shared` + `incident/shared` 직접 import + build context copy — 새 phase 의 코드는 A2A wrap 만 |

---

## 어떻게 동작

### `serve_a2a + LazyExecutor` (AWS canonical pattern)

A2A sub-agent 의 핵심은 *AgentCore SDK 의 `serve_a2a()`* 사용 — Strands `A2AServer.to_fastapi_app()` 단독은 `BedrockCallContextBuilder` 미부착으로 인해 `@requires_access_token` decorator 가 동작 안 함 (workload-token 헤더 → ContextVar 전달 실패 → HTTP 424).

```python
from bedrock_agentcore.runtime import serve_a2a
from strands.multiagent.a2a.executor import StrandsA2AExecutor

class LazyMonitorExecutor(StrandsA2AExecutor):
    """첫 request 시 real agent build — module init 시 workload-token 없음 회피.

    AgentCard 는 init 시 placeholder agent (tools=[]) 에서 도출 — caller 는 url 만 필요."""

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
    serve_a2a(LazyMonitorExecutor(), port=9000)
```

자세한 발견 과정 + AWS docs reference: [`docs/research/a2a_intro.md`](../research/a2a_intro.md) §10.

### Supervisor 가 sub-agent 를 `@tool` 로 노출

Strands `Agent` 에 `sub_agents=` 파라미터 자체 없음 → sub-agent 호출은 *도구로 노출*. Supervisor 의 `agentcore_runtime.py`:

```python
@tool
async def call_monitor_a2a(query: str) -> str:
    """Monitor A2A sub-agent 호출 — 라이브 CloudWatch alarm 분류 (real vs noise)."""
    return await _call_subagent(MONITOR_A2A_ARN, query)

@tool
async def call_incident_a2a(query: str) -> str:
    """Incident A2A sub-agent 호출 — 단일 alarm 의 runbook 진단. query 는 `{"alarm_name": "..."}` JSON str."""
    return await _call_subagent(INCIDENT_A2A_ARN, query)

agent = create_supervisor_agent(
    tools=[call_monitor_a2a, call_incident_a2a],
    system_prompt_filename="system_prompt.md",
)
```

`_call_subagent` 내부:
1. `@requires_access_token` 로 Cognito Client M2M token 획득 (Phase 2 재사용)
2. `httpx.AsyncClient` 에 Bearer 헤더 + Session-Id 헤더 주입
3. `A2ACardResolver` 로 sub-agent AgentCard fetch (`<base>/.well-known/agent-card.json`)
4. `ClientFactory(config).create(agent_card)` → A2AClient
5. `send_message(msg)` — Task lifecycle (working → completed)
6. `artifact.parts[0].root.text` 추출

### Option X — Phase 2 Client M2M 토큰의 sub-agent 통과

AgentCore `customJWTAuthorizer.allowedClients` 는 **`aud` (= client_id) 만 검증, `scope` 미검증**. 따라서 Phase 2 의 Gateway scope 토큰 (`aiops-demo-${user}-resource-server/invoke`) 이 sub-agent A2A inbound 에도 통과. Phase 5 가 새 Cognito client 추가 0 → 약 -325 LoC 단순화.

### Option G — Phase 4 shared/ 직접 재사용

monitor_a2a/incident_a2a 자체에 `shared/` 없음. deploy_runtime.py 가 build context 로 copy:

```
agents/monitor_a2a/runtime/         ← Docker build context
├── agentcore_runtime.py
├── Dockerfile / requirements.txt
├── shared/             ← Phase 4 monitor/shared 복사 (Phase 4 무수정)
└── _shared_debug/      ← repo root _shared_debug 복사 (DEBUG=1 시 FlowHook)

agents/incident_a2a/runtime/        ← Option A 확장 — 3 디렉토리
├── shared/             ← Phase 4 monitor/shared (helper)
├── incident_shared/    ← Phase 4 incident/shared (truth)
└── _shared_debug/
```

preservation rule (workshop side-by-side 비교) 정합 — Phase 4 코드는 read-only.

### 호출 흐름 (end-to-end)

```
invoke_runtime.py (--query "현재 상황 진단해줘")
    │ boto3.invoke_agent_runtime(payload={query}, runtimeUserId=DEMO_USER)
    ▼ SIGV4 IAM 인증
Supervisor Runtime (HTTP, port 8080)
    │ @app.entrypoint supervisor(payload, context)
    │ create_supervisor_agent(tools=[call_monitor_a2a, call_incident_a2a])
    │
    ├─ agent.stream_async(query)
    │     LLM (Sonnet 4.6) routing 결정 ──┐
    │                                      │
    │     ┌─ @tool call_monitor_a2a ◀─────┤
    │     │   _fetch_a2a_token() ─── Cognito Client M2M (Phase 2)
    │     │   httpx.AsyncClient + Bearer
    │     │   A2ACardResolver.get_agent_card()
    │     │   ClientFactory.create(card).send_message(msg)
    │     │       │
    │     │       ▼ A2A JSON-RPC over HTTPS
    │     │   Monitor A2A Runtime (port 9000)
    │     │       │ JWT inbound (allowedClients=[Phase 2 Client])
    │     │       │ LazyMonitorExecutor.execute()
    │     │       │   _build_real_monitor_agent() (첫 request 시)
    │     │       │     _fetch_gateway_token() — Gateway scope 토큰
    │     │       │     create_mcp_client(token) → live tools
    │     │       │     create_agent(tools, "system_prompt_live.md")
    │     │       │   agent.stream_async(query)
    │     │       │     → tool call: cloudwatch-wrapper___describe_alarms
    │     │       │     → LLM 자연어 분류 (real vs noise)
    │     │       ▼ A2A artifact
    │     │   artifact.parts[0].root.text
    │     │   "alarm 2개, real 1: payment-bob-status-check (P1), noise 1: ..."
    │     │
    │     ├─ @tool call_incident_a2a ◀────┤
    │     │   동일 패턴, payload = {"alarm_name": "payment-bob-status-check"}
    │     │   Incident A2A Runtime
    │     │     → tool call: s3-storage___get_runbook
    │     │     → LLM JSON 진단 + 권장 조치
    │     │
    │     └─ LLM 통합 응답 stream ────────┘
    │           summary / monitor / incidents / next_steps JSON
    │
    ├─ yield agent_text_stream {text} × N    ← Supervisor LLM 자체 + sub-agent 응답 인용
    ├─ yield token_usage {usage}             ← Supervisor LLM 만 (sub-agent token 별도 — CloudWatch)
    └─ yield workflow_complete
```

자세한 protocol 흐름: [`docs/research/a2a_intro.md`](../research/a2a_intro.md) §6 (Supervisor 시나리오 다이어그램).

---

## 진행 단계

### 1. 사전 확인

- Phase 0 완료 (EC2 + 2 alarm alive — `payment-${DEMO_USER}-*`).
- Phase 2 완료 (Cognito stack + Gateway alive — `COGNITO_CLIENT_ID` / `GATEWAY_URL` 등 root `.env`).
- Phase 4 의 `infra/s3-lambda/deploy.sh` 완료 (storage Lambda + Gateway Target `s3-storage` alive — incident 의존).
- Phase 4 의 `agents/monitor/shared/` + `agents/incident/shared/` 가 repo 에 존재 (Option G — 코드 source).
- AWS 자격 증명 + Docker daemon + `uv sync`.

> **Phase 3/4 Runtime 미alive 도 OK**: Phase 5 는 Phase 3/4 의 *코드만* 재사용. Phase 3 Monitor Runtime / Phase 4 Incident Runtime 자체가 alive 일 필요 없음 (Phase 5 가 별 Runtime — `*_a2a`).

### 2. Deploy (3 단계 sequential)

```bash
# Step 1 — Monitor A2A (의존 없음)
uv run agents/monitor_a2a/runtime/deploy_runtime.py

# Step 2 — Incident A2A (의존 없음)
uv run agents/incident_a2a/runtime/deploy_runtime.py

# Step 3 — Supervisor (sub-agent ARN cross-load 후 마지막)
uv run agents/supervisor/runtime/deploy_runtime.py
```

각 deploy 5-10분 (cold start) / ~52초 (warm — ECR layer cache). 각 단계마다:
- shared/ + `_shared_debug/` build context copy (Option G + Phase 3/4 parity)
- toolkit `Runtime.configure()` — sub-agent 는 `protocol="A2A"` + JWT authorizer, supervisor 는 `protocol="HTTP"` + authorizer 미설정 (SigV4 default)
- `Runtime.launch()` — ECR build + push + Runtime 생성 + env_vars 주입 (`DEBUG` 호스트 값 forward 포함)
- IAM inline policy + `OAuth2CredentialProvider` (Phase 2 Client 재사용)
- READY 대기 + repo root `.env` 갱신 (`MONITOR_A2A_*` / `INCIDENT_A2A_*` / `SUPERVISOR_*` prefix)

Supervisor deploy 의 step [2/6] 가 **sub-agent ARN cross-load** 수행 — root `.env` 에서 `MONITOR_A2A_RUNTIME_ARN` + `INCIDENT_A2A_RUNTIME_ARN` 직접 read 후 Supervisor container 의 env_vars 로 주입.

### 3. 검증

#### 3-1. End-to-end smoke (Operator → Supervisor → 2 sub-agents)

```bash
uv run agents/supervisor/runtime/invoke_runtime.py --query "현재 상황 진단해줘"
```

성공 시 출력 (실측 — 48.0초, 7,045 tokens, us-east-1):

```json
{
  "summary": "현재 유효 알람 1건 (payment-bob-status-check, P1) 발생 중입니다. ...",
  "monitor": "라이브 알람 총 2개 중 real 1개 (payment-bob-status-check), noise 1개 ...",
  "incidents": [
    {
      "alarm": "payment-bob-status-check",
      "diagnosis": "payment 서비스 EC2 인스턴스의 status check 실패. Kernel panic ...",
      "severity": "P1",
      "recommended_actions": [
        "describe instance status via aws ec2 describe-instance-status",
        "reboot instance within first 5 minutes",
        ...
      ]
    }
  ],
  "next_steps": [
    "Run aws ec2 describe-instance-status for payment-bob instance immediately",
    ...
  ]
}

📊 Tokens — Total: 7,045 | Input: 6,266 | Output: 779 | Cache R/W: 0/0
✅ 완료 (48.0초)
```

token_usage 의 `Cache R/W` 는 **Supervisor LLM 자체** 만 추적 — sub-agent 의 token + cache 는 별도 (CloudWatch metrics 또는 sub-agent 의 자체 log).

#### 3-2. Prompt caching 확인 — 같은 query 재호출

5분 이내 같은 query 로 다시 invoke:

```bash
uv run agents/supervisor/runtime/invoke_runtime.py --query "현재 상황 진단해줘"
```

Cache R/W 가 `0/0` → `<x>/0` (warm) 로 변동 — Supervisor 의 system_prompt + tool schema cache hit. Layer 1 (`cache_tools="default"`) + Layer 2 (system prompt cachePoint) — Phase 3/4 와 동일 패턴.

> sub-agent 의 cache 는 LazyExecutor 의 `self._built` 게이트 덕에 두 번째 invocation 부터 hit (placeholder 가 real agent 로 한번만 build).

#### 3-3. DEBUG 모드 — host (operator timeline) + container (per-LLM-call) 양면

두 layer 가 독립적으로 toggle 가능. host = 운영자 wall-clock 4 시점, container = LLM 내부 per-call detail.

| Layer | 활성 | 출력 surface | 보이는 trace |
|---|---|---|---|
| **host** (invoke_runtime.py) | `DEBUG=1 uv run agents/supervisor/runtime/invoke_runtime.py ...` (shell env, **재배포 X**) | stdout (같은 터미널) | `HTTP response 도착` / `first SSE byte (TTFT)` / `first text token` / `token_usage event` 4 timing |
| **container** (3 Runtime) | `DEBUG=1 uv run agents/.../deploy_runtime.py` (deploy 시 baked in container) | CloudWatch logs (별 터미널 tail) | per-LLM-call TTFT / usage / message complete (tool_use·tool_result) / FlowHook BeforeModel·BeforeToolCall |

##### host DEBUG (재배포 X)

`agents/supervisor/runtime/invoke_runtime.py` 가 `_shared_debug.dprint` 4 시점 timing 출력:

```bash
DEBUG=1 uv run agents/supervisor/runtime/invoke_runtime.py --query "현재 상황 진단해줘"
```

DEBUG off 시 (`uv run ...` 단독) dprint 가 no-op — 기존 출력 동일.

##### container DEBUG (재배포 필요)

3 Runtime 모두 DEBUG=1 환경변수로 재배포 — 의존성 역순 (sub-agent 먼저, Supervisor 마지막):

```bash
DEBUG=1 uv run agents/monitor_a2a/runtime/deploy_runtime.py
DEBUG=1 uv run agents/incident_a2a/runtime/deploy_runtime.py
DEBUG=1 uv run agents/supervisor/runtime/deploy_runtime.py
```

각 deploy 직후 status:
```
DEBUG 모드:        ACTIVE (CloudWatch logs 에 FlowHook trace 출력)
```

read-only 검증:
```bash
set -a; source .env; set +a
for ID in "$SUPERVISOR_RUNTIME_ID" "$MONITOR_A2A_RUNTIME_ID" "$INCIDENT_A2A_RUNTIME_ID"; do
  aws bedrock-agentcore-control get-agent-runtime --agent-runtime-id "$ID" \
    --region "$AWS_REGION" --query 'environmentVariables.DEBUG' --output text
done
# 3 모두 "1" 출력이면 ON
```

invoke 후 각 Runtime CloudWatch tail (별 터미널 권장 — 또는 `--since 5m` 으로 사후 조회):

```bash
aws logs tail "/aws/bedrock-agentcore/runtimes/${SUPERVISOR_RUNTIME_ID}-DEFAULT"   --since 5m --region "$AWS_REGION" --format short | grep -E "TTFT|usage total|🔧 toolUse"
aws logs tail "/aws/bedrock-agentcore/runtimes/${MONITOR_A2A_RUNTIME_ID}-DEFAULT"  --since 5m --region "$AWS_REGION" --format short | grep -E "TTFT|usage total"
aws logs tail "/aws/bedrock-agentcore/runtimes/${INCIDENT_A2A_RUNTIME_ID}-DEFAULT" --since 5m --region "$AWS_REGION" --format short | grep -E "TTFT|usage total"
```

확인 가능 trace:
- `[DEBUG Bedrock → Supervisor] call #N TTFT XXXms` — per-LLM-call 첫 토큰까지
- `[DEBUG Bedrock → Supervisor] usage total=X in=X out=X cacheR=X cacheW=X` — call 별 / 누적
- `┏━━━ message complete (role=assistant) 🔧 toolUse: call_monitor_a2a({...})` — tool 선택 visualization
- `[DEBUG Supervisor → Gateway] tool call: ...` — FlowHook BeforeToolCall (Supervisor 에서 "Gateway" 라벨이 "sub-agent A2A" 의미로 재해석됨)

> A2A protocol 의 stream loop 는 `StrandsA2AExecutor` 내부 (우리가 소유 X) → sub-agent 의 `dump_stream_event` 호출 부재. FlowHook 의 BeforeModel + AfterModel + BeforeToolCall 만으로 가시화 (Phase 4 대비 message complete trace 한 단계 적음).

##### 양면 timeline worked example

운영자 입장에선 host (4 timing) 가 enough; deep debugging (어느 sub-agent 가 느린지, 어느 LLM call 이 cache miss 했는지) 시 container 도 enable. 실측한 34.6초 invoke 의 host stdout + Supervisor container per-LLM-call breakdown 표 + 핵심 통찰 (Bedrock LLM 본체 3.1s vs sub-agent A2A 24s) — [`phase5_detail.md §1`](phase5_detail.md#1-양면-timeline-worked-example-debug-observability).

자세한 trace 의미: [`debug_mode.md`](debug_mode.md).

#### 3-4. Session-Id 전파 — 3 layer warm container 재사용

Phase 3/4 단독 invoke 의 `--session-id` 패턴이 Phase 5 에 3 layer 로 확장. Operator 가 동일 session-id 로 재호출하면 Supervisor + monitor_a2a + incident_a2a 3 microVM 모두 warm 재사용.

##### 전파 경로

```
Operator CLI (--session-id S)
    │ boto3.invoke_agent_runtime(runtimeSessionId=S)
    ▼ wire header: X-Amzn-Bedrock-AgentCore-Runtime-Session-Id: S
Supervisor Runtime (microVM 키 S 재사용)
    │ AgentCore SDK 가 inbound header 를 ContextVar 에 set
    │ → BedrockAgentCoreContext.get_session_id() == S
    │
    ├─ @tool call_monitor_a2a → _call_subagent
    │     │ httpx header: X-Amzn-Bedrock-AgentCore-Runtime-Session-Id: S
    │     ▼
    │   Monitor A2A Runtime (microVM 키 S 재사용)
    │     └─ LazyExecutor._built=True (real agent + MCP client 캐시)
    │
    └─ @tool call_incident_a2a → _call_subagent
          │ httpx header: ... Session-Id: S
          ▼
        Incident A2A Runtime (microVM 키 S 재사용)
          └─ LazyExecutor._built=True
```

##### 시연 — 같은 session-id 로 2회 invoke

```bash
SESSION="workshop-$(uuidgen | tr -d -)"    # 41자 (AgentCore 제약 ≥ 33)

# 1st invoke — cold (3 microVM 모두 새로)
uv run agents/supervisor/runtime/invoke_runtime.py --query "현재 상황 진단해줘" --session-id "$SESSION"

# 2nd invoke — warm (3 microVM 모두 재사용)
uv run agents/supervisor/runtime/invoke_runtime.py --query "현재 상황 진단해줘" --session-id "$SESSION"
```

2026-05-12 실측: **44.6s (cold) → 28.4s (warm)**, **-36%** — microVM cold-start + LazyExecutor 첫 build 절감이 핵심. Bedrock LLM 호출 자체는 변동 없음.

자세한 — host CLI / container `_call_subagent` 핵심 코드, 측정 분해 (Supervisor + monitor_a2a + incident_a2a 각 ~5s 절감 출처), caveat 4종 (Bedrock prompt cache 와 독립 / idle 만료 / 길이 제약 / 동시성 위험): [`phase5_detail.md §2`](phase5_detail.md#2-session-id-전파--내부-구조--실측--caveat).

### 4. 정리

```bash
# reverse 순서 (의존 역순)
bash agents/supervisor/runtime/teardown.sh
bash agents/incident_a2a/runtime/teardown.sh
bash agents/monitor_a2a/runtime/teardown.sh
```

각 teardown 6 step (Runtime → DELETED 대기 → OAuth provider → ECR → IAM Role → CW Log) + repo root `.env` 의 prefixed entry cleanup (`SUPERVISOR_*` / `INCIDENT_A2A_*` / `MONITOR_A2A_*`) + 다른 phase 자원 보존 verify (Phase 0/2/4 + 다른 Phase 5 sub-agent).

> Phase 5 의 infra/ stack 0 → CFN stack teardown 무. Phase 0/2/4 의 stack 은 phase 별 정리 (Phase 4: `bash infra/s3-lambda/teardown.sh`, Phase 2: `bash infra/cognito-gateway/teardown.sh`).

---

## Reference

| 자료 | 용도 |
|---|---|
| [`agents/supervisor/runtime/agentcore_runtime.py`](../../agents/supervisor/runtime/agentcore_runtime.py) | HTTP entrypoint + `@tool` wrapping a2a.client |
| [`agents/supervisor/shared/agent.py`](../../agents/supervisor/shared/agent.py) | Strands Agent — caching + FlowHook(Supervisor) |
| [`agents/supervisor/shared/prompts/system_prompt.md`](../../agents/supervisor/shared/prompts/system_prompt.md) | routing 정책 + JSON 통합 schema |
| [`agents/supervisor/runtime/invoke_runtime.py`](../../agents/supervisor/runtime/invoke_runtime.py) | Operator + admin 통합 진입점 (SigV4) |
| [`agents/monitor_a2a/runtime/agentcore_runtime.py`](../../agents/monitor_a2a/runtime/agentcore_runtime.py) | `serve_a2a + LazyMonitorExecutor` — A2A 서버 |
| [`agents/incident_a2a/runtime/agentcore_runtime.py`](../../agents/incident_a2a/runtime/agentcore_runtime.py) | 동일 패턴 + Option G 의 두 shared/ import |
| [`agents/{*}/runtime/deploy_runtime.py`](../../agents/) | 5 또는 6 단계 배포 — Option G build context + DEBUG forward |
| [`agents/{*}/runtime/teardown.sh`](../../agents/) | 6 step reverse + negative check (다른 Phase 5 sub-agent 보존) |
| [`debug_mode.md`](debug_mode.md) | DEBUG=1 시 3 Runtime 모두 FlowHook trace |
| [`phase5_detail.md`](phase5_detail.md) | §3-3 worked example timeline + §3-4 session-id 내부 구조·실측·caveat |
| [`phase4.md`](phase4.md) | Phase 4 Incident — Option G 의 source. sequential CLI 비교점 |
| [`../design/phase6a.md`](../design/phase6a.md) | 의사결정 로그 (D1~D6 + Option X / G / Change 연기) |
| [`../research/a2a_intro.md`](../research/a2a_intro.md) | A2A 프로토콜 직관 + serve_a2a canonical pattern (§10) |

---

## 알려진 제약

- **`serve_a2a` 강제**: Strands `A2AServer.to_fastapi_app()` 단독으로 Bedrock AgentCore Runtime 에 deploy 하면 `BedrockCallContextBuilder` 미부착 → workload-token ContextVar 빈 채로 `@requires_access_token` 실패 (HTTP 424). 반드시 `bedrock_agentcore.runtime.serve_a2a()` 진입점 사용.
- **`LazyExecutor` 강제**: OAuth-dependent agent 는 module init 시 workload-token 없음 → `Agent(name=..., tools=[real_tools])` 가 import 시점에 token 호출 → ValueError. placeholder agent 로 init 후 첫 `execute()` 에서 real agent build.
- **Option X 의 scope 미검증**: AgentCore JWT authorizer 가 `aud` 만 검증, `scope` 미검증 — 다른 scope 의 토큰도 통과 가능 (보안 모델 의존도가 client_id 단위). 별 audience 분리 필요 시 추가 Cognito client 생성 (Option X 폐기 변형).
- **sub-agent token usage 미집계**: Supervisor 의 `token_usage` SSE event 는 Supervisor LLM 만 추적 → sub-agent 의 token 은 CloudWatch metrics 또는 sub-agent 의 자체 log 참조. Total cost 계산 시 3 Runtime 합산 필요.
- **3 OAuth provider 중복**: 각 Runtime 마다 `aiops_demo_${user}_{name}_gateway_provider` 별도 생성 — Cognito Client M2M credentials 는 모두 같지만 AgentCore 가 provider 단위로만 token 발급. Cognito 자원 자체는 1개, provider record 만 3개.
- **Change Agent 부재**: phase6a.md design 의 D6 (Change Agent + deployments-storage Lambda) 는 후속 phase 로 연기. Phase 5 = 2 sub-agent (monitor + incident) 만. 3+ sub-agent topology 시연은 별 phase.
- **Phase 4 dependency**: Option G 가 Phase 4 코드 directory 의 file 존재만 요구 (`agents/monitor/shared/` + `agents/incident/shared/`). Phase 4 Runtime 자체는 alive 일 필요 없음 — build context copy 만. Phase 4 의 storage Lambda (`infra/s3-lambda/`) 는 alive 필요 (incident sub-agent 의 MCP tool 의존).
- **AgentCard caching 부재**: Supervisor 의 `_call_subagent` 가 매 호출마다 `/.well-known/agent-card.json` fetch. sub-agent 호출이 보통 2-3회/query 이므로 부담 작음 — 그러나 high-throughput orchestrator 시 module-level cache 검토 가치 있음.
- **Bedrock prompt cache hit 미관측 (재현 필요)**: 2026-05-12 실측에서 같은 session-id + 같은 query 연속 2회 invoke 시 Cache R/W 0/0 유지 (§3-2 예측 미실현). microVM 재사용 (host 워밍) 과 Bedrock prompt cache (invocation 단위) 는 독립적 — cache hit 시현은 single invoke 안 multi-turn 패턴이 필요. cachePoint 배치 또는 invocation 모델 재검토 가치.
