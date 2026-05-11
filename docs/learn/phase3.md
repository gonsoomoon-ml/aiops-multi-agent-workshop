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

첫 배포 ~5-10분 (Docker build + ECR push 가 대부분), 이후 update ~40초. 성공 시 `agents/monitor/runtime/.env` 에 `RUNTIME_ARN` / `RUNTIME_ID` / `OAUTH_PROVIDER_NAME` 저장.

### 3. 검증

#### 3-1. P3-A4 — live mode 알람 분류 (라이브 alarm `payment-${DEMO_USER}-*` 대상)

```bash
uv run agents/monitor/runtime/invoke_runtime.py --mode live
```

답변에 noise/real 라벨 정확히 분리 + token usage 출력.

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

#### 3-3. CloudWatch 로그 (옵션 — debug mode 시점)

```bash
aws logs tail /aws/bedrock-agentcore/runtimes/aiops_demo_${DEMO_USER}_monitor \
    --follow --region "${AWS_REGION:-us-west-2}"
```

`DEBUG=1 uv run agents/monitor/runtime/deploy_runtime.py` 으로 배포하면 container env 에 `DEBUG=1` forward → FlowHook + TTFT + message complete 박스 + usage trace 가 CloudWatch 에 출력. 자세히: [`debug_mode.md`](debug_mode.md).

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
