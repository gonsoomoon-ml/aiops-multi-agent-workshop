# Phase 6a — Supervisor + Change Agent + A2A 활성화

> 📍 **참고**: `plan_summary.md` 에서 이 phase 는 **Phase 5** 로 재번호 (2026-05-09) — 옛 Phase 5 (NL Policy) 가 stretched 로 이동, Phase 6b 폐기로 인한 정리. 파일명 / commit / 코드 디렉토리 (`agents/*_a2a/`) 는 역사 보존을 위해 `6a` 그대로 유지.

> Phase 4 (`docs/design/phase4.md`) 가 multi-agent 진입을 sequential CLI 로 시연한 후, 이 단계에서 **Supervisor Runtime + Change Agent Runtime + A2A 프로토콜 (server + caller 양쪽)** + **Cognito Client A/B** + **deployments-storage Lambda** 를 추가한다.
> Phase 5 (AgentCore NL Policy) 는 본 프로젝트 scope 에서 **건너뜀** — Phase 4 → Phase 6a 직행. Phase 5 결정에 묶여있던 항목 (incidents/ log, AgentCore Memory) 은 §1 에서 재배치.
> Phase 0/2/3/4 자원 (Cognito UserPool, Client, Gateway, 3 Target, Lambda × 3, Monitor + Incident Runtime) 은 **무변경** — Phase 6a PR 영향 범위 격리, 회귀 0건 목표.

> **A2A 개념 사전 학습**: 본 phase 는 A2A 프로토콜을 처음 활성화한다. A2A 가 무엇이고 어떻게 동작하는지에 대한 직관적 설명은 `docs/research/a2a_intro.md` 참고. 본 design 은 그 기반 위에서 구체적 구현 결정을 다룬다.
>
> **Reference truth**: 2026-05-08 research 에서 Strands SDK + AgentCore Runtime A2A 의 **실제 API 표면** 을 확인 (`docs/research/a2a_intro.md` §참고 + design 본문 각주). 본 design 의 코드 sketch 는 그 결과를 반영한 *교정본* — 초기 design (commit `f380dcc`) 의 가정 일부 (Strands `Agent(sub_agents=[RemoteA2aAgent…])`, `A2AStarletteApplication` direct wrap, A2A 환경에서 `@app.entrypoint` 유지 등) 는 **실제 API 와 불일치하여 본 follow-up 으로 수정됨**.
>
> **Preservation rule (2026-05-09)**: workshop instructor 가 Phase 4 (HTTP, 작동) 와 Phase 6a (A2A, 신규) 를 **side-by-side** 비교 가능하도록 `agents/monitor/`, `agents/incident/` 등 이전 phase 코드는 **수정 금지**. Phase 6a 의 Monitor/Incident A2A 변형은 신규 디렉토리 `agents/monitor_a2a/` + `agents/incident_a2a/` 에 작성 (originally §2-4 의 in-place 수정 계획을 폐기). 변경 사항: §2-3 에 두 디렉토리 추가, §2-4 의 monitor/incident 수정 행 제거, Step F 가 retrofit 이 아닌 신규 작성으로 정의 변경.
>
> **Option X (2026-05-09 review)**: 사용자 결정 — **새 Cognito 자원 추가 0**. Phase 2 의 Client 만 재사용 (sub-agent A2A inbound + Supervisor outbound 모두). Operator CLI 는 Phase 4 패턴 SigV4 IAM 그대로. AgentCore `customJWTAuthorizer.allowedClients` 가 토큰의 `aud` (= client_id) 만 검증, scope 미검증 → Gateway scope 토큰이 multiple audience 에 통과. 영향: D3, D4 폐기 (Cognito Client A/B 제거); §6 단순화 (`cognito_extras.yaml` 삭제); §8 단순화 (Operator CLI 가 boto3 SigV4); §2-1 인벤토리 -7 자원 (Cognito Client A + B + ResourceServer + OperatorUser + 2 OAuth provider variant). 약 -325 LoC 단순화.
>
> **Change Agent 연기 (2026-05-09 review)**: 사용자 결정 — Change Agent (D6) 는 **후속 phase 로 연기**. Phase 6a 는 *A2A activation* 한 가지 핵심 메시지에 집중. 영향: D5/D6 폐기 (deployments-storage Lambda + Target 삭제); §4 (Change Agent), §7 (deployments-storage Lambda) 무효화; sub-agent 3 → 2 (monitor_a2a + incident_a2a 만); `agents/change/`, `infra/phase6a/`, `deployments/`, `incidents/` 4 디렉토리 삭제; Phase 6a 의 infra/ stack 0 (Phase 0/2/3/4 자원만 사용). 약 -1100 LoC 추가 단순화. Change + write tool + per-agent 모델 분리는 Phase 6b (또는 별 phase) 단독 주제로 배치.
>
> **Operator CLI 통합 (2026-05-09 review)**: 사용자 결정 — Option X 후 `agents/operator/cli.py` 와 `agents/supervisor/runtime/invoke_runtime.py` 가 둘 다 SigV4 IAM 으로 95% 코드 중복. **`agents/operator/` 디렉토리 삭제**, `agents/supervisor/runtime/invoke_runtime.py` 가 Operator + admin 통합 진입점. §8 (Operator CLI 상세) 무효화. Phase 4 pattern (각 agent 자기 invoke_runtime.py) 와 정합.
>
> **Option G — Phase 4 shared/ 직접 재사용 (2026-05-09 review)**: 사용자 결정 — `agents/monitor_a2a/shared/` + `agents/incident_a2a/shared/` 가 Phase 4 와 100% 동일 copy → 청중 인지 부하만 추가. **두 디렉토리 삭제**, `monitor_a2a/runtime/` + `incident_a2a/runtime/` 의 import 와 build context 모두 Phase 4 `agents/monitor/shared/` + `agents/incident/shared/` 직접 재사용. 영향: §2-3 의 monitor_a2a/incident_a2a shared/** 행 무효화; ~590 LoC 단순화; phase-by-phase 메시지 ("Phase 4 위에 A2A wrap 만 추가") 명확화. preservation rule 정합 (Phase 4 read-only — 수정 0, import + build context copy).

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

→ Phase 6a PR 영향 범위 = `agents/{supervisor,change,operator}/` 신규 + `infra/phase6a/{cognito_extras,deployments_lambda}.yaml` 신규 + Monitor/Incident `agentcore_runtime.py` 에 A2A server wrap 추가 + 두 Runtime 재배포 (코드 변경분 반영) + `data/runbooks/` 또는 `deployments/` 컨텐츠 minimal seed.

**Cognito UserPool / Client / Resource Server / Gateway / 기존 3 Target / Lambda × 3 / IAM Roles 모두 미터치.** 신규 Cognito Client A/B 는 별 CFN stack (`aiops-demo-${user}-phase6a-cognito-extras`) 으로 격리.

---

## 0-4. Educational 가치

워크샵 청중이 Phase 6a PR 을 line-by-line 읽었을 때 학습하는 것:

1. **Strands `sub_agents` 패턴** — Supervisor 가 `RemoteA2aAgent(url=..., bearer_token=...)` 인스턴스 3개를 보유. LLM 이 routing 결정. Phase 4 의 "CLI 가 caller" 패턴이 LLM-driven 으로 진화.
2. **A2A 프로토콜 server wrap** — 기존 `@app.entrypoint` 본문은 carry-over, `A2AStarletteApplication` 으로 둘러싸기만 함. AgentCard schema 노출. Bearer JWT 검증 via AgentCore Inbound Authorizer (Cognito UserPool 으로 직접) 또는 Starlette middleware.
3. **Cognito 의 다중 클라이언트 분리** — Client (Gateway M2M, Phase 2 에서 정착) + Client A (operator, Authorization Code 또는 USER_PASSWORD) + Client B (M2M, A2A scope) 의 책임 분리. 동일 UserPool 안에서 audience 다른 JWT.
4. **OAuth2CredentialProvider 의 multi-provider 패턴** — Supervisor Runtime 에 두 provider: (a) `gateway_provider` (Client, Gateway 호출용), (b) `a2a_provider` (Client B, sub-agents 호출용). Phase 3 OAuth gotcha 가 multi-provider 로 자연 확장.
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
| **D3** | Cognito Client A (operator → Supervisor) | **신규 발급 — UserPasswordAuth grant + 워크샵 prefix user** | (b) Authorization Code with PKCE / (c) Client 재사용 | 워크샵 단순성 — operator CLI 가 username/password 로 1줄 prompt 후 JWT 획득. PKCE 는 browser 흐름 → CLI 불편. Client 재사용 시 audience/scope 충돌 (Gateway 용) |
| **D4** | Cognito Client B (Supervisor M2M → sub-agents) | **신규 발급 — client_credentials grant + 신규 scope `agent-invoke`** | (b) Client 재사용 (Gateway scope `/invoke` 도 부여) / (c) Client A 재사용 | Client 의 scope `aiops-demo-${user}-resource-server/invoke` 는 Gateway 전용 — sub-agent A2A audience 와 분리 필요. 신규 scope `agent-invoke` 로 audience 격리 → 권한 누출 방지. Client A 는 user-bound 토큰이라 M2M 부적합 |
| **D5** | deployments storage 분리 | **신규 Lambda + 신규 Gateway Target** | (b) github-storage Lambda 에 `get_deployments_log` tool 추가 / (c) S3 직접 read | user 결정 ("keep original"). plan_summary 의 architecture diagram 도 GitHub Target 1개 (`rules/ data/runbooks/ deployments/`) 통합 묘사이지만, **권한 분리 + Change Agent 의 caller 격리** + 향후 write 권한 확장 여지 (D6) 를 위해 분리. educational scope memory 는 plumbing 추상화 — 그러나 **agent 별 도구 분리**는 plumbing 이 아니라 architecture decision 영역 |
| **D6** | Change Agent 권한 범위 | **read deployments + write incidents/ + 적절한 추가 write (full where appropriate)** | (b) read-only / (c) read + 명시적 1 tool write | user 결정. workshop 청중에게 "Agent 가 read-only 가 아니라 write 도 할 수 있다" 는 educational 가치 + Change Agent 의 본질 (변경 추적/롤백 결정) 이 read-only 로는 불완전 |
| **D7** | Phase 4 sequential CLI 처리 | **본 design 에서 다루지 않음** — Step D 가 미구현이므로 deprecate 할 코드 없음. Supervisor 가 단일 multi-agent 경로 | (b) sequential CLI 별도 유지 (educational 비교용) / (c) `--legacy-sequential` 옵션 | user 결정. 기존 코드 부재 + Supervisor 가 LLM-driven 으로 routing 시연 → CLI hardcoded routing 과 비교 가치는 design doc §0-4 의 "진화 line-level 비교" 로 충분 |
| **D8** | Sub-agent 호출 패턴 (caller 측) | **`@tool` 함수 N개로 wrap — 각 tool 이 `a2a.client.A2AClient.send_message()` 직접 호출** | (b) `Agent(sub_agents=[RemoteA2aAgent(...)])` — **Strands 미지원 (existence 확인)** / (c) `strands_tools.A2AClientToolProvider` — generic `target_agent_url` 노출, 덜 ergonomic | research 결과: Strands `Agent.__init__` 에 `sub_agents` 파라미터 자체 없음. `RemoteA2aAgent` 는 Google ADK 전용. Strands 표준은 sub-agent 를 *도구로 노출* — `@tool` wrapper. 이름이 의도된 (`call_monitor`, `call_incident`, `call_change`) tool 이 LLM routing 에 더 명확. Reference: `02-use-cases/A2A-realestate-agentcore-multiagents/realestate_coordinator/agent.py:325-361` |
| **D9** | AgentCore Inbound Authorizer | **사용 — Cognito UserPool 을 Runtime 의 Authorizer 로 직접 등록** (`customJwtAuthorizer.allowedClients`) | (b) Starlette middleware 로 직접 JWT 검증 / (c) Lambda authorizer | AgentCore native 기능 활용 (educational). middleware 는 코드 부담 + 검증 logic 직접 작성. Lambda authorizer 는 Phase 6a 외부 자원 추가. **주의**: AgentCore 는 `aud`/`client_id` 만 검증 — scope 검증 안 함 (§5-3, §6-2 부연) |
| **D10** | AgentCore Memory + cross-agent context | **계속 보류 — Phase 7+ 재평가** | (b) Phase 6a 도입 / (c) dormant flag 만 추가 | Phase 4 D6 carry-over. cross-agent memory 본격 시나리오 (Incident 가 prior incident lookup, Supervisor 가 history-aware routing) 는 incidents/ 누적이 선행 — 누적 자체가 별도 phase. premature 회피 |

### 1-2. 결정 간 의존 관계

```
D1 (Supervisor → 3 sub-agents)
 └─→ D2 (A2A 활성화 — caller 와 server 동시)
       ├─→ D3 (Client A — operator 진입)
       ├─→ D4 (Client B — Supervisor M2M)
       ├─→ D8 (`@tool` 함수 wrapping a2a.client — Strands sub-agent 표준 패턴)
       └─→ D9 (Inbound Authorizer — server 측 JWT 검증, allowedClients 만)

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
| 3 | OAuth2CredentialProvider | `aiops_demo_${DEMO_USER}_supervisor_gateway_provider` | 1 | Supervisor deploy (boto3) — Client M2M, Gateway 호출용 |
| 4 | OAuth2CredentialProvider | `aiops_demo_${DEMO_USER}_supervisor_a2a_provider` | 1 | Supervisor deploy — **Client B M2M, sub-agents A2A 호출용** |
| 5 | OAuth2CredentialProvider | `aiops_demo_${DEMO_USER}_change_gateway_provider` | 1 | Change deploy — Client M2M, Gateway 호출용 |
| 6 | IAM Role (Supervisor Runtime) | `AmazonBedrockAgentCoreSDKRuntime-...-aiops_demo_${user}_supervisor-...` | 1 | toolkit 자동 |
| 7 | IAM Role (Change Runtime) | `AmazonBedrockAgentCoreSDKRuntime-...-aiops_demo_${user}_change-...` | 1 | toolkit 자동 |
| 8 | IAM inline policy | `SupervisorRuntimeExtras` | 1 | Supervisor deploy — 두 OAuth provider 의 GetResourceOauth2Token + Cognito secret read |
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
| Cognito UserPool + Client + Resource Server (기존 scope `/invoke`) | **그대로** |
| Gateway (`aiops-demo-${user}-gateway-...`) | **그대로** |
| Gateway Target × 3 (history-mock, cloudwatch-wrapper, github-storage) | **그대로** |
| Lambda × 3 (history-mock, cloudwatch-wrapper, github-storage) | **그대로** |
| Phase 2 IAM Role `aiops-demo-${user}-gateway-role` | **그대로** (Phase 4 가 inline policy 추가, Phase 6a 가 또 1건 추가 — D5) |
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

#### `agents/monitor_a2a/` (신규 — Phase 4 monitor/ 의 A2A 변형, preservation rule)
| 파일 | 분량 | 역할 |
|---|---|---|
| `agents/monitor_a2a/__init__.py` | 0 LoC | — |
| `agents/monitor_a2a/shared/**` | (Phase 4 monitor/shared 전체 복사 — agent.py, auth_local.py, mcp_client.py, env_utils.py, modes.py, prompts/, tools/) | self-contained — Phase 4 monitor 와 무관하게 독립 동작 |
| `agents/monitor_a2a/runtime/agentcore_runtime.py` | ~80 LoC | **A2A protocol** — `A2AServer(agent=…, http_url=AGENTCORE_RUNTIME_URL, serve_at_root=True).to_fastapi_app()` + uvicorn port 9000. `@app.entrypoint` 미사용 (A2A protocol 특성) |
| `agents/monitor_a2a/runtime/deploy_runtime.py` | ~290 LoC | Phase 4 monitor `deploy_runtime.py` 패턴 + protocolConfiguration A2A + customJWTAuthorizer (allowedClients=[Client B]) |
| `agents/monitor_a2a/runtime/Dockerfile` | toolkit 자동 | EXPOSE 9000 |
| `agents/monitor_a2a/runtime/requirements.txt` | ~5 줄 | `strands-agents`, `a2a-sdk`, `bedrock-agentcore`, `fastapi`, `uvicorn` |
| `agents/monitor_a2a/runtime/teardown.sh` | ~120 줄 | Phase 4 monitor teardown 패턴 |
| `agents/monitor_a2a/runtime/README.md` | ~30 줄 | — |

→ **agent name**: `aiops_demo_${DEMO_USER}_monitor_a2a` (Phase 4 와 별도 Runtime). OAuth provider: `{agent_name}_gateway_provider`.

#### `agents/incident_a2a/` (신규 — Phase 4 incident/ 의 A2A 변형)
| 파일 | 분량 | 역할 |
|---|---|---|
| `agents/incident_a2a/__init__.py` | 0 LoC | — |
| `agents/incident_a2a/shared/**` | (Phase 4 incident/shared 전체 복사 — agent.py + prompts/) | — |
| `agents/incident_a2a/runtime/agentcore_runtime.py` | ~90 LoC | A2A protocol + Strands Agent + Gateway tool filter (`github-storage___`) |
| `agents/incident_a2a/runtime/deploy_runtime.py` | ~310 LoC | Phase 4 incident pattern (Option A — monitor_a2a/shared + incident_a2a/shared 둘 다 build context 복사) + A2A authorizer |
| 기타 | (monitor_a2a 와 동일) | |

→ **agent name**: `aiops_demo_${DEMO_USER}_incident_a2a`. Helper 의 출처는 **`monitor_a2a/shared`** (Phase 4 monitor/shared 가 아님 — preservation 위해 격리).

#### `data/runbooks/` 또는 `deployments/`
| 파일 | 분량 | 역할 |
|---|---|---|
| `deployments/README.md` | ~30 줄 | 디렉토리 구조 + 형식 |
| `deployments/2026-05-08.log` | ~10 줄 | minimal seed (워크샵 시점 기준 mock 배포 로그) |

### 2-4. 코드 파일 (변경)

| 파일 | 변경 분량 | 변경 내용 |
|---|---|---|
| `agents/monitor/**` | **수정 없음 (preservation rule)** | Phase 4 Monitor 코드 미터치. A2A 변형은 `agents/monitor_a2a/` 신규 디렉토리에 (§2-3-bis) |
| `agents/incident/**` | **수정 없음 (preservation rule)** | Phase 4 Incident 코드 미터치. A2A 변형은 `agents/incident_a2a/` 신규 디렉토리에 (§2-3-bis) |
| `pyproject.toml` | +5 줄 | `a2a-sdk>=0.3.24,<1.0` (Strands 1.38 호환 핀) + `fastapi>=0.115.0` (Strands `A2AServer` 의존) — additive만 |
| `docs/design/phase6a.md` | (이 파일) | preservation rule 반영 follow-up |

### 2-5. Runtime 환경 변수

#### Supervisor Runtime (신규)
```
GATEWAY_URL                       carry-over from Phase 2
OAUTH_PROVIDER_NAME               aiops_demo_${user}_supervisor_gateway_provider
A2A_OAUTH_PROVIDER_NAME           aiops_demo_${user}_supervisor_a2a_provider
COGNITO_GATEWAY_SCOPE             aiops-demo-${user}-resource-server/invoke
COGNITO_A2A_SCOPE                 aiops-demo-${user}-agent-invoke/invoke   (별 ResourceServer)
SUPERVISOR_MODEL_ID               global.anthropic.claude-sonnet-4-6
DEMO_USER                         carry-over
MONITOR_RUNTIME_ARN               arn:aws:bedrock-agentcore:{region}:{acct}:runtime/{id}
INCIDENT_RUNTIME_ARN              (동일 형식)
CHANGE_RUNTIME_ARN                (동일 형식)
OTEL_RESOURCE_ATTRIBUTES          service.name=aiops_demo_${user}_supervisor
AGENT_OBSERVABILITY_ENABLED       true
```

> **A2A URL 자동 구성** (research 확인): Supervisor 의 `@tool` 들이 ARN 만 알면 caller-side 에서 `https://bedrock-agentcore.{region}.amazonaws.com/runtimes/{quote(arn)}/invocations/` 자동 조립. AgentCard discovery 는 그 base + `.well-known/agent-card.json`. Phase 4 의 `invoke_runtime.py` 가 이미 같은 URL 생성 패턴 사용 중 → 직접 carry-over.

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

#### Monitor + Incident Runtime (carry-over + A2A 전환)
```
... (Phase 3/4 그대로 — GATEWAY_URL, OAUTH_PROVIDER_NAME, COGNITO_GATEWAY_SCOPE 등) ...
AGENTCORE_RUNTIME_URL             AgentCore 가 자동 주입 — AgentCard `url` 필드에 그대로 사용 (research §6 gotcha)
```

> **A2A_ENABLED dual-mode env 제거** (research 확인): A2A Runtime 은 `protocolConfiguration: A2A` 로 *protocol 자체가 다름* (port 9000, root path, JSON-RPC). 기존 HTTP 모드 entrypoint 와 dual-mode 분기 불가능. Monitor/Incident 코드를 A2A 전용으로 일원화 — local 단독 테스트는 별 entry-script (예: `agents/monitor/runtime/local_dev.py`) 로 분리하거나 Strands Agent 를 직접 호출하는 unit test 로 대체.
> **`COGNITO_USER_POOL_ID`, `COGNITO_A2A_AUDIENCE` env 불필요** (research 확인): JWT 검증은 AgentCore Runtime native 처리 — `customJwtAuthorizer.discoveryUrl` + `allowedClients` 가 Runtime CFN/boto3 설정에 직접 들어감. 컨테이너 코드 안에서 검증할 필요 없음.

### 2-6. 의존성 변화 (`pyproject.toml`)

| 추가 dep | 버전 (reference 기준) | 사용 처 |
|---|---|---|
| `a2a-sdk` | `==0.3.24` (reference repo 와 동일 핀) | server (Monitor/Incident/Change 의 `A2AServer` 의존) + caller (Supervisor 의 `a2a.client.A2AClient`). **`strands-agents` 는 a2a-sdk 를 번들 안 함** — explicit 추가 필요 (research 확인) |
| `strands-agents` | ≥ `1.10.0` | `strands.multiagent.a2a.A2AServer` 보유 버전. 미만이면 `monitoring_strands_agent` 식 boilerplate 패턴으로 fallback 필요 |
| `httpx` | (a2a-sdk 가 이미 의존) | caller-side `RemoteA2aAgent` 가 아니라 직접 `httpx.AsyncClient` 사용 (§3-3 코드) |
| (선택) `pyjwt` | — | operator CLI — Cognito JWT decode (선택, 검증은 안 함) |

→ 신규 dep 핵심 1건 (`a2a-sdk`) + version constraint 1건 (`strands-agents>=1.10.0`). Phase 4 까지의 `bedrock-agentcore`, `bedrock-agentcore-starter-toolkit`, `boto3` 모두 carry-over.

---

## 3. Supervisor Agent 상세 (D1, D2, D8)

### 3-1. `agents/supervisor/shared/agent.py`

Phase 4 incident `shared/agent.py` 와 **동일한** `tools=` 시그니처 — sub-agent 도 caller 입장에서 *tool* (research 확인):

```python
"""Supervisor Agent factory — Phase 4 와 동일한 tools= 패턴.

차이점은 tools 의 정체: Phase 4 incident 는 Gateway MCP tool 들,
Supervisor 는 sub-agent A2A 호출을 wrap 한 @tool 함수들 (call_monitor 등).
"""
from pathlib import Path
import os
from strands import Agent
from strands.handlers.callback_handler import null_callback_handler
from strands.models import BedrockModel

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def create_supervisor_agent(
    tools: list,                                          # [call_monitor, call_incident, call_change]
    system_prompt_filename: str = "system_prompt.md",
) -> Agent:
    """Strands Agent — sub-agent 호출 함수를 tools 로 등록."""
    return Agent(
        model=BedrockModel(
            model_id=os.environ.get("SUPERVISOR_MODEL_ID") or "global.anthropic.claude-sonnet-4-6",
            region_name=os.environ.get("AWS_REGION") or "us-west-2",
        ),
        tools=tools,                                       # ★ sub-agent 도 tool 로 노출
        system_prompt=(_PROMPTS_DIR / system_prompt_filename).read_text(encoding="utf-8"),
        callback_handler=null_callback_handler,
    )
```

→ **Strands `Agent` 에 `sub_agents=` 파라미터 자체 없음** (research 확인 — `Agent.__init__` 인자 enumerate 결과). Strands 의 sub-agent 표준 패턴은 *"sub-agent 를 도구로 노출"* — `@tool` decorator 가 LLM 에게 sub-agent 의 시그니처 (이름 + 설명 + 인자) 를 그대로 보여줌. system_prompt 가 routing 정책을 가르치고, LLM 이 `call_monitor` / `call_incident` / `call_change` 중 어떤 도구를 부를지 결정.

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

> Supervisor Runtime 은 외부 (Operator CLI) 에서 진입을 받음 — Bearer JWT 검증 후 LLM 추론. `protocolConfiguration` 은 **HTTP** 유지 (A2A 가 아님). 따라서 `BedrockAgentCoreApp` + `@app.entrypoint` 패턴 사용 가능.

```python
import os
from typing import Any, AsyncGenerator
from urllib.parse import quote
from uuid import uuid4

import httpx
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from bedrock_agentcore.identity.auth import requires_access_token
from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
from a2a.types import Message, Part, Role, TextPart
from strands import tool

from supervisor_shared.agent import create_supervisor_agent

REGION = os.environ.get("AWS_REGION", "us-west-2")
A2A_PROVIDER = os.environ["A2A_OAUTH_PROVIDER_NAME"]


def _runtime_url(arn: str) -> str:
    return f"https://bedrock-agentcore.{REGION}.amazonaws.com/runtimes/{quote(arn, safe='')}/invocations/"


async def _call_subagent(arn: str, query: str) -> str:
    """A2A 호출 — Cognito Client B Bearer + AgentCard discovery + send_message."""

    @requires_access_token(provider_name=A2A_PROVIDER, scopes=[],
                           auth_flow="M2M", into="bearer_token", force_authentication=True)
    async def _do_call(*, bearer_token: str = "") -> str:
        headers = {
            "Authorization": f"Bearer {bearer_token}",
            "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": str(uuid4()),
        }
        async with httpx.AsyncClient(timeout=300, headers=headers) as h:
            card = await A2ACardResolver(httpx_client=h, base_url=_runtime_url(arn)).get_agent_card()
            client = ClientFactory(ClientConfig(httpx_client=h, streaming=False)).create(card)
            msg = Message(kind="message", role=Role.user,
                          parts=[Part(TextPart(kind="text", text=query))],
                          message_id=uuid4().hex)
            async for event in client.send_message(msg):
                # event[0] = Task; artifacts[0].parts[0].root.text 가 응답 본문
                return event[0].artifacts[0].parts[0].root.text
        return ""

    return await _do_call()


@tool
async def call_monitor(query: str) -> str:
    """Call Monitor sub-agent for CloudWatch alarm 분석 + history."""
    return await _call_subagent(os.environ["MONITOR_RUNTIME_ARN"], query)


@tool
async def call_incident(query: str) -> str:
    """Call Incident sub-agent for runbook 진단 + 권장 조치."""
    return await _call_subagent(os.environ["INCIDENT_RUNTIME_ARN"], query)


@tool
async def call_change(query: str) -> str:
    """Call Change sub-agent for 24h 배포 변경 read + incident write."""
    return await _call_subagent(os.environ["CHANGE_RUNTIME_ARN"], query)


app = BedrockAgentCoreApp()


@app.entrypoint
async def supervisor(payload: dict, context: Any) -> AsyncGenerator[dict, None]:
    query = payload.get("query") or ""
    agent = create_supervisor_agent(tools=[call_monitor, call_incident, call_change])
    async for event in agent.stream_async(query):
        # SSE yield (Phase 3 패턴) — Strands 가 tool 호출 시점에 stream 안에서 A2A hop 실행
        if "data" in event:
            yield {"type": "text", "data": event["data"]}
```

→ **핵심 차이** (이전 design 대비):
- `RemoteA2aAgent` (Google ADK 전용, Strands 미보유) **사용 안 함**
- `Agent(sub_agents=…)` (Strands 미지원) **사용 안 함**
- Sub-agent 호출은 `@tool` 함수가 직접 `a2a.client.A2AClient` 호출
- AgentCard URL 은 ARN → URL 자동 조립 (별 env 불필요)
- `requires_access_token` decorator 가 Bearer 자동 주입 — Phase 3/4 의 Gateway 호출 패턴이 multi-provider 로 확장

### 3-4. caller-side OAuth provider 별도 발급 이유 (D4 부연)

Phase 3 의 단일 provider (`gateway_provider`) 는 Client (Gateway 호출용 audience). A2A 호출용 token 은 sub-agent Runtime 의 `allowedClients` 에 매칭되어야 하므로 **Client B (별 audience)** 로 발급된 토큰이 필요. 같은 Cognito UserPool 안에서 Client 만 추가하면 충분 — 별 UserPool 신설 불필요.

**Audience 격리가 본질, scope 는 hygiene** (research 확인 + §6-2):
- AgentCore 의 권한 결정은 `aud` 매칭만 — Client 토큰의 `aud` 는 Client, Client B 토큰의 `aud` 는 Client B
- 따라서 Supervisor Runtime 에 두 OAuth provider:
  - `gateway_provider` (Client credentials) → Gateway 의 `allowedClients=[C]` 통과
  - `a2a_provider` (Client B credentials) → sub-agent Runtime 의 `allowedClients=[B]` 통과
- scope 는 Cognito 측에서 발급 정책 분리 + 감사 가시성 제공 — AgentCore 의 권한 결정에는 무관

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
| `data/runbooks/` read | ❌ | Incident 의 영역 — 책임 분리 |
| `deployments/` write | ❌ | 배포 자체는 외부 시스템 — workshop scope 외 |
| Lambda invoke (Gateway 외) | ❌ | Gateway 만 통한 도구 호출 (C2 원칙 보존) |

→ "full where appropriate" = 책임 영역 (deployments + incidents) 안에서 read+write 모두 허용. 책임 외 (data/runbooks/, 외부 배포) 는 명시 차단.

---

## 5. A2A 프로토콜 활성화 상세 (D2, D9)

### 5-1. server-side wrap (Strands `A2AServer` 패턴)

> **`@app.entrypoint` + `BedrockAgentCoreApp` 사용 안 함** (research 확인). A2A protocol Runtime 은 port 9000 root path 의 FastAPI/Starlette app 을 직접 expose. Strands 가 한 줄로 wrap 제공:

```python
# agents/monitor/runtime/agentcore_runtime.py (Incident, Change 도 동일 패턴)
import os
import uvicorn
from fastapi import FastAPI
from strands.multiagent.a2a import A2AServer

from monitor_shared.agent import create_agent
from monitor_shared.mcp_client import build_gateway_client

REGION = os.environ.get("AWS_REGION", "us-west-2")
RUNTIME_URL = os.environ.get("AGENTCORE_RUNTIME_URL", "http://127.0.0.1:9000/")

# Phase 3/4 의 도구/Agent 구성은 그대로 — A2A 는 protocol layer 만 추가
mcp_client = build_gateway_client()
mcp_client.start()
gateway_tools = mcp_client.list_tools_sync()

agent = create_agent(
    tools=gateway_tools,
    system_prompt_filename="system_prompt.md",
    name="monitor",                                   # AgentCard.name
    description="CloudWatch alarm 분석 + history 진단",  # AgentCard.description
)

# AgentCard 자동 생성 — agent.tool_registry 의 각 tool 이 skill 로 export
a2a_server = A2AServer(
    agent=agent,
    http_url=RUNTIME_URL,                             # AgentCore 가 env 주입
    serve_at_root=True,                               # AgentCore 의 URL prefix 호환 필수
)

app = FastAPI()
app.mount("/", a2a_server.to_fastapi_app())


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9000)
```

→ **핵심 차이** (이전 design 대비):
- `A2AStarletteApplication` 직접 사용 안 함 — Strands 1.10+ 의 `A2AServer` 가 80 LoC 짜리 `AgentExecutor` 패턴을 한 줄로 압축
- `@app.entrypoint` **삭제** — A2A protocol Runtime 은 entrypoint 개념 자체가 없음
- AgentCard 의 `skills` 는 `agent.tool_registry` 에서 자동 도출 — 수동 `AgentSkill(...)` 작성 불필요
- `serve_at_root=True` 가 AgentCore 의 path-prefix 호환 핵심 (research §6 gotcha #2)
- AgentCard `url` 필드는 `http_url` 인자에 그대로 들어가야 함 (`AGENTCORE_RUNTIME_URL` env, AgentCore 자동 주입)

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

#### Change Runtime (신규 create)

```python
agentcore_control.create_agent_runtime(
    agentRuntimeName=f"aiops_demo_{DEMO_USER}_change",
    protocolConfiguration={"serverProtocol": "A2A"},
    requestHeaderConfiguration={
        "requestHeaderAllowlist": ["X-Amzn-Bedrock-AgentCore-Runtime-Custom-Actorid"],
    },
    authorizerConfiguration={
        "customJWTAuthorizer": {
            "discoveryUrl": f"https://cognito-idp.{REGION}.amazonaws.com/{user_pool_id}/.well-known/openid-configuration",
            "allowedClients": [client_b_id],          # Client B M2M token 만 허용 (aud 검증)
        },
    },
    ...
)
```

#### Monitor + Incident Runtime (기존 — `update_agent_runtime` 로 사후 부착)

> Phase 4 시점에 이미 deploy 된 Runtime → `update_agent_runtime` 로 protocol 전환 (HTTP→A2A) + Authorizer 부착. **boto3 `update_agent_runtime` 는 full PUT** (research 확인) — 모든 필드 재전송 필요. partial 가정하면 기존 환경변수가 사라지는 등 부작용:

```python
# agents/monitor/runtime/deploy_runtime.py 일부
existing = agentcore_control.get_agent_runtime(agentRuntimeId=runtime_id)
agentcore_control.update_agent_runtime(
    agentRuntimeId=runtime_id,
    agentRuntimeArtifact=existing["agentRuntimeArtifact"],          # 새 ECR 이미지로 교체
    roleArn=existing["roleArn"],
    networkConfiguration=existing["networkConfiguration"],
    environmentVariables=existing["environmentVariables"],          # ★ 빠뜨리면 clear 됨
    protocolConfiguration={"serverProtocol": "A2A"},                # HTTP → A2A
    requestHeaderConfiguration={
        "requestHeaderAllowlist": ["X-Amzn-Bedrock-AgentCore-Runtime-Custom-Actorid"],
    },
    authorizerConfiguration={                                       # 신규 부착
        "customJWTAuthorizer": {
            "discoveryUrl": discovery_url,
            "allowedClients": [client_b_id],
        },
    },
)
```

#### 검증 의미론

- **AgentCore 가 검증하는 것**: JWT signature (Cognito JWKS), `iss`, `aud` (= `allowedClients` 매칭), `client_id` claim
- **AgentCore 가 검증하지 않는 것**: `scope` claim — Cognito 측에서 정의한 scope 는 AgentCore Authorizer 통과 후에는 무시됨 (§6-2 부연)
- 통과 후 Runtime 에 도달: AgentCore 가 `Authorization` header 제거 + `x-amzn-bedrock-agentcore-runtime-workload-accesstoken` (workload 식별 토큰) 주입
- Starlette middleware / Lambda authorizer 작성 불필요 — AgentCore native 처리

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

**중요한 의미론 명료화** (research 확인):
- AgentCore 의 `customJwtAuthorizer` 는 **`aud` (= `client_id`) 만 검증**. JWT 의 `scope` claim 은 검증 안 함
- 따라서 본 phase 의 새 scope `agent-invoke/invoke` 는 **AgentCore 측 권한 결정에 영향 없음**
- 그럼에도 별 ResourceServer + scope 를 정의하는 이유:
  - **Cognito 측 토큰 발급 정책 분리**: Client B 가 Gateway scope (`invoke`) 를 발급받지 못하도록 차단 (혹은 그 반대)
  - **감사 추적**: JWT decode 시 scope 가 의도 (Gateway 호출 vs A2A 호출) 를 명시
  - **향후 확장 여지**: 다른 service 에서 scope 검증을 추가하더라도 토큰 자체는 이미 분리되어 있음
- 결국 두 가지 분리 layer:
  - **Cognito 측 (scope)**: 어떤 Client 가 어떤 scope 를 받을 수 있는가
  - **AgentCore 측 (allowedClients)**: 받은 토큰의 `aud` 가 매칭되는가
- 본 phase 의 권한 결정 = **`allowedClients` 만**. scope 는 hygiene

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
| **P6a-A6** | Phase 6a teardown 후 Phase 0/2/3/4 자원 보존 | `infra/phase6a/teardown.sh` + Supervisor/Change `teardown.sh` 후 — Monitor + Incident Runtime / Cognito UserPool / Client / Gateway / 기존 3 Lambda + 3 Target 모두 그대로. Phase 2 Gateway Role 의 phase4 inline policy 도 보존 (phase6a 만 detach) |

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

> 2026-05-08 research 후 갱신. `host_adk_agent` (Google ADK) 는 *Strands 와 다른* SDK 라 코드 차용 불가 — Cognito CFN 패턴만 차용. 실제 코드 차용은 **Strands 기반** 두 reference 에서.

| 차용 | 본 phase 사용처 |
|---|---|
| `/home/ubuntu/amazon-bedrock-agentcore-samples/01-tutorials/01-AgentCore-runtime/05-hosting-a2a/02-a2a-agent-sigv4/agent.py` | **Strands `A2AServer.to_fastapi_app()` 최소 예제** — Monitor/Incident/Change server 의 `agentcore_runtime.py` 골격 (§5-1) |
| `/home/ubuntu/amazon-bedrock-agentcore-samples/02-use-cases/A2A-realestate-agentcore-multiagents/realestate_coordinator/agent.py:325-361,454-459` | **Strands supervisor + Cognito M2M 의 `@tool` wrapping `a2a.client.A2AClient` 패턴** — Supervisor 의 `agentcore_runtime.py` (§3-3) 의 직접 reference |
| `/home/ubuntu/amazon-bedrock-agentcore-samples/01-tutorials/01-AgentCore-runtime/05-hosting-a2a/02-a2a-agent-sigv4/client.py:91-145` | A2A client 의 `A2ACardResolver` + `ClientFactory` + `send_message` 시퀀스 — §3-3 의 `_call_subagent()` 핵심 |
| `/home/ubuntu/amazon-bedrock-agentcore-samples/02-use-cases/A2A-multi-agent-incident-response/cloudformation/cognito.yaml` | **Cognito CFN 패턴 — multi-Client + Resource Server + Custom Resource Lambda 가 client_secret 을 Secrets Manager 에 자동 업데이트** — `infra/phase6a/cognito_extras.yaml` (§6-1) 차용 |
| `/home/ubuntu/amazon-bedrock-agentcore-samples/02-use-cases/A2A-multi-agent-incident-response/cloudformation/monitoring_agent.yaml:906-933` | Runtime CFN 의 A2A protocol + customJWTAuthorizer + RequestHeaderAllowlist 구성 — Phase 6a 의 deploy_runtime.py 가 boto3 호출로 동등 결과 |
| `/home/ubuntu/amazon-bedrock-agentcore-samples/02-use-cases/A2A-multi-agent-incident-response/host_adk_agent/agent.py:43-63` | `requires_access_token(provider_name=..., auth_flow="M2M", into="bearer_token", force_authentication=True)` 데코레이터 사용 패턴 — §3-3 의 `_fetch_a2a_token` (Google ADK 코드지만 데코레이터는 SDK 무관) |
| `/home/ubuntu/developer-briefing-agent/` | dba 패턴 — Supervisor/Change 의 `shared/agent.py + prompts/` 분리, intuitive function naming, deploy_runtime.py 5단계 |
| `/home/ubuntu/sample-deep-insight/managed-agentcore/` | per-agent 모델 분리 (Supervisor/Change 가 별 MODEL_ID env), OTEL service.name 자동 |
| Phase 4 `infra/github-lambda/github_lambda.yaml` | `infra/phase6a/deployments_lambda.yaml` 의 cross-stack policy 패턴 |
| Phase 4 `infra/github-lambda/setup_github_target.py` | `infra/phase6a/setup_deployments_target.py` 의 create-or-update 패턴 (A1 fix) |
| `docs/research/a2a_intro.md` | 본 phase 의 A2A 개념 사전 학습 자료 — workshop 청중이 본 design 읽기 전 권장 |

**~~기존 차용 (deprecated by research)~~**:
- ~~`host_adk_agent/agent.py:37-100` 의 `RemoteA2aAgent` + `LazyClientFactory` 패턴~~ → Google ADK 전용. Strands 로 차용 불가. Phase 6a 는 `@tool` wrapping `a2a.client.A2AClient` 패턴 (`realestate_coordinator` 차용) 으로 대체
- ~~`monitoring_strands_agent/main.py + agent_executor.py` 의 `A2AStarletteApplication` + 직접 `AgentExecutor` 작성 패턴~~ → Strands 1.10+ 의 `A2AServer.to_fastapi_app()` 가 동일 결과를 한 줄로 제공. ~80 LoC 의 boilerplate 가 1 LoC 로 압축

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
D8   Sub-agent caller — `@tool` × 3 wrapping `a2a.client.A2AClient` (Strands `sub_agents=` 미지원, RemoteA2aAgent 는 Google ADK 전용)
D9   Inbound Authorizer — Cognito UserPool 직접 (`allowedClients` 만 검증, scope 미검증)
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
├── data/runbooks/           # Phase 4 partial (Phase 6a 보강 시 noisy-cpu.md 등 추가)
├── deployments/        # ★ Phase 6a — 24h 배포 로그 minimal seed
├── incidents/          # ★ Phase 6a 첫 등장 — Change 가 append (write)
└── docs/design/
    ├── phase2.md
    ├── phase3.md
    ├── phase4.md
    └── phase6a.md      # ★ 본 문서
```

→ Phase 5 디렉토리는 없음 (skip). Phase 6b/7 은 별도 design 시점에 추가.
