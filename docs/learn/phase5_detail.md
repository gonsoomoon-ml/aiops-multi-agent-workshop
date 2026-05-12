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
