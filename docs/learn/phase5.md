# Phase 5 — Supervisor + A2A 프로토콜 활성화

> Phase 5 는 **Supervisor Runtime** 이 *Supervisor orchestrator* 가 되어 **A2A 프로토콜** 로 2 sub-agent (`monitor_a2a` + `incident_a2a`) 를 호출. routing 정책은 hardcoded 가 아니라 system_prompt 와 sub-agent `@tool` 시그니처 → LLM 이 어떤 sub-agent 를 언제 호출할지 결정.

A2A 프로토콜 기본을 참고하세요: [`docs/research/a2a_intro.md`](../research/a2a_intro.md).

---

## 1. 왜 필요한가   *(~5 min read)*

| 동기 | Phase 4 한계 (또는 단순 대안) | Phase 5 해결 |
|---|---|---|
| Supervisor orchestration | 2 독립 Runtime — orchestration 계층 없음. operator 가 수동 dispatch (Monitor 출력의 real_alarm 추출 후 Incident 별도 invoke) | Supervisor Runtime 이 sub-agent routing 결정 — LLM 이 system_prompt + `@tool` 시그니처 보고 어떤 sub-agent 를 언제 호출할지 동적 분기 |
| **Team-owned multi-agent** (A2A 채택 이유) | **in-process supervisor** (sub-agent 를 `@tool` 로 노출) 였다면 latency·구현 속도 유리. 하지만 enterprise = 각 agent 가 별도 팀 소유 (Monitor 팀 / Incident 팀) → in-process 불가 | A2A 프로토콜 (JSON-RPC over HTTP + AgentCard + JWT) — cross-team owned Runtime 을 caller-as-LLM-tool 패턴 (Strands `@tool` wrapping `a2a.client`) 으로 호출 |
| 자원 확장 비용 | Cognito Client 분리 시 보안 자원 +N | Phase 2 Client 재사용 (sub-agent JWT inbound 통과) — Cognito 추가 자원 0 |
| 코드 중복 | Phase 4 shared/ 가 sub-agent A2A 변형에 그대로 필요 | Phase 4 `monitor/shared` + `incident/shared` 직접 import + build context copy — 새 phase 의 코드는 A2A wrap 만 |

---

## 2. 진행 (Hands-on)   *(quick try ~10 min / full ~45 min / teardown ~5 min)*

### 2-1. 빠른 체험 (Quick try)

> **사전**: Phase 0~4 deploy 완료 + AWS 자격증명. (root `.env` 는 phase 별 deploy 가 누적 채움 — [`env_config.md`](env_config.md))

Phase 5 deploy — 3 Runtime, 의존 순서 (한 줄씩 실행):

```bash
uv run agents/monitor_a2a/runtime/deploy_runtime.py
```

```bash
uv run agents/incident_a2a/runtime/deploy_runtime.py
```

```bash
uv run agents/supervisor/runtime/deploy_runtime.py
```

Supervisor 호출 — HTTP via SigV4, 내부에서 A2A 로 2 sub-agent 분기:

```bash
uv run agents/supervisor/runtime/invoke_runtime.py --query "현재 상황 진단해줘"
```

**기대 결과** (cold, ~50초):
- stdout: `{ summary, monitor, incidents, next_steps }` JSON
- Supervisor LLM 이 system_prompt 만 보고 `call_monitor_a2a` + `call_incident_a2a` 둘 다 호출 결정
- 통합 진단 → 운영자에게 "어떤 alarm 이 real, 어떤 게 noise, 권장 조치" 답변

→ 시간 있으면 §2-2~2-5 로 full deploy + 검증 + 정리. §3 무엇 / §4 어떻게 로 internals deep dive.

### 2-2. 사전 확인 (Full deploy 시작 전)

- Phase 0 완료 (EC2 + 2 alarm alive — `payment-${DEMO_USER}-*`).
- Phase 2 완료 (Cognito stack + Gateway alive — `COGNITO_CLIENT_ID` / `GATEWAY_URL` 등 root `.env`).
- Phase 4 의 `infra/s3-lambda/deploy.sh` 완료 (storage Lambda + Gateway Target `s3-storage` alive — incident 의존).
- Phase 4 의 `agents/monitor/shared/` + `agents/incident/shared/` 가 repo 에 존재 (코드 source).
- AWS 자격 증명 + Docker daemon + `uv sync`.

> **Phase 3/4 Runtime 미alive 도 OK**: Phase 5 는 Phase 3/4 의 *코드만* 재사용. Phase 3 Monitor Runtime / Phase 4 Incident Runtime 자체가 alive 일 필요 없음 (Phase 5 가 별 Runtime — `*_a2a`).

### 2-3. Deploy (3 단계 sequential, 상세)

Step 1 — Monitor A2A (의존 없음):

```bash
uv run agents/monitor_a2a/runtime/deploy_runtime.py
```

Step 2 — Incident A2A (의존 없음):

```bash
uv run agents/incident_a2a/runtime/deploy_runtime.py
```

Step 3 — Supervisor (sub-agent ARN cross-load 후 마지막):

```bash
uv run agents/supervisor/runtime/deploy_runtime.py
```

각 deploy 5-10분 (cold start) / ~52초 (warm — ECR layer cache). 각 단계마다:
- shared/ + `_shared_debug/` build context copy (Phase 3/4 parity)
- toolkit `Runtime.configure()` — sub-agent 는 `protocol="A2A"` + JWT authorizer, supervisor 는 `protocol="HTTP"` + authorizer 미설정 (SigV4 default)
- `Runtime.launch()` — ECR build + push + Runtime 생성 + env_vars 주입 (`DEBUG` 호스트 값 forward 포함)
- IAM inline policy + `OAuth2CredentialProvider` (Phase 2 Client 재사용)
- READY 대기 + repo root `.env` 갱신 (`MONITOR_A2A_*` / `INCIDENT_A2A_*` / `SUPERVISOR_*` prefix)

Supervisor deploy 의 step [2/6] 가 **sub-agent ARN cross-load** 수행 — root `.env` 에서 `MONITOR_A2A_RUNTIME_ARN` + `INCIDENT_A2A_RUNTIME_ARN` 직접 read 후 Supervisor container 의 env_vars 로 주입.

### 2-4. 검증 (P5-A1~A5)

#### End-to-end smoke (Operator → Supervisor → 2 sub-agents)

```bash
uv run agents/supervisor/runtime/invoke_runtime.py --query "현재 상황 진단해줘"
```

성공 시 출력 (실측 — 41.9초, 31,572 tokens [3 Runtime 합산], us-east-1):

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

📊 Monitor        — Total: 8,471  | Input: 934   | Output: 523   | Cache R/W: 3,507/3,507
📊 Incident       — Total: 6,948  | Input: 1,569 | Output: 379   | Cache R/W: 2,500/2,500
📊 Supervisor     — Total: 16,153 | Input: 2,509 | Output: 1,068 | Cache R/W: 8,384/4,192
📊 Combined       — Total: 31,572 | Input: 5,012 | Output: 1,970 | Cache R/W: 14,391/10,199
✅ 완료 (41.9초)
```

token_usage SSE event 가 3 Runtime 별 (Monitor / Incident / Supervisor) + Combined 합산 4 line 으로 분해 표시 — 워크샵 청중이 multi-agent token cost 의 분포 + cache hit ratio 를 한눈에 파악 가능.

#### Prompt caching 확인 — 같은 query 재호출

5분 이내 같은 query 로 다시 invoke:

```bash
uv run agents/supervisor/runtime/invoke_runtime.py --query "현재 상황 진단해줘"
```

Cache R/W 가 `0/0` → `<x>/0` (warm) 로 변동 — Supervisor 의 system_prompt + tool schema cache hit. Layer 1 (`cache_tools="default"`) + Layer 2 (system prompt cachePoint) — Phase 3/4 와 동일 패턴.

> sub-agent 의 cache 는 LazyExecutor 의 `self._built` 게이트 덕에 두 번째 invocation 부터 hit (placeholder 가 real agent 로 한번만 build).

> **latency 효과의 함정** — Bedrock cache 가 cost 는 ~90% 절감하지만 *latency 효과는 size + wrapper 의존*. agentic workload (Strands wrapper, 본 Phase 5 처럼) 에선 -5% 수준. 직접 측정 + 3-layer 모델: [`phase5_prompt_cache_effect.md`](phase5_prompt_cache_effect.md).

#### DEBUG 모드 — host (operator timeline) + container (per-LLM-call) 양면

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
```

```bash
DEBUG=1 uv run agents/incident_a2a/runtime/deploy_runtime.py
```

```bash
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

CloudWatch logs 에 trace 를 채우기 위해 Supervisor 1회 invoke (`DEBUG=1` prefix 는 host stdout 의 4-timing 도 같이 출력 — 양면 timeline 한 번에 시연):

```bash
DEBUG=1 uv run agents/supervisor/runtime/invoke_runtime.py --query "현재 상황 진단해줘"
```

invoke 후 각 Runtime CloudWatch tail (별 터미널 권장 — 또는 `--since 5m` 으로 사후 조회):

Supervisor:

```bash
aws logs tail "/aws/bedrock-agentcore/runtimes/${SUPERVISOR_RUNTIME_ID}-DEFAULT"   --since 5m --region "$AWS_REGION" --format short | grep -E "\[DEBUG|┏━|🔧"
```

Monitor A2A:

```bash
aws logs tail "/aws/bedrock-agentcore/runtimes/${MONITOR_A2A_RUNTIME_ID}-DEFAULT"  --since 5m --region "$AWS_REGION" --format short | grep -E "\[DEBUG|┏━|🔧"
```

Incident A2A:

```bash
aws logs tail "/aws/bedrock-agentcore/runtimes/${INCIDENT_A2A_RUNTIME_ID}-DEFAULT" --since 5m --region "$AWS_REGION" --format short | grep -E "\[DEBUG|┏━|🔧"
```

> grep 의 3 anchor — `[DEBUG` (timing/MCP/tool call 라인), `┏━` (message complete + LLM call 박스 시작), `🔧` (Supervisor 의 toolUse 선택 시각화). `BedrockAgentCoreApp` (Supervisor) 와 `serve_a2a` (sub-agent) 의 FlowHook 가 서로 다른 라인 포맷을 가지지만 이 3 anchor 로 양쪽 모두 catch.

확인 가능 trace — **Supervisor** (BedrockAgentCoreApp):
- `[DEBUG Bedrock → Supervisor] call #N TTFT XXXms` — per-LLM-call 첫 토큰까지
- `[DEBUG Bedrock → Supervisor] usage total=X in=X out=X cacheR=X cacheW=X` — call 별 / 누적
- 3-line 박스 (tool 선택 visualization):
  ```
  ┏━━━ message complete (role=assistant) ━━━━━━━━━━━━━━━━━
      🔧 toolUse: call_monitor_a2a({'query': '...'})
  ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ```
- `[DEBUG Supervisor → Gateway] tool call: ...` — FlowHook BeforeToolCall (Supervisor 에서 "Gateway" 라벨이 "sub-agent A2A" 의미로 재해석됨)

확인 가능 trace — **sub-agent** (`serve_a2a` + LazyExecutor, line 229 의 stream-loop 차이로 포맷 다름):
- `[DEBUG Bedrock → Monitor] call #N done — total XXXms` — per-LLM-call 전체 소요 (TTFT 측정 불가 — A2A stream 내부 소유 X)
- `[DEBUG Monitor → Gateway] MCP client init (gateway_url=..., bearer=…)` — LazyExecutor 첫 build 시점의 MCP init
- `[DEBUG Monitor → Gateway] tool call: cloudwatch-wrapper___list_live_alarms({})` — FlowHook BeforeToolCall
- `┏━━━ Monitor → Bedrock — LLM call #N (msgs=X, +Y new since #N-1) ━━━` — message complete (Phase 4 대비 한 단계 적음)

> A2A protocol 의 stream loop 는 `StrandsA2AExecutor` 내부 (우리가 소유 X) → sub-agent 의 `dump_stream_event` 호출 부재. FlowHook 의 BeforeModel + AfterModel + BeforeToolCall 만으로 가시화 (Phase 4 대비 message complete trace 한 단계 적음).

##### 양면 timeline worked example

운영자 입장에선 host (4 timing) 가 enough; deep debugging (어느 sub-agent 가 느린지, 어느 LLM call 이 cache miss 했는지) 시 container 도 enable. 실측한 34.6초 invoke 의 host stdout + Supervisor container per-LLM-call breakdown 표 + 핵심 통찰 (Bedrock LLM 본체 3.1s vs sub-agent A2A 24s) — [`phase5_detail.md §1`](phase5_detail.md#1-양면-timeline-worked-example-debug-observability).

자세한 trace 의미: [`debug_mode.md`](debug_mode.md).

#### Session-Id 전파 — 3 layer warm container 재사용

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

Step 1 — session-id 생성 (41자, AgentCore 제약 ≥ 33):

```bash
SESSION="workshop-$(uuidgen | tr -d -)"
```

Step 2 — 1st invoke (cold, 3 microVM 모두 새로):

```bash
uv run agents/supervisor/runtime/invoke_runtime.py --query "현재 상황 진단해줘" --session-id "$SESSION"
```

Step 3 — 2nd invoke (warm, 3 microVM 모두 재사용):

```bash
uv run agents/supervisor/runtime/invoke_runtime.py --query "현재 상황 진단해줘" --session-id "$SESSION"
```

2026-05-12 실측: **44.6s (cold) → 28.4s (warm)**, **-36%** — microVM cold-start + LazyExecutor 첫 build 절감이 핵심. Bedrock LLM 호출 자체는 변동 없음.

자세한 — host CLI / container `_call_subagent` 핵심 코드, 측정 분해 (Supervisor + monitor_a2a + incident_a2a 각 ~5s 절감 출처), caveat 4종 (Bedrock prompt cache 와 독립 / idle 만료 / 길이 제약 / 동시성 위험): [`phase5_detail.md §2`](phase5_detail.md#2-session-id-전파--내부-구조--실측--caveat).

### 2-5. 정리 / Teardown

의존 역순으로 한 줄씩 실행 (Supervisor 가 caller 이므로 가장 먼저 제거):

```bash
bash agents/supervisor/runtime/teardown.sh
```

```bash
bash agents/incident_a2a/runtime/teardown.sh
```

```bash
bash agents/monitor_a2a/runtime/teardown.sh
```

각 teardown 6 step (Runtime → DELETED 대기 → OAuth provider → ECR → IAM Role → CW Log) + repo root `.env` 의 prefixed entry cleanup (`SUPERVISOR_*` / `INCIDENT_A2A_*` / `MONITOR_A2A_*`) + 다른 phase 자원 보존 verify (Phase 0/2/4 + 다른 Phase 5 sub-agent).

> Phase 5 의 infra/ stack 0 → CFN stack teardown 무. Phase 0/2/4 의 stack 은 phase 별 정리 (Phase 4: `bash infra/s3-lambda/teardown.sh`, Phase 2: `bash infra/cognito-gateway/teardown.sh`).

---

## 3. 무엇을 만드나   *(~5 min read)*

> 순서 — **deploy/build dependency** (§2-3 Hands-on 의 명령 순서와 1:1). sub-agent (의존 없음) 먼저 → Supervisor (sub-agent ARN cross-load) → tooling. Caller-callee runtime 흐름 (Operator → Supervisor → sub-agents) 은 §4 §호출 흐름 참조.

| 산출물 | 위치 | 비고 |
|---|---|---|
| **Monitor A2A Runtime** | `agents/monitor_a2a/runtime/agentcore_runtime.py` | `serve_a2a(LazyMonitorExecutor())` — A2A 프로토콜 서버. JWT inbound (Phase 2 Client). Phase 4 `monitor/shared/` (agent factory + `system_prompt_live.md`) 직접 재사용 |
| **Incident A2A Runtime** | `agents/incident_a2a/runtime/agentcore_runtime.py` | 동일 `serve_a2a` 패턴. Phase 4 `monitor/shared/` (helper) + `incident/shared/` (agent factory + `system_prompt.md`, truth) 모두 import |
| **Supervisor Runtime** (HTTP) | `agents/supervisor/runtime/agentcore_runtime.py` | `BedrockAgentCoreApp` + `@app.entrypoint` — Operator 진입. SigV4 IAM inbound. payload `{query}` → SSE yield 3종. 두 sub-agent 를 `@tool` 로 wrapping (caller-as-LLM-tool) |
| **Supervisor agent factory** | `agents/supervisor/shared/agent.py` | Strands Agent — caching Layer 1+2 + `FlowHook(agent_name="Supervisor")` if DEBUG=1 |
| **Supervisor system prompt** | `agents/supervisor/shared/prompts/system_prompt.md` | routing 정책 — LLM 이 어느 `@tool` 호출 결정 + 최종 통합 JSON schema |
| **3 deploy 스크립트** | `agents/{monitor_a2a,incident_a2a,supervisor}/runtime/deploy_runtime.py` | sub-agent **5 단계** / Supervisor **6 단계** (step [2/6] sub-agent ARN cross-load 추가). shared/ + `_shared_debug/` build context copy → toolkit configure → launch → IAM extras + OAuth provider → READY → repo root `.env` 저장 (prefixed) |
| **Operator CLI 통합** | `agents/supervisor/runtime/invoke_runtime.py` | boto3 `invoke_agent_runtime` (SigV4) — Operator + admin 통합 진입점. Phase 4 invoke_runtime 패턴 carry-over. `--session-id` 옵션으로 3-layer warm container 재사용 (§2-4 Session-Id 전파) |
| **3 teardown** | `agents/{supervisor,incident_a2a,monitor_a2a}/runtime/teardown.sh` | 의존 역순 실행 (Supervisor 가 caller → 가장 먼저 제거). 각 6 step + repo root `.env` prefixed entry cleanup + Phase 0/2/3/4 자원 + 다른 Phase 5 자원 보존 verify |

**Phase 5 가 새로 만드는 AWS 자원 (infra stack 0)**:
- AgentCore Runtime × 3 + ECR repo × 3 + IAM execution role × 3 (toolkit 자동 생성)
- `OAuth2CredentialProvider` × 3 — 각 Runtime 별 (모두 같은 Phase 2 Client M2M credentials)
- IAM inline policy × 3 (`MonitorA2aRuntimeExtras` / `IncidentA2aRuntimeExtras` / `SupervisorRuntimeExtras`)
- CloudWatch Log Group × 3 (Runtime stdout 용. OTEL span 은 Phase 2 의 공유 `aiops-demo-observability` group 으로 송신 — 새 log group 아님)

**재사용 자원 (Phase 0/2/4)**:
- Cognito UserPool + Client (Phase 2)
- Gateway + 3 Target (history-mock / cloudwatch-wrapper / s3-storage)
- S3 storage Lambda (Phase 4 — incident runbook 의존)
- EC2 + 2 alarm (Phase 0 — monitor 분류 대상)
- Phase 4 `monitor/shared/` + `incident/shared/` (agent factory + prompts 포함 — *코드만 재사용*, deploy_runtime.py 가 build context 로 copy)
- `_shared_debug/` (Phase 2 — FlowHook + dprint, 3 Runtime 의 DEBUG trace 공통 helper)

---

## 4. 어떻게 동작   *(~15 min read)*

> 순서 — **호출 흐름 (end-to-end overview)** 먼저, 그 다음 sub-section 별 implementation detail. Top-down 으로 big picture 잡고 component drill-down.

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
    │     │       │     → tool call: cloudwatch-wrapper___list_live_alarms
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
    ├─ yield token_usage {usage}             ← Combined 4-line (Monitor + Incident + Supervisor + 합산). sub-agent usage 는 A2A Artifact.metadata 로 노출
    └─ yield workflow_complete
```

자세한 protocol 흐름: [`docs/research/a2a_intro.md`](../research/a2a_intro.md) §6 (Supervisor 시나리오 다이어그램).

### `serve_a2a + LazyExecutor` (AWS canonical pattern) — sub-agent 측

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
        self._build_lock = asyncio.Lock()   # concurrent 첫 request race 방지 (double-checked locking)

    async def execute(self, context, event_queue):
        if not self._built:
            async with self._build_lock:
                if not self._built:        # double-check after acquiring lock
                    # request 시점 — `serve_a2a` 의 BedrockCallContextBuilder 가 workload-token
                    # 을 ContextVar 에 채움 → `requires_access_token` decorator OK.
                    self.agent = await _build_real_monitor_agent()
                    self._built = True
        await super().execute(context, event_queue)

if __name__ == "__main__":
    serve_a2a(LazyMonitorExecutor(), port=9000)
```

`_build_lock` 가 첫 request 동시 도착 race 보호 — 두 번째 이후 path 는 lock 없이 (`self._built` flag 체크만). 자세한 발견 과정 + AWS docs reference: [`docs/research/a2a_intro.md`](../research/a2a_intro.md) §10.

### Supervisor 가 sub-agent 를 `@tool` 로 노출 — caller 측

Strands `Agent` 에 `sub_agents=` 파라미터 자체 없음 → sub-agent 호출은 *도구로 노출*. Supervisor 의 `agentcore_runtime.py`:

```python
@tool
async def call_monitor_a2a(query: str) -> str:
    """Monitor A2A sub-agent 호출 — 라이브 CloudWatch alarm 분류 (real vs noise)."""
    text, usage = await _call_subagent(MONITOR_A2A_ARN, query)
    _record_subagent_usage("monitor", usage)   # Phase 5b — usage 누적 → 4-line 출력
    return text

@tool
async def call_incident_a2a(query: str) -> str:
    """Incident A2A sub-agent 호출 — 단일 alarm 의 runbook 진단. query 는 `{"alarm_name": "..."}` JSON str."""
    text, usage = await _call_subagent(INCIDENT_A2A_ARN, query)
    _record_subagent_usage("incident", usage)
    return text

agent = create_supervisor_agent(
    tools=[call_monitor_a2a, call_incident_a2a],
    system_prompt_filename="system_prompt.md",
)
```

`_call_subagent` 가 `tuple[str, dict | None]` 반환 — `@tool` 함수는 LLM 에게는 `str` (text) 만 노출하고, usage 는 invocation-scoped `_subagent_usage` ContextVar 에 stash → 호출 흐름 §의 `token_usage` 4-line 출력 구현.

`_call_subagent` 내부 (6 단계):
1. `@requires_access_token` 로 Cognito Client M2M token 획득 (Phase 2 재사용)
2. `httpx.AsyncClient` 에 Bearer 헤더 + Session-Id 헤더 주입
3. `A2ACardResolver` 로 sub-agent AgentCard fetch (`<base>/.well-known/agent-card.json`)
4. `ClientFactory(config).create(agent_card)` → A2AClient + `send_message(msg)` (Task lifecycle: working → completed)
5. `artifact[0].parts[0].root.text` 추출 — sub-agent 의 최종 응답
6. **`artifact.metadata["usage"]`** 추출 (Phase 5b — sub-agent 가 `LazyExecutor._handle_agent_result` override 로 부착) — None 가능

### Phase 2 Client M2M 토큰의 sub-agent 통과 — auth detail

AgentCore `customJWTAuthorizer.allowedClients` 는 **`aud` (= client_id) 만 검증, `scope` 미검증**. 따라서 Phase 2 의 Gateway scope 토큰 (`aiops-demo-${user}-resource-server/invoke`) 이 sub-agent A2A inbound 에도 통과. Phase 5 가 새 Cognito client 추가 0 → 약 **-325 LoC 단순화** ([`../design/phase6a.md`](../design/phase6a.md) 의 alternative path 대비 — Cognito Client A/B + ResourceServer + OperatorUser + 2 OAuth provider variant 추가 제거).

### Phase 4 shared/ 직접 재사용 — build-time detail

monitor_a2a/incident_a2a 자체에 `shared/` 없음. deploy_runtime.py 가 build context 로 copy:

```
agents/monitor_a2a/runtime/         ← Docker build context
├── agentcore_runtime.py
├── Dockerfile / requirements.txt
├── shared/             ← Phase 4 monitor/shared 복사 (Phase 4 무수정)
└── _shared_debug/      ← repo root _shared_debug 복사 (DEBUG=1 시 FlowHook)

agents/incident_a2a/runtime/        ← Docker build context (helper 가 monitor/shared 라 dir 1개 더)
├── agentcore_runtime.py
├── Dockerfile / requirements.txt
├── shared/             ← Phase 4 monitor/shared 복사 (helper)
├── incident_shared/    ← Phase 4 incident/shared 복사 (truth — agent + prompts)
└── _shared_debug/      ← repo root _shared_debug 복사 (DEBUG=1 시 FlowHook)
```

preservation rule (workshop side-by-side 비교) 정합 — Phase 4 코드는 read-only.

---

## 5. References

| 자료 | 용도 |
|---|---|
| **sub-agent — Monitor A2A** | |
| [`agents/monitor_a2a/runtime/agentcore_runtime.py`](../../agents/monitor_a2a/runtime/agentcore_runtime.py) | `serve_a2a + LazyMonitorExecutor` — A2A 서버. Phase 5b 의 sub-agent usage metadata 부착 |
| **sub-agent — Incident A2A** | |
| [`agents/incident_a2a/runtime/agentcore_runtime.py`](../../agents/incident_a2a/runtime/agentcore_runtime.py) | 동일 `serve_a2a` 패턴 + 두 shared/ import (monitor helper + incident truth) |
| **caller — Supervisor** | |
| [`agents/supervisor/runtime/agentcore_runtime.py`](../../agents/supervisor/runtime/agentcore_runtime.py) | HTTP entrypoint + `@tool` wrapping a2a.client + Phase 5b sub-agent usage propagation (ContextVar stash + 4-line yield) |
| [`agents/supervisor/shared/agent.py`](../../agents/supervisor/shared/agent.py) | Strands Agent — caching + FlowHook(Supervisor) |
| [`agents/supervisor/shared/prompts/system_prompt.md`](../../agents/supervisor/shared/prompts/system_prompt.md) | routing 정책 + JSON 통합 schema |
| [`agents/supervisor/runtime/invoke_runtime.py`](../../agents/supervisor/runtime/invoke_runtime.py) | Operator + admin 통합 진입점 (SigV4) |
| **tooling** | |
| `agents/{monitor_a2a,incident_a2a,supervisor}/runtime/deploy_runtime.py` (3 agent 각자) | sub-agent **5 단계** / Supervisor **6 단계** — build context + DEBUG forward |
| `agents/{supervisor,incident_a2a,monitor_a2a}/runtime/teardown.sh` (의존 역순) | 6 step reverse + negative check (다른 Phase 5 sub-agent 보존) |
| **learn doc (Phase 5 family)** | |
| [`debug_mode.md`](debug_mode.md) | DEBUG=1 시 3 Runtime 모두 FlowHook trace |
| [`env_config.md`](env_config.md) | `.env` lifecycle — phase 별 추가 entry + Phase 5 cross-load 흐름 |
| [`phase5_detail.md`](phase5_detail.md) | 양면 timeline worked example + Session-Id 전파 내부 구조·실측·caveat |
| [`phase5_prompt_cache_effect.md`](phase5_prompt_cache_effect.md) | Bedrock prompt cache latency 효과 — 3-layer 모델 (size + wrapper + write cost) + 직접 측정값 (-38% direct API vs -4.4% Strands wrapper) |
| **cross-phase / external** | |
| [`phase4.md`](phase4.md) | Phase 4 Incident narrative — `monitor/shared` + `incident/shared` 코드 source (Phase 5 가 build context 로 직접 재사용) |
| [`../design/phase6a.md`](../design/phase6a.md) | 의사결정 로그 (D1~D6 + 이월 결정 + Option X / G / Change 단순화 출처) |
| [`../research/a2a_intro.md`](../research/a2a_intro.md) | A2A 프로토콜 직관 + serve_a2a canonical pattern (§10) + Supervisor 시나리오 다이어그램 (§6) |

---
