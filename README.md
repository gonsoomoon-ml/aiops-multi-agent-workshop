# AIOps Multi-Agent Workshop — A2A across team-owned agents

- **AI Multi-agent 가 시스템 운영 자동화에 어떻게 적용되는지** Strands Agent + Amazon Bedrock AgentCore + A2A 프로토콜로 학습.
- Flow: CloudWatch alarm 발생 → 운영자 query (`"현재 상황 진단해줘"`) → Supervisor (LLM orchestrator) → Monitor (CloudWatch alarm 조회 + real/noise 판정 — `status-check` real, `noisy-cpu` noise) + Incident (runbook 진단) sub-agent (A2A) → 통합 진단 JSON.

> **왜 A2A 인가 — Team-owned multi-agent**
>
> **AgentCore Runtime 에서 multi-agent 를 구성하는 방법은 A2A 가 유일하지 않음.** 공식 문서가 제시하는 design space (택1):
>
> 1. **In-process supervisor (agents-as-tools)** — 한 container 안에 supervisor + sub-agent 가 같은 프로세스로 동작. sub-agent 를 `@tool` 로 노출. latency / 구현 속도 유리, 팀 경계 X.
> 2. **boto3 `invoke_agent_runtime` direct call** — sub-agent 를 각각 별도 Runtime 으로 배포하되 supervisor 가 A2A SDK 없이 boto3 API 로 JSON payload 직접 호출. protocol overhead 0, 단 interoperability/discovery 표준 없음.
> 3. **Strands Graph / Swarm / Workflow** — Strands SDK 의 명시적 multi-agent primitive (DAG / 자율 협업 / pipeline) 로 LLM routing 의 비결정성을 회피. 단일 Strands process 내 동작.
> 4. **A2A 프로토콜** *(본 워크샵)* — sub-agent 를 별도 Runtime + JSON-RPC + AgentCard + JWT 로 호출.
>
> **본 워크샵이 A2A 를 채택한 이유**: enterprise 환경 = **각 agent 가 별도 팀 소유** (예: Monitor 팀이 Monitor agent owner, Incident 팀이 Incident agent owner). 같은 process 에 묶을 수 없음 (→ 1·3 제외), 표준 protocol 로 cross-framework 협업 필요 (→ 2 제외). 본 워크샵의 **Supervisor + 2 A2A sub-agent** 구조 = enterprise multi-agent 아키텍처의 **최소 시뮬레이션**.

---

## 1. 시나리오 — "결제 서비스 P1 장애 대응"

```
T-0       운영자가 stop_instance.sh 실행 → 결제 EC2 정지
T+30s     CloudWatch alarm 발화 (payment-${DEMO_USER}-status-check, real)
T+1m      운영자: invoke_runtime.py --query "현재 상황 진단해줘"
            └─ Supervisor Runtime 진입 (HTTP, SigV4)
T+1m → 2m Supervisor LLM (orchestrator, 1분간) — system_prompt 만 보고 routing:
            ├─ call_monitor_a2a   → 라이브 alarm 분류 (real 1 + noise 1 = false alarm, alarm `Classification` tag 기반)
            └─ call_incident_a2a  → real alarm 의 runbook 매칭 + P1 진단 + 권장 조치
T+2m      Supervisor 통합 JSON stdout:
            { summary, monitor, incidents, next_steps }
          (실측: 41.9초 / 31,572 tokens [3 Runtime 합산 — Supervisor 16,153 + Monitor 8,471 + Incident 6,948])

(stretched) EC Mall 확장
```

---

## 2. 여정 요약 — 6 phase 가 3 act 로 진화


| Act                        | Phase | 추가되는 layer                                                                                         | 핵심 학습 / 시스템 목표                                                                            |
| -------------------------- | ----- | -------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| **I. 기반 + 로컬 baseline**    | 0-1   | EC2 + 라이브 alarm 2종 (real + noise) + 첫 Strands Agent (mock)                                         | Strands SDK 로 간단한 로컬 Agent 작성 (AWS 의존 0 — 회귀 baseline)                                    |
| **II. AWS managed 승격**     | 2-3   | Gateway + MCP + Cognito JWT + Runtime container                                                    | 도구 외부화 (`@tool` → Lambda behind Gateway) / **로컬 Agent → AgentCore Runtime 배포** (동일 코드 승격) |
| **III. Multi-agent + A2A** | 4-5   | Incident Runtime + storage 추상화 (S3/GitHub) + Supervisor + Monitor A2A + Incident A2A (A2A 프로토콜 활성) | **Supervisor LLM 이 sub-agent routing 결정** (`serve_a2a` + LazyExecutor — hardcoded 분기 0)   |


---

## 3. 아키텍처

Phase 5 active call path. 시나리오 = 시간축 (T-0~T+2m), 아래 다이어그램 = 공간축 (어디서 무엇이 돌아가나).

```
┌─────────────────────────────────────────────────────────────────────┐
│  Operator (Human)                                                   │
│    └─ invoke_runtime.py --query "..."                               │
└─────────────────────────────┬───────────────────────────────────────┘
                              │ SigV4 (IAM)
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│  AgentCore Runtime  —  Supervisor                       (Phase 5)   │
│    LLM orchestrator + @tool wrap a2a.client                         │
└──────┬──────────────────────────────────────────┬───────────────────┘
       │ A2A JSON-RPC + Bearer JWT                │
       ▼                                          ▼
┌──────────────────────┐                  ┌──────────────────────┐
│ Monitor A2A          │                  │ Incident A2A         │
│   Runtime (Phase 5)  │                  │   Runtime (Phase 5)  │
│   alarm 분류         │                  │   runbook 진단       │
└──────┬───────────────┘                  └──────┬───────────────┘
       │ MCP streamable HTTP + Bearer JWT        │
       └─────────────────────┬───────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  AgentCore Gateway  —  MCP server (3 targets)                       │
│    ├─ history-mock        →  Lambda  (mock alarm history) (Phase 2) │
│    ├─ cloudwatch-wrapper  →  Lambda  →  CloudWatch alarm  (Phase 2) │
│    └─ storage             →  Lambda  →  S3 / GitHub       (Phase 4) │
│         (STORAGE_BACKEND env 분기 — default=s3)                     │
└─────────────────────────────────────────────────────────────────────┘

  ─── 공통 인프라 (모든 phase 횡단) ───────────────────────────────────
   Cognito UserPool + Client (Phase 2)
        → JWT (M2M) → Gateway 검증 (Phase 2) + A2A inbound 검증 (Phase 5)
   EC2 simulator + CloudWatch alarm 2종 (Phase 0)
        → payment-${DEMO_USER}-status-check  (real alarm)
        → payment-${DEMO_USER}-noisy-cpu     (noise alarm)
```

---

## 4. 학습할 기술

**Strands SDK**

- **Strands Agent SDK** *(Phase 1)* — `BedrockModel` + `@tool` + `MCPClient` + `stream_async`
- **Strands hooks** *(Phase 2)* — `BeforeModelCallEvent` / `AfterModelCallEvent` / `BeforeToolCallEvent` 로 pre-call 시점 + LLM duration + TTFT 측정

**AWS Bedrock AgentCore**

- **AgentCore Runtime** *(Phase 3)* — 컨테이너 배포, 로컬 코드 그대로 서비스화
- **AgentCore Gateway** *(Phase 2)* — MCP 도구 외부화 + JWT 검증 3 단계 (Cognito issue → Gateway authorizer → Lambda `client_context.custom`)
- **AgentCore Identity** *(Phase 3)* — OAuth2 provider 자동 token inject

**프로토콜 + 오케스트레이션**

- **MCP 프로토콜** *(Phase 2)* — streamable HTTP + `<target>___<tool>` namespacing
- **A2A 프로토콜** *(Phase 5)* — `serve_a2a` + `LazyExecutor` AWS canonical 패턴
- `**@tool` wrapping a2a.client** *(Phase 5)* — Strands `Agent` 가 `sub_agents` 미지원 → sub-agent 를 도구로 노출, LLM 이 routing 결정 (caller-as-LLM-tool)
- **Multi-agent orchestration** *(Phase 5)* — A2A graph + LLM-driven sub-agent dispatch

**인증 + 인프라**

- **JWT M2M 인증** *(Phase 2)* — Cognito ResourceServer + scope + `customJWTAuthorizer`
- **CFN + boto3 하이브리드** *(cross-phase)* — 표준 자원은 IaC, AgentCore 자원은 SDK step-by-step
- **Cross-stack IAM** *(Phase 4)* — storage Lambda stack 이 cognito-gateway 의 GatewayIamRole 에 inline policy 부착 (stack 간 dependency 격리)
- **Storage backend 추상화** *(Phase 4)* — `STORAGE_BACKEND=s3/github` env 분기, Lambda 응답 shape byte-level 동형 → Agent 코드 변경 X 로 backend swap

**성능 + 관측**

- **Prompt caching** *(Phase 3+)* — `cache_tools="default"` + `SystemContentBlock` cachePoint (Layer 1+2) → single invocation 내 즉시 hit + 5분 warm TTL
- **Warm container reuse** *(Phase 3+; Phase 5 에서 3 Runtime 으로 확장)* — `runtimeSessionId` 반복으로 같은 microVM 재사용 → TTFT 단축 (prompt cache 와 분리된 caching layer)
- **Debug mode** *(Phase 2)* — env `DEBUG=1` 로 phase 횡단 trace (auth / MCP / tool / TTFT / cache), `agent_name` parameter 로 multi-agent 라벨 격리

---

## 5. 사전 요구사항

- **AWS 계정** *(Phase 0+)* — us-east-1 region (Bedrock + AgentCore 가용성)
- **IAM 권한** *(Phase 0+)* — `AdministratorAccess` (또는 동등) — CFN / IAM / Lambda / Cognito / Bedrock / AgentCore / EC2 / CloudWatch / S3 / ECR / SSM 자원 생성 필요. **워크샵 단순화용** — 운영은 least-privilege role 권장.
- **AgentCore Runtime quota** *(Phase 5)* — 5개 (Monitor + Incident + Monitor A2A + Incident A2A + Supervisor)
- **Python 3.12+** *(Phase 0+)* + `[uv](https://github.com/astral-sh/uv)`
- **Docker daemon** *(Phase 3+)* — local `docker build` → ECR push 용도 (Runtime 실행은 AWS managed)
- **GitHub Personal Access Token** *(Phase 4+)* — `repo` scope (**STORAGE_BACKEND=github 선택 시에만**)

---

## 6. 폴더 구조

```
aiops-multi-agent-workshop/
├── agents/                      # Strands Agent + AgentCore Runtime 코드
│   ├── monitor/                 #   Phase 1-3: 로컬 + Runtime
│   ├── incident/                #   Phase 4: Incident Runtime + shared
│   ├── monitor_a2a/             #   Phase 5: A2A 프로토콜 활성 (Phase 4 shared/ 직접 import)
│   ├── incident_a2a/            #   Phase 5: 동일 패턴
│   └── supervisor/              #   Phase 5: A2A caller (HTTP inbound, A2A outbound)
├── _shared_debug/               # Phase 2+ FlowHook 기반 Debug trace 공통 helper
├── infra/                       # CFN 신규 자원이 있는 phase 만 디렉토리
│   ├── ec2-simulator/           #   Phase 0
│   ├── cognito-gateway/         #   Phase 2
│   ├── s3-lambda/               #   Phase 4: S3 storage backend (default)
│   └── github-lambda/           #   Phase 4: GitHub storage backend (STORAGE_BACKEND=github)
├── data/                        # GitHub repo 가 보유할 데이터 (이 repo 가 곧 GitHub data store)
│   ├── runbooks/                #   Incident Agent 가 read 하는 진단 절차 markdown
│   └── mock/phase1/             #   Phase 1 mock alarm history (history mock Lambda 가 vendor)
├── docs/
│   ├── learn/                   #   Phase 별 narrative (workshop 청중용) + teardown
│   ├── design/                  #   Phase 별 의사결정 로그 (D1~D10)
│   └── research/                #   A2A / AgentCore 학습 노트 + POC mini-projects
├── setup/                       # one-off setup helper (GitHub PAT → SSM)
├── pyproject.toml               # Python 프로젝트 + uv 의존성 정의
├── uv.lock                      # uv lockfile (pinned)
├── bootstrap.sh                 # dev 환경 + .env + SSM token 일괄
└── teardown_all.sh              # 8 step 자원 일괄 삭제
```

---

## 7. Quickstart

### 1. 부트스트랩 (1회)

```bash
bash bootstrap.sh
```

`uv sync` + AWS 자격증명 사전 검증 + `.env` (AWS_REGION / DEMO_USER / STORAGE_BACKEND 결정 — **default `s3`, PAT 불필요**) + (`STORAGE_BACKEND=github` 선택 시에만 추가) GitHub PAT → SSM SecureString 5단계 검증.

> `.env` 의 전체 lifecycle (파일 2종 / phase 별 추가 entry / Phase 5 cross-load / teardown cleanup / security) — `[docs/learn/env_config.md](docs/learn/env_config.md)`.

### 2. Phase 별 학습 + deploy

각 phase 의 narrative 는 `docs/learn/phase{N}.md`. **순서대로** 읽고 해당 phase 의 deploy 명령 실행. 각 narrative 에 "무엇 (what it is)" + "어떻게 동작 (how it works)" + 검증 (P{N}-A1~A5 = phase 별 acceptance check 5종) 포함.


| Phase   | 이름                                        | 핵심 산출물                                                                                                | Narrative                                      | 예상 소요 | 상태  |
| ----- | ----------------------------------------- | ----------------------------------------------------------------------------------------------------- | ---------------------------------------------- | ----- | --- |
| <nobr>**환경구성**</nobr> | 실습 환경 구축         | Workshop code server + kiro 설정     | [docs/learn/workshop_setup.md](docs/learn/workshop_setup.md)    |  10 분   | ✅  |
| **0**   | 기반 인프라                                    | EC2 시뮬레이터 + CloudWatch alarm 2종 (real + noise) + 카오스 스크립트                                             | [docs/learn/phase0.md](docs/learn/phase0.md) | 30 분  | ✅   |
| **1**   | Strands Agent (local, mock)               | 로컬 Monitor Agent (Strands) + 3가지 진단 유형 (Rule 폐기 / Threshold 상향 / Time window 제외)                      | [docs/learn/phase1.md](docs/learn/phase1.md) | 40 분  | ✅   |
| **2**   | AgentCore Gateway + MCP + Debug mode      | AgentCore Gateway + MCP 도구 외부화 (CloudWatch + history mock Lambda) + FlowHook 기반 Debug trace (DEBUG=1) | [docs/learn/phase2.md](docs/learn/phase2.md) | 60 분  | ✅   |
| **3**   | AgentCore Runtime — Monitor               | Monitor Agent → AgentCore Runtime 승격                                                                  | [docs/learn/phase3.md](docs/learn/phase3.md) | 60 분  | ✅   |
| **4**   | AgentCore Runtime — Incident + Storage    | Incident Runtime + storage Lambda (`STORAGE_BACKEND=s3` default / `github` 선택)                        | [docs/learn/phase4.md](docs/learn/phase4.md) | 60 분  | ✅   |
| **5**   | AgentCore A2A — Supervisor + 2 sub-agents | Supervisor + Monitor A2A + Incident A2A — A2A 활성화 (`serve_a2a` + LazyExecutor)                        | [docs/learn/phase5.md](docs/learn/phase5.md) | 90 분  | ✅   |
| **6**   | Cross-Account Monitoring                  | STS AssumeRole 기반 Target Account CloudWatch alarm 통합 조회 — Food Order 데모 앱 모니터링                          | [docs/learn/phase6.md](docs/learn/phase6.md) | 20 분  | ✅   |


> ✅ = narrative 작성 완료 / 🚧 = 작성 대기 — 미완성 시 코드 직접 참조.

> **Phase 5 deploy 주의** — Supervisor 가 sub-agent ARN 을 root `.env` 에서 cross-load. 의존 순서 (`monitor_a2a → incident_a2a → supervisor`) 와 `.env` lifecycle 전체: `[docs/learn/env_config.md](docs/learn/env_config.md)`.

**Stretched** (시간 여유 / 후속 자료):

- **Policy** — AgentCore NL Policy readonly enforcement + 거부 시연

---

## 8. Teardown / Reset

전체 자원 일괄 삭제 (의존성 역순 8 step):

```bash
bash teardown_all.sh           # 확인 prompt 후 진행
bash teardown_all.sh --yes     # 확인 prompt skip (CI/auto 용)
```

step 별 분해 + idempotent 보장 + 검증 명령은 [docs/learn/teardown.md](docs/learn/teardown.md) 참조.

---

## 9. References

### 1. 외부 upstream repo — 차용 패턴

본 프로젝트가 직접 차용한 4 upstream repo:


| Repo                                                                                                                                | 차용 패턴                                                                                                                                              |
| ----------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| [amazon-bedrock-agentcore-samples](https://github.com/awslabs/amazon-bedrock-agentcore-samples) — A2A-multi-agent-incident-response | Cognito CFN (UserPool + ResourceServer + Client M2M), `MCPClient(workload_token)` (Phase 3 Runtime), `RemoteA2aAgent` (Phase 5 Supervisor 참조)      |
| [ec-customer-support-e2e-agentcore](https://github.com/gonsoomoon-ml/ec-customer-support-e2e-agentcore)                             | Phase 2 Gateway + Target boto3 step-by-step (lab-03 / lab-09)                                                                                      |
| [developer-briefing-agent](https://github.com/gonsoomoon-ml/developer-briefing-agent)                                               | local-agent ↔ managed-agentcore split + 단일 `create_agent()` truth source (C1), `prompts/system_prompt.md` externalization, SSM SecureString PAT 패턴 |
| [sample-deep-insight](https://github.com/aws-samples/sample-deep-insight)                                                           | (cherry-pick) per-agent `MODEL_ID` env, OTEL `service.name` → CloudWatch GenAI Observability 자동 통합                                                 |


