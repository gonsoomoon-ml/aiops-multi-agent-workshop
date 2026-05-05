> ⚠️ **DEPRECATED (2026-04-26 작성)** — 본 문서는 v2 장문 계획서로, 이후 [`plan_summary.md`](../plan_summary.md) (8 섹션) 으로 재작성·축약되었으며 단일 진실 원천(SoT)은 `plan_summary.md` 입니다. 본 파일은 4가지 진단 유형, 부록 B 등 흡수된 컨셉의 역사적 출처로만 보존됩니다. 작업 시 본 파일을 기준으로 삼지 마세요.

# Cloud Op AI Ops 데모 시스템 구현 계획 (v2)

> **목적**: Cloud Operation Group의 "장애 진단·대응" 워크플로를 멀티에이전트로 자동화하는
> **데모 시스템**의 구현 계획서. AWS Bedrock AgentCore Runtime + Strands + A2A 프로토콜로
> Monitor / Incident / Change 3개 Agent를 협업시켜 단일 사용자 질의에 진단 리포트를
> 자동 생성·커밋한다.
>
> v1 단일 Agent 계획(`plan.v1-single-agent.md`)의 Rule Optimization 분석 로직과 Mock 데이터는
> Monitor Agent의 핵심 비즈니스 로직과 부록 A/B로 흡수됨.

---

## 1. 시스템 목표

데모가 시연하고 검증할 5가지:

| # | 시스템 능력 | 검증 기준 |
|---|---|---|
| C1 | Strands 로컬 Agent → AgentCore Runtime 동일 코드 승격 | 로컬 CLI 응답 == Runtime 응답 (동일 입력, 동일 출력 구조) |
| C2 | AgentCore Gateway + MCP로 도구를 Agent 코드 외부에 운영 | Gateway target 2종(CloudWatch mock, GitHub) MCP로 등록, Agent는 `list_tools_sync()`만 호출 |
| C3 | A2A 프로토콜로 독립 Runtime 간 호출 | Workflow / Supervisor 두 Orchestrator 모두 다른 Runtime의 AgentCard로 호출 |
| C4 | AgentCore Policy로 Agent 권한·행동 가드레일 코드 외부화 | Agent별 IAM Role scope-down + NL Policy 1건의 거부 시연 가능 |
| C5 | 동일 시나리오를 두 Orchestration 패턴(Workflow / Supervisor)으로 실행 | 토큰·지연·결정성 측정값을 산출 |

### 시스템이 해결하는 운영 문제

- 반나절 수작업 → **수 분 자동화**
- 주관적 "감" 기반 판단 → **정량 데이터 기반** 의사결정
- 일회성 점검 → **반복 가능한 주기 자동 진단 체계**
- 진단·결정 이력을 **GitHub commit으로 일관 관리**
- 1명 운영자가 모든 도메인을 살피던 구조 → **도메인별 Agent가 협업**

---

## 2. 시나리오 — "결제 서비스 P1 장애 대응"

데모 시스템이 처리하는 단일 통합 시나리오. 4개 운영 페르소나(모니터링 / 장애관리 / 변경관리 / DR)가 사건 타임라인의 다른 단계를 담당. **DR 도메인은 v2 데모 범위에서 제외** — 향후 확장.

### 사건 타임라인

```
T-0       결제 API 5XX 급증, CloudWatch alarm fire
            │
            ▼
T+1m   ① Monitor Agent    — alarm/log 수집, noise vs real 판정
            │  "real incident — 결제 API 5XX 142건/min"
            │  (4가지 진단 유형 적용 → 부록 B)
            ▼
T+3m   ② Incident Agent   — 런북 매칭, severity 결정, 티켓 초안
            │  "RB-042 매칭 → P1 escalate, INC-1107 초안 생성"
            ▼
T+5m   ③ Change Agent     — 최근 24h 배포·구성 변경 회귀 의심 (Light)
            │  "30분 전 payment-svc v3.4.1 배포 — 회귀 후보 1건"
            ▼
T+8m   Orchestrator      — 3개 결과 종합 → GitHub diagnosis/ 자동 커밋
                         + 운영자에게 권고 액션 제시
```

### 페르소나 ↔ Agent 매핑

| 페르소나 | Agent | 도구 | 핵심 의사결정 | 빌드 깊이 |
|---|---|---|---|---|
| 모니터링 담당자 | **Monitor** | CloudWatch (DescribeAlarms / DescribeAlarmHistory / FilterLogEvents) + GitHub | noise vs real 판정 (4가지 진단 유형) | **Full** |
| 장애관리 담당자 | **Incident** | GitHub `runbooks/` read + `incidents/` write | runbook 매칭, severity 결정, 티켓 초안 | **Full** |
| 변경관리 담당자 | **Change** | GitHub `deployments/` read | 회귀 후보 변경 1건 식별 | **Light** (~50 LoC) |
| DR 담당자 | (제외) | - | failover go/no-go | **데모 범위 외** |

---

## 3. 시스템 아키텍처

```
[운영자 터미널 CLI]
       │
       ▼
┌──────────────────────────────────────────────────────────────┐
│  Orchestrator  (두 가지 구현이 동일 시나리오를 실행)          │
│   ├─ Workflow:    Python asyncio 코드 (결정론적)             │
│   └─ Supervisor:  Strands Agent + sub_agents (LLM 라우팅)    │
└──────────────────────────────────────────────────────────────┘
       │  A2A (JSON-RPC 2.0 + OAuth M2M, AgentCore Runtime 네이티브)
       ├──────────────┬──────────────┐
       ▼              ▼              ▼
┌─────────────┐ ┌─────────────┐ ┌─────────────┐
│ Monitor     │ │ Incident    │ │ Change      │
│ (Strands)   │ │ (Strands)   │ │ (Strands)   │
│ AgentCore   │ │ AgentCore   │ │ AgentCore   │
│ Runtime     │ │ Runtime     │ │ Runtime     │
└─────────────┘ └─────────────┘ └─────────────┘
       │              │              │
       │  MCP (streamable-http + Bearer)
       ▼              ▼              ▼
┌──────────────────────────────────────────────────────────────┐
│  AgentCore Gateway (MCP)                                     │
│   ├─ CloudWatch Mock Target (Lambda + Smithy + 합성 데이터)  │
│   └─ GitHub Target          (Lambda + PyGithub, 실 repo)     │
└──────────────────────────────────────────────────────────────┘
       │
       ▼
[GitHub repo]  rules/ runbooks/ deployments/ diagnosis/ incidents/
```

### 컴포넌트 인벤토리

| 컴포넌트 | 종류 | 수 | 비고 |
|---|---|---|---|
| Strands Agent | Python 모듈 | 3 + 1 (Supervisor) | Monitor·Incident Full / Change Light / Supervisor |
| Orchestrator | Python | 2 | Workflow(asyncio) + Supervisor(Strands) — 비교 시연 |
| AgentCore Runtime | AWS::BedrockAgentCore::Runtime | 4 | Agent 3개 + Supervisor 1개 |
| AgentCore Gateway | AWS::BedrockAgentCore::Gateway | 1 | MCP 게이트웨이 |
| Gateway Target | AWS::BedrockAgentCore::GatewayTarget | 2 | CloudWatch mock / GitHub |
| Lambda | AWS::Lambda::Function | 2 | Gateway target 백엔드 |
| Cognito | UserPool 1 + UserPoolClient 4 | 1+4 | Agent별 M2M, 미리 배포 후 ARN 공유 |
| IAM Role | Runtime 실행 role | 4 | Agent별 scope-down (부록 C) |
| NL Policy | AgentCore Policy | 1+ | 거부 시연용 |
| CloudWatch / X-Ray | 관측 | 자동 | Runtime이 자동 emit |

### 데이터·인증 흐름 (요청 1건)

```
운영자 → CLI → Orchestrator
            ↓ A2A JSON-RPC + Authorization Bearer (Cognito M2M)
        Monitor Runtime (또는 다른 Agent Runtime)
            ↓ MCP streamable-http + Bearer (Gateway용 OAuth M2M 토큰 교환)
        AgentCore Gateway
            ↓ Smithy 매핑 → AWS SigV4 / Lambda invoke
        CloudWatch mock Lambda  / GitHub Lambda
            ↓
        실 repo (commit)
```

---

## 4. 구현 단계 (Phase 1~6)

각 Phase는 독립 산출물을 가진 빌드 단위. Phase가 끝나면 그 시점의 데모를 단독 시연 가능.

| Phase | 산출물 | 의존 | 추정 |
|---|---|---|---|
| 1 | Monitor Agent 로컬 (Strands + 함수형 도구 + 4가지 진단 유형) | - | 1d |
| 2 | Gateway + MCP로 CloudWatch / GitHub 도구 외부화 | P1 | 1.5d |
| 3 | Monitor를 AgentCore Runtime + A2A 서버로 승격 | P2 | 1d |
| 4 | Incident Agent 추가 + Workflow Orchestrator로 A2A 호출 | P3 | 1.5d |
| 5 | AgentCore Policy 적용 (IAM scope-down + NL Policy) | P4 | 1d |
| 6 | Change Agent (Light) + Supervisor Orchestrator + 비교 측정 | P5 | 1.5d |
| | **합계** | | **7.5d** (1인) |

---

### Phase 1 — Monitor Agent 로컬

**산출물**: `local/run_monitor.py` 단독 실행 가능.

```python
# agents/monitor/agent.py — 로컬 모드
from strands import Agent
from strands.models import BedrockModel
from tools.cloudwatch_mock import describe_alarms, describe_alarm_history
from tools.github_local import list_files, put_file

agent = Agent(
    name="Monitor Agent",
    model=BedrockModel("global.anthropic.claude-sonnet-4-5-20250929-v1:0"),
    system_prompt=open("prompts/monitor.md").read(),  # ← 부록 B 4가지 진단 유형
    tools=[describe_alarms, describe_alarm_history, list_files, put_file],
)
```

**로컬 도구**:
- `tools/cloudwatch_mock.py` — `mock_data/alarms.py`(부록 A) 그대로 반환
- `tools/github_local.py` — PyGithub 직접 호출

**처리 가능한 두 모드**:
- 정례: `"최근 1주 noise alarm 진단해줘"`
- 사안성: `"결제 API 5XX 급증 — 분석해줘"` (Phase 4 통합 시나리오의 시작점)

**진행 스트리밍 (사용자 시점)**:
```
→ cloudwatch.describe_alarm_history(since=7d) — 317건
→ github.list_files("rules/") — 18개
→ [분석] alarm별 집계 + noise 후보 선별
→ github.put_file("diagnosis/2026-04-26-noise.md")
```

**수락 기준**:
- Mock 15건 중 **noise 11건 + real 4건** 판정
- 진단 섹션 형식이 부록 A의 `ec2-cpu-high-web-fleet` 샘플과 일치
- 제안 적용 시 예상 주간 Fire **~80% 감소** 메시지 산출
- GitHub `diagnosis/2026-04-26-noise.md` 1건 commit 생성

---

### Phase 2 — Gateway + MCP 도구 외부화

**산출물**: AgentCore Gateway 1개 + Target 2개. Agent 코드는 도구 import 제거, `gateway_client.list_tools_sync()`만 호출.

| Target | Lambda | Smithy | 노출 도구 |
|---|---|---|---|
| `cloudwatch-mock` | `gateway/lambdas/cloudwatch_mock/` (`mock_data/alarms.py` 임베드) | `gateway/smithy/cloudwatch.json` | `DescribeAlarms`, `DescribeAlarmHistory`, `FilterLogEvents` |
| `github-tool` | `gateway/lambdas/github_tool/` (PyGithub) | `gateway/smithy/github.json` | `list_files`, `get_file`, `put_file`, `create_pr` |

```python
# Agent 변경 (전·후 동일 동작)
from utils.gateway import create_gateway_client

gateway_client = create_gateway_client(workload_token)
gateway_client.start()
gateway_tools = gateway_client.list_tools_sync()

agent = Agent(model=..., system_prompt=..., tools=gateway_tools)
```

**핵심 설계 결정**:
- **Smithy 1장으로 도구 schema 정의** → Gateway가 자동으로 MCP 도구 노출 (Lambda에 도구 정의 코드 작성 X)
- OAuth M2M 토큰: `bedrock-agentcore.get_resource_oauth2_token(workloadIdentityToken=..., resourceCredentialProviderName=GATEWAY_PROVIDER, oauth2Flow="M2M")`

**수락 기준**: Phase 1과 동일한 입력·출력. 단, Agent 프로세스에서 도구 코드 import 0건. Gateway 콘솔에서 7개 MCP tool 확인 가능.

---

### Phase 3 — Monitor를 AgentCore Runtime + A2A 서버로 승격

**산출물**: `agents/monitor/` 디렉터리 하나로 ECR push → Runtime 생성 → A2A 카드 노출까지.

```
agents/monitor/
├── agent.py            ← Phase 2 Strands Agent (그대로)
├── agent_executor.py   ← A2A AgentExecutor 구현 (incident-response 샘플 패턴)
├── main.py             ← A2AStarletteApplication + uvicorn
├── prompt/             ← system prompt (부록 B 포함)
├── Dockerfile
└── requirements.txt
```

**`main.py` 핵심**:
```python
agent_card = AgentCard(
    name="Monitor Agent",
    description="결제 서비스 alarm/log 분석 + 4가지 진단 유형",
    url=os.environ["AGENTCORE_RUNTIME_URL"],
    capabilities=AgentCapabilities(streaming=True),
    skills=[AgentSkill(id="analyze_alarms", tags=["cloudwatch"])],
)
app = A2AStarletteApplication(
    agent_card=agent_card,
    http_handler=DefaultRequestHandler(MonitorAgentExecutor(), InMemoryTaskStore()),
).build()
```

**`agent_executor.py`**:
- 헤더에서 `x-amzn-bedrock-agentcore-runtime-session-id`, `-actorid`, `-workload-accesstoken` 추출
- Strands `agent.stream()` 결과를 A2A `TaskUpdater`로 중계
- cancel·error 처리

**배포** (`deploy/02_monitor.sh`): ECR build·push → `AWS::BedrockAgentCore::Runtime` 생성 → SSM에 ARN·provider 저장.

**수락 기준**:
- `python test/connect.py --agent monitor "alarm 분석"` 호출이 Phase 2 로컬 결과와 동일
- AgentCard URL `https://bedrock-agentcore.{region}.amazonaws.com/runtimes/{ARN}/invocations/.well-known/agent-card.json` 응답 OK

---

### Phase 4 — Incident Agent 추가 + Workflow Orchestrator (A2A 첫 호출)

**산출물**: 두 번째 Agent Runtime + 결정론적 Python Workflow가 두 Agent를 A2A로 호출.

#### Incident Agent (Strands, Full)

- 도구: GitHub `runbooks/`·`incidents/` 검색·작성
- 시스템 프롬프트: "Monitor가 넘긴 alarm 요약을 받아 runbook 매칭, severity 결정, incident 티켓 초안 작성"
- 패키지 구조는 Monitor와 동일

#### Workflow Orchestrator (LLM 아님)

```python
# orchestrator/workflow.py
from utils.a2a import a2a_call  # M2M 인증 + AgentCard 로드 + JSON-RPC 호출

async def orchestrate(query: str) -> dict:
    monitor_result = await a2a_call(MONITOR_ARN, query)

    if monitor_result["severity_hint"] in ("medium", "high"):
        incident_result = await a2a_call(
            INCIDENT_ARN,
            f"이 alarm으로 runbook 매칭 + 티켓 초안: {monitor_result}",
        )
        return {"monitor": monitor_result, "incident": incident_result}

    return {"monitor": monitor_result}
```

**시연**:
```
$ python cli.py --orchestrator workflow "결제 API 5XX 급증 — 분석"

→ workflow → monitor (A2A): "최근 15분 결제 API alarm/log 요약"
   ← {"severity_hint": "high", "real_alarms": 3, ...}
→ workflow → incident (A2A): "위 alarm으로 runbook 매칭 + severity"
   ← {"runbook": "RB-042", "severity": "P1", "ticket_draft": "..."}
→ workflow: 두 결과 dict 반환 (LLM 종합 X — Phase 6에서 도입)
```

**수락 기준**:
- Workflow 응답에 두 Agent 결과 모두 포함
- X-Ray trace에 `cli → workflow → monitor / incident` 2-hop 의존성 가시
- Monitor·Incident Runtime 각각 독립 배포 (개별 ECR repo, 개별 Cognito client)

---

### Phase 5 — AgentCore Policy 적용

**산출물**: Agent 코드 변경 없이 Policy on/off로 동작이 달라지는 시연.

#### Layer A — Runtime IAM Role scope-down (`policies/iam/`)

| Agent | 허용 권한 |
|---|---|
| Monitor | `cloudwatch:Describe*`, `logs:FilterLogEvents`, GitHub PAT는 read-only secret |
| Incident | GitHub `runbooks/` read + `incidents/` write only |
| Change | GitHub `deployments/` **read only** |

검증: `aws iam simulate-principal-policy`로 거부 시뮬레이션.

#### Layer B — AgentCore NL Policy 1건 (`policies/nl/no_rules_write.txt`)

```
"Incident Agent must never write to rules/ directory.
 Change Agent must never write — only read."
```

→ NL → Cedar 자동 변환 → Runtime에 attach.

**거부 시연**: Incident Agent에 `"rules/payment.yaml 수정해줘"` 입력 → Policy 거부 → X-Ray + CloudWatch에 거부 사유 기록.

**제외**: Identity Provider 분리(Layer C 후보)는 Phase 4에서 Cognito client 분리로 이미 흡수됨.

**수락 기준**:
- 동일 Agent 코드를 Policy on/off로 두 번 호출, 결과 차이 명확
- 거부 시연이 trace에 보임 (deny reason 텍스트 포함)

---

### Phase 6 — Change Agent (Light) + Supervisor + 패턴 비교

**산출물**: 3-Agent 풀 통합 + 동일 시나리오를 Workflow ↔ Supervisor 두 패턴으로 실행한 측정 데이터.

#### Change Agent (Light, ~50 LoC)

```python
# agents/change/agent.py
agent = Agent(
    name="Change Agent",
    model=BedrockModel(...),
    system_prompt="최근 24h 배포·구성 변경 중 회귀 후보 1건 식별. JSON으로 답.",
    tools=[gateway_tools["list_files"], gateway_tools["get_file"]],
)
```

ECR push → Runtime 배포 → A2A 카드 노출은 Monitor·Incident와 동일 패턴 (`deploy/04_change.sh`).

#### Supervisor Orchestrator (Strands Agent)

```python
# orchestrator/supervisor.py
from strands import Agent
from strands.multiagent.a2a import RemoteA2aAgent

monitor  = RemoteA2aAgent(name="monitor",  agent_card=MONITOR_CARD_URL,  auth_provider="cognito-monitor-m2m")
incident = RemoteA2aAgent(name="incident", agent_card=INCIDENT_CARD_URL, auth_provider="cognito-incident-m2m")
change   = RemoteA2aAgent(name="change",   agent_card=CHANGE_CARD_URL,   auth_provider="cognito-change-m2m")

supervisor = Agent(
    name="Cloud Op Supervisor",
    model=BedrockModel(...),
    system_prompt=open("prompts/orchestrator.md").read(),
    sub_agents=[monitor, incident, change],
)
```

`prompts/orchestrator.md`:
```
You are the Cloud Op orchestrator. For an incident query:
1. monitor: 현황 데이터 수집 (필수)
2. monitor 결과가 'real incident'면:
   2a. incident + change를 병렬 호출
3. 모든 결과를 Markdown으로 종합 → github.put_file('diagnosis/{date}-{ticket}.md')
```

#### 비교 측정

같은 입력 `"결제 API 장애 진단해서 리포트 올려줘"`을 두 번 실행하고 측정:

| 측정 | Workflow (Phase 4) | Supervisor (Phase 6) |
|---|---|---|
| LLM 호출 수 | 2 | 3+ |
| Input 토큰 합 | (측정) | (측정) |
| Output 토큰 합 | (측정) | (측정) |
| End-to-end 지연 | (측정) | (측정) |
| 결정성 (10회 반복) | 100% 동일 | (측정) |
| 시나리오 변경 시 | 코드 수정 | 프롬프트 수정 |
| 디버깅 난이도 | Python trace로 충분 | LLM 결정 로그 + X-Ray 필요 |

**Supervisor 시연 출력**:
```
$ python cli.py --orchestrator supervisor "결제 API 장애 진단해서 리포트 올려줘"

[stream]
  → monitor : real incident 확정 (3건)
  ║ incident: P1, RB-042 매칭, 티켓 INC-1107 초안
  ║ change  : payment-svc v3.4.1 (30분 전) — 회귀 후보
  → github  : diagnosis/2026-04-26-INC-1107.md 커밋

✅ 권고 액션
  1. payment-svc v3.4.0 롤백 (Change 권고)
  2. P1 incident 채널 통보 (티켓: INC-1107)
```

**수락 기준**:
- 두 Orchestrator가 같은 입력에 동등한 비즈니스 결과 산출 (티켓 번호·회귀 후보 동일)
- GitHub에 실제 commit 1건 생성
- 비교 측정값 표가 README에 첨부됨

---

### 운영·관측 (Phase 6 이후)

- AgentCore Observability 콘솔에서 3-Agent invocation 트레이스
- X-Ray로 Workflow / Supervisor 둘 다 fan-out trace 확인
- CloudWatch metrics: token usage / latency / error rate per agent
- Bonus 시연: real CloudWatch `DescribeAlarms` 1건으로 mock 1건 교체 (Mock 전용 필드 `_ack_ratio_7d` 등이 사라지는 모습 확인)

---

## 5. Repo 구조

```
cloud-op-ai-ops/
├── README.md                ← 데모 시스템 사용 가이드
├── plan.md                  ← 본 문서 (구현 계획)
├── plan.v1-single-agent.md  ← v1 단일 Agent 구버전 (참고)
├── setup/
│   ├── preflight.sh         ← AWS/Bedrock/GitHub 자격 확인
│   ├── seed_github.py       ← rules/runbooks/deployments mock 시드
│   └── cognito_clients.env  ← 사전 배포 Cognito ARN/ClientID
├── mock_data/
│   └── alarms.py            ← v1 §5 합성 alarm 15건 + 1주 history (그대로)
├── prompts/
│   ├── monitor.md           ← 부록 B 4가지 진단 유형 포함
│   ├── incident.md
│   ├── change.md
│   └── orchestrator.md      ← Phase 6 Supervisor용
├── tools/
│   ├── cloudwatch_mock.py   ← Phase 1 로컬 도구
│   └── github_local.py
├── gateway/
│   ├── smithy/
│   │   ├── cloudwatch.json
│   │   └── github.json
│   └── lambdas/
│       ├── cloudwatch_mock/ ← mock_data/alarms.py 임베드
│       └── github_tool/
├── agents/
│   ├── monitor/             ← Full
│   ├── incident/            ← Full
│   └── change/              ← Light (~50 LoC)
├── orchestrator/
│   ├── workflow.py          ← Phase 4 결정론적 Python
│   ├── supervisor.py        ← Phase 6 Strands Agent
│   └── Dockerfile           ← Phase 6 Runtime
├── policies/
│   ├── iam/                 ← Phase 5 Layer A
│   └── nl/                  ← Phase 5 Layer B
├── deploy/
│   ├── 00_cognito.cfn.yaml  ← 사전 배포 (Cognito UserPool + 4 Client)
│   ├── 01_gateway.sh
│   ├── 02_monitor.sh
│   ├── 03_incident.sh
│   ├── 04_change.sh
│   ├── 05_supervisor.sh
│   └── cleanup.sh
├── local/
│   └── run_monitor.py       ← Phase 1 로컬 실행
├── cli.py                   ← --orchestrator workflow|supervisor
└── test/
    └── connect.py           ← Agent별 A2A 직접 호출
```

> DR Agent 관련 파일·디렉터리는 v2 데모 범위에서 제외.

---

## 6. 핵심 설계 결정 기록

| # | 결정 | 대안 | 채택 사유 |
|---|---|---|---|
| D1 | **3 Agent 빌드 (Monitor·Incident Full + Change Light)** | 4 Agent / 1 Agent | 다중 Agent 가치는 3개로 충분, 빌드 복잡도 ↓, Change는 패턴만 보이면 OK |
| D2 | **DR 도메인 데모 범위 제외** | DR Agent 풀 빌드 / DR mock | mock 데이터 셋업 부담 ↑, failover 의사결정은 진짜 인프라 없으면 설득력 약함 |
| D3 | **Orchestrator를 Workflow + Supervisor 둘 다 구현** | Supervisor만 / Workflow만 | 두 패턴의 트레이드오프 측정이 데모의 핵심 가치 |
| D4 | **A2A 프로토콜 채택** (Strands sub_agents 인-프로세스가 아니라) | Strands `Swarm`/`Graph` | 각 Agent가 독립 Runtime — 팀별 독립 배포·소유 메시지. AgentCore Runtime의 A2A 네이티브 지원 활용 |
| D5 | **모든 Agent를 Strands로 통일** (incident-response 샘플의 ADK/OpenAI 혼용 제거) | 다중 SDK 혼용 | 인증·운영 단순화, "프레임워크 자유" 메시지는 v3로 미룸 |
| D6 | **Mock CloudWatch + Real GitHub** | All real / All mock | 결과 안정성(mock) + 결과물 임팩트(실제 commit) 균형. real CloudWatch는 Bonus 시연만 |
| D7 | **Policy = IAM scope-down + NL Policy 1건** | Cedar 직접 작성 / IAM만 | NL Policy의 거부 시연이 가장 강한 인상, IAM은 보편적 가드레일 |
| D8 | **Cognito UserPool 1 + UserPoolClient 4 (Agent별 분리)** | 단일 Client 공유 | Agent별 Identity 분리가 Policy/감사 추적의 전제 |
| D9 | **베이스 샘플 차용**: `02-use-cases/A2A-multi-agent-incident-response`의 Strands MonitoringAgent + AgentExecutor 패턴 | 0부터 작성 | 검증된 A2A 통합 코드, 4-5x 빠른 빌드 |
| D10 | **v1 Mock 데이터·진단 로직 100% 흡수** | 새로 작성 | v1의 4가지 진단 유형은 Monitor의 비즈니스 가치. 폐기 시 데모 약화 |

---

## 7. 의존·전제 (Dependencies & Assumptions)

- **AWS 리전**: us-west-2 (A2A 정식 지원)
- **Bedrock 모델 액세스**: Claude Sonnet 4.5 (`global.anthropic.claude-sonnet-4-5-20250929-v1:0`) — Agent용. Haiku 4.5 (`global.anthropic.claude-haiku-4-5-20251001-v1:0`) — Change Agent 비용 절감용 옵션
- **GitHub**: 데모용 repo 1개 + PAT(`repo` scope) 또는 GitHub App
- **Python**: 3.12+, `uv` 패키지 매니저
- **컨테이너**: Docker (ECR 푸시용)
- **Cognito UserPool**: 사전 1회 배포 후 `cognito_clients.env`로 재사용
- **인프라 수명**: 데모 끝나면 `deploy/cleanup.sh`로 1시간 내 전량 삭제
- **비용**: 데모 1회 실행당 < $1 (Bedrock 토큰 + Lambda 호출 + Runtime 실행시간 기준 추정)

---

## 8. Open Questions

1. **A2A SDK 의존성** — `a2a` Python 패키지 직접 사용 / Strands `RemoteA2aAgent` 추상화로 충분? (Strands가 어디까지 캡슐화하는지 검증 필요)
2. **Cognito 배포 모델** — 단일 UserPool에서 4 Client 발급 / Agent마다 별도 UserPool? 후자가 격리 강함
3. **Memory 사용 여부** — incident-response 샘플은 AgentCore Memory를 단·장기 양쪽에 사용. v2에서는 단기만? 아예 제외?
4. **GitHub repo 모델** — 데모용 단일 공용 repo (모든 commit이 한 곳) / 시연마다 신규 repo
5. **NL Policy 위치** — Runtime마다 attach / 전역 1건? 거부 동작 차이는?
6. **실제 운영 이행 시점** — 데모는 mock CloudWatch. 실제 채택 시 alarm 시드 자동화는 어떻게?

---

## 9. 부록 A — Mock CloudWatch 데이터 (v1 §5 흡수)

`mock_data/alarms.py`로 임베드. CloudWatch Mock Lambda가 그대로 반환.

### 합성 Alarm 15건

| #   | AlarmName                   | 서비스/Metric                              | 임계     | 1주 Fire          | Auto-resolve | 평균 Duration | Ack 비율     | 예상 판정                         |
| --- | --------------------------- | --------------------------------------- | ------ | ---------------- | ------------ | ----------- | ---------- | ----------------------------- |
| 1   | `payment-api-5xx-rate`      | APIGW `5XXError` > 10                   | 10/min | 3                | 0%           | 22m         | 100%       | ✅ 정상 (진짜 이슈)                  |
| 2   | `ec2-cpu-high-web-fleet`    | EC2 `CPUUtilization` > 70%              | 70     | **142**          | 96%          | 4m          | 2%         | ⚠️ Threshold 상향               |
| 3   | `rds-prod-cpu`              | RDS `CPUUtilization` > 90%              | 90     | 5                | 40%          | 18m         | 100%       | ✅ 정상                          |
| 4   | `lambda-checkout-errors`    | Lambda `Errors` > 1                     | 1      | **87**           | 100%         | 1m          | 0%         | ⚠️ Threshold 상향               |
| 5   | `alb-target-5xx`            | ALB `HTTPCode_Target_5XX` > 5           | 5/5m   | **56**           | 89%          | 3m          | 5%         | ⚠️ 조건 결합                      |
| 6   | `nightly-batch-cpu-spike`   | EC2 `CPUUtilization` > 80%              | 80     | **49** (02-04시)  | 100%         | 12m         | 0%         | ⚠️ Time window 제외             |
| 7   | `deploy-time-5xx`           | ALB `5XXError` > 3                      | 3      | **34** (배포 시간대)  | 100%         | 2m          | 0%         | ⚠️ Time window 제외             |
| 8   | `dynamodb-throttle-orders`  | DDB `ThrottledRequests` > 0             | 0      | 8                | 50%          | 9m          | 87%        | ✅ 정상                          |
| 9   | `sqs-queue-depth-legacy-v1` | SQS `ApproximateNumberOfMessages` > 100 | 100    | **21**           | 100%         | 7m          | 0% (90일+)  | ⚠️ Rule 폐기                    |
| 10  | `old-ec2-status-check`      | EC2 `StatusCheckFailed` > 0             | 0      | **18**           | 100%         | 2m          | 0% (120일+) | ⚠️ Rule 폐기                    |
| 11  | `api-latency-p99`           | APIGW `Latency` p99 > 2000ms            | 2000   | 7                | 57%          | 14m         | 100%       | ✅ 정상                          |
| 12  | `ecs-memory-web`            | ECS `MemoryUtilization` > 60%           | 60     | **98**           | 94%          | 2m          | 3%         | ⚠️ Threshold 상향               |
| 13  | `s3-4xx-public-bucket`      | S3 `4xxErrors` > 20                     | 20     | **41**           | 76%          | 5m          | 12%        | ⚠️ 조건 결합                      |
| 14  | `rds-connections-high`      | RDS `DatabaseConnections` > 80          | 80     | **63** (출퇴근 시간대) | 100%         | 8m          | 0%         | ⚠️ Time window / Threshold    |
| 15  | `waf-blocked-requests`      | WAF `BlockedRequests` > 0               | 0      | **204**          | 100%         | 1m          | 0%         | ⚠️ Rule 폐기 or Threshold 대폭 상향 |

**판정 분포**: ✅ 정상 4건 (1, 3, 8, 11) / ⚠️ Threshold 3건 / ⚠️ 조건 결합 2건 / ⚠️ Time window 3건 / ⚠️ Rule 폐기 3건.

### 데이터 스키마

```python
# describe_alarms 응답 한 건
{
    "AlarmName": "ec2-cpu-high-web-fleet",
    "MetricName": "CPUUtilization",
    "Namespace": "AWS/EC2",
    "Threshold": 70.0,
    "ComparisonOperator": "GreaterThanThreshold",
    "EvaluationPeriods": 1,
    "Period": 300,
    "StateValue": "OK",
    "StateUpdatedTimestamp": "2026-04-22T14:12:08Z",
    # Mock 전용 (real CloudWatch에는 없음 — Bonus 시연 시 사라짐)
    "_tags": {"service": "web", "env": "prod", "team": "platform"},
    "_ack_ratio_7d": 0.02,
}
```

`describe_alarm_history`는 위 15개에 대해 1주치 `StateUpdate` 이벤트 **약 900건** 반환 (Fire 횟수 × 2 — ALARM↔OK 전환).

### Monitor Agent 산출 리포트 샘플 (수락 기준)

```markdown
### ⚠️ ec2-cpu-high-web-fleet — Threshold 상향 권장

**현재 정의**
- Metric: AWS/EC2 CPUUtilization (Average)
- Threshold: > 70%, Period 5m, EvaluationPeriods 1

**1주 발생 패턴**
- Fire: 142건 / Auto-resolve: 96% / 평균 Duration: 4분 / Ack: 2%
- 주간 트래픽 피크(09:00-11:00, 14:00-16:00) 집중

**원인 추론**
정상 피크 트래픽의 90-percentile CPU가 73%. 현 임계 70%는 정상 부하에도 걸림.
96%가 조치 없이 자동 해소되고 ack도 2%로 실무 무시 상태.

**제안**
- Threshold: 70% → **85%** (90-percentile + 여유)
- EvaluationPeriods: 1 → **2** (단발성 스파이크 흡수)
- 예상 Fire 감소: 142 → ~8건/주 (**-94%**)
```

---

## 10. 부록 B — Monitor Agent의 4가지 진단 유형 (v1 §2 흡수)

`prompts/monitor.md` 핵심 의사결정 프레임. Monitor Agent가 noise 후보를 식별한 뒤 어떤 개선안을 제안할지 판단.

| 유형 | 트리거 신호 | 제안 |
|---|---|---|
| **Threshold 상향** | 정상 트래픽에도 반응. Auto-resolve > 90%, Ack < 5% | 임계값을 정상 범위 상단(예: 90-percentile)으로 ↑ |
| **조건 결합 (AND)** | 단일 metric만 보면 오탐 잦음. Auto-resolve 80~90%대 | 다른 metric·이벤트와 동시 위반 시에만 fire |
| **Time window 제외** | 새벽 배치·배포 등 예측 가능 시간대에 집중 | 해당 시간대 alarm suppress |
| **Rule 폐기** | 장기간 ack/action 0건 (90일+). 실무 가치 없음 | 규칙 자체 삭제 |

이 4가지는 Phase 1 수락 기준이자, Phase 4 Incident Agent에 넘기는 입력 구조이자, 부록 A 표 "예상 판정" 컬럼의 출처. **Monitor Agent는 위 4가지 중 1개로 분류한 뒤 부록 A 형식의 진단 섹션을 생성**해야 함.

---

## 11. 부록 C — Agent별 IAM 권한 매트릭스 (Phase 5 Layer A)

| 권한 | Monitor | Incident | Change | Supervisor |
|---|---|---|---|---|
| `bedrock:InvokeModel` | ✅ | ✅ | ✅ | ✅ |
| `bedrock-agentcore:GetResourceOauth2Token` | ✅ | ✅ | ✅ | ✅ |
| `cloudwatch:Describe*` | ✅ | ❌ | ❌ | ❌ |
| `logs:FilterLogEvents` | ✅ | ❌ | ❌ | ❌ |
| `lambda:InvokeFunction` (Gateway target) | ✅ | ✅ | ✅ | ❌ |
| GitHub `runbooks/` read | ❌ | ✅ | ❌ | ❌ |
| GitHub `runbooks/` write | ❌ | ❌ | ❌ | ❌ |
| GitHub `incidents/` write | ❌ | ✅ | ❌ | ❌ |
| GitHub `deployments/` read | ❌ | ❌ | ✅ | ❌ |
| GitHub `deployments/` write | ❌ | ❌ | ❌ | ❌ |
| GitHub `diagnosis/` write | ❌ | ❌ | ❌ | ✅ (또는 Workflow 코드) |
| `bedrock-agentcore:InvokeAgentRuntime` (A2A) | ❌ | ❌ | ❌ | ✅ |
| Secrets Manager (PAT 읽기) | read-only | scoped | scoped | scoped |
