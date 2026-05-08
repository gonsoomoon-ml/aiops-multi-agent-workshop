# Phase 6a — Supervisor + Change Agent + A2A 활성화

> Phase 4 (`docs/design/phase4.md`) 가 multi-agent 진입을 sequential CLI 로 시연한 후, 이 단계에서 **Supervisor Runtime + Change Agent Runtime + A2A 프로토콜 (server + caller 양쪽)** + **Cognito Client A/B** + **deployments-storage Lambda** 를 추가한다.
> Phase 5 (AgentCore NL Policy) 는 본 프로젝트 scope 에서 **건너뜀** — Phase 4 → Phase 6a 직행. Phase 5 결정에 묶여있던 항목 (incidents/ log, AgentCore Memory) 은 §1 에서 재배치.
> Phase 0/2/3/4 자원 (Cognito UserPool, Client C, Gateway, 3 Target, Lambda × 3, Monitor + Incident Runtime) 은 **무변경** — Phase 6a PR 영향 범위 격리, 회귀 0건 목표.

---

## 0-1. 한 줄 정의

**Phase 6a = orchestration 진입.** "Operator CLI 가 Bearer JWT 로 Supervisor 에 진입하면, Supervisor 가 Strands `sub_agents` (= `RemoteA2aAgent` × 3) 로 Monitor / Incident / Change 를 A2A 프로토콜로 호출해 통합 응답을 반환한다." Phase 4 의 sequential CLI 가 했던 caller 역할을 Supervisor 가 LLM-driven 으로 대체.

| 측면 | Phase 4 (current) | **Phase 6a (이번)** |
|---|---|---|
| Runtime 개수 | 2 (Monitor + Incident) | **4 (+ Supervisor + Change)** |
| Multi-agent caller | CLI sequential (boto3 SIGV4) — *미구현* | **Supervisor (Strands `sub_agents`)** |
| Multi-agent transport | (해당 없음 — CLI 직접 호출) | **A2A JSON-RPC over HTTP + Bearer JWT** |
| 도구 Lambda 개수 | 3 (history-mock, cloudwatch-wrapper, github-storage) | **4 (+ deployments-storage)** |
| Cognito Client | C (Phase 2) — Gateway M2M | **C 그대로 + A (operator) + B (Supervisor M2M)** |
| Monitor Runtime | `@app.entrypoint` 단일 entrypoint | **+ A2A server wrap (`A2AStarletteApplication`)** |
| Incident Runtime | `@app.entrypoint` 단일 entrypoint | **+ A2A server wrap** |
| Operator 진입점 | `invoke_runtime.py` (boto3 SIGV4) | **Operator CLI** (`agents/operator/cli.py`) — Cognito 인증 + Supervisor A2A 호출 |
| AgentCore Memory | 보류 (Phase 4 D6) | **계속 보류 — Phase 7 또는 별 phase 에서 재평가** |

---

## 0-2. 시스템 목표 매핑 (C1 ~ C5)

`docs/design/plan_summary.md` §시스템 목표 매핑:

| # | 능력 | Phase 6a 에서의 역할 | 검증 방법 |
|---|---|---|---|
| C1 | 같은 코드 local/Runtime | **회귀 없음** — Monitor/Incident 의 entrypoint 본문 carry-over (A2A wrap 만 추가). Supervisor/Change 도 동일 dba 패턴 | P6a-A1 (Phase 4 P4-A2/A4 회귀) |
| C2 | Gateway + MCP 도구 외부화 | **확장** — deployments-storage Target 추가 (Change 가 caller). 4 Target 으로 진화 | P6a-A4 (Change 가 deployments read) |
| **C3** | A2A 프로토콜로 독립 Runtime 간 호출 | **★ 핵심 활성화** — server (3 sub-agents) + caller (Supervisor) 동시. Phase 4 의 "이월" 약속 이행 | P6a-A2 (Supervisor 단일 invoke 가 A2A 로 3 sub-agents 호출), P6a-A3 (A2A 호출 trace) |
| C4 | AgentCore Policy | **scope cut** — Phase 5 건너뛰며 본 phase 에서도 미부착 | — |
| C5 | Workflow vs Supervisor | 무관 (Phase 6b stretch) | — |

→ **Phase 6a 의 직접 deliverable = C3 활성화 (A2A) + C2 확장 (deployments) + Strands `sub_agents` 패턴 시연**. C4 는 본 프로젝트 영구 제외 (워크샵 분량 제약).

---

## 0-3. Phase 6a 가 **하지 않는** 것 (scope cuts)

자세한 목록은 §9 Out of Scope. 한 줄 요약:

- **AgentCore NL Policy** (Phase 5 건너뜀) — 본 프로젝트 scope 에서 영구 제외. 워크샵 분량 제약 + AgentCore Runtime + A2A + Strands sub_agents 학습량이 이미 큼
- **AgentCore Memory + Strands hooks** — Phase 7 또는 별도 phase 로 재이월. cross-agent memory 가 본격 의미를 가지려면 다회 incident 누적 시나리오 필요
- **Workflow Orchestrator** — Phase 6b stretch (비교 측정용)
- **EC mall 통합** — Phase 7 (외부 의존)
- **`incidents/` log write 누적 패턴** — Phase 6a 는 Change 의 read-only deployments 만. incidents/ 누적 (Memory 로 대체 vs 명시 write) 결정은 Phase 7+
- **Phase 4 sequential CLI 의 deprecation 처리** — Phase 4 Step D 가 미구현이므로 deprecate 할 코드 자체가 없음. Supervisor 가 단일 multi-agent 경로 (D7)
- **S3 fallback** — GitHub 만으로 충분한 시점까지 미룸

→ Phase 6a PR 영향 범위 = `agents/{supervisor,change,operator}/` 신규 + `infra/phase6a/{cognito_extras,deployments_lambda}.yaml` 신규 + Monitor/Incident `agentcore_runtime.py` 에 A2A server wrap 추가 + 두 Runtime 재배포 (코드 변경분 반영) + `runbooks/` 또는 `deployments/` 컨텐츠 minimal seed.

**Cognito UserPool / Client C / Resource Server / Gateway / 기존 3 Target / Lambda × 3 / IAM Roles 모두 미터치.** 신규 Cognito Client A/B 는 별 CFN stack (`aiops-demo-${user}-phase6a-cognito-extras`) 으로 격리.

---

## 0-4. Educational 가치

워크샵 청중이 Phase 6a PR 을 line-by-line 읽었을 때 학습하는 것:

1. **Strands `sub_agents` 패턴** — Supervisor 가 `RemoteA2aAgent(url=..., bearer_token=...)` 인스턴스 3개를 보유. LLM 이 routing 결정. Phase 4 의 "CLI 가 caller" 패턴이 LLM-driven 으로 진화.
2. **A2A 프로토콜 server wrap** — 기존 `@app.entrypoint` 본문은 carry-over, `A2AStarletteApplication` 으로 둘러싸기만 함. AgentCard schema 노출. Bearer JWT 검증 via AgentCore Inbound Authorizer (Cognito UserPool 으로 직접) 또는 Starlette middleware.
3. **Cognito 의 다중 클라이언트 분리** — Client C (Gateway M2M, Phase 2 에서 정착) + Client A (operator, Authorization Code 또는 USER_PASSWORD) + Client B (M2M, A2A scope) 의 책임 분리. 동일 UserPool 안에서 audience 다른 JWT.
4. **OAuth2CredentialProvider 의 multi-provider 패턴** — Supervisor Runtime 에 두 provider: (a) `gateway_provider` (Client C, Gateway 호출용), (b) `a2a_provider` (Client B, sub-agents 호출용). Phase 3 OAuth gotcha 가 multi-provider 로 자연 확장.
5. **Multi-agent topology 가 코드와 어떻게 1:1 매핑되는지** — plan_summary 의 "스타 토폴로지" 다이어그램 이 Supervisor 의 `sub_agents=[monitor, incident, change]` list 한 줄로 코드화.
6. **Phase 4 → 6a 진화의 line-level 비교** — Phase 4 sequential CLI 가 *implemented if it had been built* 었다면 ~50 LoC. Supervisor 의 `sub_agents` + LLM routing 은 ~30 LoC + system prompt. 같은 시연을 LLM 위임으로 해결하는 패턴.

---

## 0-5. 본 문서 구조 (§1 ~ §10)

| 섹션 | 내용 |
|---|---|
| §1 | 의사결정 로그 (D1 ~ D10) |
| §2 | 인벤토리 — AWS 자원 / 코드 파일 / env vars |
| §3 | Supervisor Agent 상세 (sub_agents + routing prompt + caller-side OAuth) |
| §4 | Change Agent 상세 (deployments read + system_prompt + 권한 범위) |
| §5 | A2A 프로토콜 활성화 상세 (server-side wrap, AgentCard, JWT 검증) |
| §6 | Cognito Client A/B 상세 (CFN 별 stack, scope, audience) |
| §7 | deployments-storage Lambda 상세 (Phase 4 github-storage 패턴 carry-over) |
| §8 | Operator CLI 상세 (Cognito 인증 + A2A 호출 + SSE 스트림) |
| §9 | Acceptance 기준 P6a-A1 ~ A6 + smoke test |
| §10 | Out of scope + Reference codebase 매핑 |

---

## 1. 의사결정 로그 (D1 ~ D10)

phase4.md §1 의 의사결정 로그 패턴 따라.

### 1-1. 결정 요약 표

| # | 항목 | 선택 | 대안 | 핵심 근거 |
|---|---|---|---|---|
| **D1** | Supervisor 호출 대상 | **Monitor + Incident + Change 3개 모두** | (b) Change 만 / (c) Monitor + Incident (Change 제외) | plan_summary 의 "스타 토폴로지" 명시 + workshop educational 가치는 LLM 의 routing 결정 시연 (sub-agent 1개면 routing 의미 없음). user 결정 |
| **D2** | A2A 프로토콜 활성화 범위 | **server (Monitor/Incident/Change 3개) + caller (Supervisor)** | (b) caller 만 (sub-agents 는 SIGV4 그대로) / (c) server 만 (CLI 가 A2A 호출) | resource.md §1 의 "Phase 6a Supervisor 변환 시 핵심 참조" 약속 + Phase 4 D2 ("server-only 는 dead code") 의 정합. Supervisor 가 등장하는 시점 = caller 출현 시점 = server 도 의미 있는 시점 |
| **D3** | Cognito Client A (operator → Supervisor) | **신규 발급 — UserPasswordAuth grant + 워크샵 prefix user** | (b) Authorization Code with PKCE / (c) Client C 재사용 | 워크샵 단순성 — operator CLI 가 username/password 로 1줄 prompt 후 JWT 획득. PKCE 는 browser 흐름 → CLI 불편. Client C 재사용 시 audience/scope 충돌 (Gateway 용) |
| **D4** | Cognito Client B (Supervisor M2M → sub-agents) | **신규 발급 — client_credentials grant + 신규 scope `agent-invoke`** | (b) Client C 재사용 (Gateway scope `/invoke` 도 부여) / (c) Client A 재사용 | Client C 의 scope `aiops-demo-${user}-resource-server/invoke` 는 Gateway 전용 — sub-agent A2A audience 와 분리 필요. 신규 scope `agent-invoke` 로 audience 격리 → 권한 누출 방지. Client A 는 user-bound 토큰이라 M2M 부적합 |
| **D5** | deployments storage 분리 | **신규 Lambda + 신규 Gateway Target** | (b) github-storage Lambda 에 `get_deployments_log` tool 추가 / (c) S3 직접 read | user 결정 ("keep original"). plan_summary 의 architecture diagram 도 GitHub Target 1개 (`rules/ runbooks/ deployments/`) 통합 묘사이지만, **권한 분리 + Change Agent 의 caller 격리** + 향후 write 권한 확장 여지 (D6) 를 위해 분리. educational scope memory 는 plumbing 추상화 — 그러나 **agent 별 도구 분리**는 plumbing 이 아니라 architecture decision 영역 |
| **D6** | Change Agent 권한 범위 | **read deployments + write incidents/ + 적절한 추가 write (full where appropriate)** | (b) read-only / (c) read + 명시적 1 tool write | user 결정. workshop 청중에게 "Agent 가 read-only 가 아니라 write 도 할 수 있다" 는 educational 가치 + Change Agent 의 본질 (변경 추적/롤백 결정) 이 read-only 로는 불완전 |
| **D7** | Phase 4 sequential CLI 처리 | **본 design 에서 다루지 않음** — Step D 가 미구현이므로 deprecate 할 코드 없음. Supervisor 가 단일 multi-agent 경로 | (b) sequential CLI 별도 유지 (educational 비교용) / (c) `--legacy-sequential` 옵션 | user 결정. 기존 코드 부재 + Supervisor 가 LLM-driven 으로 routing 시연 → CLI hardcoded routing 과 비교 가치는 design doc §0-4 의 "진화 line-level 비교" 로 충분 |
| **D8** | Strands `sub_agents` 등록 방식 | **`Agent(sub_agents=[RemoteA2aAgent(...)] × 3)` — Strands 표준 시그니처** | (b) Supervisor 가 plain `@tool` 함수 3개 (boto3 wrapper) — A2A 우회 / (c) Supervisor 가 `Workflow` 패턴 사용 (Phase 6b) | resource.md §1 의 host_adk_agent 패턴 정확 차용. Strands 의 sub_agents 는 RemoteA2aAgent 와 1차 통합 → A2A 활성화의 첫 caller 역할 |
| **D9** | AgentCore Inbound Authorizer | **사용 — Cognito UserPool 을 Runtime 의 Authorizer 로 직접 등록** | (b) Starlette middleware 로 직접 JWT 검증 / (c) Lambda authorizer | AgentCore native 기능 활용 (educational). middleware 는 코드 부담 + 검증 logic 직접 작성. Lambda authorizer 는 Phase 6a 외부 자원 추가 |
| **D10** | AgentCore Memory + cross-agent context | **계속 보류 — Phase 7+ 재평가** | (b) Phase 6a 도입 / (c) dormant flag 만 추가 | Phase 4 D6 carry-over. cross-agent memory 본격 시나리오 (Incident 가 prior incident lookup, Supervisor 가 history-aware routing) 는 incidents/ 누적이 선행 — 누적 자체가 별도 phase. premature 회피 |

### 1-2. 결정 간 의존 관계

```
D1 (Supervisor → 3 sub-agents)
 └─→ D2 (A2A 활성화 — caller 와 server 동시)
       ├─→ D3 (Client A — operator 진입)
       ├─→ D4 (Client B — Supervisor M2M)
       ├─→ D8 (Strands sub_agents — RemoteA2aAgent caller)
       └─→ D9 (Inbound Authorizer — server 측 JWT 검증)

D5 (deployments 분리 Lambda)
 └─→ D6 (Change 권한 — read deployments + write incidents/)
       └─→ Lambda toolSchema 가 read+write tool 분리 (§7-2)

D7 (sequential CLI 미처리)        — Phase 4 Step D 미구현 사실 반영
D10 (Memory 보류)                  — Phase 7+ 재이월
```

→ D1+D2+D3+D4+D8+D9 묶음 = "A2A 활성화 풀스택" — Supervisor 가 등장하는 동일 phase 에 server/caller/auth/JWT 검증이 모두 정렬.

### 1-3. Phase 4 결정 항목과의 연속성

| Phase 4 결정 | Phase 6a 에서의 처리 |
|---|---|
| D1 (Incident shared/ 슬림) | 동일 패턴 — Supervisor/Change 도 `agent.py` + `prompts/` 만, helper 는 monitor/shared 직접 import |
| D2 (A2A → Phase 6a 이월) | **★ 본 phase 에서 활성화** — server (Monitor/Incident/Change) + caller (Supervisor) |
| D3 (GitHub Lambda Tool 1개) | **확장** — deployments-storage Lambda 신규 (별 Lambda + 별 Target) |
| D4 (runbook 동일 repo) | 동일 — deployments/ 도 같은 repo |
| D5 (Cognito Client B Phase 6 미룸) | **★ 본 phase 에서 발급** + Client A 도 함께 |
| D6 (Memory 보류) | **★ 보류 유지 (Phase 7+ 로 이월)** |

→ Phase 4 의 미해결 항목 (D2, D5) 을 본 phase 에서 일괄 활성화. Phase 6a 의 결정은 **10건** — Phase 4 (6건) 보다 많은 이유는 *처음 등장하는 axis* 가 많기 때문 (operator/A2A/sub_agents/Inbound Authorizer/multi-provider OAuth).

---

## 2. 인벤토리

### 2-1. AWS 자원 (신규)

| # | 자원 | 이름 | 분량 | 생성 도구 |
|---|---|---|---|---|
| 1 | Bedrock AgentCore Runtime | `aiops_demo_${DEMO_USER}_supervisor` | 1 | `agents/supervisor/runtime/deploy_runtime.py` |
| 2 | Bedrock AgentCore Runtime | `aiops_demo_${DEMO_USER}_change` | 1 | `agents/change/runtime/deploy_runtime.py` |
| 3 | OAuth2CredentialProvider | `aiops_demo_${DEMO_USER}_supervisor_gateway_provider` | 1 | Supervisor deploy (boto3) — Client C M2M, Gateway 호출용 |
| 4 | OAuth2CredentialProvider | `aiops_demo_${DEMO_USER}_supervisor_a2a_provider` | 1 | Supervisor deploy — **Client B M2M, sub-agents A2A 호출용** |
| 5 | OAuth2CredentialProvider | `aiops_demo_${DEMO_USER}_change_gateway_provider` | 1 | Change deploy — Client C M2M, Gateway 호출용 |
| 6 | IAM Role (Supervisor Runtime) | `AmazonBedrockAgentCoreSDKRuntime-...-aiops_demo_${user}_supervisor-...` | 1 | toolkit 자동 |
| 7 | IAM Role (Change Runtime) | `AmazonBedrockAgentCoreSDKRuntime-...-aiops_demo_${user}_change-...` | 1 | toolkit 자동 |
| 8 | IAM inline policy | `Phase6aSupervisorRuntimeExtras` | 1 | Supervisor deploy — 두 OAuth provider 의 GetResourceOauth2Token + Cognito secret read |
| 9 | IAM inline policy | `Phase6aChangeRuntimeExtras` | 1 | Change deploy |
| 10 | Cognito UserPoolClient (A) | `aiops-demo-${DEMO_USER}-client-a` | 1 | `infra/phase6a/cognito_extras.yaml` (CFN) |
| 11 | Cognito UserPoolClient (B) | `aiops-demo-${DEMO_USER}-client-b` | 1 | 동일 CFN |
| 12 | Cognito Resource Server scope | `aiops-demo-${DEMO_USER}-resource-server/agent-invoke` | 1 (신규 scope) | 동일 CFN — Phase 2 ResourceServer 에 scope 추가 또는 별 ResourceServer 신규 (§6 결정) |
| 13 | Cognito User (operator) | `operator-${DEMO_USER}` | 1 | `infra/phase6a/cognito_extras.yaml` 또는 별 boto3 후처리 (USER_PASSWORD 가능 여부에 따라) |
| 14 | Inbound Authorizer 설정 | (Runtime config) | Runtime × 3 (Monitor + Incident + Change) | 각 Runtime deploy 시 `customJwtAuthorizer` 옵션 |
| 15 | Lambda function | `aiops-demo-${DEMO_USER}-deployments-storage` | 1 | `infra/phase6a/deployments_lambda.yaml` (CFN) |
| 16 | Lambda IAM Role | `aiops-demo-${DEMO_USER}-deployments-storage-role` | 1 | 동일 CFN |
| 17 | IAM inline policy (cross-stack) | `aiops-demo-${user}-phase6a-gateway-invoke-deployments` | 1 | 동일 CFN — Phase 2 Gateway Role 에 invoke 권한 (Phase 4 패턴 정확 차용) |
| 18 | Gateway Target | `deployments-storage` | 1 | `infra/phase6a/setup_deployments_target.py` (boto3) |
| 19 | ECR repo | toolkit 자동 (Supervisor + Change) | 2 | `Runtime.launch()` |
| 20 | CloudWatch Log Group | `/aws/bedrock-agentcore/runtimes/...` × 2 (Supervisor + Change) | 2 | toolkit 자동 |

### 2-2. AWS 자원 (carry-over from Phase 4 — **변경 없음** + Runtime 재배포 1회)

| 자원 | 상태 |
|---|---|
| Cognito UserPool + Client C + Resource Server (기존 scope `/invoke`) | **그대로** |
| Gateway (`aiops-demo-${user}-gateway-...`) | **그대로** |
| Gateway Target × 3 (history-mock, cloudwatch-wrapper, github-storage) | **그대로** |
| Lambda × 3 (history-mock, cloudwatch-wrapper, github-storage) | **그대로** |
| Phase 2 IAM Role `aiops-demo-${user}-phase2-gateway-role` | **그대로** (Phase 4 가 inline policy 추가, Phase 6a 가 또 1건 추가 — D5) |
| Monitor Runtime (`aiops_demo_${user}_monitor`) | **본문 미터치, A2A wrap 추가 → 재배포** (코드 변경분 반영) |
| Incident Runtime (`aiops_demo_${user}_incident`) | **본문 미터치, A2A wrap 추가 → 재배포** (코드 변경분 반영) |
| Phase 3 Monitor OAuth provider | **그대로** |
| Phase 4 Incident OAuth provider | **그대로** |

→ Phase 4 자원 **무변경**. Monitor + Incident Runtime 만 재배포 (코드 변경분 반영). 기존 OAuth provider / IAM Role / endpoint ARN 모두 유지.

### 2-3. 코드 파일 (신규)

#### `agents/supervisor/`
| 파일 | 분량 | 역할 |
|---|---|---|
| `agents/supervisor/__init__.py` | 0 LoC | — |
| `agents/supervisor/shared/__init__.py` | 0 LoC | — |
| `agents/supervisor/shared/agent.py` | ~50 LoC | `create_supervisor_agent(sub_agents, system_prompt_filename)` — Strands `Agent(sub_agents=...)` |
| `agents/supervisor/shared/prompts/system_prompt.md` | ~80 줄 | LLM routing prompt — Monitor/Incident/Change 구분, escalation policy |
| `agents/supervisor/runtime/agentcore_runtime.py` | ~120 LoC | `@app.entrypoint` + A2A caller-side `RemoteA2aAgent` 인스턴스 3개 + Strands sub_agents 등록 + 두 OAuth provider 사용 |
| `agents/supervisor/runtime/deploy_runtime.py` | ~330 LoC | Phase 4 incident deploy 패턴 carry-over + 두 OAuth provider 부착 |
| `agents/supervisor/runtime/invoke_runtime.py` | ~80 LoC | Supervisor 단독 invoke (operator CLI 와 별개의 관리자용 — boto3 SIGV4) |
| `agents/supervisor/runtime/Dockerfile` | toolkit 자동 | — |
| `agents/supervisor/runtime/requirements.txt` | ~12 줄 | + `a2a-sdk` (caller-side) |
| `agents/supervisor/runtime/teardown.sh` | ~120 줄 | Phase 4 incident teardown 패턴 |
| `agents/supervisor/runtime/README.md` | ~30 줄 | — |

#### `agents/change/`
| 파일 | 분량 | 역할 |
|---|---|---|
| `agents/change/__init__.py` | 0 LoC | — |
| `agents/change/shared/__init__.py` | 0 LoC | — |
| `agents/change/shared/agent.py` | ~40 LoC | Phase 4 incident agent.py 패턴 — `create_agent(tools, system_prompt_filename)` |
| `agents/change/shared/prompts/system_prompt.md` | ~70 줄 | 24h 배포 회귀 탐지 prompt — deployments read + incidents write |
| `agents/change/runtime/agentcore_runtime.py` | ~100 LoC | `@app.entrypoint` + A2A server wrap + `deployments-storage___` + `github-storage___` 도구 prefix 필터링 |
| `agents/change/runtime/deploy_runtime.py` | ~290 LoC | Phase 4 incident deploy 패턴 |
| `agents/change/runtime/invoke_runtime.py` | ~80 LoC | Change 단독 invoke |
| `agents/change/runtime/Dockerfile` | toolkit 자동 | — |
| `agents/change/runtime/requirements.txt` | ~10 줄 | + `a2a-sdk` (server-side) |
| `agents/change/runtime/teardown.sh` | ~100 줄 | — |
| `agents/change/runtime/README.md` | ~25 줄 | — |

#### `agents/operator/`
| 파일 | 분량 | 역할 |
|---|---|---|
| `agents/operator/cli.py` | ~150 LoC | Cognito Client A 인증 (USER_PASSWORD) → JWT 획득 → Supervisor A2A endpoint 호출 (Bearer) → SSE stream stdout |
| `agents/operator/README.md` | ~40 줄 | 사용법 + workshop 청중 prefix user 등록 절차 |

#### `infra/phase6a/`
| 파일 | 분량 | 역할 |
|---|---|---|
| `infra/phase6a/cognito_extras.yaml` | ~150 줄 | CFN — Client A + Client B + 신규 scope `agent-invoke` + operator user. Phase 2 stack 미터치 |
| `infra/phase6a/deployments_lambda.yaml` | ~110 줄 | CFN — Lambda + IAM Role + cross-stack policy on Phase 2 Gateway Role (Phase 4 github_lambda.yaml 패턴 정확 차용) |
| `infra/phase6a/lambda_src/deployments_storage/handler.py` | ~150 LoC | Phase 4 github-storage handler 패턴 — `get_deployments_log(date)` (read) + `append_incident(payload)` (write — D6) |
| `infra/phase6a/setup_deployments_target.py` | ~110 LoC | boto3 — Phase 4 setup_github_target 의 create-or-update 패턴 |
| `infra/phase6a/deploy.sh` | ~140 줄 | Phase 4 deploy 패턴 — cognito_extras + deployments_lambda 순차 + boto3 Target 등록 + Inbound Authorizer 설정 |
| `infra/phase6a/teardown.sh` | ~120 줄 | reverse 삭제 + Phase 0/2/3/4 보존 검증 |
| `infra/phase6a/README.md` | ~80 줄 | 사전 조건 (Phase 2/3/4 alive) + 절차 + 검증 |

#### `runbooks/` 또는 `deployments/`
| 파일 | 분량 | 역할 |
|---|---|---|
| `deployments/README.md` | ~30 줄 | 디렉토리 구조 + 형식 |
| `deployments/2026-05-08.log` | ~10 줄 | minimal seed (워크샵 시점 기준 mock 배포 로그) |

### 2-4. 코드 파일 (변경)

| 파일 | 변경 분량 | 변경 내용 |
|---|---|---|
| `agents/monitor/runtime/agentcore_runtime.py` | +30 LoC / -0 | A2A server wrap (`A2AStarletteApplication` 으로 `app` 둘러쌈) + AgentCard schema 노출. 본문 entrypoint logic 그대로 |
| `agents/incident/runtime/agentcore_runtime.py` | +30 LoC / -0 | 동일 — A2A server wrap |
| `agents/monitor/runtime/deploy_runtime.py` | +20 LoC | Inbound Authorizer 설정 (Cognito UserPool + audience = Client B) |
| `agents/incident/runtime/deploy_runtime.py` | +20 LoC | 동일 |
| `agents/monitor/runtime/requirements.txt` | +1 줄 | `a2a-sdk` |
| `agents/incident/runtime/requirements.txt` | +1 줄 | `a2a-sdk` |
| `agents/monitor/shared/mcp_client.py` | **변경 없음** | A2A 는 별 transport — MCPClient 는 그대로 |
| `pyproject.toml` | +2 줄 | `a2a-sdk` workspace dep |
| `docs/design/phase6a.md` | (이 파일) | — |

### 2-5. Runtime 환경 변수

#### Supervisor Runtime (신규)
```
GATEWAY_URL                       carry-over from Phase 2
OAUTH_PROVIDER_NAME               aiops_demo_${user}_supervisor_gateway_provider
A2A_OAUTH_PROVIDER_NAME           aiops_demo_${user}_supervisor_a2a_provider
COGNITO_GATEWAY_SCOPE             aiops-demo-${user}-resource-server/invoke
COGNITO_A2A_SCOPE                 aiops-demo-${user}-resource-server/agent-invoke
SUPERVISOR_MODEL_ID               global.anthropic.claude-sonnet-4-6
DEMO_USER                         carry-over
MONITOR_A2A_URL                   https://...{monitor_runtime_id}.../invocations  (또는 A2A endpoint)
INCIDENT_A2A_URL                  https://...{incident_runtime_id}.../invocations
CHANGE_A2A_URL                    https://...{change_runtime_id}.../invocations
OTEL_RESOURCE_ATTRIBUTES          service.name=aiops_demo_${user}_supervisor
AGENT_OBSERVABILITY_ENABLED       true
```

#### Change Runtime (신규)
```
GATEWAY_URL                       carry-over
OAUTH_PROVIDER_NAME               aiops_demo_${user}_change_gateway_provider
COGNITO_GATEWAY_SCOPE             aiops-demo-${user}-resource-server/invoke
CHANGE_MODEL_ID                   global.anthropic.claude-haiku-4-5-20251001  (cost option)
DEMO_USER                         carry-over
OTEL_RESOURCE_ATTRIBUTES          service.name=aiops_demo_${user}_change
AGENT_OBSERVABILITY_ENABLED       true
```

#### Monitor + Incident Runtime (carry-over + A2A 추가)
```
... (Phase 3/4 그대로) ...
A2A_ENABLED                       true   (entrypoint 분기에 사용 — A2A wrap 진입)
COGNITO_USER_POOL_ID              carry-over (Inbound Authorizer 검증용)
COGNITO_A2A_AUDIENCE              ${COGNITO_CLIENT_B_ID}   (audience claim 검증)
```

### 2-6. 의존성 변화 (`pyproject.toml`)

| 추가 dep | 사용 처 |
|---|---|
| `a2a-sdk` | Monitor/Incident/Change runtime (server) + Supervisor runtime (caller) |
| (선택) `httpx` | Supervisor 의 `RemoteA2aAgent` 내부 — a2a-sdk 가 이미 포함하면 추가 불필요 |
| (선택) `pyjwt` | operator CLI — Cognito JWT decode (선택, 검증은 안 함) |

→ 신규 dep 1~3 건. Phase 4 까지의 `strands-agents`, `bedrock-agentcore`, `bedrock-agentcore-starter-toolkit`, `boto3` 모두 carry-over.

---

## 3. Supervisor Agent 상세 (D1, D2, D8)

### 3-1. `agents/supervisor/shared/agent.py`

Phase 4 incident `shared/agent.py` 의 시그니처 확장 — `tools` 대신 `sub_agents` 를 받음:

```python
"""Supervisor Agent factory — sub_agents 주입 패턴 (Strands)."""
from pathlib import Path
from strands import Agent
from strands.handlers.callback_handler import null_callback_handler
from strands.models import BedrockModel
from a2a_sdk import RemoteA2aAgent  # caller-side (Supervisor 가 sub-agents 호출)

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def create_supervisor_agent(
    sub_agents: list,                         # [RemoteA2aAgent × 3]
    system_prompt_filename: str = "system_prompt.md",
) -> Agent:
    """Strands Agent + sub_agents 등록.

    sub_agents 는 caller (runtime/agentcore_runtime.py) 가 OAuth provider 로
    Bearer JWT 획득 후 RemoteA2aAgent 인스턴스로 wrap 하여 주입.
    """
    return Agent(
        model=BedrockModel(
            model_id=os.environ.get("SUPERVISOR_MODEL_ID") or "global.anthropic.claude-sonnet-4-6",
            region_name=os.environ.get("AWS_REGION") or "us-west-2",
        ),
        sub_agents=sub_agents,                 # ★ 핵심
        system_prompt=(_PROMPTS_DIR / system_prompt_filename).read_text(encoding="utf-8"),
        callback_handler=null_callback_handler,
    )
```

→ Strands `sub_agents` 파라미터가 LLM routing 의 핵심. system_prompt 가 routing 정책 (어떤 alarm 이면 Incident, 어떤 시점에 Change 호출 등) 을 LLM 에게 가르침.

### 3-2. `agents/supervisor/shared/prompts/system_prompt.md` (요지)

```markdown
# Supervisor Agent

당신은 운영 사고 대응 orchestrator. 운영자 질의를 받아 Monitor / Incident / Change
sub-agent 를 적절히 호출하고 통합 응답을 작성합니다.

## sub-agents
- monitor — CloudWatch alarm 상태 + history 분석. "최근 N시간 alarm 상황", "현재 살아있는 alarm" 류
- incident — 단일 alarm 의 runbook 진단 + 권장 조치. alarm_name 단위 호출
- change — 최근 24h 배포 변경 사항 read + incident log write. 배포 회귀 의심 / 사후 기록

## 호출 정책
1. 운영자가 "현재 상황" / "최근 alarm" 류 질의 → monitor 단독 호출 후 응답
2. monitor 응답에 real_alarms 가 있으면 → 각 alarm 마다 incident 호출 (병렬 가능)
3. real_alarms 1건 이상 + 24h 내 배포 있음 의심 → change 호출해 회귀 가능성 검증
4. 모든 incident 완료 후 → change 에 incident log append 요청

## 출력
JSON — schema:
{
  "summary": "<1-2 문장 요약>",
  "monitor": <monitor 응답 그대로>,
  "incidents": [<incident 응답 array>],
  "changes": <change 응답 또는 null>,
  "next_steps": ["<영어 verb phrase>", ...]
}
```

### 3-3. `agents/supervisor/runtime/agentcore_runtime.py` 핵심

```python
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from bedrock_agentcore.identity.auth import requires_access_token
from a2a_sdk import RemoteA2aAgent
from supervisor_shared.agent import create_supervisor_agent

GATEWAY_PROVIDER = os.environ["OAUTH_PROVIDER_NAME"]
A2A_PROVIDER = os.environ["A2A_OAUTH_PROVIDER_NAME"]


@requires_access_token(provider_name=A2A_PROVIDER, scopes=[os.environ["COGNITO_A2A_SCOPE"]],
                       auth_flow="M2M", into="access_token")
async def _fetch_a2a_token(*, access_token: str = "") -> str:
    """Supervisor 가 sub-agents 를 호출할 때 쓸 Bearer JWT — Client B M2M."""
    return access_token


app = BedrockAgentCoreApp()


@app.entrypoint
async def supervisor(payload: dict, context: Any) -> AsyncGenerator[dict, None]:
    query = payload.get("query") or ""
    a2a_token = await _fetch_a2a_token()

    # 3개 sub-agents 모두 동일 Bearer 사용 (Client B M2M)
    sub_agents = [
        RemoteA2aAgent(name="monitor", url=os.environ["MONITOR_A2A_URL"], bearer_token=a2a_token),
        RemoteA2aAgent(name="incident", url=os.environ["INCIDENT_A2A_URL"], bearer_token=a2a_token),
        RemoteA2aAgent(name="change", url=os.environ["CHANGE_A2A_URL"], bearer_token=a2a_token),
    ]

    agent = create_supervisor_agent(sub_agents=sub_agents)
    async for event in agent.stream_async(query):
        # ... SSE yield (Phase 3 패턴) ...
```

→ Phase 3/4 의 OAuth provider 패턴이 multi-provider 로 확장. caller 측 token 획득 로직만 추가.

### 3-4. caller-side OAuth provider 별도 발급 이유 (D4 부연)

Phase 3 의 단일 provider (`gateway_provider`) 는 scope `aiops-demo-${user}-resource-server/invoke` — Gateway 호출용. A2A 호출용 token 은 audience 가 sub-agent 의 Inbound Authorizer (Client B) → 별 scope `agent-invoke` 가 적합. 같은 Cognito UserPool 안에서 Resource Server scope 만 추가하면 충분 — 별 UserPool 신설 불필요.

---

## 4. Change Agent 상세 (D6)

### 4-1. `agents/change/shared/agent.py`

Phase 4 incident `shared/agent.py` 와 동일 시그니처. tools 만 다름:

```python
def create_agent(tools: list, system_prompt_filename: str) -> Agent:
    return Agent(
        model=BedrockModel(
            model_id=os.environ.get("CHANGE_MODEL_ID") or "global.anthropic.claude-haiku-4-5-20251001",
            region_name=os.environ.get("AWS_REGION") or "us-west-2",
        ),
        tools=tools,
        system_prompt=(_PROMPTS_DIR / system_prompt_filename).read_text(encoding="utf-8"),
        callback_handler=null_callback_handler,
    )
```

→ **모델 분리** — Change 는 Haiku (cost option). Monitor/Incident/Supervisor 의 Sonnet 과 구분. plan_summary 의 per-agent 모델 선택 정책 따름.

### 4-2. tool prefix 필터 (entrypoint)

```python
TOOL_TARGET_PREFIXES = ("deployments-storage___", "github-storage___")  # ★ 두 개 모두

# entrypoint 내부:
all_tools = mcp_client.list_tools_sync()
tools = [t for t in all_tools if t.tool_name.startswith(TOOL_TARGET_PREFIXES)]
```

→ Change 는 deployments read + incidents write (github-storage 의 신규 tool 활용 — §7-2). Monitor/Incident 의 도구는 격리.

### 4-3. system_prompt (요지)

```markdown
# Change Agent

당신은 변경 관리 전문가. 운영 사고가 의심될 때 최근 24시간 배포 이력을 조회하고
incident log 를 작성합니다.

## 도구
- deployments-storage___get_deployments_log(date) — 특정 일자의 배포 로그 read
- github-storage___append_incident(...) — incidents/ 에 사고 사후 기록 write
- (Phase 6a 후속) github-storage___get_runbook 은 호출 안 함 — Incident 가 처리

## 책임
1. Supervisor 가 호출 시 — 최근 24h deployments read → 의심 배포 식별
2. incident 응답을 받아 incidents/<date>.log 에 append (D6 — full write 권한)
3. severity 판단 (배포 회귀면 P1, 외부 원인이면 P3)
```

### 4-4. 권한 범위 (D6 부연)

D6 결정: "if proper, give all permission" — Change Agent 가 *적절한* 모든 권한 보유. 구체:

| 권한 | 부여? | 이유 |
|---|---|---|
| `deployments/` read | ✅ | Change 의 본질적 책임 |
| `incidents/` append (write) | ✅ | 사고 사후 기록 — Change 의 자연스러운 outcome |
| `runbooks/` read | ❌ | Incident 의 영역 — 책임 분리 |
| `deployments/` write | ❌ | 배포 자체는 외부 시스템 — workshop scope 외 |
| Lambda invoke (Gateway 외) | ❌ | Gateway 만 통한 도구 호출 (C2 원칙 보존) |

→ "full where appropriate" = 책임 영역 (deployments + incidents) 안에서 read+write 모두 허용. 책임 외 (runbooks/, 외부 배포) 는 명시 차단.

---

## 5. A2A 프로토콜 활성화 상세 (D2, D9)

### 5-1. server-side wrap

기존 `@app.entrypoint` 본문은 carry-over. `A2AStarletteApplication` 으로 둘러싸기만 함:

```python
# Monitor / Incident / Change 의 agentcore_runtime.py 모두 동일 패턴
from a2a_sdk import A2AStarletteApplication, AgentCard

agent_card = AgentCard(
    name=f"aiops_demo_{DEMO_USER}_monitor",   # 또는 incident, change
    description="...",
    skills=[{"name": "diagnose", "description": "..."}],   # Strands 의 도구/기능 노출
)

app = BedrockAgentCoreApp()
a2a_app = A2AStarletteApplication(agent_card=agent_card, runtime_app=app)


@app.entrypoint
async def monitor(payload, context):
    # ... 기존 entrypoint 그대로 ...
```

→ Phase 3 entrypoint 의 SSE yield 패턴 그대로. A2A 는 protocol layer 추가만.

### 5-2. AgentCard schema (요지)

```json
{
  "name": "aiops_demo_${user}_monitor",
  "description": "CloudWatch alarm 분석 + history 진단",
  "version": "1.0.0",
  "capabilities": ["streaming"],
  "skills": [
    {
      "name": "diagnose",
      "description": "Past or live alarm diagnosis",
      "inputSchema": {"type": "object", "properties": {"mode": {"enum": ["past", "live"]}, "query": {"type": "string"}}}
    }
  ]
}
```

→ AgentCard 는 sub-agent 의 capability 광고. Supervisor 의 LLM 이 AgentCard 를 읽어 routing 결정 가능.

### 5-3. JWT 검증 (Inbound Authorizer — D9)

각 sub-agent Runtime 의 deploy 단계에서:

```python
agentcore_control.create_agent_runtime(
    ...
    customJwtAuthorizer={
        "discoveryUrl": f"https://cognito-idp.{REGION}.amazonaws.com/{user_pool_id}/.well-known/openid-configuration",
        "allowedClients": [client_b_id],          # Client B M2M token 만 허용
        "allowedAudience": [client_b_id],
    },
)
```

→ AgentCore Runtime 자체가 JWT 검증 — issuer / audience / signature 모두 native 처리. Starlette middleware 작성 불필요.

### 5-4. caller-side `RemoteA2aAgent`

§3-3 코드 참조. 핵심:
- Bearer JWT 는 Supervisor 의 `_fetch_a2a_token()` 에서 획득 (Client B M2M)
- Strands `Agent.stream_async()` 가 sub_agents 호출 시 자동 Bearer 주입
- A2A JSON-RPC over HTTP — POST `${url}/jsonrpc` (a2a-sdk 표준)

---

## 6. Cognito Client A/B 상세 (D3, D4)

### 6-1. `infra/phase6a/cognito_extras.yaml` 핵심부

```yaml
Resources:
  # Resource Server scope 추가 — Phase 2 기존 ResourceServer 에 신규 scope
  # (Cognito 는 ResourceServer 에 scope 추가 시 ResourceServer 자체를 재정의 — Phase 2 stack 미터치 위해 별 ResourceServer 신설)
  AgentInvokeResourceServer:
    Type: AWS::Cognito::UserPoolResourceServer
    Properties:
      Identifier: !Sub "aiops-demo-${DemoUser}-agent-invoke"
      Name: !Sub "aiops-demo-${DemoUser}-agent-invoke"
      UserPoolId: !ImportValue aiops-demo-${DemoUser}-userpool-id   # Phase 2 export
      Scopes:
        - ScopeName: invoke
          ScopeDescription: A2A invoke between agents

  # Client A — operator CLI
  ClientA:
    Type: AWS::Cognito::UserPoolClient
    Properties:
      ClientName: !Sub "aiops-demo-${DemoUser}-client-a"
      UserPoolId: !ImportValue aiops-demo-${DemoUser}-userpool-id
      GenerateSecret: true
      ExplicitAuthFlows:
        - ALLOW_USER_PASSWORD_AUTH
        - ALLOW_REFRESH_TOKEN_AUTH
      AllowedOAuthFlows: [code]
      AllowedOAuthScopes:
        - !Sub "${AgentInvokeResourceServer.Identifier}/invoke"
      AllowedOAuthFlowsUserPoolClient: true

  # Client B — Supervisor M2M
  ClientB:
    Type: AWS::Cognito::UserPoolClient
    Properties:
      ClientName: !Sub "aiops-demo-${DemoUser}-client-b"
      UserPoolId: !ImportValue aiops-demo-${DemoUser}-userpool-id
      GenerateSecret: true
      AllowedOAuthFlows: [client_credentials]
      AllowedOAuthScopes:
        - !Sub "${AgentInvokeResourceServer.Identifier}/invoke"
      AllowedOAuthFlowsUserPoolClient: true

  # Operator user (Client A 가 인증할 사용자)
  OperatorUser:
    Type: AWS::Cognito::UserPoolUser
    Properties:
      Username: !Sub "operator-${DemoUser}"
      UserPoolId: !ImportValue aiops-demo-${DemoUser}-userpool-id
      MessageAction: SUPPRESS                      # 이메일 안 보냄
      DesiredDeliveryMediums: []
      UserAttributes:
        - Name: email_verified
          Value: "true"

Outputs:
  ClientAId: { Value: !Ref ClientA }
  ClientASecret: { Value: !GetAtt ClientA.ClientSecret }   # Sensitive
  ClientBId: { Value: !Ref ClientB }
  ClientBSecret: { Value: !GetAtt ClientB.ClientSecret }
  OperatorUserName: { Value: !Sub "operator-${DemoUser}" }
```

### 6-2. Phase 2 stack 보존 — 신규 ResourceServer 신설 (D4 부연)

Phase 2 stack 의 `aiops-demo-${user}-resource-server` 에 scope 추가는 stack 변경. 본 phase 는 **별 ResourceServer** (`aiops-demo-${user}-agent-invoke`) 신설 — Phase 2 stack 완전 미터치. trade-off: Cognito 안에서 두 ResourceServer 공존 — workshop 청중에게 "scope namespace 분리" 학습 기회.

### 6-3. Operator user 비밀번호 설정

CFN 으로 `MessageAction: SUPPRESS` 후 별도 boto3 후처리:

```bash
# infra/phase6a/deploy.sh 의 일부
TEMP_PASSWORD=$(openssl rand -base64 24)
aws cognito-idp admin-set-user-password \
    --user-pool-id "$COGNITO_USER_POOL_ID" \
    --username "operator-${DEMO_USER}" \
    --password "$TEMP_PASSWORD" \
    --permanent
echo "$TEMP_PASSWORD" > "${PROJECT_ROOT}/.env.operator"   # gitignore
```

`.env.operator` 는 gitignore + workshop 청중이 자기 비밀번호 보유. `agents/operator/cli.py` 가 이 파일 read.

---

## 7. deployments-storage Lambda 상세 (D5, D6)

### 7-1. CFN — Phase 4 github_lambda.yaml 패턴 정확 차용

`infra/phase6a/deployments_lambda.yaml` 은 Phase 4 의 Lambda + IAM Role + cross-stack inline policy 패턴 그대로. 차이:
- FunctionName: `aiops-demo-${user}-deployments-storage`
- Code: `./lambda_src/deployments_storage`
- 신규 cross-stack policy: `aiops-demo-${user}-phase6a-gateway-invoke-deployments` on Phase 2 Gateway Role

→ Phase 4 의 review fix (cross-stack inline policy 패턴) 그대로 적용 — Phase 6a stack delete 시 policy 만 detach, Phase 2 Role 보존.

### 7-2. Lambda handler — 두 도구

```python
# infra/phase6a/lambda_src/deployments_storage/handler.py
def lambda_handler(event, context):
    tool = _tool_name(context)
    params = event or {}

    if tool.endswith("get_deployments_log"):
        date = params.get("date", "")
        path = f"deployments/{date}.log"
        try:
            content = _fetch_github_file(repo, branch, path)
            return {"deployments_found": True, "path": path, "content": content}
        except urllib.error.HTTPError as e:
            return {"deployments_found": False, "path": path, "status": e.code, "error": str(e)}

    if tool.endswith("append_incident"):
        # D6: write 권한 — incidents/<date>.log 에 append
        date = params.get("date", "")
        body = params.get("body", "")
        path = f"incidents/{date}.log"
        try:
            existing = _fetch_github_file(repo, branch, path)
        except urllib.error.HTTPError as e:
            existing = "" if e.code == 404 else None
            if existing is None: raise
        new_content = (existing + "\n" + body).strip() + "\n"
        _put_github_file(repo, branch, path, new_content, message=f"Incident append {date}")
        return {"appended": True, "path": path}

    return {"error": f"unknown tool: {tool!r}"}
```

→ `_put_github_file` 는 GitHub Contents API PUT — token scope 가 `repo` (write) 필요. workshop README 에 명시.

### 7-3. Gateway Target schema

```python
DEPLOYMENTS_TOOL_SCHEMA = [
    {
        "name": "get_deployments_log",
        "description": "Read deployments/<date>.log from GitHub.",
        "inputSchema": {
            "type": "object", "required": ["date"],
            "properties": {"date": {"type": "string", "description": "YYYY-MM-DD"}}
        }
    },
    {
        "name": "append_incident",
        "description": "Append incident record to incidents/<date>.log on GitHub.",
        "inputSchema": {
            "type": "object", "required": ["date", "body"],
            "properties": {
                "date": {"type": "string"},
                "body": {"type": "string", "description": "Incident summary markdown"}
            }
        }
    },
]
```

→ Phase 4 의 `setup_github_target.py` 와 동일 구조. `setup_deployments_target.py` 는 create-or-update 패턴 (Phase 4 의 A1 fix 차용) ✅.

### 7-4. github-storage Lambda 와 분리한 이유 (D5 부연)

| 측면 | github-storage 통합 | deployments-storage 분리 (선택) |
|---|---|---|
| Lambda 코드 분량 | +50 LoC (handler dispatch 추가) | 별 ~150 LoC |
| IAM 권한 | 같은 Role — read+write 혼재 | 별 Role — write 권한 격리 |
| Tool schema | 1 Target 의 4 tools | 2 Target 의 2+1 tools |
| Caller agent 격리 | Incident + Change 가 같은 Lambda 호출 | Incident → github-storage, Change → deployments-storage |
| teardown 영향 | github-storage Lambda 삭제 시 deployments 도 사라짐 | Phase 6a 만 삭제 가능 |

→ 분리 선택 — agent 별 도구 격리 + write 권한의 lambda-수준 격리 + Phase 별 teardown 독립성. 통합 대안의 코드 절약은 ~80 LoC 미만 — workshop educational 가치 (agent 별 caller 흐름 가시성) 가 더 큼.

---

## 8. Operator CLI 상세 (D3)

### 8-1. `agents/operator/cli.py` 핵심

```python
"""Operator CLI — Cognito Client A 인증 + Supervisor A2A 호출."""
import argparse, json, os, sys
import boto3, requests
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(PROJECT_ROOT / ".env.operator", override=True)        # 비밀번호

REGION = os.environ.get("AWS_REGION", "us-west-2")
COGNITO_CLIENT_A_ID = os.environ["COGNITO_CLIENT_A_ID"]
COGNITO_CLIENT_A_SECRET = os.environ["COGNITO_CLIENT_A_SECRET"]
USERNAME = f"operator-{os.environ['DEMO_USER']}"
PASSWORD = os.environ["OPERATOR_PASSWORD"]                        # .env.operator
SUPERVISOR_A2A_URL = os.environ["SUPERVISOR_A2A_URL"]


def get_jwt() -> str:
    """Cognito Client A 로 USER_PASSWORD_AUTH → JWT."""
    cognito = boto3.client("cognito-idp", region_name=REGION)
    resp = cognito.initiate_auth(
        ClientId=COGNITO_CLIENT_A_ID,
        AuthFlow="USER_PASSWORD_AUTH",
        AuthParameters={"USERNAME": USERNAME, "PASSWORD": PASSWORD},
    )
    return resp["AuthenticationResult"]["IdToken"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", required=True)
    args = parser.parse_args()

    jwt = get_jwt()
    payload = {"jsonrpc": "2.0", "method": "stream", "id": 1, "params": {"query": args.query}}
    headers = {"Authorization": f"Bearer {jwt}", "Content-Type": "application/json"}

    with requests.post(f"{SUPERVISOR_A2A_URL}/jsonrpc", json=payload, headers=headers, stream=True) as resp:
        for line in resp.iter_lines():
            if line:
                # SSE parse — Phase 4 invoke_runtime.py 패턴 carry-over
                ...


if __name__ == "__main__":
    main()
```

### 8-2. Supervisor 단일 진입점 — invoke_runtime.py 와의 차이

`agents/supervisor/runtime/invoke_runtime.py` 는 *관리자용* — boto3 SIGV4 로 Supervisor 직접 호출 (디버깅). `agents/operator/cli.py` 는 *워크샵 청중용* — Cognito 인증 통과해 A2A 로 호출 (정상 경로).

---

## 9. Acceptance + smoke test

### 9-1. P6a-A1 ~ A6

| # | 검증 항목 | 검증 방법 |
|---|---|---|
| **P6a-A1** | Phase 4 회귀 없음 | Phase 4 의 P4-A2 + P4-A4 재실행 — Incident 단독 invoke (status-check + noisy-cpu) 가 그대로 통과 |
| **P6a-A2** | Operator CLI → Supervisor → 3 sub-agents 통합 응답 | `python agents/operator/cli.py --query "현재 상황 진단해줘"` → JSON 응답에 monitor + incidents[] + change 모두 포함 |
| **P6a-A3** | A2A 호출 검증 (server 측 trace) | sub-agent CloudWatch 로그에 Bearer JWT 검증 + caller=Supervisor 흔적. Inbound Authorizer rejection (잘못된 token) → 401 |
| **P6a-A4** | Change Agent deployments read | Supervisor 응답의 `changes.deployments` 가 `2026-05-08.log` content 포함 |
| **P6a-A5** | Change Agent incidents/ write | Supervisor 호출 후 GitHub repo 의 `incidents/<date>.log` 가 신규 파일 또는 append 됨 |
| **P6a-A6** | Phase 6a teardown 후 Phase 0/2/3/4 자원 보존 | `infra/phase6a/teardown.sh` + Supervisor/Change `teardown.sh` 후 — Monitor + Incident Runtime / Cognito UserPool / Client C / Gateway / 기존 3 Lambda + 3 Target 모두 그대로. Phase 2 Gateway Role 의 phase4 inline policy 도 보존 (phase6a 만 detach) |

### 9-2. smoke test 절차 (요약)

```bash
# 1. 사전 — Phase 4 alive (Phase 2/3/4 deploy 통과)
# 2. SSM token scope 확장 — repo:read → repo (write 포함)
read -s -p "GitHub PAT (repo full): " GH_PAT && \
  aws ssm put-parameter --name /aiops-demo/github-token \
    --type SecureString --value "$GH_PAT" --region us-west-2 --overwrite && unset GH_PAT

# 3. Phase 6a infra
bash infra/phase6a/deploy.sh                          # cognito_extras + deployments_lambda + Target

# 4. Monitor + Incident A2A wrap 재배포
uv run agents/monitor/runtime/deploy_runtime.py
uv run agents/incident/runtime/deploy_runtime.py

# 5. Change + Supervisor 신규 배포
uv run agents/change/runtime/deploy_runtime.py
uv run agents/supervisor/runtime/deploy_runtime.py

# 6. P6a-A2 — Operator CLI 통합 호출
python agents/operator/cli.py --query "현재 상황 진단해줘"

# 7. P6a-A4/A5 — GitHub repo 확인
git pull && cat incidents/$(date +%Y-%m-%d).log

# 8. P6a-A6 — teardown
bash agents/supervisor/runtime/teardown.sh
bash agents/change/runtime/teardown.sh
bash infra/phase6a/teardown.sh
# Monitor/Incident Runtime + Phase 2/3/4 자원 살아있는지 확인
```

---

## 10. Out of scope + Reference codebase 매핑

### 10-1. Out of scope (Phase 6a 가 안 하는 것)

| 항목 | 도입 시점 | 미루는 이유 |
|---|---|---|
| **AgentCore NL Policy** | **본 프로젝트 영구 제외** | 워크샵 분량 (Strands + AgentCore + A2A + sub_agents 학습량 이미 큼). Phase 5 건너뜀 |
| **AgentCore Memory + Strands hooks** | Phase 7+ | cross-agent memory 본격 시나리오는 incidents/ 누적 선행 (D10) |
| **Workflow Orchestrator** | Phase 6b stretch | Supervisor vs Workflow 비교 측정 — 시간 여유 시 |
| **`incidents/` Memory 통합** | Phase 7+ | 본 phase 는 GitHub 명시 write — Memory 비교는 후속 |
| **Phase 4 sequential CLI 부활** | 미고려 | D7 — Step D 미구현 사실 + Supervisor 가 단일 multi-agent 경로 |
| **EC mall 통합** | Phase 7 | 외부 의존 |
| **S3 fallback** | Phase 7+ | GitHub 충분 |
| **Anonymous A2A (Bearer 없는)** | 미고려 | 모든 A2A 호출 = Cognito JWT 검증 (D9) |

### 10-2. Reference codebase 매핑

| 차용 | 본 phase 사용처 |
|---|---|
| `/home/ubuntu/amazon-bedrock-agentcore-samples/02-use-cases/A2A-multi-agent-incident-response/` | A2A 패턴 — cognito.yaml (Client A/B + ResourceServer scope), `host_adk_agent/agent.py:37-100` (RemoteA2aAgent), agentcore_runtime A2A wrap |
| `/home/ubuntu/developer-briefing-agent/` | dba 패턴 — Supervisor/Change 의 `shared/agent.py + prompts/` 분리, intuitive function naming, deploy_runtime.py 5단계 |
| `/home/ubuntu/sample-deep-insight/managed-agentcore/` | per-agent 모델 분리 (Supervisor/Change 가 별 MODEL_ID env), OTEL service.name 자동 |
| Phase 4 `infra/phase4/github_lambda.yaml` | `infra/phase6a/deployments_lambda.yaml` 의 cross-stack policy 패턴 |
| Phase 4 `infra/phase4/setup_github_target.py` | `infra/phase6a/setup_deployments_target.py` 의 create-or-update 패턴 (A1 fix) |

---

## 11. Transition diff 예고 (Phase 6a → 7+)

| 항목 | Phase 6a (현) | Phase 7+ |
|---|---|---|
| Memory | 보류 | 활성화 (cross-agent context — Incident 가 prior incident lookup) |
| EC mall | mock instance | 실 EC mall 통합 (alarm 확장만으로 동일 시나리오) |
| `incidents/` 누적 | GitHub append (Change 가 write) | Memory 또는 GitHub — 어느 쪽이 educational 더 가치 있는지 비교 |
| Workflow Orchestrator | 미사용 | (stretch) Supervisor vs Workflow 비교 측정 |
| S3 fallback | 미사용 | GitHub 차단 시 동등 인터페이스 swap 시연 |

→ Phase 6a 가 multi-agent orchestration 의 minimum 골격. 이후는 시나리오 다양화 / 비교 측정 / 운영 내구성 강화.

---

## 부록 A. 의사결정 빠른 참조

```
D1   Supervisor → Monitor + Incident + Change (3개)
D2   A2A — server (3 sub) + caller (Supervisor)
D3   Cognito Client A — UserPasswordAuth + 워크샵 prefix user
D4   Cognito Client B — client_credentials + scope agent-invoke
D5   deployments storage — 신규 Lambda + Target (github-storage 와 분리)
D6   Change Agent — read deployments + write incidents (full where appropriate)
D7   Phase 4 sequential CLI — 본 design 미처리 (Step D 미구현)
D8   Strands sub_agents — RemoteA2aAgent × 3
D9   Inbound Authorizer — Cognito UserPool 직접 (Starlette middleware 회피)
D10  AgentCore Memory — 계속 보류 (Phase 7+ 재평가)
```

---

## 부록 B. 디렉토리 구조 (구현 후 예상)

```
aiops-multi-agent-demo/
├── agents/
│   ├── monitor/        # Phase 3 (entrypoint A2A wrap 추가)
│   ├── incident/       # Phase 4 (entrypoint A2A wrap 추가)
│   ├── supervisor/     # ★ Phase 6a 신규
│   ├── change/         # ★ Phase 6a 신규
│   └── operator/       # ★ Phase 6a 신규 — Operator CLI
├── infra/
│   ├── phase2/         # Phase 2 cognito + 2 Lambda
│   ├── phase4/         # Phase 4 github_lambda
│   └── phase6a/        # ★ 신규 — cognito_extras + deployments_lambda + Operator user
├── runbooks/           # Phase 4 partial (Phase 6a 보강 시 noisy-cpu.md 등 추가)
├── deployments/        # ★ Phase 6a — 24h 배포 로그 minimal seed
├── incidents/          # ★ Phase 6a 첫 등장 — Change 가 append (write)
└── docs/design/
    ├── phase2.md
    ├── phase3.md
    ├── phase4.md
    └── phase6a.md      # ★ 본 문서
```

→ Phase 5 디렉토리는 없음 (skip). Phase 6b/7 은 별도 design 시점에 추가.
