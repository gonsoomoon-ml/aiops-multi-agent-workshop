# Phase 3 — Monitor Agent → AgentCore Runtime 승격

> Phase 2 의 local Monitor agent 를 AgentCore Runtime 컨테이너로 옮긴다. 동일 `from shared.agent import create_agent` 의 single source of truth 로 C1 (local == Runtime 응답) 시연. Cognito M2M 토큰은 OAuth2CredentialProvider 가 SDK 안에서 자동 inject — agent 코드는 `Authorization` 헤더 직접 다루지 않음.

설계 원본 (의사결정 D1~D10): [`docs/design/phase3.md`](../design/phase3.md).

---

## 무엇을 만드나

| 산출물 | 위치 | 비고 |
|---|---|---|
| `BedrockAgentCoreApp` entrypoint | `agents/monitor/runtime/agentcore_runtime.py` | `@app.entrypoint` 함수 `monitor_agent` — payload `{mode, query}` → SSE yield (`agent_text_stream` / `token_usage` / `workflow_complete`) |
| Runtime 컨테이너 | `Dockerfile` + `requirements.txt` | uv-based Python 3.12 + OTEL distro + non-root user (uid 1000) |
| 5단계 배포 스크립트 | `deploy_runtime.py` | (1) shared/+_shared_debug/ copy → (2) toolkit configure → (3) launch (build + ECR push + Runtime 생성) → (4) IAM extras + OAuth provider → (5) READY 대기 + `.env` 저장 |
| 호출 테스트 | `invoke_runtime.py` | `boto3 invoke_agent_runtime` (SIGV4) + SSE 파싱 + token usage |
| 자원 정리 | `teardown.sh` | 6 step reverse + Phase 2 자원 보존 negative check |

새 AWS 자원: AgentCore Runtime × 1 + ECR repo × 1 + IAM execution role × 1 (toolkit 자동) + `OAuth2CredentialProvider` × 1 + CloudWatch log group × 1.

---

## 왜 필요한가

| 동기 | Phase 2 한계 | Phase 3 해결 |
|---|---|---|
| C1 (system goal) | local Strands agent 만 — Runtime 미시연 | 동일 `create_agent()` 를 Runtime 컨테이너에서 호출 → "코드 변경 0, 환경만 다름" |
| Cognito M2M 토큰 관리 | local 가 직접 `oauth2/token` POST + clientSecret 다룸 | OAuth2CredentialProvider 가 workload identity → Cognito 교환 자동, secret 은 SecretsManager 에만 |
| Observability | local print | OTEL distro + GenAI Observability auto-integration → CloudWatch dashboards |
| 워크샵 학습 | "로컬 PoC" 단계 | "production 친화 컨테이너" 단계 — 청중이 본격 AWS managed agent 경험 |

---

## 어떻게 동작

### 자원 (toolkit + boto3 hybrid)

| 자원 | 생성 도구 | 비고 |
|---|---|---|
| Dockerfile / ECR repo / IAM execution role | `bedrock_agentcore_starter_toolkit.Runtime.configure()` | non-interactive auto-create |
| Runtime (build + push + 생성) | `Runtime.launch(env_vars=...)` | env_vars 로 GATEWAY_URL / OAUTH_PROVIDER_NAME / DEMO_USER / AWS_REGION / DEBUG 등 주입 |
| IAM inline policy `MonitorRuntimeExtras` | `iam.put_role_policy()` (boto3) | `GetResourceOauth2Token` + Cognito secret read (toolkit 미제공) |
| `OAuth2CredentialProvider` | `agentcore-control.create_oauth2_credential_provider()` (boto3) | Cognito Client 의 client_credentials 흐름 자동화 (D2) |

### OAuth provider 자동 inject 매커니즘

```
agentcore_runtime.py:
    @requires_access_token(
        provider_name=OAUTH_PROVIDER_NAME,
        scopes=[COGNITO_GATEWAY_SCOPE],
        auth_flow="M2M",
        into="access_token",
    )
    async def _fetch_gateway_token(*, access_token: str = "") -> str:
        return access_token
```

- decorator 가 IAM workload identity → AgentCore Identity 의 `GetResourceOauth2Token` 호출
- AgentCore Identity 가 provider 에 등록된 clientId/clientSecret 로 Cognito `oauth2/token` 호출
- 응답 JWT 를 `access_token` kwarg 로 함수에 주입
- 코드는 그 token 을 `mcp_client.create_mcp_client(gateway_token=...)` 에 전달

→ agent 코드 자체는 `Authorization: Bearer ...` 헤더 직접 작성 0. Cognito client_secret 도 agent 가 모름 (provider 등록 시 한 번만 입력).

### 호출 흐름

```
invoke_runtime.py
    │  boto3.invoke_agent_runtime(payload={mode, query}, runtimeUserId=DEMO_USER)
    ▼
AgentCore Runtime endpoint
    │  SIGV4 인증
    ▼
container: agentcore_runtime.py:monitor_agent()
    │  payload.mode → MODE_CONFIG[mode] (target_prefix + system_prompt_file)
    │
    ├─ _fetch_gateway_token()           ← @requires_access_token 자동 inject
    │   (provider → Cognito M2M → JWT)
    │
    ├─ create_mcp_client(token)         ← shared/mcp_client.py (Phase 2 와 동일)
    │
    ├─ list_tools_sync() + filter by prefix
    │
    ├─ create_agent(tools, prompt)      ← shared/agent.py (Phase 2 와 동일 — C1)
    │   (prompt caching Layer 1+2 활성, FlowHook 등록 if DEBUG=1)
    │
    ▼
agent.stream_async(query)
    │  → yield agent_text_stream {text} × N
    │  → yield token_usage {usage}
    │  → yield workflow_complete
```

→ Phase 2 의 9-step 시퀀스와 본질 동일. 다른 점만:
- token 획득 = `@requires_access_token` (Phase 2 local 은 `auth_local.py` 의 2-mode dispatch)
- 출력 = SSE yield (Phase 2 local 은 stdout print)

자세한 sequence 시각화: [`debug_mode.md`](debug_mode.md) §5-1 + [`phase2.md`](phase2.md) `### 시퀀스` (Phase 3 도 같은 entity 흐름, Bedrock/Gateway/Lambda 부분 동일).

---

## 진행 단계

### 1. 사전 확인

- Phase 2 완료 (repo root `.env` 에 `GATEWAY_URL` / `COGNITO_*` 채워짐)
- AWS 자격 증명 (`aws configure` 또는 `AWS_PROFILE`)
- Docker daemon 실행 중 (`Runtime.launch()` 가 `docker buildx` 호출)
- `uv sync` 완료 (`bedrock_agentcore_starter_toolkit` 설치)

### 2. Deploy

```bash
uv run agents/monitor/runtime/deploy_runtime.py
```

첫 배포 ~5-10분 (Docker build + ECR push 가 대부분), 이후 update ~40초. 성공 시 **repo root `.env`** 에 `MONITOR_RUNTIME_NAME` / `MONITOR_RUNTIME_ARN` / `MONITOR_RUNTIME_ID` / `MONITOR_OAUTH_PROVIDER_NAME` 저장 (Phase 4/5 의 `INCIDENT_*` / `SUPERVISOR_*` 와 prefix namespace 분리).

### 3. 검증

#### 3-1. P3-A4 — live mode 알람 분류 (라이브 alarm `payment-${DEMO_USER}-*` 대상)

```bash
uv run agents/monitor/runtime/invoke_runtime.py --mode live
```

답변에 noise/real 라벨 정확히 분리 + token usage + TTFT/total elapsed 출력. 마지막 라인 예:
```
📊 Tokens — Total: 6,334 | Input: 1,051 | Output: 311 | Cache R/W: 4,972/0
✅ 완료 — TTFT 4.5초 / total 6.6초
```

**TTFT (Time To First Token)** = invoke 시작부터 첫 `agent_text_stream` chunk 도착까지의 client-perceived latency. Container 내부 FlowHook 의 TTFT (Bedrock 호출 latency) 와 다름 — client TTFT 는 network RTT + AgentCore 라우팅 + container 의 전체 agent loop + 첫 chunk 시작점까지 모두 포함.

#### 3-2. P3-A3 — C1 검증 (수동 비교)

같은 mode 로 local + Runtime 양쪽 실행 후 결과 비교:

```bash
uv run agents/monitor/local/run.py --mode past
uv run agents/monitor/runtime/invoke_runtime.py --mode past
```

확인 포인트:
- 답변 본문 텍스트 (LLM 비결정성 안에서 동일 구조 + 같은 분류)
- token 분포 (input/output/cacheR/cacheW)
- 도구 호출 횟수 / 결과

**structural 증명**: `agents/monitor/local/run.py` + `agents/monitor/runtime/agentcore_runtime.py` 둘 다 `from shared.agent import create_agent` — import 경로 자체가 C1 의 single source of truth 증명.

> Phase 3 first-pass 의 `verify_c1.py` (4 assertion × 3 runs schema diff 자동화) 는 second-pass 에서 **제거** — structural invariant 가 코드 구조에서 enforced, automated test 가 LLM 출력 변동에 fragile (`docs/design/phase3.md` §8-2 의 의사결정 로그만 historical 보존).

#### 3-3. Debug 모드 (선택) — Container trace 를 CloudWatch logs 로

호스트 `DEBUG=1` 은 `invoke_runtime.py` 의 client process 에만 영향. 진짜 debug 코드 (FlowHook / dump_stream_event) 는 Runtime container 안에서 실행되므로 **container env 가 `DEBUG=1` 이어야** trace 활성. container env 는 deploy 시점에 고정 → 재배포 필요.

```bash
# 1. DEBUG=1 으로 재배포 → container env 에 DEBUG=1 forward
DEBUG=1 uv run agents/monitor/runtime/deploy_runtime.py

# 2. invoke (DEBUG prefix 불필요 — container 가 이미 DEBUG=1)
uv run agents/monitor/runtime/invoke_runtime.py --mode live

# 3. CloudWatch logs 에서 trace 확인 — .env 변수 shell 에 export 후 tail
set -a; source .env; set +a
aws logs tail /aws/bedrock-agentcore/runtimes/${MONITOR_RUNTIME_ID}-DEFAULT \
    --follow --region "${AWS_REGION:-us-west-2}"
```

> 로그 그룹 이름 형식: `/aws/bedrock-agentcore/runtimes/<MONITOR_RUNTIME_ID>-DEFAULT` — Runtime ID (예: `aiops_demo_bob_monitor-5Ir33SD7Dl`) + `-DEFAULT` (endpoint qualifier) suffix. AgentCore 가 deploy 시 자동 생성. shell 에서 `${MONITOR_RUNTIME_ID}` 변수 사용 전 반드시 `set -a; source .env; set +a` 로 export (python-dotenv 는 invoke/deploy 안에서만 load, shell 은 미공유).

확인 가능 trace (DEBUG=1 container 기준):
- `Monitor → AgentCore Identity` (provider 경로) → `AgentCore Identity → Monitor` (JWT)
- `Monitor → Gateway` (MCP client init) → `Gateway → Monitor` (tool list + schemas)
- `system prompt loaded` 박스
- `Monitor → Bedrock LLM call #N` (delta messages dump) + `call #N TTFT Xms` + `call #N done — total Yms`
- `Bedrock → Monitor (decided: call tool)` 박스 (toolUse 결정)
- `Monitor → Gateway` (tool call)
- `Lambda → Monitor (tool result)` 박스
- `Bedrock → Monitor` (usage + cache R/W)

자세한 trace 의미 / 색·박스 의미: [`debug_mode.md`](debug_mode.md).

#### 3-4. Warm container 효과 (선택) — `--session-id`

매 invoke 가 새 microVM 에 할당되면 container 가 cold start (python interpreter + module import + SDK 초기화 등). 같은 `runtimeSessionId` 로 반복 호출 시 AgentCore 가 같은 warm container 로 routing → **TTFT 단축** 시연 가능.

```bash
# 1. Fresh microVM (cold container) — session-id 미설정
uv run agents/monitor/runtime/invoke_runtime.py --mode live

# 2. 같은 session-id 로 재호출 (warm container hit)
#    AgentCore 제약: runtimeSessionId 최소 33자 — UUID hex (32자) + prefix 권장
SID="workshop-$(uuidgen | tr -d -)"   # → workshop-<32 hex chars> = 41자
uv run agents/monitor/runtime/invoke_runtime.py --mode live --session-id "$SID"
uv run agents/monitor/runtime/invoke_runtime.py --mode live --session-id "$SID"
uv run agents/monitor/runtime/invoke_runtime.py --mode live --session-id "$SID"
```

마지막 라인 `✅ 완료 — TTFT X.X초 / total Y.Y초` 비교:
- 1차 cold microVM: TTFT 6~8초 범위
- 같은 ID 재호출 (warm): TTFT 4~6초 범위 → **~0.5-3초 단축** (network/AgentCore 운영 변동성 포함)
- 실측 폭은 매 시점 다름 — workshop 라이브 시연 시 청중이 직접 확인

**두 가지 caching layer 비교**:

| Layer | 도구 | 효과 | 어디서 측정 |
|---|---|---|---|
| **Prompt cache** (Bedrock) | `cache_tools="default"` + system prompt cachePoint | input token 단가 ~90% 감 | usage 라인의 `Cache R/W` |
| **Warm container** (AgentCore) | `runtimeSessionId` 반복 | **TTFT 단축 (~0.5-3초)** | `✅ 완료 — TTFT X.X초` |

둘 다 다른 메커니즘 — 청중에 "비용 절감 vs 응답성 향상" 차이 학습.

dba `chat.py` 가 multi-turn 대화에 같은 패턴 사용 (첫 응답에서 받은 sessionId 를 후속 invoke 에 재전달). 본 invoke_runtime.py 는 단일 호출이라 사용자가 ID 명시.

### 4. 정리 (P3-A5)

```bash
bash agents/monitor/runtime/teardown.sh
```

6 step reverse — Runtime → DELETED 대기 → OAuth provider → ECR → IAM role → CW log group → `.env` cleanup. Phase 2 자원 (Cognito stack / Gateway / Lambda) 보존 negative check 자동.

---

## Reference

| 자료 | 용도 |
|---|---|
| [`agents/monitor/runtime/agentcore_runtime.py`](../../agents/monitor/runtime/agentcore_runtime.py) | Runtime entrypoint — `@app.entrypoint` + SSE yield |
| [`agents/monitor/runtime/deploy_runtime.py`](../../agents/monitor/runtime/deploy_runtime.py) | 5단계 배포 (build context + toolkit + IAM/OAuth + READY 대기) |
| [`agents/monitor/runtime/Dockerfile`](../../agents/monitor/runtime/Dockerfile) | uv-based Python 3.12 + OTEL distro |
| [`agents/monitor/runtime/teardown.sh`](../../agents/monitor/runtime/teardown.sh) | 6 step reverse + negative check |
| [`agents/monitor/runtime/README.md`](../../agents/monitor/runtime/README.md) | 폴더 단위 운용 안내 (deploy / invoke / teardown / debug) |
| [`debug_mode.md`](debug_mode.md) | DEBUG=1 시 FlowHook / TTFT / cache 통계 — Phase 3 container 에서도 동작 |
| [`phase2.md`](phase2.md) | Phase 2 narrative — Phase 3 가 그대로 import 하는 `shared/` helpers 의 출처 |
| [`../design/phase3.md`](../design/phase3.md) | 의사결정 로그 (D1~D10) — OAuth provider 도입 / SSE schema / IAM extras |

---

## 알려진 제약

- **Docker daemon 의존**: `Runtime.launch()` 가 `docker buildx` 호출. 호스트에 Docker 없으면 배포 불가.
- **첫 배포 시간**: ~5-10분 (Docker build + ECR push). 이후 update 는 ~40초 (caching).
- **OAuth provider 재배포**: 기존 provider 이름 충돌 시 `ConflictException` / `ValidationException "already exists"` 둘 다 idempotent 처리 (`deploy_runtime.py:attach_extras_and_oauth_provider`).
- **`AWS_REGION` 일관**: deploy 시 `AWS_REGION` env 를 명시적으로 set (Phase 2 와 동일 region). Dockerfile 은 region 하드코딩 제거 — deploy 가 env_vars 로 주입.
- **container `DEBUG=1` 출력처**: stdout/stderr → CloudWatch 로그. real-time tail 로 봄 (`aws logs tail ... --follow`).
