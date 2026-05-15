# Phase 3 — Monitor Agent → AgentCore Runtime 승격

> Phase 3 는 Phase 2 의 local Monitor agent 를 **AgentCore Runtime 컨테이너로 승격**. 동일 `from shared.agent import create_agent` 의 single source of truth 로 **local == Runtime 응답 검증**. Cognito M2M 토큰은 **OAuth2CredentialProvider** 가 SDK 안에서 자동 inject — agent 코드는 `Authorization` 헤더 직접 다루지 않음.

---

## 1. 왜 필요한가   *(~3 min read)*

Phase 3 는 Phase 2 의 local Strands agent 를 **AgentCore Runtime container 로 승격** — `create_agent()` 의 single source of truth 유지로 코드 변경 0. 4가지 동기:


| 동기                         | Phase 2 한계                                       | Phase 3 해결                                                                                                                                                                                                                                                                    |
| -------------------------- | ------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **호환성** (local == Runtime) | local Strands agent 만 — Runtime 미시연              | 동일 `create_agent()` 를 Runtime 컨테이너에서 호출 → "코드 변경 0, 환경만 다름"                                                                                                                                                                                                                   |
| Cognito M2M 토큰 관리          | local 가 직접 `oauth2/token` POST + clientSecret 다룸 | `OAuth2CredentialProvider` 가 **AgentCore Workload Identity** → Cognito JWT 자동 교환 (decorator `@requires_access_token` 적용). client_secret 은 Phase 3 deploy 시 1회 provider 등록 → AgentCore Identity 가 SecretsManager 에 보관 → **Runtime container 는 secret 미접근** (provider 이름만 알면 됨) |
| Observability              | local print                                      | OTEL distro + GenAI Observability auto-integration → CloudWatch dashboards                                                                                                                                                                                                    |
| 워크샵 학습                     | "로컬 PoC" 단계                                      | "production 친화 컨테이너" 단계 — 청중이 본격 AWS managed agent 경험                                                                                                                                                                                                                         |


---

## 2. 진행 (Hands-on)   *(deploy ~10 min / 검증 ~5 min)*

### 2-1. 사전 확인

- **bootstrap 1회 실행** (`bash bootstrap.sh`) — Phase 1 과 동일
- **Phase 2 완료** (repo root `.env` 에 `GATEWAY_URL` / `COGNITO`_* 채워짐)
- AWS 자격 증명 (`aws configure` 또는 `AWS_PROFILE`)
- Docker daemon 실행 중 (`Runtime.launch()` 가 `docker buildx` 호출)
- `uv sync` 완료 (`bedrock_agentcore_starter_toolkit` 설치)

### 2-2. Deploy

```bash
uv run agents/monitor/runtime/deploy_runtime.py
```

흐름 (~5-10분 첫 배포, 이후 update ~40초):

1. `shared/` + `_shared_debug/` → build context 디렉토리 복사
2. toolkit `Runtime.configure()` — Dockerfile / ECR repo / IAM execution role 자동 생성
3. `Runtime.launch()` — Docker build + ECR push + Runtime 자원 생성
4. boto3 — IAM extras (`MonitorRuntimeExtras` inline policy: `GetResourceOauth2Token` + Cognito secret read) + `OAuth2CredentialProvider` 생성
5. Runtime READY 대기 + repo root `.env` 저장 (`MONITOR_RUNTIME_NAME` / `MONITOR_RUNTIME_ARN` / `MONITOR_RUNTIME_ID` / `MONITOR_OAUTH_PROVIDER_NAME`)

Phase 4/5 의 `INCIDENT_*` / `SUPERVISOR_*` 와 prefix namespace 분리.

deploy 후 interactive shell 에 동기 — `.env` 갱신 값 (`MONITOR_RUNTIME_ID` 등) shell var 로 export:

```bash
source .env
```

### 2-3. 검증

#### live mode 알람 분류 (라이브 alarm `payment-${DEMO_USER}-*` 대상)

```bash
uv run agents/monitor/runtime/invoke_runtime.py --mode live
```

답변에 noise/real 라벨 정확히 분리 + token usage + TTFT/total elapsed 출력. 마지막 라인 예:

```
📊 Tokens — Total: 6,334 | Input: 1,051 | Output: 311 | Cache R/W: 4,972/0
✅ 완료 — TTFT 4.5초 / total 6.6초
```

**TTFT (Time To First Token)** = invoke 시작부터 첫 `agent_text_stream` chunk 도착까지의 client-perceived latency. Container 내부 FlowHook 의 TTFT (Bedrock 호출 latency) 와 다름 — client TTFT 는 network RTT + AgentCore 라우팅 + container 의 전체 agent loop + 첫 chunk 시작점까지 모두 포함.

#### local 과 Runtime 응답 비교 (수동)

같은 mode 로 local + Runtime 양쪽 실행 후 결과 비교.

local 실행 (project package import 으로 `-m` 모듈 형태 필수):

```bash
uv run python -m agents.monitor.local.run --mode past
```

Runtime 실행:

```bash
uv run agents/monitor/runtime/invoke_runtime.py --mode past
```

확인 포인트:

- 답변 본문 텍스트 (LLM 비결정성 안에서 동일 구조 + 같은 분류)
- token 분포 (input/output/cacheR/cacheW)
- 도구 호출 횟수 / 결과

**structural 증명**: `agents/monitor/local/run.py` + `agents/monitor/runtime/agentcore_runtime.py` 둘 다 `from shared.agent import create_agent` — import 경로 자체가 **single source of truth 증명** (local 과 Runtime 응답 동일).

### Debug 모드 (선택) — Container trace 를 CloudWatch logs 로

호스트 `DEBUG=1` 은 `invoke_runtime.py` 의 client process 에만 영향. 진짜 debug 코드 (FlowHook / dump_stream_event) 는 Runtime container 안에서 실행되므로 **container env 가 `DEBUG=1` 이어야** trace 활성. container env 는 deploy 시점에 고정 → 재배포 필요.

`DEBUG=1` 으로 재배포 (container env 에 DEBUG=1 forward):

```bash
DEBUG=1 uv run agents/monitor/runtime/deploy_runtime.py
```

invoke (DEBUG prefix 불필요 — container 가 이미 DEBUG=1):

```bash
uv run agents/monitor/runtime/invoke_runtime.py --mode live
```

`.env` 변수 shell 에 export (CloudWatch tail 명령용):

```bash
set -a; source .env; set +a
```

CloudWatch logs tail:

```bash
aws logs tail /aws/bedrock-agentcore/runtimes/${MONITOR_RUNTIME_ID}-DEFAULT --follow --region "${AWS_REGION:-us-west-2}"
```

> 로그 그룹 이름 형식: `/aws/bedrock-agentcore/runtimes/<MONITOR_RUNTIME_ID>-DEFAULT` — Runtime ID (예: `aiops_demo_${DEMO_USER}_monitor-<random-suffix>`) + `-DEFAULT` (endpoint qualifier) suffix. AgentCore 가 deploy 시 자동 생성. shell 에서 `${MONITOR_RUNTIME_ID}` 변수 사용 전 반드시 `set -a; source .env; set +a` 로 export (python-dotenv 는 invoke/deploy 안에서만 load, shell 은 미공유).

확인 가능 trace (DEBUG=1 container 기준):

- `Monitor → AgentCore Identity` (provider 경로) → `AgentCore Identity → Monitor` (JWT)
- `Monitor → Gateway` (MCP client init) → `Gateway → Monitor` (tool list + schemas)
- `system prompt loaded` 박스
- `Monitor → Bedrock LLM call #N` (delta messages dump) + `call #N TTFT Xms` + `call #N done — total Yms`
- `Bedrock → Monitor (decided: call tool)` 박스 (toolUse 결정)
- `Monitor → Gateway` (tool call)
- `Lambda → Monitor (tool result)` 박스
- `Bedrock → Monitor` (usage + cache R/W)

자세한 trace 의미 / 색·박스 의미: `[debug_mode.md](debug_mode.md)`.

#### Warm container 효과 (선택) — `--session-id`

매 invoke 가 새 microVM 에 할당되면 container 가 cold start (python interpreter + module import + SDK 초기화 등). 같은 `runtimeSessionId` 로 반복 호출 시 AgentCore 가 같은 warm container 로 routing → **TTFT 단축** 시연 가능.

Fresh microVM (cold container) — session-id 미설정:

```bash
uv run agents/monitor/runtime/invoke_runtime.py --mode live
```

같은 session-id 로 재호출 (warm container hit) — AgentCore 제약 `runtimeSessionId` 최소 33자 (UUID hex 32자 + prefix 권장):

```bash
SID="workshop-$(uuidgen | tr -d -)"
```

같은 ID 로 invoke 2-3회 반복 (각 호출 후 TTFT 변화 관찰):

```bash
uv run agents/monitor/runtime/invoke_runtime.py --mode live --session-id "$SID"
```

마지막 라인 `✅ 완료 — TTFT X.X초 / total Y.Y초` 비교:

- 1차 cold microVM: TTFT 6~8초 범위
- 같은 ID 재호출 (warm): TTFT 0.5-3초 단축 (network/AgentCore 운영 변동성 포함)
- 실측 폭은 매 시점 다름 — workshop 라이브 시연 시 청중이 직접 확인

**두 가지 caching layer 비교**:


| Layer                          | 도구                                                 | 효과                    | 어디서 측정                |
| ------------------------------ | -------------------------------------------------- | --------------------- | --------------------- |
| **Prompt cache** (Bedrock)     | `cache_tools="default"` + system prompt cachePoint | input token 단가 ~90% 감 | usage 라인의 `Cache R/W` |
| **Warm container** (AgentCore) | `runtimeSessionId` 반복                              | **TTFT 단축 (~0.5-3초)** | `✅ 완료 — TTFT X.X초`    |


### 2-4. 정리

```bash
bash agents/monitor/runtime/teardown.sh
```

6 step reverse — Runtime → DELETED 대기 → OAuth provider → ECR → IAM role → CW log group → `.env` cleanup. Phase 2 자원 (Cognito stack / Gateway / Lambda) 보존 negative check 자동.

---

## 3. 무엇을 만드나   *(~3 min read)*


| 산출물                              | 위치                                            | 비고                                                                                                                                                                |
| -------------------------------- | --------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `BedrockAgentCoreApp` entrypoint | `agents/monitor/runtime/agentcore_runtime.py` | `@app.entrypoint` 함수 `monitor_agent` — payload `{mode, query}` → SSE yield (`agent_text_stream` / `token_usage` / `workflow_complete`)                            |
| Runtime 컨테이너                     | `Dockerfile` + `requirements.txt`             | uv-based Python 3.12 + OTEL distro + non-root user (uid 1000)                                                                                                     |
| 5단계 배포 스크립트                      | `deploy_runtime.py`                           | (1) shared/+_shared_debug/ copy → (2) toolkit configure → (3) launch (build + ECR push + Runtime 생성) → (4) IAM extras + OAuth provider → (5) READY 대기 + `.env` 저장 |
| 호출 테스트                           | `invoke_runtime.py`                           | `boto3 invoke_agent_runtime` (SIGV4) + SSE 파싱 + token usage                                                                                                       |
| 자원 정리                            | `teardown.sh`                                 | 6 step reverse + Phase 2 자원 보존 negative check                                                                                                                     |


**핵심**: Phase 2 의 `shared/agent.py` 가 *그대로* Runtime container 에서 동작 — single source of truth 가 코드 import 경로에서 직접 enforced.

**새 AWS 자원**: AgentCore Runtime × 1 + ECR repo × 1 + IAM execution role × 1 (toolkit 자동) + `OAuth2CredentialProvider` × 1 + CloudWatch log group × 1.

**재사용 자원 (Phase 0/2)**: Phase 2 의 Gateway + Lambda × 2 + Cognito × 4 (Runtime → Gateway 호출), Phase 0 의 EC2 + alarm × 2 (live mode 대상).

---

## 4. 어떻게 동작   *(~8 min read)*

### 자원 (toolkit + boto3 hybrid)


| 자원                                         | 생성 도구                                                           | 비고                                                                                 |
| ------------------------------------------ | --------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| Dockerfile / ECR repo / IAM execution role | `bedrock_agentcore_starter_toolkit.Runtime.configure()`         | non-interactive auto-create                                                        |
| Runtime (build + push + 생성)                | `Runtime.launch(env_vars=...)`                                  | env_vars 로 GATEWAY_URL / OAUTH_PROVIDER_NAME / DEMO_USER / AWS_REGION / DEBUG 등 주입 |
| IAM inline policy `MonitorRuntimeExtras`   | `iam.put_role_policy()` (boto3)                                 | `GetResourceOauth2Token` + Cognito secret read (toolkit 미제공)                       |
| `OAuth2CredentialProvider`                 | `agentcore-control.create_oauth2_credential_provider()` (boto3) | Cognito Client 의 client_credentials 흐름 자동화                                         |


### Build context flatten (local → container)

`deploy_runtime.py` step 1 의 copy 가 *local 프로젝트 hierarchy* 를 *flat container layout* 으로 변환.

**Stage 1: Local repo (deploy 전)**

```
aiops-multi-agent-demo/
├── _shared_debug/                              ← root level
├── agents/monitor/
│   ├── local/run.py                            ← Phase 2 entry
│   ├── runtime/                                ← Phase 3 build target
│   │   ├── agentcore_runtime.py
│   │   ├── deploy_runtime.py
│   │   ├── Dockerfile
│   │   └── ...
│   └── shared/                                 ← helpers (Phase 2 와 공유)
│       ├── agent.py
│       ├── auth_local.py
│       └── ...
```

**Stage 2: Build context (step 1 copy 후)**

```
agents/monitor/runtime/                         ← Docker build context
├── agentcore_runtime.py
├── Dockerfile
├── shared/             ← ← copy from agents/monitor/shared/
├── _shared_debug/      ← ← copy from <root>/_shared_debug/
└── ...
```

→ build context flattens project hierarchy: `agents/monitor/shared/` → top-level `shared/`, `<root>/_shared_debug/` → top-level `_shared_debug/`.

**Stage 3: Container `/app/` (Dockerfile `COPY . .` 후)**

```
/app/
├── agentcore_runtime.py                        ← entrypoint
├── shared/                                     ← `from shared.agent import ...`
│   ├── agent.py
│   └── ...
├── _shared_debug/                              ← `from _shared_debug import ...`
└── requirements.txt
```

**Import path 영향**:


|               | Local                              | Container                 |
| ------------- | ---------------------------------- | ------------------------- |
| Project root  | `aiops-multi-agent-demo/`          | `/app/`                   |
| Shared import | `from agents.monitor.shared.agent` | `from shared.agent`       |
| Debug import  | `from _shared_debug`               | `from _shared_debug` (동일) |


→ **같은 `shared/agent.py` 파일** 이지만 import 경로가 환경 별 다름. `agents/monitor/local/run.py` 는 `from agents.monitor.shared.agent`, `agentcore_runtime.py` 는 `from shared.agent` (build context flatten 으로 prefix 사라짐). **single source of truth** = `shared/agent.py` 파일 1개 — 같은 코드가 local 과 container 양쪽에서 실행되어 응답 동일성 보장.

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

- decorator 가 **AgentCore Workload Identity** token (invoke 시 `runtimeUserId` 명시로 자동 발급) 으로 AgentCore Identity 의 `GetResourceOauth2Token` 호출
- AgentCore Identity 가 provider 에 등록된 clientId/clientSecret 로 Cognito `oauth2/token` 호출
- 응답 JWT 를 `access_token` kwarg 로 함수에 주입
- 코드는 그 token 을 `mcp_client.create_mcp_client(gateway_token=...)` 에 전달

→ agent 코드 자체는 `Authorization: Bearer ...` 헤더 직접 작성 0. **Runtime container 에는 client_secret 미주입** (env_vars 미포함, provider 가 SecretsManager 에 보관).

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

자세한 sequence 시각화: `[debug_mode.md](debug_mode.md)` §5-1 + `[phase2.md](phase2.md)` `### 시퀀스` (Phase 3 도 같은 entity 흐름, Bedrock/Gateway/Lambda 부분 동일).

## 5. References


| 자료                                                                                                 | 용도                                                                 |
| -------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| `[agents/monitor/runtime/agentcore_runtime.py](../../agents/monitor/runtime/agentcore_runtime.py)` | Runtime entrypoint — `@app.entrypoint` + SSE yield                 |
| `[agents/monitor/runtime/deploy_runtime.py](../../agents/monitor/runtime/deploy_runtime.py)`       | 5단계 배포 (build context + toolkit + IAM/OAuth + READY 대기)            |
| `[agents/monitor/runtime/Dockerfile](../../agents/monitor/runtime/Dockerfile)`                     | uv-based Python 3.12 + OTEL distro                                 |
| `[agents/monitor/runtime/teardown.sh](../../agents/monitor/runtime/teardown.sh)`                   | 6 step reverse + negative check                                    |
| `[agents/monitor/runtime/README.md](../../agents/monitor/runtime/README.md)`                       | 폴더 단위 운용 안내 (deploy / invoke / teardown / debug)                   |
| `[debug_mode.md](debug_mode.md)`                                                                   | DEBUG=1 시 FlowHook / TTFT / cache 통계 — Phase 3 container 에서도 동작    |
| `[phase2.md](phase2.md)`                                                                           | Phase 2 narrative — Phase 3 가 그대로 import 하는 `shared/` helpers 의 출처 |
|                                                                                                    |                                                                    |


