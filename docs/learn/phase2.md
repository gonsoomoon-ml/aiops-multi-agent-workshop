# Phase 2 — Gateway + MCP 도구 외부화 (CloudWatch native + history mock Lambda)

> Phase 1 의 in-process @tool 을 **AgentCore Gateway 뒤로 외부화**. Cognito JWT 인증 + 2개 Lambda Target (live CW + mock history). 청중이 "도구가 in-process → Lambda behind Gateway 로 옮겼는데 Strands Agent 코드 무변경" 검증 (시스템 목표 **C2**).

---

## 무엇을 만드나

```
┌────────────────────────────┐         ┌──────────────────────────────────┐
│ Strands Agent (local)       │         │ AgentCore Gateway (MCP server)   │
│                             │  HTTPS  │  ├─ customJWTAuthorizer          │
│  agents/monitor/local/      │ ──────▶ │  │   ├─ ① 서명 (Cognito discov)  │
│    run.py                   │  Bearer │  │   ├─ ② audience (ClientId)   │
│      ↑                      │   JWT   │  │   └─ ③ scope (rs/invoke)     │
│  agents/monitor/shared/     │         │  ├─ Target: history-mock         │
│    (4 helper files)         │         │  └─ Target: cloudwatch-wrapper   │
└────────────────────────────┘         └────────────┬─────────────────────┘
                                                    │  Lambda invoke (IAM)
                                  ┌─────────────────┴─────────────────────┐
                                  ▼                                       ▼
                       ┌──────────────────┐                    ┌──────────────────────┐
                       │ history-mock     │                    │ cloudwatch-wrapper    │
                       │ Lambda           │                    │ Lambda                │
                       │  ↓               │                    │  ↓                    │
                       │ data/mock/phase1 │                    │ boto3 cloudwatch      │
                       │ (vendor 된 mock) │                    │ describe_alarms +     │
                       │                  │                    │ list_tags_for_resource│
                       └──────────────────┘                    └──────────────────────┘
                          (Phase 1 baseline                       (Phase 0 라이브 alarm)
                           동일성 검증 — P2-A3)                    `payment-${USER}-*`
```

---

## 왜 필요한가

| Educational 가치 | 학습 포인트 |
|---|---|
| **C2 검증 — 도구 외부화** | Phase 1 의 `@tool` 함수 → Phase 2 의 Gateway+Lambda 로 옮겨도 Agent 코드 무변경 (`run_local_import.py` ≡ `run.py --mode past` 출력) |
| **AgentCore Gateway = MCP server** | MCP 표준 호환 → Strands `MCPClient` 가 list_tools/call_tool 표준 동작 |
| **Cognito JWT M2M flow** | client_credentials 로 token → Bearer 헤더 → CUSTOM_JWT authorizer 의 3-layer 검증 (서명/audience/scope) |
| **Hybrid 패턴 (CFN + boto3)** | 표준 자원 (Cognito/Lambda/IAM) = CFN, AgentCore 자원 (Gateway/Target) = boto3 — 청중이 두 영역 차이 인지 |
| **Lambda Intent shape** | LLM 친화 응답 변환 — verbose CW PascalCase 25+ 필드 → snake_case 8 필드 + classification top-level |

→ **이 phase 가 Phase 3+ 의 모든 후속 phase 가 활용하는 Gateway/Lambda 인프라 + 4 helper 의 foundation**.

---

## 어떻게 동작

### 자원 (CFN 통합 stack — `aiops-demo-${DEMO_USER}-cognito-gateway`)

| 그룹 | 자원 | 개수 | 설명 |
|---|---|---:|---|
| **Cognito** | UserPool / Domain / ResourceServer / UserPoolClient | 4 | M2M client_credentials flow + Bearer JWT 발급 |
| **Lambda** | history_mock + cloudwatch_wrapper | 2 | 위 architecture 의 두 Target backend |
| **IAM Role** | history_mock + cloudwatch_wrapper + Gateway | 3 | Lambda execution × 2 + Gateway → Lambda invoke |

### 자원 (boto3 — `setup_gateway.py`)

| 자원 | 이름 | 설명 |
|---|---|---|
| AgentCore Gateway | `aiops-demo-${USER}-gateway-<random>` | MCP server + CUSTOM_JWT authorizer (3-layer) |
| Gateway Target × 2 | `history-mock` + `cloudwatch-wrapper` | tool schema (4 도구) inline + Lambda ARN backend |

### 4 helper (`agents/monitor/shared/`)

Phase 2 부터 Strands Agent 가 Gateway 호출에 필요한 helper:

| 파일 | 책임 | 사용처 |
|---|---|---|
| `env_utils.py` | `require_env(key)` — 친화적 RuntimeError | 내부 (auth_local + mcp_client) |
| `auth_local.py` | Local 환경의 Cognito JWT 획득 (boto3 → AgentCore Identity → Cognito M2M) | `local/run.py` |
| `mcp_client.py` | MCPClient factory — Bearer JWT 헤더 주입 | `local/run.py` + 4개 후속 Runtime |
| `modes.py` | `MODE_CONFIG[mode]` → (target prefix, prompt 파일명) | `local/run.py` + monitor / monitor_a2a Runtime |

### 호출 흐름 (`local/run.py` 가 위 helper 결합)

```
.env (Phase 2 deploy 가 채움)
    │
    ▼
auth_local.get_local_gateway_token()   ← env_utils.require_env 검증
    │  Cognito M2M JWT
    ▼
mcp_client.create_mcp_client(gateway_token=...)
    │  MCPClient with Authorization: Bearer <JWT>
    ▼
mcp_client.list_tools_sync()  →  Gateway → Lambda → tool 응답
    │
    ▼  filter by modes.MODE_CONFIG[mode].target_prefix
agent.create_agent(tools=filtered, system_prompt_filename=...)
    │
    ▼
agent.stream_async(query)  →  LLM + tool calls
```

자세한 module map: [`agents/monitor/shared/__init__.py`](../../agents/monitor/shared/__init__.py).

---

## 진행 단계

### 1. 사전 확인

- [ ] **Phase 0 deploy 완료** — `bash infra/ec2-simulator/deploy.sh` (live mode 의 `cloudwatch-wrapper` 가 read 할 alarm 필요)
- [ ] AWS 자격증명 + Bedrock model access (Phase 1 동일)

> Phase 1 (mock-only) 와 다르게 Phase 2 는 **Cognito + Gateway + Lambda 실제 자원** 생성. 비용 발생 (CloudFormation + Lambda invoke).

### 2. Deploy

```bash
bash infra/cognito-gateway/deploy.sh
```

흐름 (~3-5분):
1. AWS 자격증명 + .env + DEMO_USER 사전 검증
2. DEPLOY_BUCKET 보장 (idempotent — 없으면 생성 + Public Access Block)
3. `data/mock/phase1` → Lambda 디렉토리로 vendor + `__init__.py` 생성
4. `cfn package` — Lambda zip + S3 업로드 → packaged.yaml
5. `cfn deploy` — Cognito + 2 Lambda + 3 IAM Role
6. CFN outputs 캡처 (7 var) + Cognito Client Secret 별도 조회
7. `setup_gateway.py` invoke — Gateway + 2 Target 생성/갱신 (idempotent)
8. `.env` 갱신 (`COGNITO_*`, `GATEWAY_*`, `LAMBDA_*`)

성공 시 출력:
```
[deploy] Phase 2 deploy 완료
  Gateway URL: https://aiops-demo-bob-gateway-xxxx.gateway.bedrock-agentcore.us-west-2.amazonaws.com
  Lambda (history_mock):  arn:aws:lambda:us-west-2:...:function:aiops-demo-bob-history-mock
  Lambda (cloudwatch):    arn:aws:lambda:us-west-2:...:function:aiops-demo-bob-cloudwatch-wrapper
  검증: P2-A1~A5 (docs/design/phase2.md Section 8)
```

### 3. 검증

> 본 phase 의 `local/run.py` 는 OAuth provider env 가 필요 — Phase 3 Runtime deploy 가 생성 (`agents/monitor/runtime/deploy_runtime.py` 의 `create_oauth2_credential_provider`). **Phase 2 만 단독 검증은 미지원** — Phase 3 와 함께 검증.

Phase 3 deploy 완료 후:

#### 3-1. P2-A3 — Phase 1 baseline 출력 동일성 (mock 경로)

```bash
uv run python -m agents.monitor.local.run --mode past
```

Phase 1 (`run_local_import.py`) 출력과 byte-level 동일해야 함. 차이 = Gateway/Lambda 외부화 시 회귀.

#### 3-2. P2-A4/A5 — 라이브 alarm 분류

```bash
uv run python -m agents.monitor.local.run --mode live
```

Phase 0 의 2 alarm (real `payment-${USER}-status-check` + noise `payment-${USER}-noisy-cpu`) 분류 — `Tags.Classification` 라벨 그대로. `system_prompt_live.md` 의 예시 출력과 유사 형식.

#### 3-3. 통과 기준

- [ ] Gateway alive: `aws bedrock-agentcore-control list-gateways --region us-west-2`
- [ ] Tools listed (4개): mode=past 호출 시 `history-mock___*` 2개 + mode=live 호출 시 `cloudwatch-wrapper___*` 2개 매칭
- [ ] mode=past 출력이 Phase 1 baseline 과 동일 (3섹션 + 진단 매칭 정확)
- [ ] mode=live 출력이 라이브 alarm 분류 (real/noise 라벨 신뢰)
- [ ] Lambda CloudWatch Logs 에 invocation 흔적

### 4. 다음 phase 진입 또는 정리

**Phase 3 진행** (Phase 2 자원은 보존 — Phase 3+ 가 모두 의존):
→ `docs/learn/phase3.md` (Monitor Runtime 승격) — 🚧

**완전 정리** (모든 phase 자원 일괄):
→ `bash teardown_all.sh` ([`docs/learn/teardown.md`](teardown.md))

**Phase 2 만 단독 정리**:
```bash
bash infra/cognito-gateway/teardown.sh
```
→ Gateway/Target → CFN stack → DEPLOY_BUCKET → vendor cleanup → `.env` 비우기

---

## Reference

| 자료 | 용도 |
|---|---|
| [`infra/cognito-gateway/cognito.yaml`](../../infra/cognito-gateway/cognito.yaml) | CFN — Cognito × 4 + Lambda × 2 + IAM × 3 |
| [`infra/cognito-gateway/setup_gateway.py`](../../infra/cognito-gateway/setup_gateway.py) | boto3 — Gateway + 2 Target (idempotent + update branch) |
| [`infra/cognito-gateway/cleanup_gateway.py`](../../infra/cognito-gateway/cleanup_gateway.py) | boto3 reverse — Target → wait → Gateway |
| [`infra/cognito-gateway/lambda/{history_mock,cloudwatch_wrapper}/handler.py`](../../infra/cognito-gateway/lambda/) | Lambda 2개 — AgentCore Gateway invoke 패턴 (`bedrockAgentCoreToolName`) |
| [`agents/monitor/shared/__init__.py`](../../agents/monitor/shared/__init__.py) | 4-helper module map + 호출 흐름 |
| [`agents/monitor/local/run.py`](../../agents/monitor/local/run.py) | Phase 2 entry — `--mode past|live` |
| [`agents/monitor/shared/prompts/system_prompt_live.md`](../../agents/monitor/shared/prompts/system_prompt_live.md) | live mode prompt — `Tags.Classification` 신뢰 |
| [`../design/phase2.md`](../design/phase2.md) | 의사결정 로그 (D1~D10) — Smithy 폐기, hybrid CFN+boto3, Lambda intent shape |

## 알려진 제약

- **OAuth provider 의존**: `local/run.py` 는 `OAUTH_PROVIDER_NAME` env 필요 — Phase 3 Runtime deploy 가 생성. Phase 2 단독 시 local 검증 불가.
- **Token TTL**: Cognito M2M token default 1시간. Long-running session 시 새 MCPClient 생성 필요 (현 helper 는 한 번 받은 token 을 closure 에 보관).
- **Tool prefix coupling**: `modes.py` 의 prefix (`history-mock___`, `cloudwatch-wrapper___`) 가 `setup_gateway.py` 의 Target name 과 implicit 결합 — 변경 시 두 파일 동시 수정.
- **Lambda 응답 shape 차이**: `history-mock` (PascalCase, Phase 1 baseline 호환) vs `cloudwatch-wrapper` (snake_case, LLM 친화). `system_prompt_past.md` / `system_prompt_live.md` 가 각각 정합.
