# AIOps 멀티에이전트 인시던트 대응 데모 — 요약

> IT 운영의 "장애 진단·대응" 워크플로를 멀티에이전트로 자동화하는 데모 시스템.  
> AWS Bedrock AgentCore Runtime + Strands + A2A 프로토콜 기반.  
> alarm fire 후 운영자 CLI 질의 → Monitor → Incident → Change 3개 Agent 협업 → 진단 리포트 자동 생성·commit.

---

## 시스템 목표


| #   | 능력                                      | 검증 기준                                              |
| --- | --------------------------------------- | -------------------------------------------------- |
| C1  | Strands 로컬 → AgentCore Runtime 동일 코드 승격 | 로컬 == Runtime 응답                                   |
| C2  | Gateway + MCP로 도구 외부화                   | Agent 코드에 도구 import 0건                             |
| C3  | A2A 프로토콜로 독립 Runtime 간 호출               | Workflow / Supervisor 둘 다 다른 Runtime AgentCard로 호출 |
| C4  | AgentCore Policy로 권한·가드레일 외부화           | NL Policy 거부 시연 (readonly enforcement)              |
| C5  | 두 Orchestration 패턴 비교 (stretch)         | Workflow vs Supervisor 토큰·지연·결정성 측정 (Phase 6b)      |


---

## 시나리오 — "결제 서비스 P1 장애 대응"

```
T-0      운영자가 EC2 stop_instance.sh 실행
          → 실 CloudWatch alarm fire (payment-${DEMO_USER}-status-check)
T-0+30s  운영자 CLI 질의 "결제 서비스 진단해줘" → Orchestrator 시작
T+1m     ① Monitor   — (a) 라이브 alarm 1건 noise vs real 판정
                        (b) 7일 history → 3가지 진단 유형 제안
T+3m     ② Incident  — runbook 매칭 → P1 escalate, 티켓 초안
T+5m     ③ Change    — 최근 24h 배포에서 회귀 후보 1건 식별
T+8m     Orchestrator — 종합 → 진단 리포트 자동 commit + 권고 액션
```

> ※ 현재는 EC2 시뮬레이터로 시연. EC mall 도착 시 alarm 추가만으로 동일 흐름 확장 (Agent 코드 무변경).


| 페르소나 | Agent    | 도구                              | 빌드 깊이           |
| ---- | -------- | ------------------------------- | --------------- |
| 모니터링 | Monitor  | CloudWatch + GitHub             | Full            |
| 장애관리 | Incident | GitHub `runbooks/`+`incidents/` | Full            |
| 변경관리 | Change   | GitHub `deployments/` read      | Light (~50 LoC) |


---

## 아키텍처

```
[운영자 터미널 CLI]
       │  Cognito Client A (M2M)
       ▼
┌──────────────────────────────────────────────────────────────┐
│  Orchestrator                                                │
│   ├─ Supervisor (AgentCore Runtime)  [Phase 6a 필수]         │
│   │    Strands Agent + sub_agents (LLM 라우팅)              │
│   └─ Workflow (로컬 Python CLI)      [Phase 6b stretch]      │
│        asyncio + httpx (결정론적, 비교 측정용)              │
└──────────────────────────────────────────────────────────────┘
       │  A2A JSON-RPC + Bearer (스타 토폴로지, Cognito Client B)
       ├──────────────┬──────────────┐
       ▼              ▼              ▼
┌─────────────┐ ┌─────────────┐ ┌─────────────┐
│ Monitor     │ │ Incident    │ │ Change      │
│ (Strands)   │ │ (Strands)   │ │ (Strands)   │
│ AgentCore   │ │ AgentCore   │ │ AgentCore   │
│ Runtime     │ │ Runtime     │ │ Runtime     │
└─────────────┘ └─────────────┘ └─────────────┘
       │              │              │
       │  MCP streamable-http + Bearer (AgentCore Identity 자동, Cognito Client C)
       ▼              ▼              ▼
┌──────────────────────────────────────────────────────────────┐
│  AgentCore Gateway (MCP)                                     │
│   ├─ CloudWatch Target  (Smithy + 실 CloudWatch API)         │
│   │      ↑ EC2 simulator (now) → EC mall (later)             │
│   ├─ GitHub Target      (Lambda + PyGithub, 실 repo)         │
│   └─ history mock Target (Lambda, mock_data/phase1/alarm_history.py)│
└──────────────────────────────────────────────────────────────┘
       │
       ▼
[GitHub repo]  rules/ runbooks/ deployments/ diagnosis/ incidents/
       ┊  (GitHub 차단 시 fallback)
       ▼
[S3 bucket]    동일 prefix 구조, Lambda 한 곳만 교체
```

### 데이터·인증 흐름 (요청 1건)

```
운영자 → CLI → Supervisor Runtime (Phase 6b stretch: Workflow 로컬 대안 경로)
            ↓ Cognito Client A → Supervisor 진입
        Supervisor → Monitor / Incident / Change (스타 토폴로지)
            ↓ A2A JSON-RPC + Bearer (Cognito Client B)
        Sub-agent Runtime
            ↓ MCP streamable-http + Bearer
            ↑ AgentCore Identity 자동 발급 (Cognito Client C)
        AgentCore Gateway
            ↓ Smithy 매핑 → AWS SigV4 / Lambda invoke
        실 CloudWatch API  /  GitHub Lambda  /  history mock Lambda
            ↓
        실 repo (commit)    ┊ GitHub 차단 시 S3 fallback
```

### 컴포넌트 인벤토리


| 컴포넌트              | 수                                                       |
| ----------------- | ------------------------------------------------------- |
| Operator CLI      | 1 (Python ~30 LoC, Cognito Client A 사용)                 |
| Strands Agent     | 4 (Monitor + Incident + Change + Supervisor)            |
| Orchestrator      | 1 + 1 stretch (Supervisor 필수 / Workflow는 Phase 6b)    |
| AgentCore Runtime | 4                                                       |
| AgentCore Gateway | 1 (Target 3: CloudWatch native + GitHub + history mock) |
| Lambda            | 2 (GitHub + history mock)                               |
| EC2 simulator     | 1 (t3.micro + Flask + 카오스 스크립트, EC mall 도착 시 대체)       |
| Storage           | GitHub repo 1 (또는 S3 bucket 1, fallback)                |
| Cognito           | UserPool 1 + UserPoolClient 3 (A: 운영자→Supervisor / B: Supervisor→Sub-agents / C: Sub-agents→Gateway) |
| IAM Role          | 1 (통합, 모든 Runtime 공유)                              |
| NL Policy         | 1 (readonly enforcement)                                |


---

## 구현 단계


| Phase | 산출물                                                       |
| ----- | --------------------------------------------------------- |
| 0     | EC2 시뮬레이터 + CloudWatch alarm 2종 (real 1 + noise 1) + 카오스 스크립트 1종           |
| 1     | Monitor Agent 로컬 (Strands + 3가지 진단 유형, Track B mock 검증)                |
| 2     | Gateway + MCP로 도구 외부화 (CloudWatch native + GitHub) + 라이브 alarm 분류 검증  |
| 3     | Monitor → AgentCore Runtime + A2A 서버 승격                                |
| 4     | Incident Agent + GitHub storage Lambda + sequential CLI (A2A는 6a 통합 이월) |
| 5     | ~~AgentCore Policy 적용 (NL Policy readonly) + 거부 시연 스크립트~~ — **본 프로젝트 scope 제외** (Strands+AgentCore 학습량 우선) |
| 6a    | Supervisor + Change Agent + A2A 활성화 (server+caller) + Cognito Client A/B + deployments-storage Lambda + Operator CLI |
| 6b    | (stretch) Workflow Orchestrator + Workflow vs Supervisor 비교 측정           |
| 7     | EC mall 통합 — alarm 확장만으로 동일 시나리오 재현 (외부 의존: 동료 EC mall 완료)         |


---

---

## 의존·전제

- **베이스 코드 (직접 차용)**:
  - **A2A 멀티에이전트 인프라 골격**: `/home/ubuntu/amazon-bedrock-agentcore-samples/02-use-cases/A2A-multi-agent-incident-response/` — Cognito 95% / Strands 90% / CloudFormation 80% / deploy.py 75% / A2A 100% 재사용
  - **로컬↔Runtime 전환 패턴 + 부트스트랩**: `/home/ubuntu/developer-briefing-agent/` — `local-agent/` ↔ `managed-agentcore/` 폴더 분리 + `create_agent()` 단일 진실 원천 + 시스템 프롬프트 외부화 + memory hooks + `setup.sh` 통합 부트스트랩 + `setup/store_github_token.sh` SSM SecureString 패턴
  - **에이전트별 모델·관측성 env 패턴**: `/home/ubuntu/sample-deep-insight/managed-agentcore/.env.example` — per-agent `MODEL_ID` 분리 + OTEL `service.name` 자동 통합
  - **변형 포인트**: Google ADK Supervisor → Strands sub_agents 전환, OpenAI/Tavily 제거, GitHub Lambda + history mock Lambda Target 추가, EC2 카오스 + 3가지 진단 유형 신규
- **AWS 계정 액세스**: Bedrock Claude Sonnet 4.6 / Haiku 4.5 model access 활성화 + AgentCore Runtime 4개·Gateway 1개 quota 확인
- **리전**: us-west-2 (A2A 정식 지원)
- **모델 (env var로 에이전트별 분리)**:
  - `MONITOR_MODEL_ID=claude-sonnet-4-6` (기본)
  - `INCIDENT_MODEL_ID=claude-sonnet-4-6`
  - `CHANGE_MODEL_ID=claude-haiku-4-5-20251001` (비용 옵션)
  - `SUPERVISOR_MODEL_ID=claude-sonnet-4-6`
- **관측성 (선택, 거의 공짜)**: `OTEL_RESOURCE_ATTRIBUTES=service.name=<agent>` + `AGENT_OBSERVABILITY_ENABLED=true` 설정 시 CloudWatch GenAI Observability에 에이전트별 자동 표시
- **저장소** (택1):
  - **GitHub** (권장, PAT 또는 GitHub App)
  - **S3** (GitHub 차단 시 폴백) — 동일 디렉터리 구조를 prefix로 매핑, Lambda 한 곳만 교체
- **EC2 simulator**: t3.micro 1대 (Amazon Linux 2023, public subnet, SSH 접근)
- **시크릿 보관**:
  - GitHub PAT → **AWS SSM Parameter Store SecureString** (예: `/aiops-demo/github-token`, KMS 암호화)
  - Cognito client_secret → AWS Secrets Manager 또는 SSM
  - 개발 편의용 `.env` (gitignore)
- **부트스트랩 (2-스크립트 분리)**:
  - `bootstrap.sh` — dev 환경: `uv sync` → `.env` 생성 → GitHub PAT를 SSM SecureString에 저장 + GitHub API 검증
  - `deploy.py` — AWS 인프라 배포 (CloudFormation, Cognito, AgentCore Runtime, Gateway). A2A 샘플에서 차용 후 4개 Runtime + 3 Target으로 확장
  - AgentCore Memory 사용 여부는 Phase 4~5에서 결정 (현재 plan에 미정)
- **언어·도구**:
  - Python 3.12+
  - `uv` — 로컬 의존성 관리
  - Docker — AgentCore Runtime 컨테이너 빌드
- **수명**: `deploy/cleanup.sh`로 1시간 내 전량 삭제
- **데모 중 cleanup 비활성화**: `DEMO_MODE=on` 시 자동 삭제 일시 중단

---

## 데이터 — EC2 시뮬레이터 (실 CloudWatch) + history mock

**Track A — 라이브 alarm (실 CloudWatch, minimum)**
- EC2 t3.micro 1대 + Flask "결제 API" (`/health` 만)
- 알람 2종 (real/noise 라벨):
  - `payment-${DEMO_USER}-status-check` (real, 시나리오 메인 트리거)
  - `payment-${DEMO_USER}-noisy-cpu` (noise, 의도적 잘못된 임계값 — `CPUUtilization > 0.5%`)
- 카오스 스크립트: `stop_instance.sh` / `start_instance.sh` (복원)
- EC mall 도착 시 alarm 추가만으로 확장 (Agent 코드 무변경)

**Track B — history mock**
- `mock_data/phase1/alarm_history.py` — 3가지 진단 유형 검증용 7일치 history (단일 EC2로는 90일 패턴 불가)
- **제공 방식**: history mock Lambda → Gateway Target 3번째로 노출 (CloudWatch native + GitHub + history mock)
- 데이터 형식: AWS CloudWatch DescribeAlarms / DescribeAlarmHistory 응답 (PascalCase) + 합성 `ack` / `action_taken` (PD 등 incident system fused)
- Alarm 5건: noise 3 / real 2
- History 24건 (전부 손으로 작성한 literal — 처음 보는 사람이 한 번에 읽힘)
- 노이즈 패턴 분포: Threshold 상향 1 / Time window 제외 1 / Rule 폐기 1 (각 유형 정의는 §Monitor Agent 3가지 진단 유형 참조)

**스위치** — env var `CLOUDWATCH_DATA_MODE=live|history` 로 라이브/history 경로 선택. Agent 코드 무변경.

**수락 기준**:
- **Track A**: 카오스 실행 → 실 alarm fire → Agent JSON 응답의 `output.classification == "real"` → 진단 리포트 commit
- **Track B**: noise 3 / real 2 정확 판정 + Agent 응답에 `estimated_weekly_fire_reduction_pct` 정수 포함

---

## Monitor Agent 3가지 진단 유형


| 유형             | 트리거 (정량 조건)                                                                | 제안                          |
| -------------- | ----------------------------------------------------------------------------- | --------------------------- |
| Rule 폐기        | 7일 ack 0건 AND action 0건 AND `AlarmConfigurationUpdatedTimestamp` 90일+ 이전     | 규칙 삭제                       |
| Threshold 상향   | 7일 auto-resolve > 90% AND ack < 5% (위 1에 매칭 안 됨)                              | 임계값을 7일 메트릭의 P90로 상향        |
| Time window 제외 | 특정 UTC 2시간 윈도우 내 fire 비율 > 80% (위 1, 2에 매칭 안 됨)                              | 해당 시간대 suppression 윈도우 추가   |

**우선순위**: Rule 폐기 > Threshold 상향 > Time window 제외. 어느 것에도 해당 안 되면 그 알람은 noise가 아닌 real 로 판단 (`real_alarms`에 포함).

> **auto-resolve란?** OK→ALARM fire 후 사람이 ack 하지 않은 채 메트릭이 임계값 아래로 떨어져 ALARM→OK 로 돌아온 경우. 비율이 매우 높다 = 실제 문제가 아닌데 알람만 시끄럽게 울림.

**진단 출력 스키마** (Monitor Agent 응답):

```yaml
diagnoses:
  - alarm: legacy-2018-server-cpu
    type: rule_retirement
    rationale: "alarm_age_days=100, 7일 ack 0건, action 0건"
    suggested_action: "규칙 삭제"
  - alarm: web-server-memory-routine
    type: threshold_uplift
    rationale: "7일 fire 4건 전량 auto_resolve(100%), ack 0건(0%)"
    suggested_action: "임계값 70% → P90인 90%로 상향"
estimated_weekly_fire_reduction_pct: 60
real_alarms:
  - web-server-cpu-high
  - payment-api-5xx-errors
```


