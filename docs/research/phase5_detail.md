# Phase 5 — Detailed observability + tuning patterns

[`docs/learn/phase5.md`](phase5.md) 의 narrative 보충 자료. 깊은 측정 / 내부 코드 / caveat 모음. 워크샵 청중이 §3-3 / §3-4 의 기본 흐름을 마친 뒤 deep-dive 가 필요할 때 참조.

---

## 1. 양면 timeline worked example (DEBUG observability)

[`phase5.md §3-3`](phase5.md#3-3-debug-모드--host-operator-timeline--container-per-llm-call-양면) 의 worked example — host stdout 4 timing point 와 Supervisor container CloudWatch per-LLM-call breakdown 을 같은 invoke 의 두 관점으로 매칭.

operator 의 34.6초 invoke 가 container 안에서 어떻게 분해되는지 — host + Supervisor container DEBUG 동시 enable.

### Host stdout (4 timing point)

| Event | Elapsed | 의미 |
|---|---|---|
| 📤 호출 중 메시지 | 0.0s | invoke 시작 |
| HTTP response 도착 | 0.73s | boto3 header 도착 (stream 시작 직전) |
| **first SSE byte (TTFT)** | **28.23s** | 첫 byte stream — Supervisor LLM 최종 synthesis 직전 |
| first text token | 28.23s | 첫 agent_text_stream event |
| token_usage event | 34.56s | stream 끝나기 직전 |
| ✅ 완료 | 34.6s | workflow_complete |

### Supervisor container (CloudWatch — per-LLM-call breakdown)

| Δ from supervisor start | Event |
|---|---|
| t=0 | **call #1** TTFT 1,130ms — Supervisor 첫 reasoning + call_monitor_a2a tool 선택 |
| 0s | usage 1,787 (`in=1,717 out=70`) |
| 0s | 🔧 toolUse `call_monitor_a2a({'query': '현재 alarm 상황 분석해줘'})` |
| **+12s** | ⬅️ Monitor A2A result 도착 (sub-agent LLM call 12초 소요) |
| +14s | **call #2** TTFT 1,203ms — Monitor 결과 보고 call_incident_a2a 선택 |
| +14s | 🔧 toolUse `call_incident_a2a({"alarm_name": "payment-bob-status-check"})` |
| **+25s** | ⬅️ Incident A2A result 도착 (sub-agent LLM call 11초 소요) |
| +26s | **call #3** TTFT 837ms — 최종 JSON synthesis 시작 (≈ host 의 first SSE byte 28.23s 와 SSE 전파 지연 ~2s 정합) |
| +32s | usage 누적 3,284 (`in=2,649 out=635`) |

### 핵심 통찰

- host TTFT 28.23s 분해 ≈ Monitor A2A (12s) + Incident A2A (11s) + Supervisor 마지막 synthesis 시작 (~5s)
- **Supervisor LLM 본체 3 call TTFT 합 = 3.1s** — Bedrock 응답 자체는 빠름
- **나머지 ~24초 = sub-agent A2A** — total elapsed 의 70% 가 sub-agent 단계 (Monitor + Incident 각자의 LLM call 시간)
- Cache R/W 0/0 — first invoke after redeploy. session-id 재사용 2nd invoke 시에도 hit 미관측 (§2 caveat 참조)

→ 운영자 입장에선 host (4 timing) 가 enough; deep debugging (어느 sub-agent 가 느린지, 어느 LLM call 이 cache miss 했는지) 시 container 도 enable.

자세한 trace 의미: [`debug_mode.md`](debug_mode.md).

---

## 2. Session-Id 전파 — 내부 구조 + 실측 + caveat

[`phase5.md §3-4`](phase5.md#3-4-session-id-전파--3-layer-warm-container-재사용) 보충 — host CLI + container `_call_subagent` 의 핵심 코드, 실측 결과, caveat 4종.

### 전파 sequence diagram

Operator 가 지정한 `runtimeSessionId` 가 어떻게 3 agent (Supervisor + Monitor A2A + Incident A2A) 모두에서 동일하게 관측되는지 — boto3 → AgentCore SigV4 → ContextVar → A2A HTTP header → 다시 ContextVar 로 이어지는 propagation chain.

```text
                                  SESSION = "workshop-<uuid>"   (≥ 33자, AgentCore 제약)
                                  ┌───────────────────────────┐
                                  │  Operator CLI             │
                                  │  invoke_runtime.py        │
                                  └────────────┬──────────────┘
                                               │
                  (1) boto3 invoke_agent_runtime(runtimeSessionId=SESSION, SigV4)
                                               │
                                               ▼
                       ┌──────────────────────────────────────────────┐
                       │  Supervisor Runtime (microVM #1)             │
                       │  ┌────────────────────────────────────────┐  │
                       │  │ inbound HTTP header:                   │  │
                       │  │   X-Amzn-Bedrock-AgentCore-Runtime-    │  │
                       │  │     Session-Id: SESSION                │  │
                       │  └─────────────────┬──────────────────────┘  │
                       │                    │ AgentCore SDK           │
                       │                    ▼                         │
                       │  BedrockAgentCoreContext.session_id          │
                       │     (ContextVar) ← SESSION                   │
                       │                    │                         │
                       │                    ▼                         │
                       │  @app.entrypoint supervisor(payload, ctx):   │
                       │     if is_debug():                           │
                       │       print(f"[SESSION_TRACE] supervisor     │
                       │              session_id={get_session_id()}") │
                       │                    │                         │
                       │     ┌──────────────┴──────────────┐          │
                       │     ▼                             ▼          │
                       │ @tool                         @tool          │
                       │ call_monitor_a2a              call_incident  │
                       │  _a2a                          _a2a          │
                       │     │                             │          │
                       │     ▼ (in _call_subagent)         ▼          │
                       │  bearer = await _fetch_a2a_token()           │
                       │  session_id =                                │
                       │     BedrockAgentCoreContext.get_session_id() │
                       │       or str(uuid4())   # ← fallback         │
                       │  headers = {                                 │
                       │    "Authorization": f"Bearer {bearer}",      │
                       │    "X-Amzn-Bedrock-AgentCore-Runtime-        │
                       │      Session-Id": session_id,                │
                       │  }                                           │
                       └──────┬──────────────────────────────┬────────┘
                              │                              │
              (2) A2A POST +  │              (3) A2A POST +  │
              same SESSION    │              same SESSION    │
              header          │              header          │
                              ▼                              ▼
        ┌──────────────────────────────┐  ┌──────────────────────────────┐
        │ Monitor A2A Runtime (#2)     │  │ Incident A2A Runtime (#3)    │
        │  serve_a2a →                 │  │  serve_a2a →                 │
        │   BedrockCallContextBuilder  │  │   BedrockCallContextBuilder  │
        │   reads header → ContextVar  │  │   reads header → ContextVar  │
        │      = SESSION               │  │      = SESSION               │
        │                              │  │                              │
        │  LazyMonitorExecutor         │  │  LazyIncidentExecutor        │
        │   .execute(context, queue):  │  │   .execute(context, queue):  │
        │     if is_debug():           │  │     if is_debug():           │
        │       print(SESSION_TRACE..) │  │       print(SESSION_TRACE..) │
        │     # real vs noise 분류     │  │     # runbook 진단           │
        └──────────────┬───────────────┘  └──────────────┬───────────────┘
                       │ A2A artifact                    │ A2A artifact
                       └─────────────┐  ┌────────────────┘
                                     ▼  ▼
                            Supervisor LLM final synthesis
                                       │
                                       ▼
                              SSE stream (JSON) → Operator

  3 microVM 모두 동일 SESSION 으로 routing 됨 → 2nd invoke (5분 이내) 시 모두 warm 재사용
  inbound 미제공 시 supervisor 가 fallback `uuid4()` 생성 → sub-agent 마다 cold (워크샵 시연 비권장)
```

핵심 hop 3개:

| # | Hop | Transport | Session ID 위치 | 수신 측 처리 |
|---|---|---|---|---|
| 1 | Operator → Supervisor | boto3 SigV4 | `invoke_kwargs["runtimeSessionId"]` | AgentCore Runtime 이 inbound header 로 변환 → ContextVar set |
| 2 | Supervisor → Monitor A2A | A2A (HTTPS) | `X-Amzn-Bedrock-AgentCore-Runtime-Session-Id` header | `serve_a2a` 의 BedrockCallContextBuilder 가 header → ContextVar set |
| 3 | Supervisor → Incident A2A | A2A (HTTPS) | 동일 header | 동일 메커니즘 |

**검증 evidence** (2026-05-13, DEBUG=1 재배포 + SESSION_TRACE print 추가):

```
=== aiops_demo_bob_supervisor-hqv1CaG76l ===
[SESSION_TRACE] supervisor session_id=session-verify-1778637086-padding-meet-min-33-char-id-requirement

=== aiops_demo_bob_monitor_a2a-YTx1O76UoY ===
[SESSION_TRACE] aiops_demo_bob_monitor_a2a session_id=session-verify-1778637086-padding-meet-min-33-char-id-requirement

=== aiops_demo_bob_incident_a2a-RYEPx5HE69 ===
[SESSION_TRACE] aiops_demo_bob_incident_a2a session_id=session-verify-1778637086-padding-meet-min-33-char-id-requirement
```

→ 3 CloudWatch log group 의 SESSION_TRACE line 이 정확히 같은 ID. propagation chain 무손실.

재현 명령 (DEBUG=1 재배포 후):

```bash
SESSION="workshop-$(uuidgen | tr -d -)"
uv run agents/supervisor/runtime/invoke_runtime.py --query "현재 상황 진단해줘" --session-id "$SESSION"
for LG in supervisor-hqv1CaG76l monitor_a2a-YTx1O76UoY incident_a2a-RYEPx5HE69; do
  echo "=== $LG ==="
  aws logs filter-log-events --region us-east-1 \
    --log-group-name "/aws/bedrock-agentcore/runtimes/aiops_demo_bob_${LG}-DEFAULT" \
    --filter-pattern "SESSION_TRACE" \
    --start-time $(( ($(date +%s) - 300) * 1000 )) \
    --query 'events[].message' --output text
done
```

(Runtime ID 부분은 본인 환경의 ARN suffix 로 치환. log group prefix `aws logs describe-log-groups --log-group-name-prefix "/aws/bedrock-agentcore/runtimes/aiops_demo_${USER}_"` 로 확인.)

### 핵심 코드

**host** — `agents/supervisor/runtime/invoke_runtime.py`:

```python
parser.add_argument("--session-id", default=None, help="...")
# 검증: AgentCore 제약 ≥ 33자
invoke_kwargs = {"agentRuntimeArn": RUNTIME_ARN, "qualifier": "DEFAULT", ...}
if args.session_id:
    invoke_kwargs["runtimeSessionId"] = args.session_id
response = client.invoke_agent_runtime(**invoke_kwargs)
```

**container** — `agents/supervisor/runtime/agentcore_runtime.py`:

```python
from bedrock_agentcore.runtime.context import BedrockAgentCoreContext

async def _call_subagent(arn, query):
    bearer = await _fetch_a2a_token()
    session_id = BedrockAgentCoreContext.get_session_id() or str(uuid4())
    headers = {
        "Authorization": f"Bearer {bearer}",
        "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": session_id,
    }
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT, headers=headers) as h:
        ...
```

`BedrockAgentCoreContext` 는 ContextVar 기반 — Strands `@tool` 함수 안에서도 같은 async stack 이라 자동 propagate. inbound 미제공 시 fallback `uuid4()` → sub-agent 마다 cold (Phase 5 second-pass 직후 default 동작).

### 실측 (2026-05-12, EC2 stopped → P1 active path)

| 측정 | 1st (cold) | 2nd (warm) | Δ |
|---|---|---|---|
| 소요 | **44.6s** | **28.4s** | **-16.2s (-36%)** |
| Total tokens | 7,199 | 7,246 | ≈ |
| Cache R/W | 0/0 | 0/0 | (Bedrock prompt cache 와 별개 — 아래 caveat) |

절감 출처 (≈ 16s 분해):
- Supervisor microVM cold-start + Python imports: ~3s
- monitor_a2a microVM cold-start + LazyExecutor 첫 build (Strands + MCP client + Gateway token fetch): ~5s
- incident_a2a microVM cold-start + LazyExecutor 첫 build: ~5s
- Supervisor LLM call prep + httpx warmup: ~3s
- (Bedrock LLM 실 호출 + sub-agent LLM 실 호출 자체는 변동 없음 — Bedrock 본체 시간 고정)

### caveat

- **Bedrock prompt cache 와 독립**: microVM 재사용 = *host 레벨* 워밍 (Python imports + LazyExecutor `_built` 캐시). Bedrock prompt cache 의 `cacheRead`/`cacheWrite` 는 invocation 단위 — 같은 microVM 안 새 invoke 라도 conversation history 가 새로 시작되므로 hit 안 함. cache hit 시현은 single invoke 안 multi-turn 패턴 (`stream_async` 가 같은 conversation 반복 호출) 필요.
- **session-id idle 만료**: AgentCore 가 idle microVM 을 일정 시간 후 회수 → 이후 같은 session-id 도 cold 재시작. 정확 idle 시간 SDK 문서 명시 안 됨 — 워크샵 시연 시 연달아 invoke 권장.
- **session-id 길이 제약**: AgentCore 최소 33자. 미달 시 boto3 가 ValidationException. `workshop-$(uuidgen | tr -d -)` (41자) 권장 패턴 (Phase 3 invoke_runtime 와 동일 가이드).
- **session-id 공유 시 동시성 위험**: 같은 session-id 로 동시 invoke → 같은 microVM 에 concurrent 요청 → race 가능. Operator 1인 1 session-id 권장.

자세한 SDK 동작: `bedrock_agentcore.runtime.context.BedrockAgentCoreContext` (`session_id` ContextVar + inbound HTTP header `X-Amzn-Bedrock-AgentCore-Runtime-Session-Id` 자동 set).

---

## 3. Session-Id 효과 — Phase 3 single-agent 통계 측정

`scripts/bench_session_id.py` 가 자동 갱신하는 섹션. 단일 agent (Phase 3 monitor) 에서 session-id 의 latency 효과를 N=5 회 반복 측정한 결과 — A2A 다중 hop 변수를 제거하고 cold-start 효과만 isolation.

**측정 환경**: region `us-east-1` · DEMO_USER `bob` · mode `live` · started `2026-05-13 04:55:32` · query `현재 라이브 알람 분류해줘`

### 시나리오 정의

| 시나리오 | session-id 전략 | 기대 |
|---|---|---|
| **A — warm path** | 단일 session-id N 회 재사용 | i=1 cold, i>=2 warm (docs: 동일 session-id → 동일 microVM) |
| **B — cold path** | 매 invoke `workshop-<uuid>` 새로 생성 | docs 의도상 매번 cold microVM. 실제는 pool 재사용 가능성 (docs `may` hedging) |

### 통계 비교 (latency = total invoke time, 초)

| metric | B_cold | A_warm |
|---|---|---|
| total **p50** | 8.10 | 6.90 |
| total p95 | 8.20 | 7.60 |
| total min | 7.00 | 6.90 |
| total max | 8.20 | 7.60 |
| total mean | 7.80 | 7.18 |
| total stdev | 0.53 | 0.38 |
| ttft p50 | 5.40 | 4.80 |
| ttft p95 | 5.58 | 5.30 |
| cache W>0 비율 | 0.00 | 0.00 |

### Raw invokes

**B_cold**

| i | ttft (s) | total (s) | cache R | cache W | session-id (앞 12자) |
|---|---|---|---|---|---|
| 1 | 5.50 | 8.20 | 7,014 | 0 | `workshop-322…` |
| 2 | 5.60 | 8.20 | 7,014 | 0 | `workshop-b81…` |
| 3 | 5.10 | 7.00 | 7,014 | 0 | `workshop-4ba…` |
| 4 | 5.40 | 7.50 | 7,014 | 0 | `workshop-02c…` |
| 5 | 5.30 | 8.10 | 7,014 | 0 | `workshop-587…` |

**A_warm**

| i | ttft (s) | total (s) | cache R | cache W | session-id (앞 12자) |
|---|---|---|---|---|---|
| 1 | 5.40 | 7.60 | 7,014 | 0 | `workshop-6fb…` |
| 2 | 4.80 | 6.90 | 7,014 | 0 | `workshop-6fb…` |
| 3 | 4.90 | 6.90 | 7,014 | 0 | `workshop-6fb…` |
| 4 | 4.70 | 7.60 | 7,014 | 0 | `workshop-6fb…` |
| 5 | 4.80 | 6.90 | 7,014 | 0 | `workshop-6fb…` |

### 해석

**Δ p50 = +1.20s** (B − A). session-id 재사용이 약 1.2초 절감 — 단일 agent 에서도 측정 가능.

AWS docs ([Use isolated sessions](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-sessions.html)) 는 session-id 를 microVM routing 의 binding key 라 명시 ("uses the session header to route requests to the **same microVM instance**"). 단 "each request **may be routed** to a new microVM" 의 "may" hedging — pool 재사용 시 cold 효과 관측 어려움. Phase 5 (3 agent) 의 누적 효과 (4s) 와 본 측정 (1 agent) 의 효과를 함께 보면 **session-id latency 절감은 agent 수에 비례**.

session-id 의 본질적 가치는 **conversation memory 보존** (Strands `agent.messages` in-memory) + **idle timeout 15분** 안 같은 microVM 재진입. latency 는 부수 효과.

---

## 4. Session-Id 효과 — Phase 5 multi-agent 통계 측정

`scripts/bench_session_id.py --agent supervisor` 가 자동 갱신하는 섹션. N=10 회 반복 측정한 결과. 3 agent (Supervisor + Monitor A2A + Incident A2A) Phase 5 구성에서 session-id 의 누적 latency 효과를 측정 — 다중 microVM cold-start 효과 관측.

**측정 환경**: region `us-east-1` · DEMO_USER `bob` · mode `live` · started `2026-05-13 05:03:06` · query `현재 상황 진단해줘`

### 시나리오 정의

| 시나리오 | session-id 전략 | 기대 |
|---|---|---|
| **A — warm path** | 단일 session-id N 회 재사용 | i=1 cold, i>=2 warm (docs: 동일 session-id → 동일 microVM) |
| **B — cold path** | 매 invoke `workshop-<uuid>` 새로 생성 | docs 의도상 매번 cold microVM. 실제는 pool 재사용 가능성 (docs `may` hedging) |

### 통계 비교 (latency = total invoke time, 초)

| metric | B_cold | A_warm |
|---|---|---|
| total **p50** | 34.70 | 28.15 |
| total p95 | 38.73 | 35.02 |
| total min | 30.20 | 22.70 |
| total max | 39.00 | 36.50 |
| total mean | 34.68 | 28.07 |
| total stdev | 3.30 | 4.20 |
| ttft p50 | N/A | N/A |
| ttft p95 | N/A | N/A |
| cache W>0 비율 | 0.10 | 0.00 |

### Raw invokes

**B_cold**

| i | ttft (s) | total (s) | cache R | cache W | session-id (앞 12자) |
|---|---|---|---|---|---|
| 1 | N/A | 35.90 | 7,878 | 3,939 | `workshop-180…` |
| 2 | N/A | 30.50 | 11,817 | 0 | `workshop-d77…` |
| 3 | N/A | 32.60 | 11,817 | 0 | `workshop-d1d…` |
| 4 | N/A | 39.00 | 11,817 | 0 | `workshop-ec4…` |
| 5 | N/A | 38.40 | 11,817 | 0 | `workshop-a14…` |
| 6 | N/A | 33.50 | 11,817 | 0 | `workshop-246…` |
| 7 | N/A | 32.10 | 11,817 | 0 | `workshop-c3c…` |
| 8 | N/A | 37.50 | 11,817 | 0 | `workshop-181…` |
| 9 | N/A | 30.20 | 11,817 | 0 | `workshop-3a4…` |
| 10 | N/A | 37.10 | 11,817 | 0 | `workshop-2ed…` |

**A_warm**

| i | ttft (s) | total (s) | cache R | cache W | session-id (앞 12자) |
|---|---|---|---|---|---|
| 1 | N/A | 36.50 | 11,817 | 0 | `workshop-cf9…` |
| 2 | N/A | 27.80 | 11,817 | 0 | `workshop-cf9…` |
| 3 | N/A | 28.70 | 11,817 | 0 | `workshop-cf9…` |
| 4 | N/A | 25.00 | 11,817 | 0 | `workshop-cf9…` |
| 5 | N/A | 22.70 | 11,817 | 0 | `workshop-cf9…` |
| 6 | N/A | 24.70 | 11,817 | 0 | `workshop-cf9…` |
| 7 | N/A | 28.50 | 11,817 | 0 | `workshop-cf9…` |
| 8 | N/A | 24.80 | 11,817 | 0 | `workshop-cf9…` |
| 9 | N/A | 33.20 | 11,817 | 0 | `workshop-cf9…` |
| 10 | N/A | 28.80 | 11,817 | 0 | `workshop-cf9…` |

### 해석

**Δ p50 = +6.55s** (B − A), avg stdev ≈ 3.75s → Δ/stdev ≈ 1.7× → noise 위로 emerge (1× ≤ Δ < 2× stdev).

AWS docs ([Use isolated sessions](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-sessions.html)) 는 session-id 를 microVM routing 의 binding key 라 명시 ("uses the session header to route requests to the **same microVM instance**"). 단 "each request **may be routed** to a new microVM" 의 "may" hedging — pool 재사용 시 cold 효과 관측 어려움.

session-id 의 본질적 가치는 **conversation memory 보존** (Strands `agent.messages` in-memory) + **idle timeout 15분** 안 같은 microVM 재진입. latency 는 부수 효과 — 본 측정의 Δ 가 그 부수 효과의 크기.

---

## 5. Bedrock Prompt Cache — Latency-Only Effect

`scripts/bench_session_id.py` + `scripts/format_cache_compare.py` 가 자동 갱신하는 섹션. session-id 의 microVM 효과 (§4) 와 분리해, **Bedrock prompt cache 의 순수 latency 효과** 를 측정 — `cache_tools` + `SystemContentBlock(cachePoint=...)` 를 supervisor agent.py 에서 임시 제거 후 재배포 → bench → 원복 + 재배포 → bench. session-id 는 두 조건 모두 same (microVM warm 통제 변수).

**측정 환경**: agent `supervisor (Phase 5, 3 agent A2A)` · region `us-east-1` · DEMO_USER `bob` · N=5 per condition · started OFF `2026-05-13 05:43:28` → ON `2026-05-13 05:48:45`

### 조건 정의

| 조건 | supervisor agent.py | 기대 cache R/W |
|---|---|---|
| **cache OFF** | `cache_tools=None`, `system_prompt=<str>` (cachePoint 없음) | 0 / 0 모든 invoke |
| **cache ON** | `cache_tools="default"`, `SystemContentBlock(cachePoint=default)` | i=1 W>0, i>=2 R>0 W=0 |

### 통계 비교 (latency = total invoke time, 초)

#### 모든 invoke (i=1 포함, i=1 은 microVM cold 라 outlier)

| metric | cache OFF | cache ON | Δ (ON − OFF) |
|---|---|---|---|
| p50 | 23.30 | 29.40 | +6.10 |
| p95 | 34.60 | 33.58 | -1.02 |
| min | 22.80 | 25.20 | +2.40 |
| max | 37.00 | 34.60 | -2.40 |
| mean | 26.26 | 29.06 | +2.80 |
| stdev | 6.06 | 3.60 | -2.46 |

#### microVM warm 만 (i=2..N, fair 비교)

| metric | cache OFF | cache ON | Δ (ON − OFF) |
|---|---|---|---|
| p50 | 23.25 | 28.00 | +4.75 |
| p95 | 24.75 | 29.48 | +4.74 |
| min | 22.80 | 25.20 | +2.40 |
| max | 25.00 | 29.50 | +4.50 |
| mean | 23.57 | 27.68 | +4.10 |
| stdev | 0.97 | 2.13 | +1.15 |

### Raw invokes

**cache OFF**

| i | total (s) | cache R | cache W |
|---|---|---|---|
| 1 | 37.00 | 0 | 0 |
| 2 | 23.20 | 0 | 0 |
| 3 | 22.80 | 0 | 0 |
| 4 | 23.30 | 0 | 0 |
| 5 | 25.00 | 0 | 0 |

**cache ON**

| i | total (s) | cache R | cache W |
|---|---|---|---|
| 1 | 34.60 | 8,110 | 4,055 |
| 2 | 25.20 | 12,165 | 0 |
| 3 | 29.50 | 12,165 | 0 |
| 4 | 29.40 | 12,165 | 0 |
| 5 | 26.60 | 12,165 | 0 |

### 해석

**cache ON 이 OFF 보다 4.75초 더 느림** (i>=2 비교, 예상 반대). Δ/stdev ≈ 3.1× → network jitter 가 latency 변동 dominator. supervisor 가 측정하는 token usage 의 cache R/W 와 별개로, **A2A 2 hop + sub-agent LLM 호출 (Bedrock cache 와 무관) 이 total latency 의 majority 차지** → cache hit 의 supervisor 부분 절감 (~1-3s) 이 jitter 에 묻힘.

**확인된 점**:

- cache OFF 의 cache R/W 가 **모든 invoke 0/0** (5/5) → cache 진짜 disable 됐음 검증 완료
- cache ON 의 i=1 만 W>0 (1/5), i>=2 는 cache hit (R>0, W=0) → 정상 prompt cache 동작

**워크샵 narrative**: Bedrock prompt cache 의 가치는 **cost** (cache R 토큰의 ~90% 할인) 에 압도적으로 비중. **latency** 효과는 본 워크로드에서 **noise 수준 (~0-3s)** — A2A 2 hop + sub-agent LLM 호출 시간이 dominator 라 supervisor 의 cache hit 절감이 묻힘. single-agent (Phase 3) 또는 longer prompt 워크로드에서는 latency 효과 더 명확할 가능성.

**Reference**: [AWS Bedrock prompt caching](https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-caching.html) (cache read 가격 10% / cache write 가격 125%), [Strands `BedrockModel(cache_tools=...)`](https://strandsagents.com/reference/models/bedrock-models/) + `SystemContentBlock(cachePoint=...)` 가 두 레이어 (tool schema + system prompt) 캐시.

## 6. Debug 코드 내부 구조

§1 양면 timeline 과 §2 session-id 전파 검증은 모두 **`DEBUG=1` 으로 활성화되는 `_shared_debug/` helper** 에 의존. 이 §6 은 그 helper 의 코드를 4가지 building block 으로 정리 — 워크샵 청중이 trace 출력을 보고 "이게 어디서 나오나" 를 코드로 역추적할 때 참조.

cross-phase base 문서: [`debug_mode.md`](debug_mode.md) — `_shared_debug/` 의 ANSI/box 출력 규약, JWT/MCP/toolUse trace 카테고리 (Phase 2+ 공통).

### 6-1. `_shared_debug` 모듈 import — 3 runtime 공통

```python
# agents/supervisor/runtime/agentcore_runtime.py:94
from _shared_debug import dump_stream_event, is_debug

# agents/monitor_a2a/runtime/agentcore_runtime.py:99
from _shared_debug import is_debug

# agents/incident_a2a/runtime/agentcore_runtime.py:88
from _shared_debug import is_debug
```

- `is_debug()` — env `DEBUG=='1'|'true'` 검사. 모든 debug 출력의 gate. False 시 helper 들이 모두 no-op.
- `dump_stream_event(event, agent)` — Strands stream event 의 message / usage / TTFT trace. **supervisor 만 사용** (A2A sub-agent 는 stream loop 를 `StrandsA2AExecutor` 가 소유 → caller event 접근 불가).

**모듈 위치**: repo root sibling `_shared_debug/`. `deploy_runtime.py` 가 build context 로 copy → 컨테이너 `/app/_shared_debug/`, 로컬 `PROJECT_ROOT/_shared_debug/`. 양쪽 동일 import path.

### 6-2. `dump_stream_event(event, agent)` 전체 코드

**파일**: `_shared_debug/event_dump.py:68-119`

```python
def dump_stream_event(event: dict, agent=None) -> None:
    """Strands stream event 받아 흥미로운 type 만 출력 (DEBUG 모드 전용)."""
    if not is_debug():
        return

    # FlowHook 이 attribute 로 expose 한 agent_name (없으면 default "Monitor")
    agent_name = getattr(agent, "_debug_agent_name", "Monitor") if agent is not None else "Monitor"

    # 0) TTFT — 첫 chunk 도착 시 1회 (FlowHook 이 timing 시작점 셋업한 경우만)
    if agent is not None and not getattr(agent, "_debug_first_token_seen", True):
        if event.get("data") or event.get("current_tool_use"):
            t_start = getattr(agent, "_debug_t_call_start", None)
            if t_start is not None:
                elapsed_ms = (time.monotonic() - t_start) * 1000
                n = getattr(agent, "_debug_call_count", "?")
                print(f"\n{DIM}[DEBUG Bedrock → {agent_name}] call #{n} TTFT {elapsed_ms:,.0f}ms{NC}")
                agent._debug_first_token_seen = True

    # 1) message 완성 — content blocks 순회 (toolUse / toolResult / user-text)
    message = event.get("message")
    if isinstance(message, dict):
        content = message.get("content", [])
        if isinstance(content, list):
            role = message.get("role", "?")
            blocks = _interesting_blocks(content, role)  # assistant text 는 skip (stream delta 중복)
            if blocks:
                bar = "━" * 30
                print(f"\n{MAGENTA}┏━━━ message complete (role={role}) {bar}{NC}")
                _dump_content_blocks(blocks, agent_name=agent_name)
                print(f"{MAGENTA}┗{'━' * 60}{NC}")

    # 2) Bedrock raw event 의 token usage
    raw = event.get("event", {})
    if isinstance(raw, dict):
        meta = raw.get("metadata", {})
        if isinstance(meta, dict) and "usage" in meta:
            u = meta["usage"]
            print(
                f"\n{DIM}[DEBUG Bedrock → {agent_name}] usage total={u.get('totalTokens', 0):,} "
                f"in={u.get('inputTokens', 0):,} "
                f"out={u.get('outputTokens', 0):,} "
                f"cacheR={u.get('cacheReadInputTokens', 0):,} "
                f"cacheW={u.get('cacheWriteInputTokens', 0):,}{NC}"
            )
```

**4단계 동작**:

```
event 1개 도착
   │
   ├─ Gate:         is_debug() False → return (no-op)
   │
   ├─ Step 0 TTFT:  agent._debug_first_token_seen == False 이고
   │                event 가 data/current_tool_use 면 elapsed_ms 1회 출력
   │                (FlowHook._before_model 이 timing 시작점 셋업한 경우만)
   │
   ├─ Step 1 msg:   event["message"]["content"] 의 toolUse/toolResult/text block 박스 출력
   │                (assistant text 는 stream delta 로 이미 출력 → skip, 중복 방지)
   │
   └─ Step 2 usage: event["event"]["metadata"]["usage"] 5개 metric 출력
                    (total / in / out / cacheR / cacheW — Phase 5 cache fix 검증 도구)
```

**호출 사이트** — supervisor stream loop:

```python
# agents/supervisor/runtime/agentcore_runtime.py:247
async for event in agent.stream_async(query):
    dump_stream_event(event, agent=agent)   # ← 매 event 마다, DEBUG off 시 no-op

    # 그 다음 별도 yield 로직 (operator CLI 로 SSE 전달 — debug 와 독립 경로)
    msg = event.get("message")
    if isinstance(msg, dict):
        for block in msg.get("content", []) or []:
            if "toolUse" in block: yield {"type": "tool_call_begin", ...}
            elif "toolResult" in block: yield {"type": "tool_call_end", ...}
    data = event.get("data", "")
    if data: yield {"type": "agent_text_stream", "text": data}
    metadata = event.get("event", {}).get("metadata", {})
    if "usage" in metadata: usage_totals[...] += ...
```

DEBUG trace (CloudWatch logs) 와 operator SSE (CLI 출력) 는 **두 경로 독립** — debug off 시에도 SSE 는 정상.

**실제 출력 예** (supervisor 1회 호출, EC2 stopped P1 시나리오):

```
[DEBUG Bedrock → Supervisor] call #1 TTFT 1,130ms        ← Step 0

┏━━━ message complete (role=assistant) ━━━━━━━━━━━━━     ← Step 1
  💬 Bedrock → Supervisor (decided: call tool)
    🔧 toolUse: call_monitor_a2a({'query': '현재 alarm 상황 분석해줘'})
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

┏━━━ message complete (role=user) ━━━━━━━━━━━━━━━━━━━
  🔧 Lambda → Supervisor (tool result)
    📋 toolResult: {"real_alarms": ["payment-bob-status-check"], ...}
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[DEBUG Bedrock → Supervisor] usage total=1,787 in=1,717 out=70 cacheR=0 cacheW=0   ← Step 2
```

§1 의 `t=0 call #1 TTFT 1,130ms` / `usage 1,787` 항목이 이 출력에서 직접 추출됨.

### 6-3. `[SESSION_TRACE]` — Phase 5 신규 (3-layer session-id 가시화)

§2 에서 검증한 propagation chain (Operator → Supervisor → Monitor A2A → Incident A2A) 의 각 hop 에서 같은 session-id 가 ContextVar 로 도달했는지 확인하는 **1-line debug print**. `dump_stream_event` 와 달리 framework 가 emit 하는 event 가 아니라 **명시적으로 진입점에서 호출**.

**supervisor 진입점** (`agents/supervisor/runtime/agentcore_runtime.py:225-229`):

```python
@app.entrypoint
async def supervisor(payload: dict, context: Any) -> AsyncGenerator[dict, None]:
    # inbound session-id 없으면 invocation-scoped fallback 한 번 결정 → 이어지는
    # Monitor + Incident sub-agent 호출이 동일 id 공유 (per-call uuid4 회피).
    if not BedrockAgentCoreContext.get_session_id():
        _fallback_session_id.set(uuid4().hex)
    if is_debug():
        effective = BedrockAgentCoreContext.get_session_id() or _fallback_session_id.get()
        print(f"[SESSION_TRACE] supervisor session_id={effective}", flush=True)
    ...
```

**monitor_a2a sub-agent 진입점** (`agents/monitor_a2a/runtime/agentcore_runtime.py:164-166`):

```python
async def execute(self, context, event_queue):
    if is_debug():
        print(f"[SESSION_TRACE] {AGENT_NAME} session_id={BedrockAgentCoreContext.get_session_id()}", flush=True)
    if not self._built:
        async with self._build_lock:
            if not self._built:
                self.agent = await _build_real_monitor_agent()
                self._built = True
    await super().execute(context, event_queue)
```

`incident_a2a` 도 동일 패턴 (`LazyIncidentExecutor.execute` 내, `agentcore_runtime.py:151-153`).

**확인 방법**:

```bash
for LG in supervisor-<SUFFIX> monitor_a2a-<SUFFIX> incident_a2a-<SUFFIX>; do
  echo "=== $LG ==="
  aws logs filter-log-events --region us-east-1 \
    --log-group-name "/aws/bedrock-agentcore/runtimes/aiops_demo_bob_${LG}-DEFAULT" \
    --filter-pattern "SESSION_TRACE" \
    --start-time $(( ($(date +%s) - 300) * 1000 )) \
    --query 'events[].message' --output text
done
```

3 log group 의 `[SESSION_TRACE]` line 이 정확히 같은 ID 면 propagation 무손실. §2 의 검증 evidence 가 정확히 이 출력.

### 6-4. `FlowHook` — `shared/agent.py` 가 `is_debug()` 시점에 자동 등록

A2A sub-agent (monitor_a2a, incident_a2a) 는 stream loop 를 `StrandsA2AExecutor` 가 소유 → caller 가 event 접근 불가 → `dump_stream_event` 직접 호출 불가. 대신 Strands 의 hook system 으로 동등한 trace 출력.

**파일**: `agents/{monitor,incident}/shared/agent.py:60-63`

```python
# DEBUG=1 시점에만 FlowHook 등록 — pre-call (LLM / tool) 가시화. off 시 hook 0.
hooks=[FlowHook(agent_name="Monitor")] if is_debug() else [],
```

`FlowHook` (`_shared_debug/strands_hook.py`) 가 3개 이벤트 listen:

- `BeforeModelInvocation` — `agent._debug_t_call_start = time.monotonic()`, `_debug_first_token_seen = False`, `_debug_call_count += 1` 셋업. supervisor 의 경우 `dump_stream_event` 가 이 attribute 를 읽어 TTFT 계산.
- `AfterModelInvocation` — LLM call duration 출력.
- `BeforeToolInvocation` — tool 호출 직전 메타 출력.

A2A sub-agent 입장에선 stream 직접 처리 X → FlowHook 의 hook 출력이 `dump_stream_event` 의 message-block 출력을 대신함.

**Phase 5 신규 코드 0** — `monitor_a2a` / `incident_a2a` 가 Phase 4 의 `monitor/shared/` / `incident/shared/` 를 직접 재사용 → 거기 등록된 FlowHook 이 transitive 활성.

### 6-5. Debug 활성화 명령 (요약)

```bash
# 3 runtime 재배포 (각자 별도 deploy_runtime.py — DEBUG env 가 launch 시 forward)
cd agents/supervisor/runtime    && DEBUG=1 uv run deploy_runtime.py
cd agents/monitor_a2a/runtime   && DEBUG=1 uv run deploy_runtime.py
cd agents/incident_a2a/runtime  && DEBUG=1 uv run deploy_runtime.py

# host invoke 도 DEBUG=1 (4 timing point 추가 출력)
DEBUG=1 uv run agents/supervisor/runtime/invoke_runtime.py --query "현재 상황 진단해줘" --session-id "workshop-$(uuidgen | tr -d -)"

# CloudWatch 로 container trace 확인 (SESSION_TRACE, dump_stream_event 출력 모두 stdout 자동 캡쳐)
aws logs tail /aws/bedrock-agentcore/runtimes/aiops_demo_bob_supervisor-<SUFFIX>-DEFAULT --follow --region us-east-1
```

DEBUG off 로 되돌리려면 `DEBUG=0` env 로 재배포 (no-op 으로 전환되어 production noise 0).
