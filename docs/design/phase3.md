# Phase 3 — Monitor → AgentCore Runtime 승격

> Phase 2 (`docs/design/phase2.md`) 가 도구를 Gateway 뒤로 외부화한 후, 이 단계에서 Monitor Agent 자체를 AgentCore Runtime 위에 올린다.
> Cognito client_credentials 직접 POST helper 는 OAuth2CredentialProvider 로 대체되어 통째 삭제된다.
> Gateway / Cognito UserPool / Lambda 자원은 Phase 2 그대로 — Phase 3 PR 영향 범위는 Runtime 1개 + IAM 1개 + OAuth provider 1개로 제한된다.

---

## 0-1. 한 줄 정의

**Phase 3 = transition.** "Monitor 를 Runtime 으로 옮기고, 토큰 발급 helper 를 자동 주입으로 바꾼다." 그 외 모든 것 (도구 호출 경로, agent 코드, prompt, mock 데이터, Cognito stack, Gateway/Target) 은 **무변경**.

| 측면 | Phase 2 (current) | **Phase 3 (이번)** |
|---|---|---|
| Monitor 실행 환경 | 로컬 Python (`agents/monitor/local/run.py`) | **AgentCore Runtime** (`agents/monitor/runtime/agentcore_runtime.py`) |
| Gateway 인증 토큰 획득 | `agents/monitor/shared/auth/cognito_token.py` (Cognito POST helper) | **OAuth2CredentialProvider 자동 주입** (Runtime 환경) |
| 호출 진입점 | `python -m agents.monitor.local.run --mode {past\|live}` | `boto3 bedrock-agentcore.invoke_agent_runtime(payload={"mode": ..., "query": ...})` |
| caller | 운영자 CLI 직접 | 운영자 CLI → `invoke_runtime.py` → Runtime |
| 도구 호출 경로 | Strands MCPClient → Gateway → Lambda/CW | **변경 없음** (Phase 2 와 동일) |
| Cognito UserPool/Client C | Phase 2 stack 사용 | **그대로 사용** (stack 미터치) |
| Gateway / GatewayTarget × 2 | Phase 2 boto3 생성 | **그대로 사용** (재배포 불필요) |
| Lambda × 2 (history-mock, cloudwatch-wrapper) | Phase 2 CFN | **그대로 사용** |
| Phase 1 frozen baseline | unchanged | **unchanged** (offline, 의존 끊김) |

---

## 0-2. 시스템 목표 매핑 (C1 ~ C5)

`docs/design/plan_summary.md` §시스템 목표 의 5개 능력 중 Phase 3 가 **검증** 하거나 **준비** 하는 것:

| # | 능력 | Phase 3 에서의 역할 | 검증 방법 |
|---|---|---|---|
| **C1** | Strands 로컬 → AgentCore Runtime 동일 코드 승격 | **★ 핵심 검증** — 이 단계의 raison d'être | **P3-A3 (D8)**: `mode=past` 호출 시 로컬 응답 ≡ Runtime 응답 (JSON schema-level diff 4 assertion × 3 runs) |
| **C2** | Gateway + MCP로 도구 외부화 (Agent 코드에 도구 import 0건) | **회귀 없음 검증** — Phase 2 에서 충족, Phase 3 가 깨지 않는지 재확인 | **P3-A1**: `agents/monitor/runtime/agentcore_runtime.py` 에서 `from .tools` import 0건 grep |
| C3 | A2A 프로토콜로 독립 Runtime 간 호출 | **준비만** — A2A 활성화는 **Phase 6a** (Supervisor caller 도입 시점, D5 재이월). Phase 4 는 sequential CLI invoke 만 | Phase 6a 에서 검증 |
| **C4** | AgentCore Policy로 권한·가드레일 외부화 | **prerequisite 충족** — Runtime 이 있어야 Policy 부착 가능. Phase 5 가 이 위에 올라감 | Phase 5 에서 NL Policy 부착 시 검증 |
| C5 | 두 Orchestration 패턴 비교 (stretch) | 무관 — Phase 6b 의 별 트랙 | — |

→ **Phase 3 의 직접 deliverable = C1 검증 + C2 회귀 방지**. C4 는 prerequisite 만 만들고, C3/C5 는 미접촉.

---

## 0-3. Phase 3 가 **하지 않는** 것 (scope cuts)

자세한 목록은 §9 Out of Scope. 여기서는 한 줄 요약:

- A2A 서버 활성화 (Phase 4 — Incident caller 도입 시점, D5)
- AgentCore Memory (Phase 4+ — cross-agent context 필요성 평가 후, D6)
- Incident / Change / Supervisor Runtime (Phase 4 / 6a)
- AgentCore NL Policy 부착 (Phase 5)
- Cognito Client B 추가 (Phase 6a — Supervisor caller + A2A 통합 활성화 시)
- 운영자 CLI (Cognito Client A) — Phase 6 (Supervisor 도입 시)

→ Phase 3 PR 의 영향 범위 = `agents/monitor/{shared,runtime}/` + 신규 IAM Role + 신규 OAuth provider + Runtime 자체. **Cognito stack / Gateway / Lambda 미터치.**

---

## 0-4. Educational 가치

워크샵 청중이 Phase 3 PR 을 line-by-line 읽었을 때 학습하는 것:

1. **Strands Agent 로컬 → Runtime 승격이 얼마나 작은 변경인가** — `create_agent()` 함수 시그니처 그대로, entry 한 파일 (~30 LoC) 추가, helper 한 파일 통째 삭제. "single source of truth 로 작성하면 transition 이 minimal" 이라는 시스템 목표 C1 의 구체적 경험
2. **AgentCore Identity 가 무엇을 자동화하는가** — Phase 2 의 `cognito_token.py` (~50 LoC) 가 OAuth2CredentialProvider 1자원 + Runtime invoke 시 자동 주입으로 대체되는 transition diff
3. **`bedrock_agentcore_starter_toolkit.Runtime` 의 역할** — `Runtime.configure()` + `Runtime.launch()` 가 Dockerfile / ECR repo / IAM Role / docker build / ECR push 를 자동 처리. 청중이 "AgentCore Runtime API 를 직접 호출" 학습하는 게 educational 핵심 (D1 결정 근거)
4. **Phase 2 Gateway 가 Phase 3 에서 미변경인 이유** — C2 (도구 외부화) 가 Phase 2 에서 이미 충족돼서, Phase 3 의 transition 이 도구 호출 경로 무영향. "도구 외부화의 PR 격리 효과" 시연

---

## 0-5. 본 문서 구조 (§1 ~ §12)

| 섹션 | 내용 |
|---|---|
| §1 | 의사결정 로그 (D1 ~ D10 + dba 패턴 strict 비대칭 별항) |
| §2 | 인벤토리 — AWS 자원 / 코드 파일 / env vars |
| §3 | `agentcore_runtime.py` 상세 (D4) |
| §4 | `deploy_runtime.py` 상세 (D1) |
| §5 | OAuth2CredentialProvider 상세 (D2) |
| §6 | IAM Role + 권한 상세 |
| §7 | Acceptance 기준 P3-A1 ~ A6 |
| §8 | `invoke_runtime.py` + `verify_c1.py` 상세 |
| §9 | `teardown.sh` (P3-A5) |
| §10 | Transition diff (Phase 2 → 3, line-level) |
| §11 | Transition diff 예고 (Phase 3 → 4) |
| §12 | Out of scope + Reference codebase 매핑 |

---

## 1. 의사결정 로그 (D1 ~ D10)

phase2.md §2 의 의사결정 로그 패턴 따라 — 각 결정의 **선택 / 대안 / 근거** 를 기록한다. 워크샵 청중이 Phase 3 PR 을 읽을 때 "왜 이 선택인가" 를 line-by-line 추적할 수 있어야 educational 의미가 있음.

### 1-1. 결정 요약 표

| # | 항목 | 선택 | 대안 | 핵심 근거 |
|---|---|---|---|---|
| **D1** | 인프라 패턴 | **단일 `deploy_runtime.py` (toolkit + boto3)** — dba 패턴 strict | (a) all-CFN / (b) hybrid CFN+boto3 / (c) all-boto3 | dba 차용 — "Runtime API 를 직접 호출" 이 educational core. Dockerfile / ECR / IAM 보일러플레이트는 toolkit 자동 생성에 위임 |
| **D2** | OAuth2CredentialProvider 생성 | **boto3 `bedrock-agentcore-control:create_oauth2_credential_provider`** (D1 의 같은 스크립트 안) | (a) CFN-native / (b) Lambda Custom Resource (A2A 샘플) | D1 결정의 자동 귀결 — 단일 스크립트 일관성. CFN-native 가용성 verify 불필요 (boto3 API 는 GA 확정) |
| **D3** | Runtime 이름 | **`aiops_demo_${DEMO_USER}_monitor`** (underscore, suffix 없음) | (a) `aiops_demo_${DEMO_USER}_monitor_runtime` / (b) `monitor` (단순) | AgentCore agent_name 규약 (`^[a-zA-Z][a-zA-Z0-9_]{0,47}$`, 하이픈 불가). Phase 4+ 에서 `_incident`/`_change`/`_supervisor` 자연 확장 |
| **D4** | entry 위치 + 시그니처 | **`agents/monitor/runtime/agentcore_runtime.py`** + (α) Minimal + streaming, no session caching | (a) entry.py (phase2 예고 이름) / (β) session caching / (γ) sync return | dba 의 `agentcore_runtime.py` 파일명 정확 차용. Phase 3 시나리오 = 1-shot 분석 → session 불필요. C1 검증 결정성 우선 (no caching) |
| **D5** | A2A 활성화 시점 | **Phase 6a** (Supervisor caller 도입 시점, server + caller 통합) | (a) Phase 3 포함 / (b) Phase 4 server-side만 / (c) Phase 3 dormant | caller 가 없는 활성화는 dead code. resource.md §1 line 13-14 의 "RemoteA2aAgent 패턴은 Phase 6a Supervisor 변환 시 핵심 참조" 약속 준수. Phase 4 는 sequential CLI invoke 로 multi-agent 시연 (phase4.md §5 참조). **2026-05-07 phase4.md design 시 Phase 4 → Phase 6a 로 재이월** |
| **D6** | AgentCore Memory | **보류** (Phase 4+) | (a) Phase 3 포함 / (c) dormant | D4 (no session) + D5 (no A2A) 와 일관 — Phase 3 = transition only. plan_summary §171 "Phase 4~5 에서 결정" 약속 준수. P3-A3 결정성 (stateless) |
| **D7** | OTEL 관측성 | **포함** — `aws-opentelemetry-distro` + `opentelemetry-instrument` CMD + env (`OTEL_RESOURCE_ATTRIBUTES`, `AGENT_OBSERVABILITY_ENABLED`) | (b) skip / (c) flag toggle | plan_summary §159 "거의 공짜". dba/A2A 둘 다 동일 패턴. CloudWatch GenAI Observability 콘솔에 자동 표시 → workshop visual deliverable |
| **D8** | C1 검증 (P3-A3) | **JSON schema-level diff** — 4 assertion (diagnoses.type set / .alarm set / real_alarms set / pct ±10) × 3 runs | (b) byte diff / (c) golden file / (d) tool seq / (e) hybrid | LLM 비결정성 흡수 + 결정 동일성 검증. plan_summary §220-235 의 진단 출력 스키마가 자연 비교 단위. golden file 유지비 회피 |
| **D9** | ECR push 경로 | **`Runtime.launch()` 자동 처리** | (b) 명시 docker buildx + ECR push / (c) CodeBuild | D1 의 자동 귀결. dba 정확 차용. 비용 0, Docker daemon 만 필요 (이미 plan_summary §175 prerequisite) |
| **D10** | 디렉토리 구조 | **`agents/monitor/runtime/` 단일 폴더** (Phase 3 의 모든 artifact 집중, `infra/phase3/` 미생성) | (a) `infra/phase3/` 분리 / (b) tests/ 폴더 도입 | dba 패턴 strict — `managed-agentcore/` 단일 폴더 정신 그대로. Phase 0/2 와의 비대칭은 §1-3 별항 참조 |

---

### 1-2. 결정 간 의존 관계

10개 결정이 모두 독립적이지는 않음. 워크샵 청중이 의사결정 트리를 추적할 수 있도록 의존 관계 명시:

```
D1 (단일 deploy 스크립트, toolkit + boto3)
 ├─→ D2  (OAuth provider 도 같은 스크립트의 boto3 호출)
 ├─→ D9  (Runtime.launch() 가 ECR push 처리 — 별 결정점 사실상 없음)
 └─→ D10 (artifact 한 폴더 집중 — dba 패턴의 단일 스크립트 정신 연장)

D4 (no session caching)
 ├─→ D5  (no A2A — caller 없는 활성화 회피, 인지 부하 ↓)
 ├─→ D6  (no Memory — stateless 일관)
 └─→ D8  (JSON schema diff — stateless 응답이라 결정성 ↑)

D7 (OTEL) — 독립 (다른 결정 영향 없음)
D3 (Runtime 이름) — 독립 (제약: hyphen 불가)
```

→ **3 cluster**:
- **Cluster A (D1, D2, D9, D10)**: 인프라 패턴 = dba strict
- **Cluster B (D4, D5, D6, D8)**: Phase 3 = transition only, stateless
- **Cluster C (D3, D7)**: 독립 — Runtime 이름 + 관측성

---

### 1-3. dba 패턴 strict 적용으로 인한 Phase 0/2 와의 비대칭 (별항)

**관찰된 비대칭**:

| Phase | 인프라 위치 | 패턴 출처 |
|---|---|---|
| Phase 0 | `infra/ec2-simulator/` | 자체 패턴 (EC2 + alarms + chaos scripts) |
| Phase 2 | `infra/cognito-gateway/` (CFN) + boto3 (Gateway 부분) | A2A `cloudformation/cognito.yaml` + ec-customer-support `lab-03-agentcore-gateway.ipynb` 의 hybrid |
| **Phase 3** | **`agents/monitor/runtime/`** (artifact 단일 폴더) — **`infra/phase3/` 부재** | **dba `managed-agentcore/` strict** |
| Phase 4+ (예고) | TBD — Incident agent 도입 시점에 결정 | Phase 3 패턴 (단일 폴더) 또는 Phase 2 패턴 (hybrid) 중 선택 |

**왜 비대칭이 의도적인가**:

1. **각 Phase 의 educational core 가 다름**:
   - Phase 2 educational core = "AgentCore Gateway / Target API 의 boto3 호출 시퀀스" → Gateway 만 boto3 분리, 부수 자원 (Cognito UserPool / Lambda) 은 CFN 으로 묶음
   - Phase 3 educational core = "AgentCore Runtime API + OAuth2CredentialProvider 의 boto3 호출 + toolkit 의 자동 처리 영역" → 단일 스크립트로 통합해야 호출 흐름이 한눈에 보임
2. **base codebase 의 정확한 차용 단위가 다름**:
   - Phase 2 의 base = A2A `cloudformation/cognito.yaml` + ec-customer-support `lab-03 setup_gateway.py` (둘 다 hybrid 의 부분)
   - Phase 3 의 base = dba `managed-agentcore/` 폴더 전체 (`Dockerfile` + `agentcore_runtime.py` + `deploy.py` + `example_invoke.py` 가 한 단위)
   - dba 가 hybrid 가 아니라 strict 단일 폴더라서, 우리도 strict 가 차용 의미를 살림
3. **Phase 4+ 가 어느 패턴을 따를지는 그 시점에 결정** — Incident agent 가 single-runtime 이면 Phase 3 패턴 (`agents/incident/runtime/`), 만약 multi-resource (예: GitHub Lambda 추가) 가 같이 있다면 Phase 2 패턴 (`infra/github-lambda/`) 선택. premature 회피.

**워크샵 설명 시 framing**: "각 Phase 가 차용한 base codebase 의 구조를 보존 → 청중이 base 와 우리 코드를 1:1 비교 학습. 인프라 패턴의 균일성보다 base codebase 와의 line-by-line 비교 가치 우선."

---

### 1-4. 의사결정 외 — 결정점이 아닌 항목 (이미 정해진 것)

phase2.md / plan_summary.md 에서 이미 결정돼 Phase 3 에서 재논의하지 않은 항목:

| 항목 | 값 | 출처 |
|---|---|---|
| Region | `us-west-2` | plan_summary §153 |
| Multi-user prefix | `${DEMO_USER}` | Phase 0 / Phase 2 prefix 패턴 |
| Monitor 모델 | `claude-sonnet-4-6` | plan_summary §155 (`MONITOR_MODEL_ID`) |
| `create_agent()` 시그니처 | `(tools, system_prompt_filename) → Agent` | phase2.md §6-3 (단일 진실 source) |
| Mode 분기 (`past` / `live`) | phase2 `MODE_CONFIG` 그대로 | phase2.md §6-9 (target prefix filtering) |
| Gateway URL | Phase 2 stack output (`gateway_url`) | phase2.md §3 |
| Cognito Client C ID/Secret | Phase 2 `aiops-demo-${DEMO_USER}-phase2-cognito` stack output | phase2.md §3 |
| Cognito scope | `gateway/invoke` | phase2.md §2-5 |
| storage backend | Phase 3 미사용 (storage 도입은 Phase 4 GitHub Lambda 시점) | plan_summary §82-85 |

---

## 2. 인벤토리

신규/변경/삭제 자원·코드·환경변수의 완전 목록. Phase 2 carry-over 자원도 명시 — "무엇을 손대지 않는가" 가 Phase 3 PR 영향 범위 격리의 증거.

### 2-1. AWS 자원 (신규)

| 자원 | 이름 | 생성 방법 | 부속 권한 / 의존 |
|---|---|---|---|
| **AgentCore Runtime** | `aiops_demo_${DEMO_USER}_monitor` (D3) | `Runtime.launch()` (toolkit) | ECR Repo + IAM Role |
| **ECR Repository** | `bedrock-agentcore-aiops_demo_${DEMO_USER}_monitor` (toolkit default) | `Runtime.configure(auto_create_ecr=True)` | LifecyclePolicy: keep last 10 images (toolkit default) |
| **IAM Execution Role** | `AmazonBedrockAgentCoreSDKRuntime-${region}-{hash}` (toolkit default) | `Runtime.configure(auto_create_execution_role=True)` + post-deploy `iam.put_role_policy` (§6) | Bedrock invoke + ECR + CW Logs (default), GetResourceOauth2Token + SecretsManager (post-deploy 추가) |
| **OAuth2CredentialProvider** | `aiops_demo_${DEMO_USER}_monitor_gateway_provider` | boto3 `bedrock-agentcore-control:create_oauth2_credential_provider` (D2, §5) | Cognito Client C credential 참조 (Phase 2 stack output) |
| **CloudWatch Log Group** | `/aws/bedrock-agentcore/runtimes/aiops_demo_${DEMO_USER}_monitor` | Runtime 첫 invoke 시 자동 생성 | IAM Role 의 CW Logs 권한 |

→ 자원 5개. CFN stack 0개 (D1 의 dba 패턴).

### 2-2. AWS 자원 (carry-over from Phase 2 — **변경 없음**)

| 자원 | 이름 | 비고 |
|---|---|---|
| Cognito UserPool | `aiops-demo-${DEMO_USER}-userpool` | Phase 2 stack `aiops-demo-${DEMO_USER}-phase2-cognito` |
| Cognito ResourceServer | identifier `aiops-demo-${DEMO_USER}-resource-server` | scope `gateway/invoke` |
| Cognito UserPoolClient C | M2M, GenerateSecret=true | client_credentials grant |
| AgentCore Gateway | `aiops-demo-${DEMO_USER}-gateway-{id}` | Phase 2 boto3 |
| GatewayTarget × 2 | `history-mock`, `cloudwatch-wrapper` | Phase 2 boto3 |
| Lambda × 2 | `history_mock`, `cloudwatch_wrapper` | Phase 2 CFN |
| Phase 0 EC2 + alarms | `payment-${DEMO_USER}-{status-check,noisy-cpu}` | Phase 0 CFN |

→ Phase 3 PR 가 미터치 자원 8개. Phase 3 teardown (§9) 도 이들 자원 미터치.

### 2-3. 코드 파일 (신규 — 9개, 모두 `agents/monitor/runtime/` 안)

| 파일 | 분량 (예상) | 역할 | 결정 |
|---|---|---|---|
| `agentcore_runtime.py` | ~50 LoC | BedrockAgentCoreApp + entrypoint | D4 |
| `Dockerfile` | ~20 LoC | uv + opentelemetry-instrument + non-root + EXPOSE 8080 | D7, dba 차용 |
| `deploy_runtime.py` | ~150 LoC | toolkit + boto3 5단계 (build context copy → configure → launch → IAM/OAuth → READY polling → .env) | D1 |
| `invoke_runtime.py` | ~80 LoC | boto3 `invoke_agent_runtime` + SSE 파싱 (dba `example_invoke.py` 차용) | P3-A3/A4 검증 |
| `verify_c1.py` | ~80 LoC | JSON schema diff 4 assertion × 3 runs | D8 |
| `teardown.sh` | ~50 LoC | boto3 reverse: Runtime delete → ECR delete → OAuth provider delete → IAM Role detach + delete | P3-A5 |
| `requirements.txt` | ~10 lines | strands + bedrock-agentcore + boto3 + dotenv (uv export) | — |
| `.dockerignore` | ~5 lines | `__pycache__`, `.pytest_cache`, `*.pyc`, `.env`, `shared/__pycache__` | — |
| `README.md` | ~40 LoC | Phase 3 배포/검증 절차 (workshop 청중용 step-by-step) | — |

→ 신규 9개. 분량 합계 ~485 LoC.

### 2-4. 코드 파일 (변경 — 2개)

| 파일 | 변경 내용 | 분량 변화 |
|---|---|---|
| `agents/monitor/shared/mcp_client.py` | `from agents.monitor.shared.auth.cognito_token import get_gateway_access_token` 제거 + `_transport()` 안의 `token = get_gateway_access_token()` + `headers={"Authorization": f"Bearer {token}"}` 라인 제거 | -5 LoC (단순화) |
| `pyproject.toml` | `[project.dependencies]` 에서 `requests >= 2` 제거 + `[tool.uv.dev-dependencies]` 또는 별 dependency group 에 `bedrock_agentcore_starter_toolkit` 추가 | net 0 (1 제거 + 1 추가) |

→ 변경 2개. mcp_client.py 의 변경은 phase2.md §6-9 의 transition diff 예고 그대로.

### 2-5. 코드 파일 (삭제 — 폴더 통째)

| 경로 | 분량 | 이유 |
|---|---|---|
| `agents/monitor/shared/auth/cognito_token.py` | ~50 LoC | Cognito POST + 1h cache 가 OAuth2CredentialProvider 자동 주입으로 대체됨 (D2) |
| `agents/monitor/shared/auth/__init__.py` | 0 LoC (빈 파일) | 폴더 placeholder, 부모 삭제와 함께 |
| `agents/monitor/shared/auth/` (폴더) | — | 위 2개 삭제 후 빈 폴더 — `git rm -r` |

→ 삭제 50 LoC, Phase 2 의 "transitional helper 통째 삭제" 약속 (phase2.md §6-9) 이행.

### 2-6. Build context 임시 산출물 (gitignored)

| 경로 | 생성 시점 | 내용 | cleanup |
|---|---|---|---|
| `agents/monitor/runtime/shared/` | `deploy_runtime.py` step [0] | `agents/monitor/shared/` 의 사본 (`auth/` 제외 — 그 시점에 이미 삭제됨) | docker build 후 `shutil.rmtree` (선택) 또는 그대로 두고 .gitignore 로 추적 제외 |

→ `.gitignore` 추가 (Phase 3 PR diff): `agents/monitor/runtime/shared/`

### 2-7. Runtime 환경 변수 (`Runtime.launch(env_vars={...})`)

| Key | Value | 출처 | 사용 위치 |
|---|---|---|---|
| `GATEWAY_URL` | repo root `.env` 의 `GATEWAY_URL` | Phase 2 `infra/cognito-gateway/setup_gateway.py` 가 boto3 로 Gateway 생성 후 `.env` 에 기록 (CFN 자원 아님) | `mcp_client.py:create_mcp_client()` |
| `OAUTH_PROVIDER_NAME` | `aiops_demo_${DEMO_USER}_monitor_gateway_provider` | D2 | AgentCore Identity 가 invoke 시 자동 read (코드 참조 0건 — Runtime 환경 가정) |
| `MONITOR_MODEL_ID` | `claude-sonnet-4-6` | plan_summary §155 | `shared/agent.py:create_agent()` 의 `BedrockModel(model_id=...)` |
| `OTEL_RESOURCE_ATTRIBUTES` | `service.name=aiops_demo_${DEMO_USER}_monitor` | D7 | `aws-opentelemetry-distro` (auto-instrument) |
| `AGENT_OBSERVABILITY_ENABLED` | `true` | D7 | OTEL distro → CW GenAI Observability 자동 통합 |
| `DEMO_USER` | `${DEMO_USER}` 그대로 | bootstrap `.env` | log identifier (옵션 — Phase 0/2 prefix 패턴 carry-over) |

→ env 6개. `Runtime.launch(env_vars=...)` arg 로 전달.

### 2-8. 의존성 변화 (`pyproject.toml`)

| 패키지 | 변경 | 이유 |
|---|---|---|
| `requests >= 2` | **제거** | `cognito_token.py` 삭제로 더 이상 사용 안 함 (Phase 2 transitional) |
| `bedrock_agentcore_starter_toolkit` | **추가** (dev dependency 또는 별 group) | `deploy_runtime.py` 의 `Runtime.configure/launch` |
| `bedrock_agentcore` | 그대로 (Phase 2 에서 이미) | Runtime 컨테이너 안의 `BedrockAgentCoreApp` |

→ Runtime 컨테이너의 의존성은 별도 (`agents/monitor/runtime/requirements.txt` — uv export 산출물). pyproject.toml 은 dev/local 환경용.

### 2-9. 인벤토리 차이 한눈 비교

phase2.md §6-1 의 "3-state 비교" 패턴 따라 Phase 1 / Phase 2 / Phase 3 의 누적 자원 표:

| 측면 | Phase 1 baseline (frozen) | Phase 2 current | **Phase 3 current (이번)** |
|---|---|---|---|
| Agent 실행 환경 | 로컬 Python (offline mock) | 로컬 Python + Gateway | **AgentCore Runtime + Gateway** |
| Agent code | `local/run_local_import.py` | `local/run.py --mode {past\|live}` | **`runtime/agentcore_runtime.py` (entrypoint)** |
| 도구 import | `from .tools.alarm_history import ...` (4개) | 0건 (P2-A1) | **0건 (회귀 없음, P3-A1)** |
| Gateway 토큰 helper | 없음 | `auth/cognito_token.py` (transitional) | **삭제** |
| OAuth provider | 없음 | 없음 | **신규 1자원** |
| Runtime | 없음 | 없음 | **신규 1자원** |
| ECR Repo | 없음 | 없음 | **신규 1자원** |
| IAM Role | 없음 | (Lambda 용 1개, Phase 2) | **+1 (Runtime 용)** |
| Cognito | 없음 | UserPool + Client C | unchanged |
| Gateway / Target | 없음 | Gateway + Target × 2 | unchanged |
| Lambda | 없음 | 2개 | unchanged |
| Phase 1 frozen baseline | this column | unchanged | unchanged (offline 의존 끊김) |

→ Phase 3 의 누적 변화 = "AWS 자원 +5 / 코드 +9 -2 / 의존성 +1 -1 / 폴더 1개 (`agents/monitor/shared/auth/`) 삭제".

> **§3 의 보정** (이 문서 작성 중 발견된 추가 변경): 신규 코드 9개 → **10개** (`shared/modes.py` 추가, §3-2 결정), 변경 코드 2개 → **3개** (`local/run.py` 의 MODE_CONFIG inline → import). 또한 §3-7 의 local 경로 token 획득 후보 (a-2) 가 §7 에서 확정될 시 +1.

---

## 3. `agentcore_runtime.py` 상세 (D4)

Phase 3 의 entrypoint. `BedrockAgentCoreApp.entrypoint` 데코레이터로 Runtime invoke 진입점을 등록하고, Phase 2 의 `local/run.py` 호출 흐름을 그대로 재사용해 C1 (single source of truth) 을 시연한다.

### 3-1. 파일 위치 + 역할

- 위치: `agents/monitor/runtime/agentcore_runtime.py`
- 분량 예상: ~50 LoC (entry + helper)
- 역할: `BedrockAgentCoreApp` 등록 → payload `{mode, query}` 받기 → `MODE_CONFIG` 분기 → `create_mcp_client()` + `create_agent()` 호출 → streaming SSE yield

### 3-2. 의존 모듈 (Runtime 컨테이너 안에서 import)

| import | 출처 | 역할 |
|---|---|---|
| `BedrockAgentCoreApp` | `bedrock_agentcore.runtime` | Runtime 진입점 등록 |
| `create_agent` | `agents.monitor.shared.agent` (Phase 2 단일 진실 source 그대로) | Strands Agent 생성 — 시그니처 변경 없음 |
| `create_mcp_client` | `agents.monitor.shared.mcp_client` (Phase 3 변경 후 — token line 제거됨) | Strands MCPClient 생성 — Authorization header 자동 (OAuth provider) |
| `MODE_CONFIG` | `agents.monitor.shared.modes` (신규, ~5 LoC) | mode → (target_prefix, prompt_filename) 매핑 |

**디자인 결정 — `MODE_CONFIG` 위치**:

Phase 2 는 `local/run.py:23-26` 에 inline. Phase 3 에서 entry 도 같은 dict 가 필요. 후보:
- (a) `local/run.py` 에서 import → 패키지 의존이 어색 (local 이 runtime 보다 무겁게 보임)
- (b) `shared/modes.py` 신규로 분리 → local/runtime 양쪽이 import. 단일 진실 source 유지 ★
- (c) entry 와 local 양쪽에 중복 — divergence 위험

→ **(b) 채택** — `agents/monitor/shared/modes.py` 신규 (~5 LoC) 추가. §2 인벤토리에 보정 반영 (위 `>` quote 박스).

### 3-3. payload + yield 스키마 (D4 결정 그대로)

**Payload (Runtime invoke 시)**:
```json
{
  "mode": "past" | "live",
  "query": "..."
}
```
- `mode` default = `"live"`
- `query` default = mode 별 template (코드 안에 정의)

**Yield events (3종, dba 패턴)**:

| type | 필드 | 시점 |
|---|---|---|
| `agent_text_stream` | `text: <chunk>` | streaming 중 LLM text chunk 마다 |
| `token_usage` | `usage: {inputTokens, outputTokens, totalTokens, cacheReadInputTokens, cacheWriteInputTokens}` | streaming 종료 직후 (메타데이터 누적) |
| `workflow_complete` | `text: ""` | 마지막 신호 (SSE stream 종료) |

→ `invoke_runtime.py` (§8) 가 SSE stream 을 위 3종으로 파싱해서 stdout 에 출력.

### 3-4. 호출 흐름 (실제 코드 ~70 LoC)

```python
"""agents/monitor/runtime/agentcore_runtime.py — Phase 3 Runtime entrypoint."""
import os
from typing import Any, AsyncGenerator

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from bedrock_agentcore.identity.auth import requires_access_token

from agents.monitor.shared.agent import create_agent
from agents.monitor.shared.mcp_client import create_mcp_client
from agents.monitor.shared.modes import MODE_CONFIG

OAUTH_PROVIDER_NAME   = os.environ["OAUTH_PROVIDER_NAME"]
COGNITO_GATEWAY_SCOPE = os.environ["COGNITO_GATEWAY_SCOPE"]  # 예: aiops-demo-${DEMO_USER}-resource-server/invoke

QUERY_PAST = "지난 7일 alarm history를 분석해 3가지 진단 유형으로 제안하고, real alarm은 따로 나열해줘."
QUERY_LIVE_TEMPLATE = (
    "현재 라이브 알람 (payment-{user}-* prefix) 의 상태와 classification 을 분석해, "
    "실제로 봐야 할 알람만 알려줘."
)

app = BedrockAgentCoreApp()


# OAuth2CredentialProvider → Cognito client_credentials 교환 결과를 access_token kwarg 로 주입.
# Runtime 안에서만 호출 가능 — workload identity token 이 invoke 시 함께 들어와야 동작.
@requires_access_token(
    provider_name=OAUTH_PROVIDER_NAME,
    scopes=[COGNITO_GATEWAY_SCOPE],
    auth_flow="M2M",
    into="access_token",
)
async def _fetch_gateway_token(*, access_token: str = "") -> str:
    return access_token


@app.entrypoint
async def monitor_agent(payload: dict, context: Any) -> AsyncGenerator[dict, None]:
    mode = payload.get("mode", "live")
    target_prefix, prompt_filename = MODE_CONFIG[mode]
    query = payload.get("query") or (
        QUERY_PAST if mode == "past"
        else QUERY_LIVE_TEMPLATE.format(user=os.environ.get("DEMO_USER", "ubuntu"))
    )

    gateway_token = await _fetch_gateway_token()                      # ← OAuth provider 호출
    mcp_client = create_mcp_client(gateway_token=gateway_token)       # ← Bearer header 주입
    with mcp_client:
        all_tools = mcp_client.list_tools_sync()
        tools = [t for t in all_tools if t.tool_name.startswith(target_prefix)]
        if not tools:
            received = [t.tool_name for t in all_tools]
            yield {
                "type": "agent_text_stream",
                "text": f"[error] mode={mode} 도구 0개. prefix '{target_prefix}' 매칭 실패. 받음: {received}",
            }
            yield {"type": "workflow_complete", "text": ""}
            return

        agent = create_agent(tools, prompt_filename)
        usage_totals = {
            "inputTokens": 0, "outputTokens": 0, "totalTokens": 0,
            "cacheReadInputTokens": 0, "cacheWriteInputTokens": 0,
        }
        async for event in agent.stream_async(query):
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
```

→ Phase 2 `local/run.py:_amain()` 의 호출 시퀀스 (`mcp_client → list_tools → filter → create_agent → stream_async`) 그대로 보존. 차이 두 가지:
1. **stdout `print()` → SSE `yield`** — Runtime 응답 형식 (D4)
2. **`create_mcp_client(gateway_token=...)`** — Phase 2 의 helper-내부 token 획득이 Runtime 환경에서는 `requires_access_token` 데코레이터로 외부화. caller 가 token 명시. 두 줄 추가 (`gateway_token = await _fetch_gateway_token()` + arg 전달).

→ **caller 측 전제 (invoke_runtime.py 도)**: SIGV4 invoke 시 `runtimeUserId` 파라미터 명시 필수 — 없으면 `requires_access_token` 데코레이터가 workload identity token 을 못 받아 `ValueError: Workload access token has not been set` 발생.

### 3-5. `local/run.py` ↔ `agentcore_runtime.py` 1:1 매핑 (C1 시연 자료)

| 단계 | `local/run.py` (Phase 2 + 3) | `agentcore_runtime.py` (Phase 3) | 차이 |
|---|---|---|---|
| 1 | `argparse` → `mode` | `payload.get("mode")` | CLI arg → invoke payload |
| 2 | `MODE_CONFIG[mode]` | 동일 | 무 (`shared/modes.py` 공유) |
| 3a (token 획득) | `get_local_gateway_token()` (`auth_local.py`, boto3 `GetResourceOauth2Token` 명시 호출) | `await _fetch_gateway_token()` (`requires_access_token` 데코레이터 — workload identity 자동 활용) | 호출 매커니즘만 다름. **둘 다 같은 OAuth provider 이름·scope 사용** → 같은 Cognito access_token 발급 |
| 3b | `create_mcp_client(gateway_token=...)` | 동일 | 무 (mcp_client.py 단일 truth source — caller 가 token 명시하는 형식으로 통일) |
| 4 | `with mcp_client:` | 동일 | 무 |
| 5 | `list_tools_sync()` + filter | 동일 | 무 |
| 6 | `create_agent(tools, prompt_filename)` | 동일 | 무 (단일 진실 source) |
| 7 | `async for event in agent.stream_async(query):` | 동일 | 무 |
| 8 | `print(data, end="", flush=True)` | `yield {"type": "agent_text_stream", "text": data}` | stdout → SSE yield |
| 9 | `_print_token_usage(usage_totals)` (stdout) | `yield {"type": "token_usage", "usage": ...}` | stdout → SSE yield |
| 10 | (없음) | `yield {"type": "workflow_complete", "text": ""}` | Runtime SSE 종료 시그널 신규 |

→ **단계 4~7 (5개) 호출 시퀀스 동일**. 차이 두 곳: 단계 3a (token 획득 매커니즘) + 단계 8/9/10 (출력 stdout → SSE). C1 검증의 직접 근거 (워크샵 청중이 두 파일 옆에 두고 비교 학습).

### 3-6. `mcp_client.py` 변경 diff (Phase 2 → 3)

```diff
 # agents/monitor/shared/mcp_client.py
-from agents.monitor.shared.auth.cognito_token import get_gateway_access_token
+from .env_utils import require_env

-def create_mcp_client() -> MCPClient:
-    gateway_url = os.environ["GATEWAY_URL"]
+def create_mcp_client(gateway_token: str) -> MCPClient:
+    gateway_url = require_env("GATEWAY_URL")
     def _transport():
-        token = get_gateway_access_token()
         return streamablehttp_client(
             url=gateway_url,
-            headers={"Authorization": f"Bearer {token}"},
+            headers={"Authorization": f"Bearer {gateway_token}"},
             timeout=timedelta(seconds=120),
         )
     return MCPClient(_transport)
```

**왜 token 획득 코드가 사라졌는데도 양쪽 환경에서 작동하는가** (workshop 핵심 설명 포인트):

- **Phase 2**: `mcp_client.py` 내부에서 `get_gateway_access_token()` 호출 (`auth/cognito_token.py` ~50 LoC — Cognito POST + 1h cache).
- **Phase 3**: token 획득을 **caller 측으로 외부화**. `mcp_client.py` 는 token 을 받아 헤더에 박는 것만 담당.
  - **Runtime caller** (`agentcore_runtime.py`): SDK 데코레이터 `requires_access_token(provider_name, scopes, auth_flow="M2M")` 가 workload identity → Cognito M2M 교환을 자동 처리 → `access_token` kwarg 로 주입.
  - **Local caller** (`local/run.py`): boto3 `bedrock-agentcore.get_resource_oauth2_token()` 명시 호출 (`auth_local.py` ~10 LoC). workload identity 가 없으니 IAM 자격증명만으로 호출.
- 두 caller 모두 **같은 OAuth provider + 같은 scope** 를 참조 → 같은 Cognito access_token 발급 → 같은 헤더로 Gateway 호출. C1 (single source of truth) 의 핵심: token 을 어떻게 받았는지에 무관하게 `mcp_client` 는 한 줄로 동일 동작.
- 매커니즘 detail: §5 OAuth2CredentialProvider 상세

### 3-7. local 경로의 영향 (Phase 3 PR 후)

Phase 3 PR 에서 `local/run.py` 는 어떻게 되나?

- **선택 (a) 그대로 유지** — `local/run.py --mode {past|live}` 가 동작해야 함. 이유: P3-A6 (single source of truth 검증) 이 "local + runtime 둘 다 동일 create_agent 호출" 을 요구. local 경로가 살아 있어야 검증됨 ★
- (b) 삭제 — Phase 3 = Runtime 전환이니 local 불필요?

→ **(a) 채택**: local 경로는 Phase 3 PR 후에도 살아남는다.

**Local 환경에서 token 획득**

Local 에서는 Runtime SDK 의 `requires_access_token` 데코레이터를 못 쓴다 (workload identity token 미존재). `auth_local.py` 가 boto3 `bedrock-agentcore.get_resource_oauth2_token()` 을 IAM 자격증명만으로 명시 호출한다 (~10 LoC).

**최종 채택 (a-2)** — boto3 명시 호출 helper. 신규 파일 `shared/auth_local.py` 추가. `requests` 의존 재도입 없음, OAuth2 추상화 한 단 위라 educational 가치 높음.

**검토했다가 기각한 대안**:

1. (a-1) `mcp_client.py` 가 env 감지 분기 — Phase 3 초기 시도 시 잠시 도입했으나 (a-2) 채택 시점에 제거. **이유**: workshop 청중이 "이게 어느 경로로 동작하는가" 를 추적하기 어려움. magic 분기 vs caller-explicit 중 후자가 educational.
3. (a-3) auth/cognito_token.py 를 local 폴더로 이동 — `requests` 의존 재도입 약속 깨짐.
4. (a-4) Local 은 Phase 2 mcp_client 를 frozen 으로 import — divergence (mcp_client 두 버전).

### 3-8. `__main__` block 의 의도

```python
if __name__ == "__main__":
    app.run()
```

- **로컬 개발 시 사용**: Runtime 컨테이너 빌드 없이 `python -m agents.monitor.runtime.agentcore_runtime` 으로 직접 실행 → BedrockAgentCoreApp 가 HTTP 서버 모드 (port 8080) 로 기동 → `curl localhost:8080/...` 로 invoke 시뮬레이션 가능
- **Docker 컨테이너 안에서 사용**: `Dockerfile` 의 `CMD ["opentelemetry-instrument", "python", "-m", "agentcore_runtime"]` 가 같은 진입점 호출 (단, OTEL instrument prefix 추가)
- **장점**: dev/prod 코드 동일 (dba 패턴 정확 차용)

---

## 4. `deploy_runtime.py` 상세 (D1)

Phase 3 의 핵심 인프라 스크립트. dba `managed-agentcore/deploy.py` 패턴을 차용해 단일 Python 파일로 5단계 (build context 복사 → toolkit configure → toolkit launch → post-deploy IAM/OAuth → READY polling → .env 저장) 를 처리한다.

### 4-1. 파일 위치 + 사전 조건

- 위치: `agents/monitor/runtime/deploy_runtime.py`
- 분량 예상: ~150 LoC
- 실행 방법: `uv run agents/monitor/runtime/deploy_runtime.py`
- 사전 조건:
  1. `aws configure` (또는 `AWS_PROFILE` 환경 변수) — workload identity 발급에 IAM 자격증명 필요
  2. `bedrock_agentcore_starter_toolkit` 설치 (pyproject.toml dev dependency, §2-8)
  3. Docker daemon 실행 중 (Runtime.launch 가 docker build 호출)
  4. Phase 2 stack 배포 완료 (`aiops-demo-${DEMO_USER}-phase2-cognito`) — Cognito Client C credential + Gateway URL 가져옴
  5. `agents/monitor/shared/auth/` 이미 삭제됨 (Phase 3 PR 의 transition diff 반영)

### 4-2. 5단계 흐름

```
[0/5] build context 준비 — agents/monitor/shared/ 를 agents/monitor/runtime/shared/ 로 복사
[1/5] toolkit Runtime.configure() — Dockerfile + ECR repo + IAM Role 자동 생성
[2/5] toolkit Runtime.launch() — Docker build → ECR push → Runtime create (~5-10분)
[3/5] post-deploy 추가 권한 — IAM put_role_policy + OAuth2CredentialProvider create
[4/5] READY polling — get_agent_runtime status (10s × 60)
[5/5] .env 저장 — RUNTIME_ARN / RUNTIME_ID / OAUTH_PROVIDER_NAME
```

→ dba `deploy.py:52-256` 의 6단계 (`[0]` skill copy → `[1]` configure → `[2]` launch → `[3]` SSM 권한 → `[4]` READY → `[5]` .env) 와 1:1 매핑. 차이는 Step [3] 에서 SSM 대신 GetResourceOauth2Token + SecretsManager 권한 + OAuth provider 생성.

### 4-3. Step [0] — Build context 준비

```python
SCRIPT_DIR = Path(__file__).resolve().parent           # agents/monitor/runtime/
project_root = SCRIPT_DIR.parents[2]                    # repo 루트

# shared/ 복사 (auth/ 는 Phase 3 PR 에서 이미 삭제)
src_shared = project_root / "agents" / "monitor" / "shared"
dst_shared = SCRIPT_DIR / "shared"
if dst_shared.exists():
    shutil.rmtree(dst_shared)
shutil.copytree(src_shared, dst_shared)
```

- **이유**: Docker build context = `SCRIPT_DIR` (entrypoint 와 같은 폴더). `COPY ../../shared` 같은 build context 밖 참조 불가
- **gitignore 영향**: `agents/monitor/runtime/shared/` 를 .gitignore 에 추가 (§2-6)
- **dba 차용**: dba `deploy.py:60-94` 가 `skills/` `shared/` `prompts/` 3개 복사. 우리는 `shared/` 1개 만 (prompts 는 `shared/prompts/` 안에 이미 nested)

### 4-4. Step [1] — `Runtime.configure()`

```python
from bedrock_agentcore_starter_toolkit import Runtime

DEMO_USER = os.environ["DEMO_USER"]
AGENT_NAME = f"aiops_demo_{DEMO_USER}_monitor"          # D3
REGION = "us-west-2"

agentcore_runtime = Runtime()
response = agentcore_runtime.configure(
    agent_name=AGENT_NAME,
    entrypoint="agentcore_runtime.py",                  # D4 - 파일 이름 (SCRIPT_DIR 기준)
    auto_create_execution_role=True,                    # IAM Role 자동 생성
    auto_create_ecr=True,                               # ECR repo 자동 생성
    requirements_file="requirements.txt",
    region=REGION,
    non_interactive=True,
)
print(f"   Dockerfile: {response.dockerfile_path}")
print(f"   Config:     {response.config_path}")
```

**자동 생성되는 자원** (configure 호출만으로 — launch 전):
- `Dockerfile` (toolkit default) — 만약 우리가 직접 작성한 Dockerfile (D7) 이 있으면 toolkit 이 그걸 우선 사용 (확인 필요 — toolkit 동작)
- ECR Repository: `bedrock-agentcore-aiops_demo_${DEMO_USER}_monitor` (LifecyclePolicy: keep last 10)
- IAM Execution Role: `AmazonBedrockAgentCoreSDKRuntime-{region}-{hash}` (default 권한 — Bedrock invoke + ECR + CW Logs + ECR token)

→ 이 Role 이 Step [3] 에서 추가 권한 부착 대상.

### 4-5. Step [2] — `Runtime.launch()`

```python
# env_vars 준비 — Phase 2 가 repo root .env 에 기록한 carry-over 값 read
# (Phase 2 deploy.sh:87 + setup_gateway.py 가 Cognito client secret + Gateway URL 을
#  .env 에 채움. CFN output 에는 client secret 노출 불가 — GenerateSecret 의 제약.)
from dotenv import load_dotenv
PROJECT_ROOT = SCRIPT_DIR.parents[2]                    # repo 루트 (.env 위치)
load_dotenv(PROJECT_ROOT / ".env")

GATEWAY_URL = os.environ["GATEWAY_URL"]                 # Phase 2 setup_gateway.py 작성
OAUTH_PROVIDER_NAME = f"aiops_demo_{DEMO_USER}_monitor_gateway_provider"  # D2

env_vars = {
    "GATEWAY_URL": GATEWAY_URL,
    "OAUTH_PROVIDER_NAME": OAUTH_PROVIDER_NAME,
    "MONITOR_MODEL_ID": os.environ.get("MONITOR_MODEL_ID", "claude-sonnet-4-6"),
    "OTEL_RESOURCE_ATTRIBUTES": f"service.name={AGENT_NAME}",
    "AGENT_OBSERVABILITY_ENABLED": "true",
    "DEMO_USER": DEMO_USER,
}

launch_result = agentcore_runtime.launch(
    env_vars=env_vars,
    auto_update_on_conflict=True,                       # 재배포 시 update
)
print(f"   Runtime ARN: {launch_result.agent_arn}")
print(f"   Runtime ID:  {launch_result.agent_id}")
print(f"   ECR URI:     {launch_result.ecr_uri}")
```

- **소요 시간**: 첫 배포 ~5-10분, 업데이트 ~40초 (dba 검증 수치)
- **자동 처리 (toolkit 내부)**: docker buildx → ECR auth → docker push → bedrock-agentcore-control:create_agent_runtime
- **`auto_update_on_conflict=True`**: 같은 agent_name 이 이미 있으면 update_agent_runtime 호출 (idempotent 재실행)

### 4-6. Step [3] — Post-deploy 추가 권한 + OAuth provider

이 단계는 toolkit 이 처리하지 않는 Phase 3-specific 자원/권한을 boto3 로 직접 처리.

#### 4-6-a. IAM put_role_policy — 추가 권한 부착

```python
agentcore_control = boto3.client("bedrock-agentcore-control", region_name=REGION)
runtime_info = agentcore_control.get_agent_runtime(agentRuntimeId=launch_result.agent_id)
role_arn = runtime_info["roleArn"]
role_name = role_arn.split("/")[-1]
account_id = role_arn.split(":")[4]

iam = boto3.client("iam")
inline_policy = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "GetResourceOauth2Token",
            "Effect": "Allow",
            "Action": ["bedrock-agentcore:GetResourceOauth2Token"],
            "Resource": "*",
        },
        {
            "Sid": "ReadCognitoClientSecret",
            "Effect": "Allow",
            "Action": ["secretsmanager:GetSecretValue"],
            "Resource": [
                # OAuth provider 가 내부적으로 secret 을 보관할 수 있어 read 권한 필요
                f"arn:aws:secretsmanager:{REGION}:{account_id}:secret:bedrock-agentcore-identity!*",
            ],
        },
    ],
}
iam.put_role_policy(
    RoleName=role_name,
    PolicyName="Phase3RuntimeExtras",
    PolicyDocument=json.dumps(inline_policy),
)
print(f"   ✅ 추가 권한 부착: {role_name}")
```

→ §6 IAM Role 상세에서 권한 항목별 근거.

#### 4-6-b. OAuth2CredentialProvider create

```python
# Cognito carry-over — repo root .env (Phase 2 deploy.sh + setup_gateway.py 가 채움)
client_id     = os.environ["COGNITO_CLIENT_C_ID"]
client_secret = os.environ["COGNITO_CLIENT_C_SECRET"]      # cognito-idp:DescribeUserPoolClient 결과
user_pool_id  = os.environ["COGNITO_USER_POOL_ID"]
domain        = os.environ["COGNITO_DOMAIN"]
authorization_endpoint = f"https://{domain}.auth.{REGION}.amazoncognito.com/oauth2/authorize"
token_endpoint         = f"https://{domain}.auth.{REGION}.amazoncognito.com/oauth2/token"

agentcore_control.create_oauth2_credential_provider(
    name=OAUTH_PROVIDER_NAME,
    credentialProviderVendor="CustomOauth2",
    oauth2ProviderConfigInput={
        "customOauth2ProviderConfig": {
            "clientId": client_id,
            "clientSecret": client_secret,
            "oauthDiscovery": {
                "authorizationServerMetadata": {
                    "issuer": f"https://cognito-idp.{REGION}.amazonaws.com/{user_pool_id}",
                    "authorizationEndpoint": authorization_endpoint,  # client_credentials 흐름에서 미사용이지만 boto3 schema 가 required
                    "tokenEndpoint": token_endpoint,
                    "responseTypes": ["token"],
                },
            },
        },
    },
)
print(f"   ✅ OAuth2CredentialProvider 생성: {OAUTH_PROVIDER_NAME}")
```

→ 매커니즘 + Cognito output 매핑은 §5 OAuth2CredentialProvider 상세.

→ **idempotent 처리**: 만약 같은 이름이 이미 존재하면 `ConflictException` → catch 후 skip (또는 update). 워크샵 재배포 시나리오 보호.

### 4-7. Step [4] — READY polling

```python
terminal_states = ["READY", "CREATE_FAILED", "DELETE_FAILED", "UPDATE_FAILED"]
status = "CREATING"
max_attempts = 60                                       # 최대 10분 (10s × 60)

for attempt in range(1, max_attempts + 1):
    time.sleep(10)
    resp = agentcore_control.get_agent_runtime(agentRuntimeId=launch_result.agent_id)
    status = resp["status"]
    print(f"   [{attempt}/{max_attempts}] {status}")
    if status in terminal_states:
        break

if status != "READY":
    print(f"❌ Runtime 실패 (상태: {status})")
    print(f"   CloudWatch 로그 확인:")
    print(f"   aws logs tail /aws/bedrock-agentcore/runtimes/{AGENT_NAME} --follow --region {REGION}")
    sys.exit(1)
```

→ dba `deploy.py:181-205` 동일 패턴.

### 4-8. Step [5] — `.env` 저장

```python
env_file = SCRIPT_DIR / ".env"
if env_file.exists():
    with open(env_file, "r") as f:
        lines = [
            line for line in f.readlines()
            if not line.startswith("RUNTIME_ARN=")
            and not line.startswith("RUNTIME_ID=")
            and not line.startswith("RUNTIME_NAME=")
            and not line.startswith("OAUTH_PROVIDER_NAME=")
            and not line.strip().startswith("# Phase 3 Runtime")
        ]
else:
    lines = []

lines.append(f"\n# Phase 3 Runtime ({datetime.now().strftime('%Y-%m-%d')})\n")
lines.append(f"RUNTIME_NAME={AGENT_NAME}\n")
lines.append(f"RUNTIME_ARN={launch_result.agent_arn}\n")
lines.append(f"RUNTIME_ID={launch_result.agent_id}\n")
lines.append(f"OAUTH_PROVIDER_NAME={OAUTH_PROVIDER_NAME}\n")

with open(env_file, "w") as f:
    f.writelines(lines)
```

→ `.env` 위치 = `agents/monitor/runtime/.env` (이 폴더의 invoke_runtime.py / verify_c1.py / teardown.sh 모두 같은 파일에서 read).

→ `.gitignore` 이미 `.env` 등록 (Phase 0 부터 — 검증 필요).

### 4-9. 출력 (성공 시 마지막 요약)

```
============================================================
  Phase 3 — AgentCore Runtime 배포 완료
============================================================
   Runtime 이름:           aiops_demo_ubuntu_monitor
   Runtime ARN:            arn:aws:bedrock-agentcore:us-west-2:057716757052:agent-runtime/...
   ECR URI:                057716757052.dkr.ecr.us-west-2.amazonaws.com/bedrock-agentcore-aiops_demo_ubuntu_monitor:latest
   OAuth Provider 이름:    aiops_demo_ubuntu_monitor_gateway_provider
   리전:                   us-west-2

   다음 단계:
   1. mode=past 검증:      uv run agents/monitor/runtime/invoke_runtime.py --mode past
   2. mode=live 검증:      uv run agents/monitor/runtime/invoke_runtime.py --mode live
   3. C1 검증:             uv run agents/monitor/runtime/verify_c1.py
   4. 로그 확인:           aws logs tail /aws/bedrock-agentcore/runtimes/aiops_demo_ubuntu_monitor --follow
   5. 자원 정리:           bash agents/monitor/runtime/teardown.sh
============================================================
```

→ 사용자 다음 step 으로의 안내 (workshop UX). dba `deploy.py:240-251` 동일 패턴.

### 4-10. 미해결 사항 (구현 시 검증 필요)

| 항목 | 검증 시점 | 대안 |
|---|---|---|
| toolkit 의 Dockerfile auto-generation 우선순위 — 우리가 작성한 `Dockerfile` (D7) vs toolkit default | Step [1] 실행 직후 | toolkit 이 우리 Dockerfile 무시하면 `Runtime.configure(dockerfile_path=...)` arg 명시 |
| `customOauth2ProviderConfig` 의 정확한 schema (issuer/tokenEndpoint/responseTypes 필드) | Step [3-b] 실행 시 | boto3 docs 참조 + ConflictException catch |
| ~~Phase 2 stack output `UserPoolClientCSecret` 의 형식~~ → **해결됨**: CFN 은 `GenerateSecret: true` 의 client secret 을 output 으로 export 불가. Phase 2 `infra/cognito-gateway/deploy.sh:87` 가 `aws cognito-idp describe-user-pool-client` 호출로 secret 추출 후 repo root `.env` 에 기록. deploy_runtime.py 는 `.env` 에서 read (§4-5/§5-3 갱신) | — | — |
| OAuth provider 가 내부적으로 secret 을 보관하는 위치 (`arn:aws:secretsmanager:...:secret:bedrock-agentcore-identity!*` 패턴 정확성) | Step [3-a] IAM 권한 작성 시 | AWS docs 확인, 또는 `Resource: "*"` 로 우선 부착 후 scope down |

→ 위 4개 항목은 구현 시 반드시 검증. 디자인 단계에서는 placeholder.

---

## 5. OAuth2CredentialProvider 상세 (D2)

Phase 2 의 `cognito_token.py` (~50 LoC, Cognito client_credentials POST + 1h cache) 가 Phase 3 에서 통째 삭제되는 이유 = **OAuth2CredentialProvider 가 같은 일을 자동으로 처리**. 워크샵 청중이 "왜 코드 50 LoC 가 사라졌는데도 Gateway 호출이 동작하는가" 를 line-by-line 추적할 수 있어야 educational 의미가 있음.

### 5-1. OAuth2CredentialProvider 가 무엇을 자동화하는가

| 단계 | Phase 2 (cognito_token.py) | **Phase 3 (OAuth2CredentialProvider)** |
|---|---|---|
| 1. workload identity 식별 | (해당 없음 — 코드가 직접 client_credentials POST) | Runtime invoke 시 caller 가 `runtimeUserId` 명시 → AgentCore 가 매 호출마다 workload identity token 발급해 컨테이너에 inject |
| 2. Cognito token endpoint 호출 | `requests.post(token_url, data={grant_type, client_id, client_secret, scope})` | `requires_access_token(...)` 데코레이터가 `bedrock-agentcore:GetResourceOauth2Token` 호출 — 같은 client_credentials 흐름이지만 client_id/secret 은 AgentCore Identity 서비스가 SecretsManager 에서 자동 read |
| 3. access_token 추출 | `response.json()["access_token"]` | 데코레이터가 함수 인자 (`access_token` kwarg) 로 자동 inject |
| 4. 캐시 (1h, JWT 만료까지) | helper 안 in-memory dict + `now < expires_at - 60s` 체크 | AgentCore Identity 서비스가 자동 캐싱 |
| 5. Authorization header 주입 | `headers={"Authorization": f"Bearer {token}"}` 수동 | 우리 코드가 `mcp_client(gateway_token=...)` 로 명시 전달 — 데코레이터가 token 자체는 주입했지만 MCP transport 의 헤더 매핑은 application 책임 |

→ **단계 2~4 (Cognito 호출 + 캐시) 가 AgentCore Identity 로 이관**. 단계 1 과 5 는 application 측 명시 호출 유지 — 1 (`runtimeUserId` invoke 인자) + 5 (`gateway_token=...` mcp_client 인자) 두 줄. 줄이는 LoC 보다 **token 의 출처와 흐름을 워크샵에서 line-by-line 추적 가능하게 만드는 educational 효과** 가 핵심 (만약 SDK 가 끝까지 자동 inject 했다면 청중이 "왜 동작하는지" 못 봤을 것).

→ Phase 2 helper 의 `requests` + 캐시 코드 (~50 LoC) 가 사라지는 것이 의미 있는 단순화 — 2~4 단계가 사라진 결과.

### 5-2. Provider 자원 자체

| 항목 | 값 |
|---|---|
| 자원 타입 | `bedrock-agentcore-control` namespace 의 OAuth2CredentialProvider (D2 — boto3 API, CFN-native verify 불필요) |
| 이름 | `aiops_demo_${DEMO_USER}_monitor_gateway_provider` |
| Vendor | `CustomOauth2` (Cognito 는 표준 vendor 가 아니므로 custom) |
| ClientId/Secret | Phase 2 Cognito Client C — repo root `.env` `COGNITO_CLIENT_C_ID/SECRET` 에서 read |
| OAuth flow | `M2M` (machine-to-machine, client_credentials grant) |
| Scope | provider 자체에는 명시 안 함 — `requires_access_token(scopes=[...])` 호출 시 동적 지정. 실제 값 = `aiops-demo-${DEMO_USER}-resource-server/invoke` (Phase 2 Cognito Resource Server identifier + scope name, repo root `.env` `COGNITO_GATEWAY_SCOPE` 로 carry-over) |

### 5-3. Provider 생성 boto3 호출 (deploy_runtime.py Step [3-b] expand)

```python
# §4-5 와 동일 — repo root .env 에서 carry-over (Phase 2 deploy.sh + setup_gateway.py 가 채움)
user_pool_id = os.environ["COGNITO_USER_POOL_ID"]
domain       = os.environ["COGNITO_DOMAIN"]

agentcore_control.create_oauth2_credential_provider(
    name=OAUTH_PROVIDER_NAME,
    credentialProviderVendor="CustomOauth2",
    oauth2ProviderConfigInput={
        "customOauth2ProviderConfig": {
            "clientId": os.environ["COGNITO_CLIENT_C_ID"],
            "clientSecret": os.environ["COGNITO_CLIENT_C_SECRET"],
            "oauthDiscovery": {
                "authorizationServerMetadata": {
                    "issuer": f"https://cognito-idp.{REGION}.amazonaws.com/{user_pool_id}",
                    "authorizationEndpoint": f"https://{domain}.auth.{REGION}.amazoncognito.com/oauth2/authorize",
                    "tokenEndpoint": f"https://{domain}.auth.{REGION}.amazoncognito.com/oauth2/token",
                    "responseTypes": ["token"],
                },
            },
        },
    },
)
```

#### 필드 설명

| 필드 | 값 | 의미 |
|---|---|---|
| `name` | `aiops_demo_${DEMO_USER}_monitor_gateway_provider` | Runtime 이 invoke 시 reference 하는 식별자 |
| `credentialProviderVendor` | `CustomOauth2` | Cognito 는 표준 vendor (Google/GitHub/MS/Slack 등) 아님 |
| `clientId` | Cognito Client C 의 `ClientId` (repo root `.env` `COGNITO_CLIENT_C_ID`, Phase 2 stack output 으로도 노출) | OAuth2 client_id |
| `clientSecret` | Cognito Client C 의 `ClientSecret` (repo root `.env` `COGNITO_CLIENT_C_SECRET`, Phase 2 deploy.sh 가 `cognito-idp:DescribeUserPoolClient` 결과로 채움) | OAuth2 client_secret (AgentCore Identity 가 secret manager 에 보관) |
| `issuer` | `https://cognito-idp.{region}.amazonaws.com/{user_pool_id}` | OIDC issuer URL (UserPool 의 well-known) |
| `authorizationEndpoint` | `https://{domain}.auth.{region}.amazoncognito.com/oauth2/authorize` | OAuth2 authorize endpoint. `client_credentials` 흐름에서는 호출되지 않지만 boto3 API schema 가 required 로 검증 |
| `tokenEndpoint` | `https://{domain}.auth.{region}.amazoncognito.com/oauth2/token` | Cognito UserPool Domain 의 token endpoint |
| `responseTypes` | `["token"]` | implicit / token response type |

→ 이 한 번의 호출로 AgentCore Identity 가 "Cognito Client C 로 token 을 발급받는 방법" 을 알게 됨. Runtime 은 이 provider 의 이름만 알면 됨.

### 5-4. Runtime 안에서의 token 획득 흐름 (런타임 시나리오)

Runtime 컨테이너가 invoke 받았을 때 (`invoke_runtime.py` 호출 시):

```
0. Caller 측 (invoke_runtime.py — boto3 invoke_agent_runtime 호출)
   └─ runtimeUserId="ubuntu" 명시 → AgentCore 가 이 호출에 대해 workload identity token 발급
       └─ X-Amzn-Bedrock-AgentCore-Runtime-Workload-AccessToken 헤더로 Runtime 컨테이너에 inject

1. Runtime 컨테이너 boot (이번 invoke 의 첫 호출 시 1회)
   ├─ env vars 로딩 (GATEWAY_URL, OAUTH_PROVIDER_NAME, COGNITO_GATEWAY_SCOPE, ...)
   ├─ @app.entrypoint 함수 호출 — payload + context 인자
   └─ context 안에 workload identity token 보관 (SDK 가 헤더에서 추출)

2. monitor_agent() 가 _fetch_gateway_token() await
   └─ requires_access_token 데코레이터가 다음 작업 자동 수행:
       ├─ workload identity token (1번에서 보관) 추출
       ├─ bedrock-agentcore:GetResourceOauth2Token 호출:
       │   ├─ workloadIdentityToken: <위에서 추출>
       │   ├─ resourceCredentialProviderName: OAUTH_PROVIDER_NAME (env)
       │   ├─ scopes: [COGNITO_GATEWAY_SCOPE]                       # 데코레이터 인자
       │   └─ oauth2Flow: "M2M"
       └─ AgentCore Identity 서비스가 SecretsManager 의 client_secret 으로
          Cognito client_credentials POST → access_token 캐싱 → 반환
       ↓
       _fetch_gateway_token 함수의 access_token kwarg 로 inject → return access_token

3. monitor_agent() 가 create_mcp_client(gateway_token=access_token) 호출
   └─ mcp_client.py 가 Authorization: Bearer <token> 헤더 박아서 streamablehttp 시작

4. agent.stream_async(query) — Strands 가 MCP tool 호출 시
   └─ MCPClient 의 transport (이미 헤더 박힘) 가 Gateway 로 HTTP 요청
       └─ Gateway 가 token 검증 → Lambda/CloudWatch 호출 → 응답

5. yield 로 SSE stream 반환
```

→ **application 코드 두 줄** (`gateway_token = await _fetch_gateway_token()` + `create_mcp_client(gateway_token=...)`) 만이 token 흐름의 명시 부분. AgentCore Identity 서비스가 처리하는 부분 = SecretsManager read + Cognito POST + 캐시 (단계 2 의 데코레이터 안).

### 5-5. A2A 샘플 (`monitoring_strands_agent/utils.py:27-48`) 와의 차이

A2A 샘플은 `bedrock_agentcore` SDK 의 자동 inject 를 사용하지 않고, **명시적 `get_resource_oauth2_token` 호출** 로 직접 처리:

```python
# A2A 샘플 (참고)
agentcore_client = boto3.client("bedrock-agentcore")
response = agentcore_client.get_resource_oauth2_token(
    workloadIdentityToken=workload_token,
    resourceCredentialProviderName=GATEWAY_PROVIDER_NAME,
    scopes=["gateway/invoke"],
    oauth2Flow="M2M",
)
access_token = response["accessToken"]

# 그 후 MCPClient 에 수동 주입
```

**우리 (Phase 3) 와의 차이**:

| 측면 | A2A 샘플 | **Phase 3 Runtime** | **Phase 3 Local** |
|---|---|---|---|
| token 획득 | boto3 `get_resource_oauth2_token` 명시 호출 (workload_token 인자) | `requires_access_token` 데코레이터 (workload identity 자동 활용) | boto3 `get_resource_oauth2_token` 명시 호출 (workload_token 생략 — IAM 자격증명) |
| 코드 분량 | helper 함수 ~20 LoC | 데코레이터 + return-only 함수 ~8 LoC | helper 함수 ~10 LoC (`auth_local.py`) |
| 학습 가치 | OAuth2 flow 의 모든 단계 노출 | "데코레이터가 무엇을 줄여주는가" 시연 | A2A 샘플과 동일 (boto3 호출 명시) |
| 디버깅 | 호출 실패 시 helper 안에서 추적 | SDK 내부 fail 시 CW logs trace 필요 | helper 안에서 추적 |

→ **트레이드오프 → 분리 채택**: Runtime 환경에서는 SDK 데코레이터 활용 (단순화 효과 시연), Local 환경에서는 boto3 명시 호출 (`auth_local.py` — A2A 샘플 패턴 차용). **두 환경이 같은 OAuth provider + 같은 scope 를 참조**하므로 Cognito 측에서는 동일한 access_token 발급. workshop 청중은 양쪽 코드를 비교해 "데코레이터가 무엇을 자동화했는가" 를 직접 확인 가능.

### 5-6. 보안 함의

| 항목 | 보안 모델 |
|---|---|
| `clientSecret` 노출 위험 | OAuth provider 생성 시 AgentCore Identity 가 secrets manager 에 저장 (`bedrock-agentcore-identity` namespace). describe-stack 로 평문 노출되는 phase2 의 stack output 보다 안전 |
| Runtime IAM Role 권한 | `bedrock-agentcore:GetResourceOauth2Token` 한 액션만 — Runtime 만 token 발급 가능 |
| token 수명 | Cognito JWT default 1h. AgentCore Identity 가 만료 전 갱신 |
| workload identity boundary | 같은 Runtime 안의 모든 invoke 가 동일 token 공유 가능 (per-Runtime, not per-request) |

→ Phase 2 의 cognito_token.py (코드가 client_secret 을 환경변수에서 read) 보다 보안 boundary 더 강함.

### 5-7. cleanup 시 — provider 삭제 (P3-A5 의 부분)

```python
# teardown.sh / deploy_runtime.py 의 reverse
agentcore_control.delete_oauth2_credential_provider(name=OAUTH_PROVIDER_NAME)
```

→ §9 teardown.sh 에서 자세히. 자원 leak 방지.

### 5-8. Phase 2 와의 transition diff (재확인)

```diff
# Phase 2 → Phase 3
- agents/monitor/shared/auth/cognito_token.py        (50 LoC 삭제)
- agents/monitor/shared/auth/__init__.py             (0 LoC 삭제)
- pyproject.toml: requests >= 2                      (의존 1개 제거)

+ AWS OAuth2CredentialProvider 자원 1개              (boto3 API)
+ deploy_runtime.py Step [3-b]                       (~15 LoC, OAuth provider create 호출)
+ IAM 권한 +1 (GetResourceOauth2Token)               (post-deploy attach)
```

→ **net 효과**: Code -50 LoC, AWS 자원 +1, IAM 권한 +1. 코드 단순화 + 보안 강화 + 매커니즘 명확화.

---

## 6. IAM Role + 권한 상세

Runtime IAM Execution Role 의 권한 boundary 를 명시한다. toolkit 이 `auto_create_execution_role=True` 로 default 권한을 부착한 Role 에, Phase 3 가 추가하는 권한 (post-deploy `iam.put_role_policy`) 의 항목별 근거를 기록.

### 6-1. Role 의 정체성

| 항목 | 값 |
|---|---|
| Role 이름 | `AmazonBedrockAgentCoreSDKRuntime-{region}-{hash}` (toolkit default) |
| Trust policy | `bedrock-agentcore.amazonaws.com` 가 `sts:AssumeRole` (Runtime 만 assume 가능) |
| 생성 주체 | `bedrock_agentcore_starter_toolkit.Runtime.configure(auto_create_execution_role=True)` |
| Phase 3 의 추가 변경 | `iam.put_role_policy(PolicyName="Phase3RuntimeExtras", ...)` 로 inline policy 1개 부착 |
| Phase 4+ 영향 | Phase 4 가 Incident Runtime 추가 시 **별 Role** (toolkit 이 agent_name 별 하나씩 생성). 공유 안 함 |

### 6-2. toolkit 이 자동 부여하는 default 권한 (Phase 3 가 미터치)

`Runtime.configure(auto_create_execution_role=True)` 가 만드는 Role 의 default permissions (A2A 샘플 `cloudformation/monitoring_agent.yaml:65-100` 의 자동 생성 Role 패턴 reference):

| Sid | Action | Resource | 용도 |
|---|---|---|---|
| ECRImageAccess | `ecr:BatchGetImage`, `ecr:GetDownloadUrlForLayer` | `arn:aws:ecr:{region}:{account}:repository/*` | Runtime 이 ECR image pull |
| ECRTokenAccess | `ecr:GetAuthorizationToken` | `*` | ECR token 발급 |
| LogsCreate | `logs:CreateLogGroup`, `logs:DescribeLogStreams`, `logs:DescribeLogGroups` | `arn:aws:logs:{region}:{account}:log-group:/aws/bedrock-agentcore/runtimes/*` | CW Log Group 생성 |
| LogsPut | `logs:CreateLogStream`, `logs:PutLogEvents` | `.../log-stream:*` | log 출력 |
| BedrockModel | `bedrock:InvokeModel`, `bedrock:InvokeModelWithResponseStream` | `arn:aws:bedrock:*::foundation-model/*` + `arn:aws:bedrock:{region}:{account}:*` | LLM 호출 (Strands 의 BedrockModel) |
| XRay | `xray:PutTraceSegments`, `xray:PutTelemetryRecords`, `xray:GetSamplingRules`, `xray:GetSamplingTargets` | `*` | OTEL distro (D7) 의 X-Ray 통합 |
| CloudWatchMetrics | `cloudwatch:PutMetricData` (with namespace condition `bedrock-agentcore`) | `*` | OTEL metric publish |

→ **default 7개 Sid**. Phase 3 가 이 권한을 변경하지 않음 (toolkit 약속 → Phase 3 PR 의 영향 범위 격리).

### 6-3. Phase 3 가 추가하는 권한 (`Phase3RuntimeExtras` inline policy)

`deploy_runtime.py` Step [3-a] 에서 `iam.put_role_policy(PolicyName="Phase3RuntimeExtras", ...)` 부착:

| Sid | Action | Resource | 추가 이유 |
|---|---|---|---|
| **GetResourceOauth2Token** | `bedrock-agentcore:GetResourceOauth2Token` | `*` (또는 OAuth provider ARN — scope down 가능 시) | §5-1 의 자동 token 발급 흐름 — Runtime SDK 가 outbound MCP 호출 시 내부적으로 호출 |
| **ReadCognitoClientSecret** | `secretsmanager:GetSecretValue` | `arn:aws:secretsmanager:{region}:{account}:secret:bedrock-agentcore-identity!*` | OAuth provider 가 `clientSecret` 을 secrets manager 에 보관 — Runtime 이 token 발급 시 read 필요 |

→ **신규 2개 Sid**. 기존 default + 신규 = 총 9개 statement.

### 6-4. 의도적 미포함 권한 (scope cuts)

Phase 3 의 IAM Role 에 의도적으로 **부착하지 않는** 권한:

| 미포함 권한 | 미포함 이유 |
|---|---|
| `bedrock-agentcore:ListMemories`, `RetrieveMemoryRecords`, `BatchCreateMemoryRecords`, ... (MemoryAccess) | **D6 — Memory 보류**. Phase 4+ 에서 cross-agent context 필요성 평가 후 부착 |
| `s3:GetObject` (Smithy model S3) | A2A 샘플은 Smithy model 을 S3 에 업로드 후 read. **Phase 2 가 Smithy 미사용** — `cloudwatch-wrapper` Lambda 가 boto3 직접 (Smithy 우회). Phase 3 도 미사용 |
| `ssm:GetParameter`, `kms:Decrypt` | dba `deploy.py:153-176` 가 부착하는 SSM 권한. **Phase 3 는 SSM 미사용** — Cognito secret 은 OAuth provider 가 secrets manager 로 처리 |
| `bedrock-agentcore-control:CreateGateway`, `UpdateGateway`, ... | Runtime 이 Gateway 자체를 변경하지 않음 — Gateway 호출만 함 (호출 권한은 OAuth token 으로 처리). Phase 2 deploy 권한과 별 |
| `bedrock-agentcore-control:CreateAgentRuntime`, `UpdateAgentRuntime` | Runtime 이 자기 자신을 변경하지 않음 — 그건 dev 환경 (deploy_runtime.py) 의 권한 |

→ **5개 권한 명시적 제외**. 워크샵 청중이 "왜 이 권한은 안 부착하는가" 추적 가능.

### 6-5. Phase 4+ 에서의 변화 예고

| Phase | 추가 가능성 |
|---|---|
| Phase 4 | Incident Runtime 의 별 Role — Phase 3 와 동일 패턴 (`Phase4IncidentRuntimeExtras`). A2A 미활성화 — Cognito Client B 권한 불필요 (Phase 6a 로 이월) |
| Phase 4+ Memory | `MemoryAccess` 권한 추가 (D6 보류 풀릴 시) |
| Phase 5 NL Policy | Policy enforcement 권한 — `bedrock-agentcore:GetAgentPolicy`, ... |
| Phase 6 Supervisor | Supervisor Runtime 의 Role — Sub-agent invoke 권한 (`bedrock-agentcore:InvokeAgentRuntime`) |

→ Phase 3 의 IAM Role 은 minimal — **Monitor 의 Gateway 호출만 가능**. Phase 별 자원이 자연 누적.

### 6-6. 검증 방법 (P3-A5 의 부분)

teardown 후 IAM Role 잔존 0 검증:

```bash
aws iam list-roles --query 'Roles[?starts_with(RoleName, `AmazonBedrockAgentCoreSDKRuntime`)].RoleName'
# → 출력: [] (Phase 3 teardown 후)
```

→ §9 teardown.sh 가 처리.

### 6-7. 미해결 사항 (구현 시 검증)

| 항목 | 검증 시점 |
|---|---|
| toolkit auto-created Role 의 정확한 default 권한 (위 표는 A2A reference + 추정) | `Runtime.configure()` 호출 후 `iam.get_role_policy` 로 확인 |
| OAuth provider 의 secrets manager namespace 정확성 (`bedrock-agentcore-identity!*` pattern) | 첫 token 발급 실패 시 `Resource: "*"` 로 우선 부착 후 scope down |
| IAM Role 이름의 hash suffix 가 deterministic 인가 (재배포 시 동일 vs 새 hash) | `auto_update_on_conflict=True` 시 동작 — toolkit 동작 검증 필요 |

→ §4-10 의 미해결 항목과 일관성. 구현 단계 검증.

---

## 7. Acceptance 기준 P3-A1 ~ A6

phase2.md §1 의 "P2-A1~A5 acceptance 기준" 패턴 따라 — Phase 3 PR 머지 전 모두 PASSED 되어야 함. 각 기준은 **재현 가능한 검증 절차** + **통과 조건** + **실패 시 디버그 가이드** 로 구성.

### 7-1. P3-A1 — `from .tools` import 0건 (P2-A1 회귀 없음)

**의의**: 시스템 목표 C2 (도구 외부화) 가 Phase 2 에서 충족됨 — Phase 3 의 transition 이 이를 깨지 않는지 회귀 검증.

**검증 절차**:
```bash
grep -rn "from agents.monitor.shared.tools" agents/monitor/runtime/ agents/monitor/shared/ agents/monitor/local/
# 단, agents/monitor/local/run_local_import.py (Phase 1 frozen baseline) 는 제외 — offline mock 의존 의도

# 또는 더 엄격하게:
grep -rn "from .tools" agents/monitor/runtime/agentcore_runtime.py agents/monitor/shared/agent.py agents/monitor/shared/mcp_client.py agents/monitor/local/run.py
```

**통과 조건**: 위 grep 출력 0줄 (Phase 1 baseline 인 `run_local_import.py` 제외).

**실패 시 디버그**: 만약 1줄 이상 출력 시 — `runtime/agentcore_runtime.py` 또는 `shared/agent.py` 에 우발적 도구 import 추가 → 회귀. Gateway 경로 우회한 상태 → 즉시 fix.

---

### 7-2. P3-A2 — `cognito_token.py` 부재 + `requests` 의존 제거

**의의**: Phase 2 의 transitional helper 통째 삭제 약속 (phase2.md §6-9) 이행 확인.

**검증 절차**:
```bash
# 1. 파일 부재
ls agents/monitor/shared/auth/cognito_token.py 2>&1   # → "No such file or directory"
ls agents/monitor/shared/auth/                         # → "No such file or directory" (폴더도 삭제)

# 2. requests 제거
grep -n "requests" pyproject.toml                      # → Phase 3 transitional 삭제됨, 0줄 출력
grep -rn "^import requests\|^from requests" agents/   # → 0줄 출력 (mcp_client.py 도 import 안 함)
```

**통과 조건**: 4개 grep/ls 모두 expected (파일 부재 + 의존 미사용).

**실패 시 디버그**:
- 파일 잔존 시 → `git rm -r agents/monitor/shared/auth/` 추가
- `requests` 잔존 시 → mcp_client.py 의 transition diff (§3-6) 미적용 또는 다른 모듈 사용 — grep 으로 추적

---

### 7-3. P3-A3 — C1 검증 (mode=past JSON 동일성, D8)

**의의**: 시스템 목표 C1 (로컬 == Runtime 응답) — Phase 3 의 핵심 deliverable.

**검증 절차**:
```bash
# 1. local 응답 capture (3회)
for i in 1 2 3; do
    uv run agents/monitor/local/run.py --mode past > /tmp/local_${i}.txt
done

# 2. Runtime 응답 capture (3회)
for i in 1 2 3; do
    uv run agents/monitor/runtime/invoke_runtime.py --mode past > /tmp/runtime_${i}.txt
done

# 3. C1 검증 (verify_c1.py 가 자동)
uv run agents/monitor/runtime/verify_c1.py
```

**`verify_c1.py` 의 4 assertion (D8)** — §8 에서 구현 detail:
- **A3.1**: `set(d["type"] for d in diagnoses)` 동일 (3가지 진단 유형 set match)
- **A3.2**: `set(d["alarm"] for d in diagnoses)` 동일 (alarm 이름 set match)
- **A3.3**: `set(real_alarms)` 동일
- **A3.4**: `|local.estimated_weekly_fire_reduction_pct - runtime.estimated_weekly_fire_reduction_pct| ≤ 10`

**통과 조건**: 4 assertion × 3 runs = **12 check 모두 PASS**.

**실패 시 디버그**:
- A3.1/A3.2 fail → 진단 우선순위 (rule_retirement > threshold_uplift > time_window_exclusion) 가 다르게 적용됨 → prompt drift 또는 mock 데이터 변경. `system_prompt_past.md` + `data/mock/phase1/alarm_history.py` 확인
- A3.3 fail → real_alarms 분류 차이 → MCP tool 응답이 두 환경에서 다름 (Gateway 경유 vs 직접 호출 — 둘 다 Gateway 라 안 됨) → `list_tools_sync` filter 가 정상인가 확인
- A3.4 fail → pct 계산이 LLM 의 자유 기술 — tolerance ±10 보다 분산 큼. tolerance 늘리거나 계산식을 prompt 에 명시

---

### 7-4. P3-A4 — Runtime invoke (live mode) → Phase 0 알람 분류 정확

**의의**: Runtime 환경에서 실제 라이브 데이터 (Phase 0 의 EC2 + alarms) 에 대한 분류 정확성 검증. P0-A2 의 Phase 3 재현.

**검증 절차**:
```bash
# 1. Phase 0 카오스 시작 (real alarm fire 유도)
bash infra/ec2-simulator/stop_instance.sh
sleep 60                                                # CloudWatch alarm fire 대기

# 2. Runtime invoke (live mode)
uv run agents/monitor/runtime/invoke_runtime.py --mode live > /tmp/live_response.txt

# 3. 응답에서 분류 결과 검증
python -c "
import json, re
with open('/tmp/live_response.txt') as f:
    text = f.read()
# JSON 블록 추출 (markdown ```json ... ``` 또는 raw)
match = re.search(r'\\{[\\s\\S]*\"real_alarms\"[\\s\\S]*\\}', text)
data = json.loads(match.group())
assert 'payment-ubuntu-status-check' in data['real_alarms'], 'real alarm 누락'
assert any(d['alarm'] == 'payment-ubuntu-noisy-cpu' for d in data['diagnoses']), 'noise alarm 진단 누락'
print('✅ P3-A4 PASS')
"

# 4. 카오스 복구
bash infra/ec2-simulator/start_instance.sh
```

**통과 조건**:
- `real_alarms` 에 `payment-${DEMO_USER}-status-check` 포함 (real 분류)
- `diagnoses` 에 `payment-${DEMO_USER}-noisy-cpu` 포함 (noise 분류 — threshold_uplift 또는 다른 유형)

**실패 시 디버그**:
- real 누락 → CW alarm fire 가 안 됐거나 (chaos 미적용 / SLO 시간 못 넘김), Runtime 의 도구 호출이 실패 (CW Logs 확인)
- noise 누락 → 진단 logic 회귀 (system_prompt_live.md drift) 또는 LLM 가 `noisy-cpu` 를 real 로 잘못 판정 — prompt 수정

---

### 7-5. P3-A5 — `teardown.sh` 한 번에 자원 잔존 0

**의의**: Phase 3 의 모든 신규 자원이 깨끗하게 삭제 가능 — 워크샵 후 비용 leak 0.

**검증 절차**:
```bash
# 1. teardown 실행
bash agents/monitor/runtime/teardown.sh

# 2. 자원 잔존 0 검증 (5종)
aws bedrock-agentcore-control list-agent-runtimes --region us-west-2 \
    --query "agentRuntimes[?contains(agentRuntimeName, 'aiops_demo_${DEMO_USER}_monitor')]"
# → []

aws bedrock-agentcore-control list-oauth2-credential-providers --region us-west-2 \
    --query "credentialProviders[?contains(name, 'aiops_demo_${DEMO_USER}_monitor_gateway_provider')]"
# → []

aws ecr describe-repositories --region us-west-2 \
    --query "repositories[?contains(repositoryName, 'bedrock-agentcore-aiops_demo_${DEMO_USER}_monitor')]"
# → []

aws iam list-roles \
    --query "Roles[?starts_with(RoleName, 'AmazonBedrockAgentCoreSDKRuntime')]"
# → [] (단, 다른 사용자 Role 잔존 시 false-positive — DEMO_USER 별 hash 검증 필요)

aws logs describe-log-groups --region us-west-2 --log-group-name-prefix "/aws/bedrock-agentcore/runtimes/aiops_demo_${DEMO_USER}_monitor"
# → 빈 logGroups
```

**통과 조건**: 5개 query 모두 빈 결과.

**Phase 2 자원 보호 (negative check)**: teardown 후 Phase 2 자원이 살아 있어야 함:
```bash
aws bedrock-agentcore-control list-gateways --region us-west-2 \
    --query "gateways[?contains(name, 'aiops-demo-${DEMO_USER}-gateway')]"
# → 1개 (Phase 2 Gateway 보존)

aws cloudformation describe-stacks --stack-name "aiops-demo-${DEMO_USER}-phase2-cognito" --region us-west-2
# → Stack 보존
```

**실패 시 디버그**:
- 자원 잔존 → teardown.sh 의 reverse 순서 오류 (예: OAuth provider 가 Runtime 의존이라 Runtime 먼저 삭제 필요) → §9 의 순서 재확인
- Phase 2 자원 삭제 → teardown.sh 가 Phase 2 자원을 잘못 건드림 → 즉시 stop, Phase 2 redeploy

---

### 7-6. P3-A6 — Single source of truth 검증 (`create_agent()` 양쪽 호출)

**의의**: 시스템 목표 C1 의 또 다른 측면 — local 과 Runtime 이 **동일 코드** 를 사용 (transition 의 의미).

**검증 절차**:

**(a) static check** — `create_agent()` 호출 위치 검증:
```bash
grep -rn "from agents.monitor.shared.agent import create_agent" agents/monitor/
# → 출력 2줄:
#   agents/monitor/local/run.py:N:from agents.monitor.shared.agent import create_agent
#   agents/monitor/runtime/agentcore_runtime.py:N:from agents.monitor.shared.agent import create_agent
```

**(b) signature check** — 두 곳 모두 동일 시그니처로 호출:
```bash
grep -A 1 "create_agent(" agents/monitor/local/run.py | head -5
grep -A 1 "create_agent(" agents/monitor/runtime/agentcore_runtime.py | head -5
# → 두 출력 모두: create_agent(tools, prompt_filename) 형태
```

**(c) local path 동작 검증** (local 도 Phase 3 후 동작 — §3-7 의 placeholder 결정):

local 환경에서 `mcp_client.py` 의 token 라인 제거 후에도 동작해야 함. **§3-7 의 (a-2) 채택** — boto3 명시 호출 helper:

```python
# agents/monitor/shared/auth_local.py (신규, ~15 LoC, local 전용)
"""Local 환경 전용 — boto3 로 OAuth provider 명시 호출. Runtime 환경에서는 사용 안 됨."""
import os
import boto3

def get_local_gateway_token() -> str:
    """workload identity 없이 IAM 자격증명으로 token 획득. Local 만."""
    agentcore = boto3.client("bedrock-agentcore", region_name=os.environ["AWS_REGION"])
    response = agentcore.get_resource_oauth2_token(
        # workloadIdentityToken 생략 — boto3 가 IAM 자격증명으로 대체
        resourceCredentialProviderName=os.environ["OAUTH_PROVIDER_NAME"],
        scopes=["gateway/invoke"],
        oauth2Flow="M2M",
    )
    return response["accessToken"]
```

→ `local/run.py` 가 이 helper 를 import 해서 `streamablehttp_client(headers={"Authorization": f"Bearer {get_local_gateway_token()}"})` 로 주입. **단**, 이는 mcp_client.py 안에서 환경 분기로 처리해야 깔끔.

**§7-6 결정 — local token 처리 방식 (3-7 placeholder 확정)**:

후보 (a-2-i) — `mcp_client.py` 안에 환경 감지 분기:
```python
def create_mcp_client() -> MCPClient:
    gateway_url = os.environ["GATEWAY_URL"]
    def _transport():
        kwargs = {"url": gateway_url, "timeout": timedelta(seconds=120)}
        # Runtime 환경에서는 SDK 가 자동 inject, local 에서는 명시
        if not _is_runtime_env():
            from agents.monitor.shared.auth_local import get_local_gateway_token
            kwargs["headers"] = {"Authorization": f"Bearer {get_local_gateway_token()}"}
        return streamablehttp_client(**kwargs)
    return MCPClient(_transport)

def _is_runtime_env() -> bool:
    return os.environ.get("BEDROCK_AGENTCORE_RUNTIME") == "true" or os.environ.get("AWS_EXECUTION_ENV", "").startswith("AWS_BedrockAgentCore")
```

후보 (a-2-ii) — local/run.py 가 token 을 직접 주입 (mcp_client.py 는 unchanged):
```python
# local/run.py
from agents.monitor.shared.auth_local import get_local_gateway_token
os.environ["MCP_AUTH_TOKEN"] = get_local_gateway_token()    # mcp_client 가 이 env 읽음
```

→ **추천 (a-2-i)** — 분기를 mcp_client.py 안에 capsule. local/run.py 는 token 의 존재를 모름. Runtime 코드 (agentcore_runtime.py) 도 미변경.

**§2 인벤토리 추가 보정** (§7-6 결정 결과):
- 신규 코드: 10개 → **11개** (`shared/auth_local.py` 추가, ~15 LoC)
- 변경 코드: 3개 → **4개** (`mcp_client.py` 의 `_is_runtime_env` 분기 추가 — §3-6 의 단순 diff 가 분기 포함으로 확장)

**통과 조건**:
- (a) static check: `create_agent` import 2곳 정확
- (b) signature check: 동일 인자 형태
- (c) local 동작: `uv run agents/monitor/local/run.py --mode past` 가 정상 응답 출력 (P3-A3 의 local capture 가 이 단계의 sub-step)

**실패 시 디버그**: local 동작 실패 시 — `auth_local.py` 의 boto3 자격증명 문제 (`aws configure` 미설정), 또는 OAuth provider 가 아직 안 만들어짐 (`deploy_runtime.py` 미실행).

---

### 7-7. acceptance 통과 절차 (PR 머지 전 체크리스트)

```
□ P3-A1 grep 0줄 (도구 import 회귀 없음)
□ P3-A2 cognito_token.py 부재 + requests 미사용 (4 grep/ls)
□ P3-A3 verify_c1.py 4 assertion × 3 runs = 12 PASS
□ P3-A4 live mode 분류 정확 (real + noise 둘 다 적정)
□ P3-A5 teardown 후 Phase 3 자원 5종 잔존 0 + Phase 2 자원 보호 검증
□ P3-A6 create_agent 호출 2곳 + local mode=past 정상 동작
```

→ 모두 PASS 시 PR ready. phase2.md 의 P2-A1~A5 통과 (2026-05-05) 이후 Phase 3 의 동등 깊이 검증.

### 7-8. acceptance 외 — Phase 3 PR 의 추가 sanity check (optional)

| 항목 | 검증 방법 |
|---|---|
| Runtime cold start 시간 ≤ 30s | invoke_runtime.py 첫 실행 timing |
| OTEL trace 가 CloudWatch GenAI Observability 에 표시 | CW 콘솔 → AgentCore → "aiops_demo_${DEMO_USER}_monitor" 검색 |
| `requests` 의존 진짜 제거 — `uv tree` 출력에 부재 | `uv tree | grep requests` → 0줄 (직접 의존), transitive 만 표시 |
| Phase 1 baseline (`run_local_import.py`) 가 unchanged | `git diff main..HEAD agents/monitor/local/run_local_import.py` → 0 |

→ 위 4개는 acceptance 가 아닌 sanity check (실패해도 PR block 안 됨). 워크샵 demo 시 visual 확인.

---

## 8. `invoke_runtime.py` + `verify_c1.py` 상세

P3-A3/A4 검증의 두 도구. dba `example_invoke.py` (단일 호출 + SSE 파싱) + JSON schema diff (4 assertion × 3 runs) 의 직접 차용.

### 8-1. `invoke_runtime.py` — 단일 호출 + SSE 파싱

**역할**: `boto3 bedrock-agentcore.invoke_agent_runtime` 한 번 호출 → SSE stream 을 stdout 출력 → P3-A4 (live mode 분류 검증) + P3-A3 의 capture 단계.

**위치**: `agents/monitor/runtime/invoke_runtime.py`

**분량 예상**: ~80 LoC

**사용법**:
```bash
uv run agents/monitor/runtime/invoke_runtime.py --mode past
uv run agents/monitor/runtime/invoke_runtime.py --mode live
uv run agents/monitor/runtime/invoke_runtime.py --mode past --query "특정 알람만 분석해"
```

**구현 (~80 LoC)**:

```python
"""invoke_runtime.py — Phase 3 Runtime 단일 호출 + SSE 파싱 (dba example_invoke.py 차용)."""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
import boto3
from botocore.config import Config

SCRIPT_DIR = Path(__file__).resolve().parent
load_dotenv(SCRIPT_DIR / ".env", override=True)

REGION = os.getenv("AWS_REGION", "us-west-2")
RUNTIME_ARN = os.getenv("RUNTIME_ARN")

GREEN, YELLOW, BLUE, RED, DIM, NC = "\033[0;32m", "\033[1;33m", "\033[0;34m", "\033[0;31m", "\033[2m", "\033[0m"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Phase 3 Runtime invoke (P3-A3/A4 검증).")
    p.add_argument("--mode", choices=["past", "live"], default="live")
    p.add_argument("--query", default=None, help="(생략 시 mode 별 default template)")
    return p.parse_args()


def parse_sse_event(line_bytes: bytes) -> dict | None:
    if not line_bytes:
        return None
    try:
        text = line_bytes.decode("utf-8").strip()
        if text.startswith("data: "):
            text = text[6:]
        return json.loads(text) if text else None
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def main() -> None:
    args = parse_args()
    if not RUNTIME_ARN:
        print(f"{RED}❌ RUNTIME_ARN 가 .env 에 없음 — deploy_runtime.py 먼저 실행{NC}")
        sys.exit(1)

    print(f"{BLUE}{'=' * 60}{NC}")
    print(f"  Phase 3 Runtime invoke — mode={args.mode}")
    print(f"  Runtime ARN: {RUNTIME_ARN}")
    print(f"{BLUE}{'=' * 60}{NC}\n")

    config = Config(connect_timeout=300, read_timeout=600, retries={"max_attempts": 0})
    client = boto3.client("bedrock-agentcore", region_name=REGION, config=config)

    payload = {"mode": args.mode}
    if args.query:
        payload["query"] = args.query

    start = datetime.now()
    response = client.invoke_agent_runtime(
        agentRuntimeArn=RUNTIME_ARN,
        qualifier="DEFAULT",
        payload=json.dumps(payload),
    )

    content_type = response.get("contentType", "")
    if "text/event-stream" in content_type:
        usage_summary = None
        for line in response["response"].iter_lines(chunk_size=1):
            event = parse_sse_event(line)
            if event is None:
                continue
            if event.get("type") == "agent_text_stream":
                print(event.get("text", ""), end="", flush=True)
            elif event.get("type") == "token_usage":
                usage_summary = event.get("usage", {})
            elif event.get("type") == "workflow_complete":
                pass
        if usage_summary:
            print()
            print(
                f"{DIM}📊 Tokens — Total: {usage_summary.get('totalTokens', 0):,} | "
                f"Input: {usage_summary.get('inputTokens', 0):,} | "
                f"Output: {usage_summary.get('outputTokens', 0):,} | "
                f"Cache R/W: {usage_summary.get('cacheReadInputTokens', 0):,}/"
                f"{usage_summary.get('cacheWriteInputTokens', 0):,}{NC}"
            )
    else:
        # 비스트리밍 응답 — 단일 JSON
        body = response["response"].read().decode("utf-8")
        print(body)

    elapsed = (datetime.now() - start).total_seconds()
    print(f"\n{GREEN}✅ 완료 ({elapsed:.1f}초){NC}\n")


if __name__ == "__main__":
    main()
```

**dba 와의 차이**:
- payload: dba 는 `{prompt, dev_name}` — 우리는 `{mode, query}` (D4)
- yield event 처리: dba 는 `agent_text_stream` 만 출력 — 우리는 token_usage 도 stdout summary 추가 (Phase 2 local/run.py 의 `_print_token_usage` 재현)
- Argparse: dba 는 `--dev_name --prompt` — 우리는 `--mode --query`

→ ~80 LoC. P3-A3/A4 의 capture 단계 그대로 사용.

### 8-2. `verify_c1.py` — JSON schema diff 4 assertion × 3 runs

**역할**: P3-A3 의 자동 검증 — local 응답 vs Runtime 응답을 schema-level 로 비교, 12 check (4 × 3) PASS 시 P3-A3 PASSED.

**위치**: `agents/monitor/runtime/verify_c1.py`

**분량 예상**: ~80 LoC

**현재 상태 (2026-05-07)**: 자동 실행 **skip**. 이유 — code-level C1 은 이미 충족 (`create_agent()` 호출처가 `local/run.py` + `runtime/agentcore_runtime.py` 두 곳뿐이고 동일 단일 함수 호출, dba pattern 보장). `invoke_runtime.py --mode past` + `--mode live` 양쪽 수동 검증 완료. 자동 verify 는 `local/run.py` PYTHONPATH + `OAUTH_PROVIDER_NAME` env 로딩 fix 후 추후 실행 권장.

**사용법**:
```bash
uv run agents/monitor/runtime/verify_c1.py
# → 자동: local 3회 + Runtime 3회 호출 + 12 check 결과 출력
```

**구현 (~80 LoC)**:

```python
"""verify_c1.py — Phase 3 P3-A3 검증 (JSON schema diff 4 assertion × 3 runs)."""
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

GREEN, RED, YELLOW, NC = "\033[0;32m", "\033[0;31m", "\033[1;33m", "\033[0m"

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[2]
PCT_TOLERANCE = 10
N_RUNS = 3


def extract_json(text: str) -> dict:
    """LLM 출력 (markdown 또는 raw) 에서 final JSON 블록 추출.

    우선순위: ```json ... ``` 블록 → ```...``` 블록 → real_alarms 키 포함 raw JSON
    """
    fence = re.search(r"```json\s*(\{[\s\S]*?\})\s*```", text)
    if fence:
        return json.loads(fence.group(1))
    fence = re.search(r"```\s*(\{[\s\S]*?\})\s*```", text)
    if fence:
        return json.loads(fence.group(1))
    raw = re.search(r'\{[\s\S]*"real_alarms"[\s\S]*\}', text)
    if raw:
        return json.loads(raw.group(0))
    raise ValueError(f"JSON 블록 추출 실패. 출력 일부: {text[:200]!r}")


def run_command(cmd: list[str]) -> str:
    """external 명령 실행 + stdout 반환."""
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=PROJECT_ROOT, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f"명령 실패: {' '.join(cmd)}\nstderr: {result.stderr}")
    return result.stdout


def assert_schema_match(local: dict, runtime: dict, run_idx: int) -> list[bool]:
    """4 assertion 실행. PASS 리스트 반환."""
    results = []

    # A3.1: 진단 유형 set 동일
    local_types = {d["type"] for d in local.get("diagnoses", [])}
    runtime_types = {d["type"] for d in runtime.get("diagnoses", [])}
    a31 = local_types == runtime_types
    print(f"  [run {run_idx}] A3.1 (diagnoses.type set):       {GREEN if a31 else RED}{a31}{NC}  local={local_types} / runtime={runtime_types}")
    results.append(a31)

    # A3.2: 알람 이름 set 동일
    local_alarms = {d["alarm"] for d in local.get("diagnoses", [])}
    runtime_alarms = {d["alarm"] for d in runtime.get("diagnoses", [])}
    a32 = local_alarms == runtime_alarms
    print(f"  [run {run_idx}] A3.2 (diagnoses.alarm set):      {GREEN if a32 else RED}{a32}{NC}")
    results.append(a32)

    # A3.3: real_alarms set 동일
    local_real = set(local.get("real_alarms", []))
    runtime_real = set(runtime.get("real_alarms", []))
    a33 = local_real == runtime_real
    print(f"  [run {run_idx}] A3.3 (real_alarms set):          {GREEN if a33 else RED}{a33}{NC}")
    results.append(a33)

    # A3.4: pct ±10
    local_pct = local.get("estimated_weekly_fire_reduction_pct", 0)
    runtime_pct = runtime.get("estimated_weekly_fire_reduction_pct", 0)
    a34 = abs(local_pct - runtime_pct) <= PCT_TOLERANCE
    print(f"  [run {run_idx}] A3.4 (pct ±{PCT_TOLERANCE}):                     {GREEN if a34 else RED}{a34}{NC}  local={local_pct} / runtime={runtime_pct}")
    results.append(a34)

    return results


def main() -> None:
    print(f"{YELLOW}=== Phase 3 P3-A3 검증 — JSON schema diff 4 assertion × {N_RUNS} runs ==={NC}\n")

    all_results = []
    for i in range(1, N_RUNS + 1):
        print(f"{YELLOW}[run {i}/{N_RUNS}] capture local + runtime mode=past...{NC}")
        local_out = run_command(["uv", "run", "agents/monitor/local/run.py", "--mode", "past"])
        runtime_out = run_command(["uv", "run", "agents/monitor/runtime/invoke_runtime.py", "--mode", "past"])
        local_json = extract_json(local_out)
        runtime_json = extract_json(runtime_out)
        all_results.extend(assert_schema_match(local_json, runtime_json, i))
        print()

    n_pass = sum(all_results)
    n_total = len(all_results)
    if n_pass == n_total:
        print(f"{GREEN}=== ✅ P3-A3 PASS ({n_pass}/{n_total}) ==={NC}")
        sys.exit(0)
    else:
        print(f"{RED}=== ❌ P3-A3 FAIL ({n_pass}/{n_total}) ==={NC}")
        sys.exit(1)


if __name__ == "__main__":
    main()
```

### 8-3. `extract_json` 의 fallback 우선순위

LLM 출력 형식이 prompt 와 모델에 따라 다양 — 3단 fallback:

| 우선순위 | 패턴 | 매칭 |
|---|---|---|
| 1 | ` ```json {...} ``` ` (markdown fence with explicit lang) | 가장 흔함 |
| 2 | ` ``` {...} ``` ` (markdown fence without lang) | LLM 가 lang 생략 시 |
| 3 | `{...real_alarms...}` (raw JSON, real_alarms 키 매칭) | 메타 fence 없는 raw 출력 |

→ 3개 모두 실패 시 `ValueError` — debug 시 `text[:200]` 출력으로 prompt 재조정.

### 8-4. 12 check 의 의미 분포

| 측면 | check 수 |
|---|---|
| 진단 logic 동일 (rule_retirement 우선순위 등) | 6 (A3.1 + A3.2 × 3 runs) |
| 분류 logic 동일 (real vs noise) | 3 (A3.3 × 3 runs) |
| 정량 metric 동일 (pct fuzzy) | 3 (A3.4 × 3 runs) |

→ 진단 logic (50%) + 분류 logic (25%) + 정량 (25%). LLM 의 비결정성이 약한 영역에 가중 (진단/분류는 결정적, pct 만 fuzzy).

### 8-5. tolerance 조정 정책

`PCT_TOLERANCE = 10` 의 근거:
- LLM 응답의 pct 자유 기술이 60-80 범위 (mock 데이터 기준 — 24 events 중 noise 추정 비율)
- 다른 모델 / 다른 prompt 변형 시 ±15 까지 발생 가능 (조사 필요)
- 만약 P3-A3 가 A3.4 만 fail 하고 A3.1/A3.2/A3.3 PASS → tolerance 를 15 로 조정 OR prompt 에 pct 계산식 명시 (다음 PR)

→ tolerance 조정은 design decision (D8) 의 micro-tuning. 첫 실행 후 결정.

### 8-6. CW Logs trail 검증 (optional, P3-A3 에 포함 안 됨)

P3-A3 PASSED 후 추가 sanity:
```bash
# Runtime 호출 시 CW Logs 에 stream 이 생성되는지
aws logs describe-log-streams --region us-west-2 \
    --log-group-name "/aws/bedrock-agentcore/runtimes/aiops_demo_${DEMO_USER}_monitor" \
    --order-by LastEventTime --descending --max-items 1
```

→ §7-8 의 sanity check 와 일관 — acceptance 가 아닌 visual 확인.

---

## 9. `teardown.sh` 상세 (P3-A5)

Phase 3 의 모든 신규 자원을 reverse 순서로 삭제. P3-A5 (자원 잔존 0 + Phase 2 자원 보호) 를 충족시키는 단일 스크립트.

### 9-1. 파일 위치 + 호출

- 위치: `agents/monitor/runtime/teardown.sh`
- 호출: `bash agents/monitor/runtime/teardown.sh`
- 분량 예상: ~80 LoC

### 9-2. 삭제 순서 (의존 관계 reverse)

생성 순서 (Phase 3 deploy_runtime.py): IAM Role 자동 → ECR Repo 자동 → docker push → Runtime create → IAM put_role_policy → OAuth provider create

→ **삭제 순서 (의존 reverse)**:

```
[1/6] Runtime 삭제 (invoke 차단)
[2/6] Runtime DELETED 대기 (~10초)
[3/6] OAuth provider 삭제
[4/6] ECR images 삭제 + Repo 삭제
[5/6] IAM inline policy detach + Role 삭제
[6/6] CW Log Group 삭제
```

**왜 Runtime 먼저, OAuth provider 나중?**
- OAuth provider 가 사용 중인 Runtime 의 token 발급 path 를 끊으면 invoke 가 401 (단, teardown 시점은 invoke 없음 → 무관)
- Runtime 이 활성 상태에서 OAuth provider 삭제 시 ConflictException 가능성 → Runtime 먼저 안전
- 워크샵 청중에게는 "사용 중인 자원 (Runtime) 먼저 stop 후 의존 자원 (OAuth) cleanup" 의 일반 원칙 시연

### 9-3. 구현 (~80 LoC, bash)

```bash
#!/usr/bin/env bash
# teardown.sh — Phase 3 자원 reverse 순서 삭제 (P3-A5).
# Phase 2 (Cognito stack, Gateway, Lambda) 는 미터치.
set -euo pipefail

REGION="${AWS_REGION:-us-west-2}"
DEMO_USER="${DEMO_USER:?DEMO_USER 미설정}"
AGENT_NAME="aiops_demo_${DEMO_USER}_monitor"
OAUTH_PROVIDER_NAME="${AGENT_NAME}_gateway_provider"
ECR_REPO="bedrock-agentcore-${AGENT_NAME}"
LOG_GROUP="/aws/bedrock-agentcore/runtimes/${AGENT_NAME}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

echo -e "${YELLOW}=== Phase 3 teardown — ${AGENT_NAME} ===${NC}"

# .env 에서 RUNTIME_ID 로딩
if [ -f "${SCRIPT_DIR}/.env" ]; then
    set -a; source "${SCRIPT_DIR}/.env"; set +a
fi

# ── [1/6] Runtime 삭제 ─────────────────────────────────────────
echo -e "${YELLOW}[1/6] Runtime 삭제${NC}"
RUNTIME_ID="${RUNTIME_ID:-$(aws bedrock-agentcore-control list-agent-runtimes --region "$REGION" \
    --query "agentRuntimes[?agentRuntimeName=='${AGENT_NAME}'].agentRuntimeId" --output text)}"
if [ -n "$RUNTIME_ID" ] && [ "$RUNTIME_ID" != "None" ]; then
    aws bedrock-agentcore-control delete-agent-runtime --region "$REGION" --agent-runtime-id "$RUNTIME_ID" || true
    echo -e "  ${GREEN}✓ Runtime ${RUNTIME_ID} 삭제 요청${NC}"
else
    echo -e "  (Runtime 없음 — skip)"
fi

# ── [2/6] Runtime DELETED 대기 ─────────────────────────────────
echo -e "${YELLOW}[2/6] Runtime DELETED 대기 (max 60s)${NC}"
for i in $(seq 1 12); do
    STATUS=$(aws bedrock-agentcore-control get-agent-runtime --region "$REGION" \
        --agent-runtime-id "$RUNTIME_ID" --query 'status' --output text 2>/dev/null || echo "NOT_FOUND")
    if [ "$STATUS" = "NOT_FOUND" ] || [ "$STATUS" = "DELETED" ]; then
        echo -e "  ${GREEN}✓ Runtime ${STATUS}${NC}"
        break
    fi
    echo -e "  [${i}/12] ${STATUS}"
    sleep 5
done

# ── [3/6] OAuth2CredentialProvider 삭제 ────────────────────────
echo -e "${YELLOW}[3/6] OAuth2CredentialProvider 삭제${NC}"
aws bedrock-agentcore-control delete-oauth2-credential-provider \
    --region "$REGION" --name "$OAUTH_PROVIDER_NAME" 2>/dev/null \
    && echo -e "  ${GREEN}✓ ${OAUTH_PROVIDER_NAME} 삭제${NC}" \
    || echo -e "  (provider 없음 — skip)"

# ── [4/6] ECR images + Repo 삭제 ───────────────────────────────
echo -e "${YELLOW}[4/6] ECR Repository 삭제${NC}"
aws ecr describe-repositories --region "$REGION" --repository-names "$ECR_REPO" >/dev/null 2>&1 && {
    aws ecr delete-repository --region "$REGION" --repository-name "$ECR_REPO" --force \
        && echo -e "  ${GREEN}✓ ${ECR_REPO} (images + repo) 삭제${NC}"
} || echo -e "  (ECR repo 없음 — skip)"

# ── [5/6] IAM Role 삭제 (inline policy 부터 detach) ────────────
echo -e "${YELLOW}[5/6] IAM Role 삭제${NC}"
ROLE_ARN="${ROLE_ARN:-$(aws bedrock-agentcore-control get-agent-runtime --region "$REGION" \
    --agent-runtime-id "$RUNTIME_ID" --query 'roleArn' --output text 2>/dev/null || echo '')}"
ROLE_NAME="${ROLE_ARN##*/}"
if [ -n "$ROLE_NAME" ] && aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
    for POLICY in $(aws iam list-role-policies --role-name "$ROLE_NAME" --query 'PolicyNames' --output text); do
        aws iam delete-role-policy --role-name "$ROLE_NAME" --policy-name "$POLICY"
        echo -e "  detached inline: $POLICY"
    done
    for POLICY_ARN in $(aws iam list-attached-role-policies --role-name "$ROLE_NAME" --query 'AttachedPolicies[].PolicyArn' --output text); do
        aws iam detach-role-policy --role-name "$ROLE_NAME" --policy-arn "$POLICY_ARN"
        echo -e "  detached managed: $POLICY_ARN"
    done
    aws iam delete-role --role-name "$ROLE_NAME" \
        && echo -e "  ${GREEN}✓ Role ${ROLE_NAME} 삭제${NC}"
else
    echo -e "  (Role 없음 — skip)"
fi

# ── [6/6] CW Log Group 삭제 ────────────────────────────────────
echo -e "${YELLOW}[6/6] CW Log Group 삭제${NC}"
aws logs delete-log-group --region "$REGION" --log-group-name "$LOG_GROUP" 2>/dev/null \
    && echo -e "  ${GREEN}✓ ${LOG_GROUP} 삭제${NC}" \
    || echo -e "  (Log Group 없음 — skip)"

# ── .env cleanup ───────────────────────────────────────────────
if [ -f "${SCRIPT_DIR}/.env" ]; then
    sed -i.bak '/^RUNTIME_ARN=/d; /^RUNTIME_ID=/d; /^RUNTIME_NAME=/d; /^OAUTH_PROVIDER_NAME=/d; /^# Phase 3 Runtime/d' "${SCRIPT_DIR}/.env"
    rm -f "${SCRIPT_DIR}/.env.bak"
    echo -e "  ${GREEN}✓ .env 의 Phase 3 entry cleanup${NC}"
fi

# ── Phase 2 자원 보호 검증 (negative check) ─────────────────────
echo -e "${YELLOW}[verify] Phase 2 자원 보존 검증${NC}"
GATEWAY_COUNT=$(aws bedrock-agentcore-control list-gateways --region "$REGION" \
    --query "length(gateways[?contains(name, 'aiops-demo-${DEMO_USER}-gateway')])" --output text 2>/dev/null || echo "0")
[ "$GATEWAY_COUNT" -ge 1 ] && echo -e "  ${GREEN}✓ Phase 2 Gateway 보존${NC}" || echo -e "  ${RED}❌ Phase 2 Gateway 삭제됨 — Phase 2 redeploy 필요${NC}"
aws cloudformation describe-stacks --stack-name "aiops-demo-${DEMO_USER}-phase2-cognito" --region "$REGION" >/dev/null 2>&1 \
    && echo -e "  ${GREEN}✓ Phase 2 Cognito stack 보존${NC}" \
    || echo -e "  ${RED}❌ Phase 2 Cognito stack 삭제됨${NC}"

echo -e "${GREEN}=== ✅ Phase 3 teardown 완료 ===${NC}"
```

### 9-4. idempotency 보호

각 step 의 실패는 다음 step 를 막지 않음 — `|| true` / `|| echo skip` 패턴.

이유:
- 부분 실패 (예: Step [3] OAuth provider 가 이미 삭제된 상태) 시 다음 step 진행 가능 → 두 번째 실행 시 깨끗하게 cleanup
- 워크샵 재시도 시 "Phase 3 어디까지 cleanup 됐는지 모르겠음" 상황 처리 — 다시 실행하면 OK

### 9-5. Phase 2 자원 보호 검증 (negative check)

teardown.sh 마지막에 Phase 2 자원 살아있음을 검증 (위 9-3 코드의 `[verify]` 단계). 워크샵 사용자가 별 명령어 외울 필요 없음 — teardown.sh 한 번 실행으로 P3-A5 의 negative check 자동.

### 9-6. 부분 자원만 cleanup 옵션 (optional)

워크샵 시연 도중 "Runtime 만 새 image 로 redeploy 하고 싶다" 시나리오 — `Runtime.launch(auto_update_on_conflict=True)` 가 자동 처리해서 teardown 불필요. 따라서 teardown.sh 는 **all-or-nothing** (전체 cleanup 만).

만약 부분 cleanup 필요 시 → CLI 직접 (예: `aws ecr batch-delete-image ...`).

### 9-7. 실행 시간

| Step | 예상 시간 |
|---|---|
| [1] Runtime delete 요청 | ~1초 |
| [2] DELETED 대기 | ~10-30초 (실제 컨테이너 stop) |
| [3] OAuth provider delete | ~1초 |
| [4] ECR repo (images 포함) delete | ~5-10초 |
| [5] IAM Role delete (inline + managed detach) | ~3-5초 |
| [6] Log Group delete | ~1초 |
| **합계** | **~20-50초** (Phase 2 의 ~30-60초 teardown 과 비슷) |

→ 워크샵 마무리 시 1분 미만 — 비용 leak 0 보장.

---

## 10. Transition diff (Phase 2 → Phase 3, line-level)

phase2.md §6-9 의 ~50줄 삭제 예고를 expand. Phase 3 PR 의 모든 line-level 변경을 명시 — workshop 청중이 git diff 로 line-by-line 학습 가능.

### 10-1. PR diff 통계 요약

| 분류 | 수 | 분량 변화 |
|---|---|---|
| 신규 파일 (코드) | 11 | +485 LoC (`agents/monitor/runtime/` 9개 + `shared/modes.py` + `shared/auth_local.py`) |
| 변경 파일 | 4 | net +20 LoC (mcp_client.py 분기 추가 / local/run.py import / pyproject.toml / .gitignore) |
| 삭제 파일 (폴더 통째) | 2 | -50 LoC (`shared/auth/cognito_token.py`, `shared/auth/__init__.py`) |
| **총 net** | — | **+455 LoC, +AWS 자원 5개** |

→ §2-9 의 "AWS +5 / 코드 +9 -2" 보정 후 — 실제 PR diff 는 +11/-2.

### 10-2. 신규 파일 11개 (전부 신규 작성)

```
agents/monitor/runtime/agentcore_runtime.py    # ~50 LoC — D4 entrypoint (§3)
agents/monitor/runtime/Dockerfile              # ~20 LoC — D7 OTEL (dba 차용)
agents/monitor/runtime/deploy_runtime.py       # ~150 LoC — D1 5단계 (§4)
agents/monitor/runtime/invoke_runtime.py       # ~80 LoC — P3-A3/A4 capture (§8-1)
agents/monitor/runtime/verify_c1.py            # ~80 LoC — D8 4 assertion × 3 runs (§8-2)
agents/monitor/runtime/teardown.sh             # ~80 LoC — P3-A5 cleanup (§9)
agents/monitor/runtime/requirements.txt        # ~10 lines — uv export
agents/monitor/runtime/.dockerignore           # ~5 lines — build context exclusion
agents/monitor/runtime/README.md               # ~40 LoC — workshop 절차 안내
agents/monitor/shared/modes.py                 # ~5 LoC — MODE_CONFIG 분리 (§3-2)
agents/monitor/shared/auth_local.py            # ~15 LoC — local 전용 boto3 token (§7-6)
```

### 10-3. 변경 파일 4개 — line-level diff

#### 10-3-a. `agents/monitor/shared/mcp_client.py`

```diff
 # agents/monitor/shared/mcp_client.py
-from agents.monitor.shared.auth.cognito_token import get_gateway_access_token
+import os

 def create_mcp_client() -> MCPClient:
     gateway_url = os.environ["GATEWAY_URL"]
     def _transport():
-        token = get_gateway_access_token()
-        return streamablehttp_client(
-            url=gateway_url,
-            headers={"Authorization": f"Bearer {token}"},
-            timeout=timedelta(seconds=120),
-        )
+        kwargs = {"url": gateway_url, "timeout": timedelta(seconds=120)}
+        # Runtime 환경에서는 SDK 자동 inject, local 에서는 boto3 명시 호출
+        if not _is_runtime_env():
+            from agents.monitor.shared.auth_local import get_local_gateway_token
+            kwargs["headers"] = {"Authorization": f"Bearer {get_local_gateway_token()}"}
+        return streamablehttp_client(**kwargs)
     return MCPClient(_transport)
+
+
+def _is_runtime_env() -> bool:
+    """Runtime 컨테이너 안인지 감지. local 에서는 False → 명시 token 주입."""
+    return (
+        os.environ.get("BEDROCK_AGENTCORE_RUNTIME") == "true"
+        or os.environ.get("AWS_EXECUTION_ENV", "").startswith("AWS_BedrockAgentCore")
+    )
```

→ -8/+13 줄. token 라인 제거 + 환경 감지 분기 추가 (§7-6 의 (a-2-i)).

#### 10-3-b. `agents/monitor/local/run.py`

```diff
 # agents/monitor/local/run.py
-MODE_CONFIG = {
-    "past": ("history-mock___", "system_prompt_past.md"),
-    "live": ("cloudwatch-wrapper___", "system_prompt_live.md"),
-}
+from agents.monitor.shared.modes import MODE_CONFIG
```

→ -4/+1 줄. inline dict → 공유 모듈 import (§3-2 의 (b)).

#### 10-3-c. `pyproject.toml`

```diff
 [project]
 dependencies = [
     "strands-agents",
     "bedrock-agentcore",
-    "requests >= 2",                               # Phase 2 transitional
     "python-dotenv",
     ...
 ]

+[tool.uv.dev-dependencies]
+# Phase 3 — workshop 사용자 환경 의존
+bedrock_agentcore_starter_toolkit = ">=0.1"
```

→ -1/+3 줄. `requests` 제거 + dev dependency 그룹 추가.

#### 10-3-d. `.gitignore`

```diff
 # Existing entries...
+
+# Phase 3 build context (deploy_runtime.py step [0] 산출)
+agents/monitor/runtime/shared/
+agents/monitor/runtime/.env
+agents/monitor/runtime/.bedrock_agentcore.yaml
+agents/monitor/runtime/Dockerfile
```

→ +5 줄. `.env` 는 이미 Phase 0 부터 등록됐을 가능성 — 검증 필요. `.bedrock_agentcore.yaml` 는 toolkit 이 자동 생성하는 config 파일. `Dockerfile` 도 toolkit auto-generate 영향 시 등록.

→ **§4-10 의 "toolkit Dockerfile auto-generation 우선순위" 미해결 항목** — 우리가 Dockerfile 작성 후 toolkit 가 덮어쓰는지 확인 필요. 만약 우리 Dockerfile 살아남으면 .gitignore 에서 빼야 함.

### 10-4. 삭제 파일 2개 (폴더 통째)

```
agents/monitor/shared/auth/cognito_token.py    # ~50 LoC — Cognito POST + 1h cache (Phase 2 transitional)
agents/monitor/shared/auth/__init__.py         # 0 LoC — placeholder
agents/monitor/shared/auth/                    # 폴더 자체 (위 2개 삭제 후 git rm)
```

→ **`git rm -r agents/monitor/shared/auth/`** Phase 3 PR 에 포함.

### 10-5. AWS 자원 변화 (보강)

§2-1 의 5개 신규 자원 + §2-2 의 8개 carry-over (변경 없음). 자원 ARN level 까지 명시:

```
[신규 5개 — Phase 3 PR 머지 후]
+ Runtime: arn:aws:bedrock-agentcore:us-west-2:{account}:agent-runtime/...
+ ECR Repo: arn:aws:ecr:us-west-2:{account}:repository/bedrock-agentcore-aiops_demo_${DEMO_USER}_monitor
+ IAM Role: arn:aws:iam::{account}:role/AmazonBedrockAgentCoreSDKRuntime-{region}-{hash}
+ OAuth Provider: arn:aws:bedrock-agentcore:us-west-2:{account}:credential-provider/aiops_demo_${DEMO_USER}_monitor_gateway_provider
+ CW Log Group: arn:aws:logs:us-west-2:{account}:log-group:/aws/bedrock-agentcore/runtimes/aiops_demo_${DEMO_USER}_monitor

[변경 0개 — Phase 2 자원 그대로]
  Cognito UserPool: arn:aws:cognito-idp:us-west-2:{account}:userpool/{pool-id}    (unchanged)
  Cognito UserPoolClient C: client-id ...                                           (unchanged)
  Gateway: arn:aws:bedrock-agentcore:us-west-2:{account}:gateway/...               (unchanged)
  GatewayTarget × 2 (history-mock, cloudwatch-wrapper)                             (unchanged)
  Lambda × 2 (history_mock, cloudwatch_wrapper)                                     (unchanged)
  Phase 0 EC2 + alarms                                                              (unchanged)

[삭제 0개 — Phase 3 PR 후 Phase 2 자원 모두 살아남음]
```

### 10-6. 의존성 변화 (`uv tree` 영향)

```diff
# pyproject.toml dependencies
- requests >= 2                       # transitional 제거
+ bedrock_agentcore_starter_toolkit  # dev-dependency 신규

# transitive 영향 (확인 필요)
~ bedrock-agentcore                   # version pin 동일 (Phase 2 와)
~ strands-agents                      # 동일

# Runtime 컨테이너 의존성 (agents/monitor/runtime/requirements.txt — 별 파일)
+ aws-opentelemetry-distro==0.12.2    # D7 OTEL (Dockerfile RUN 안에서 설치, requirements.txt 에 명시)
+ strands-agents
+ bedrock-agentcore
+ boto3
+ python-dotenv
```

→ **net 의존성 변화**:
- 직접 의존: `requests` 제거, `bedrock_agentcore_starter_toolkit` (dev) 추가, `aws-opentelemetry-distro` (Runtime 전용) 추가
- transitive: `requests` 가 다른 패키지의 transitive dependency 일 수 있음 — `uv tree` 확인 시 보존됨 (직접 의존만 제거)

### 10-7. PR commit 권장 분할

phase2 의 4 commit 분할 패턴 (Step B/C/D) 따라 — Phase 3 도 step 별 commit:

```
Step A — 의존성 + 디렉토리 정리 (1 commit, 작음)
  - pyproject.toml: requests 제거 + bedrock_agentcore_starter_toolkit 추가
  - .gitignore: agents/monitor/runtime/ 산출물 추가
  - shared/auth/ 폴더 통째 삭제 (git rm -r)
  - shared/modes.py 신규 (5 LoC)
  - shared/auth_local.py 신규 (15 LoC)
  - shared/mcp_client.py 변경 (분기 추가)
  - local/run.py 변경 (modes import)
  → 변경: 5 file changed, +25 -54 LoC

Step B — Runtime 코드 (1 commit, 중간)
  - agents/monitor/runtime/agentcore_runtime.py 신규
  - agents/monitor/runtime/Dockerfile 신규
  - agents/monitor/runtime/requirements.txt 신규
  - agents/monitor/runtime/.dockerignore 신규
  → 변경: 4 file added, +85 LoC

Step C — Deploy + invoke + verify + teardown (1 commit, 큼)
  - agents/monitor/runtime/deploy_runtime.py 신규
  - agents/monitor/runtime/invoke_runtime.py 신규
  - agents/monitor/runtime/verify_c1.py 신규
  - agents/monitor/runtime/teardown.sh 신규
  - agents/monitor/runtime/README.md 신규
  → 변경: 5 file added, +430 LoC

Step D — Acceptance 검증 + docs/design 업데이트 (1 commit, 작음)
  - docs/design/phase3.md 가 이 commit 에 의해 머지된 후 P3-A1~A6 PASSED 검증
  - phase2.md 의 §6-9 transition diff 예고 항목에 "→ Phase 3 commit b2259d8 에서 이행" 메모 추가 (선택)
  → 변경: 0~1 file changed
```

→ 4 commit 분할 시 PR review 가 step 별 가능. phase2 의 commit 패턴 (`2a15ccb` Initial → `3d89e61` Step B → `71dcc1f` Step C → `b2259d8` Step D) 일관성.

### 10-8. PR 머지 전 git diff 검증

```bash
# 통계
git diff main..HEAD --stat | tail -10

# 신규 파일 11개 확인
git diff main..HEAD --name-only --diff-filter=A | grep -E "(runtime|shared)/"

# 삭제 파일 확인
git diff main..HEAD --name-only --diff-filter=D | grep "auth/"

# 변경 파일 4개 확인
git diff main..HEAD --name-only --diff-filter=M
```

→ acceptance 외 diff sanity (PR 머지 전 manual check).

---

## 11. Transition diff 예고 (Phase 3 → Phase 4)

Phase 3 의 deferred 결정 (D6 Memory) + Phase 4 의 신규 자원 (Incident Agent + GitHub storage) 이 합쳐지는 시점. **D5 (A2A) 는 phase4.md design 시 Phase 6a 로 재이월 — 2026-05-07**. Phase 4 design doc (`docs/design/phase4.md`) 가 authoritative.

### 11-1. Phase 4 핵심 변경 (예고 — phase4.md 와 정렬)

| 변경 | 출처 | Phase 4 분량 (예상) |
|---|---|---|
| **Incident Agent Runtime 추가** | plan_summary §134 (Phase 4 산출물) | 2nd Runtime — Phase 3 의 dba 패턴 재사용 (`agents/incident/runtime/`), `@app.entrypoint` 그대로 |
| **Sequential CLI invoke** | phase4.md §5 — A2A 대안 | `agents/monitor/runtime/invoke_runtime.py` 의 `--sequential` 모드 (boto3 SIGV4 Monitor → Incident) |
| **GitHub storage 도입** | plan_summary §82-85 + §134 의 Incident 가 GitHub `data/runbooks/` read | GitHub Lambda + Gateway Target 추가 (Phase 2 의 history-mock Lambda 패턴 재사용) |
| **`data/runbooks/` 디렉토리 신규** | plan_summary §82 | 동일 repo 의 `data/runbooks/payment-status-check.md` (phase4.md D4) |
| ~~**A2A 서버 활성화**~~ | ~~D5 deferred (Phase 4)~~ → **Phase 6a 로 재이월** (resource.md §1 정렬) | (Phase 4 미수행) |
| ~~**Cognito Client B 추가**~~ | ~~plan_summary §118 (Phase 4 placeholder)~~ → **Phase 6a 로 통합 이월** | (Phase 4 미수행 — A2A caller 와 함께) |

### 11-2. Phase 3 결정의 deferred 항목 vs Phase 4 본격 도입

| Phase 3 결정 | deferred 시점 | Phase 4 에서의 결정 포인트 |
|---|---|---|
| **D5 — A2A 활성화** | **Phase 6a — Supervisor caller 도입 시점 (재이월 2026-05-07)** | Monitor / Incident / Change / Supervisor 모두 A2A 서버화 + Supervisor 가 RemoteA2aAgent caller. AgentCard schema, `/.well-known/agent-card.json` endpoint, Cognito Client A/B authorization 통합 도입. resource.md §1 line 13-14 약속 준수 |
| **D6 — Memory** | Phase 4+ — cross-agent context 필요성 평가 | Monitor → Incident 호출 시 prior incident 추적 필요? incident 의 follow-up resolution 추적 필요? (cross-session memory) |
| **§3-7 placeholder — local token 처리** | §7-6 에서 (a-2-i) 결정됨 (Phase 3 자체에서 close) | Phase 4 무관 |

### 11-3. Phase 3 IAM Role 의 Phase 4 영향

§6-5 의 예고 표 따라:

| 경로 | Phase 4 변경 |
|---|---|
| Phase 3 Monitor Role | **변경 없음** — Phase 3 이 만든 `Phase3RuntimeExtras` 그대로 |
| Phase 4 Incident Role | **신규** — toolkit 자동 생성 + `Phase4IncidentRuntimeExtras` inline |
| Phase 6a A2A 활성화 시 (재이월) | Monitor Role 에 추가 권한 — `bedrock-agentcore:GetResourceOauth2Token` 으로 Cognito Client B token 발급. Phase 3 Role 에 이미 부착돼 있어 무변경 |

→ **Phase 3 Role 은 Phase 4 PR 에서 미터치** (의도). PR 영향 범위 격리.

### 11-4. Phase 3 → 4 transition 의 코드 diff (예상)

```diff
# Phase 4 PR (예상)

# 신규 파일
+ agents/incident/runtime/agentcore_runtime.py        # Phase 3 와 거의 동일 (모델만 다름)
+ agents/incident/runtime/Dockerfile                  # Phase 3 와 동일
+ agents/incident/runtime/deploy_runtime.py           # Phase 3 와 거의 동일 (agent_name + role 변경만)
+ agents/incident/shared/agent.py                     # create_agent (Strands)
+ agents/incident/shared/prompts/system_prompt.md     # Incident 용 prompt
+ agents/monitor/runtime/agent_executor.py            # A2A AgentCard + agent executor (A2A 샘플 차용)
+ agents/incident/runtime/agent_executor.py           # 동일 패턴
+ infra/github-lambda/cognito_client_b.yaml                  # Cognito stack update — Client B 추가
+ infra/github-lambda/github_lambda.yaml                     # GitHub storage Lambda + Gateway Target 추가
+ data/runbooks/payment-status-check.md                    # Incident 의 runbook 데이터

# 변경 파일
~ agents/monitor/runtime/agentcore_runtime.py         # A2A executor 등록
  (Phase 4 에선 Monitor Runtime 본문/deploy 미터치 — A2A 가 Phase 6a 로 이월)
~ docs/design/phase4.md                               # 신규 design doc

# 삭제 파일
- (없음 — Phase 3 의 모든 자원 보존)
```

→ Phase 3 의 helper 통째 삭제 패턴이 Phase 4 에서는 재발하지 않음 (Phase 3 가 transition 으로서 이미 cleanup 완료).

### 11-5. Phase 4 의 acceptance 기준 (예상)

phase2 / phase3 의 acceptance 패턴 따라 — Phase 4 가 추가할 P4-A1~A5+:

| 예상 acceptance | 검증 방법 |
|---|---|
| P4-A1 — Phase 3 P3-A1~A6 회귀 없음 | Phase 3 검증 절차 재실행 |
| P4-A2 — Incident Runtime 배포 + 단일 invoke 동작 | invoke_runtime.py incident |
| P4-A3 — Monitor → Incident A2A 호출 success (smoke test) | local CLI 에서 직접 |
| P4-A4 — GitHub Lambda → runbooks read 성공 | Incident invoke 시 runbook content 응답 포함 |
| P4-A5 — Phase 4 teardown 후 Phase 3 자원 보존 | Phase 3 teardown.sh 의 Phase 2 보호 패턴 재사용 |

### 11-6. 워크샵 시퀀스 (Phase 1 → 2 → 3 → 4 → ...)

| Phase | 워크샵 학습 포인트 (누적) |
|---|---|
| 1 | Strands + 3가지 진단 유형 (offline) |
| 2 | + Gateway + MCP + Lambda Target + Cognito M2M (transitional) |
| **3** | **+ AgentCore Runtime + OAuth2CredentialProvider + transition (helper 삭제)** |
| 4 | + 2nd Runtime (Incident) + GitHub storage + sequential CLI (A2A 미도입) |
| 5 | + AgentCore NL Policy (readonly enforcement) |
| 6a | + 3rd Runtime (Change Light) + Supervisor (필수) + Cognito Client A |
| 6b | + Workflow orchestrator (stretch, 비교 측정) |
| 7 | + EC mall 통합 (alarm 추가만으로 동일 흐름) |

→ **Phase 3 은 transition 단계** — Phase 4 의 multi-agent 화 직전 prerequisite. Phase 3 PR 머지 후 다음 step 의 의미가 명확해짐.

---

## 12. Out of scope + Reference codebase 매핑

### 12-1. Out of scope (Phase 3 가 **하지 않는** 것 — 자세한 목록)

§0-3 의 한 줄 요약을 expand. 각 항목의 **언제 도입되나** + **Phase 3 가 미루는 이유**:

| 미포함 항목 | 도입 시점 | Phase 3 가 미루는 이유 |
|---|---|---|
| **A2A 서버 활성화** (Strands → A2A AgentCard endpoint) | **Phase 6a (D5 재이월 2026-05-07)** | resource.md §1 line 13-14 ("RemoteA2aAgent 패턴은 Phase 6a Supervisor 변환 시 핵심 참조") 와 정렬. Phase 4 는 sequential CLI 로 대체 (phase4.md §5) |
| **Cognito Client B** (Supervisor → Sub-agent 인증) | **Phase 6a (재이월 2026-05-07)** | A2A caller (Supervisor) 와 함께 통합 도입. Phase 4 에서는 미사용 (sequential CLI 패턴 — phase4.md §5) |
| **Cognito Client A** (운영자 CLI → Supervisor) | Phase 6 (Supervisor 도입 시) | Supervisor 자체가 Phase 6, Client A 도 같이 |
| **AgentCore Memory** + Strands hooks | Phase 4+ (D6) | cross-agent context 필요성 평가 후. Phase 3 의 stateless 일관성 우선 |
| **Incident Agent Runtime** | Phase 4 | plan_summary §134 — Phase 4 산출물 |
| **Change Agent Runtime** (Light, ~50 LoC) | Phase 6a | plan_summary §136 |
| **Supervisor Runtime** (필수) | Phase 6a | plan_summary §136 |
| **Workflow Orchestrator** (stretch) | Phase 6b | plan_summary §137 — orchestration 비교 측정 |
| **AgentCore NL Policy** (readonly enforcement) | Phase 5 | plan_summary §135 — Runtime prerequisite (Phase 3 충족) 후 |
| **GitHub storage** (`data/runbooks/` `incidents/` `deployments/` `diagnosis/`) | Phase 4 (Incident GitHub Lambda) | Incident 가 첫 caller — 그 시점에 도입 |
| **S3 fallback** (GitHub 차단 시) | Phase 4 (GitHub Lambda 와 함께 fallback) | 동일 시점 |
| **EC mall 통합** | Phase 7 (외부 의존: 동료 EC mall 완료) | plan_summary §138 |
| **Memory hooks 코드** (StandupMemoryHooks 등 dba 패턴) | Phase 4+ (D6 보류 풀릴 시) | hooks 미주입 — `agentcore_runtime.py` 에 hooks=[] 고정 |
| **Smithy model** (CloudWatch native target) | (영구 미사용) | Phase 2 가 Smithy 우회 (cloudwatch-wrapper Lambda 가 boto3 직접). Phase 3+ 도 동일 |
| **CodeBuild** (CI image build) | (영구 미사용 — workshop) | D9 — `Runtime.launch()` 가 로컬 docker buildx 처리 |
| **Multi-Runtime Memory 공유** | Phase 6+ (Supervisor 가 도입 시) | cross-Runtime context 가 진짜 필요한 시점 = Supervisor 라우팅 |

→ 16개 항목 — Phase 3 가 명시적 제외. 워크샵 청중이 "Phase 3 의 책임이 어디까지인가" 추적.

### 12-2. Reference codebase 매핑

phase2.md §10 패턴 따라 — Phase 3 의 각 산출물이 어느 base codebase 의 어느 부분을 차용하는지 1:1 매핑. workshop 청중이 base 와 우리 코드를 line-by-line 비교 학습.

| Phase 3 산출물 | 차용 base | base 안의 위치 | 변형 |
|---|---|---|---|
| `agents/monitor/runtime/agentcore_runtime.py` | **dba** | `managed-agentcore/agentcore_runtime.py:114-148` (BedrockAgentCoreApp + entrypoint) | dev_name → mode 분기, session caching 제거, MCPClient 도입 |
| `agents/monitor/runtime/Dockerfile` | **dba** | `managed-agentcore/Dockerfile` | 거의 byte-level 동일 (region, AGENT_NAME 만 변경) |
| `agents/monitor/runtime/deploy_runtime.py` | **dba** | `managed-agentcore/deploy.py:52-256` (5단계) | Step [3]: SSM 권한 → GetResourceOauth2Token + SecretsManager + OAuth provider create. shared copy 대상 변경 |
| `agents/monitor/runtime/invoke_runtime.py` | **dba** | `managed-agentcore/example_invoke.py:74-156` | payload {dev_name, prompt} → {mode, query}. token_usage stdout 추가 |
| `agents/monitor/runtime/verify_c1.py` | **자체 작성** (D8) | — | base 없음 — phase2.md §1 의 acceptance 패턴 + Phase 1 baseline JSON schema 활용 |
| `agents/monitor/runtime/teardown.sh` | **자체 작성** (Phase 2 패턴 + dba 의 cleanup 정신) | Phase 2 `infra/cognito-gateway/teardown.sh` (boto3 reverse) | Runtime + OAuth provider + ECR Repo + IAM Role + CW Log Group cleanup |
| `agents/monitor/runtime/requirements.txt` | **dba** | `managed-agentcore/requirements.txt` | strands + bedrock-agentcore + boto3 + dotenv. memory hooks 제거 (D6) |
| `agents/monitor/runtime/.dockerignore` | **자체 작성** (소품) | — | __pycache__, .pytest_cache, *.pyc, .env |
| `agents/monitor/runtime/README.md` | **자체 작성** (workshop) | — | Phase 3 배포/검증 step-by-step (deploy → invoke → verify_c1 → teardown 순서 안내) |
| `agents/monitor/shared/modes.py` | **자체 작성** (§3-2 의 (b)) | — | Phase 2 `local/run.py:23-26` 의 inline dict 분리 |
| `agents/monitor/shared/auth_local.py` | **A2A 샘플** | `monitoring_strands_agent/utils.py:27-48` (`get_resource_oauth2_token` boto3 호출) | workload_token 생략 (local IAM 자격증명 사용), 단일 함수 export |
| OAuth2CredentialProvider 생성 호출 | **A2A 샘플 + AWS docs** | `cloudformation/monitoring_agent.yaml:636` (`credentialProviderVendor="CustomOauth2"` Lambda Custom Resource 안) | Lambda Custom Resource → boto3 명시 호출 (D2 — CFN-native verify 불필요) |
| IAM Role permissions | **A2A 샘플** | `cloudformation/monitoring_agent.yaml:65-100` (default 7 Sid) + dba `deploy.py:153-176` (post-deploy IAM put_role_policy) | SSM 권한 → GetResourceOauth2Token + SecretsManager. MemoryAccess 제거 (D6) |
| `mcp_client.py` 의 token 라인 제거 | **phase2.md §6-9 예고** | phase2.md 의 Phase 3 transition diff 표 | 그대로 이행 + 환경 분기 추가 (§7-6 (a-2-i)) |
| `cognito_token.py` 통째 삭제 | **phase2.md §6-9 약속** | phase2.md `agents/monitor/shared/auth/` | 그대로 이행 |

→ **15개 매핑**. 12개가 base codebase 차용, 3개는 자체 작성 (verify_c1.py, teardown.sh, README.md).

### 12-3. 차용 의도가 다른 base 의 분배

| Base | Phase 3 에서의 역할 | 차용 비율 |
|---|---|---|
| **dba (developer-briefing-agent)** | Runtime 컨테이너 + deploy 스크립트 + invoke 스크립트 의 골격 | ~80% (5 파일 직접 차용 + 1 파일 패턴 차용) |
| **A2A (multi-agent-incident-response)** | OAuth2CredentialProvider 호출 패턴 + IAM Role default 권한 reference | ~15% (auth_local.py + IAM permissions reference) |
| ec-customer-support | 0% — Phase 2 에서만 사용 (lab-03 setup_gateway), Phase 3 무관 | 0% |
| sample-deep-insight | 0% — env 패턴은 phase2 carry-over | 0% |

→ **dba 가 Phase 3 의 핵심 base** — D10 의 dba strict 결정 정당화. A2A 는 보조 (특히 OAuth provider create 패턴).

### 12-4. base 와 차용 안 한 것 (의도적 omit)

| 항목 | omit 이유 |
|---|---|
| dba 의 `chat.py` (interactive REPL) | workshop 시나리오 = 1-shot invoke. multi-turn REPL 은 Phase 6 Supervisor 도입 시 검토 |
| dba 의 `setup.sh` 통합 부트스트랩 | 우리는 phase2 의 `bootstrap.sh` 패턴 (이미 존재) 사용 |
| dba 의 SKILL.md skills/ 시스템 | Phase 1 `system_prompt_*.md` + mode 분기로 충분 |
| dba 의 `MemoryHooks` (Strands hooks) | D6 — Memory 보류 |
| A2A 의 `cloudformation/monitoring_agent.yaml` 전체 (CFN-native Runtime) | D1 — toolkit + boto3 hybrid 가 Phase 3 의 educational core |
| A2A 의 `Lambda Custom Resource` for OAuth provider | D2 — boto3 직접 호출 (Lambda CRD 우회 — educational 가치 0, 우회 코드만 늘림) |
| A2A 의 `host_adk_agent` (Google ADK Supervisor) | Phase 6a 에서 Strands sub_agents 로 변형 (plan_summary §148) |

→ **7개 의도적 omit**. workshop 청중이 "왜 base 의 이 부분은 차용 안 했는가" 추적 시 educational 가치.

### 12-5. base 와의 divergence — workshop 학습 포인트

base 와 우리 코드가 다른 곳마다 workshop 시 설명 가치:

| Divergence | 설명 핵심 |
|---|---|
| dba 의 session caching → Phase 3 의 stateless | 시나리오가 1-shot 이라 stateful 불필요. C1 검증 결정성 우선 |
| A2A 의 명시 OAuth 호출 → Phase 3 의 SDK 자동 inject | Runtime 환경 가정 — code 가 token 의 존재 모름 (educational core: "AgentCore Identity 의 자동 처리") |
| dba 의 SSM 의존 → Phase 3 의 OAuth provider 의존 | Phase 3 의 secret 보관은 OAuth provider 가 처리 (SSM 불필요) |
| dba 의 단일 prompt → Phase 3 의 mode 분기 (past/live) | mock 데이터 (past) + 실 CloudWatch (live) 양쪽 검증 — phase2 패턴 carry-over |
| A2A 의 Memory hooks → Phase 3 의 hooks=[] | D6 보류, Phase 3 = transition only |

→ 5개 divergence — 각각 §1 의 D 결정과 cross-reference. workshop 발표 시 "왜 다르게 갔나" 의 명확한 reasoning chain.

### 12-6. Phase 3 design doc 자체의 self-reference

이 문서가 향후 Phase 4 design 작성 시 reference 역할:

| §X | Phase 4 에서의 사용 |
|---|---|
| §1 (의사결정 로그) | Phase 4 의 의사결정 패턴 (D 번호 매기기, 채택/대안/근거 표) reference |
| §3 (agentcore_runtime.py) | Phase 4 Incident Runtime 의 entrypoint 도 같은 구조 (mode 분기만 다름) |
| §4 (deploy_runtime.py) | Phase 4 Incident deploy 도 5단계 — Step [3] 에 A2A executor 등록 추가 정도 |
| §6 (IAM Role) | Phase 4 Incident Role 도 default + extras 패턴 |
| §10 (PR commit 분할) | Phase 4 도 Step A/B/C/D 4 commit 패턴 일관 |

→ Phase 3 design 가 Phase 4+ 의 template — workshop 청중이 Phase 별 design doc 의 일관 구조를 학습.

---

> **본 design doc 작성 완료**. 작성일 2026-05-05. 검증 결과 P3-A1~A6 PASS 후 phase2 처럼 commit history (Step A/B/C/D 4 commit) 로 머지 예정.
