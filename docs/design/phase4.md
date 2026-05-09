# Phase 4 — Incident Agent 추가 + GitHub storage + sequential CLI

> Phase 3 (`docs/design/phase3.md`) 가 Monitor 를 AgentCore Runtime 위에 올린 후, 이 단계에서 **2번째 Runtime (Incident Agent)** + **GitHub storage Lambda** + **sequential CLI invoke** 를 추가한다.
> **A2A 프로토콜 활성화** (server + caller 양쪽) 는 resource.md §1 정렬에 따라 **Phase 6a (Supervisor 도입 시점) 로 통합 이월**. Phase 4 의 multi-agent 호출은 CLI 가 boto3 sequential invoke 로 시연.
> Phase 3 자원 (Monitor Runtime, Cognito stack, Gateway, Lambda × 2) 은 **무변경** — Phase 4 PR 영향 범위 격리. Phase 3 회귀 0건.

---

## 0-1. 한 줄 정의

**Phase 4 = multi-agent 진입.** "Incident Agent 를 추가하고, CLI 가 Monitor 와 Incident 를 순차로 호출하며, runbook 데이터를 GitHub Lambda 로 읽는다." Phase 3 의 dba 패턴 + Phase 2 의 Lambda Target 패턴이 양쪽에서 재사용된다.

| 측면 | Phase 3 (current) | **Phase 4 (이번)** |
|---|---|---|
| Runtime 개수 | 1 (Monitor) | **2 (Monitor + Incident)** |
| Agent-to-agent 호출 | 없음 (단일 Runtime) | **CLI sequential** — `invoke_runtime.py` 가 Monitor → Incident 순차 boto3 invoke. A2A 프로토콜은 Phase 6a 로 이월 |
| 도구 Lambda 개수 | 2 (history-mock, cloudwatch-wrapper) | **3** (+ github-storage) |
| GitHub repo 의 데이터 사용 | 없음 | **Incident 가 `data/runbooks/` read** |
| Cognito Client | C (Phase 2) — Gateway M2M | **C 그대로** (Phase 4 미터치). Client A/B 는 Phase 6a (Supervisor 도입 시) |
| Monitor Runtime | Phase 3 그대로 | **무변경** — `@app.entrypoint` 패턴 carry-over, A2A retrofit 은 Phase 6a |
| Incident Runtime | 없음 | **신규** (`agents/incident/runtime/`) — Phase 3 dba 패턴 그대로 복제 (`@app.entrypoint`) |
| AgentCore Memory | 보류 (Phase 3 D6) | **계속 보류** (Phase 5 재평가) |

---

## 0-2. 시스템 목표 매핑 (C1 ~ C5)

`docs/design/plan_summary.md` §시스템 목표 매핑:

| # | 능력 | Phase 4 에서의 역할 | 검증 방법 |
|---|---|---|---|
| C1 | 같은 코드 local/Runtime | **회귀 없음** — Monitor C1 유지, Incident 도 동일 패턴 적용 | P4-A1 (Phase 3 P3-A1 ~ A6 회귀 없음) |
| **C2** | Gateway + MCP 도구 외부화 | **★ 확장** — github-storage Target 추가, Incident 도 `from .tools` import 0건 | P4-A2 (Incident 코드 grep), P4-A4 (runbook read) |
| C3 | A2A 프로토콜로 독립 Runtime 간 호출 | **이월** — Phase 6a Supervisor 도입 시 server + caller 양쪽 동시 활성화 (resource.md §1 정렬). Phase 4 는 sequential CLI invoke 로 multi-agent 동작만 시연 | Phase 6a 에서 검증 |
| C4 | AgentCore Policy | 무관 (Phase 5) | — |
| C5 | Workflow vs Supervisor | 무관 (Phase 6b) | — |

→ **Phase 4 의 직접 deliverable = C2 확장 (GitHub Lambda) + multi-agent sequential invoke 시연**. C3 (A2A) 는 Phase 6a 통합 활성화로 이월 — workshop 청중에게 "caller (Supervisor) 가 등장하기 전엔 A2A 가 의미 없는 dead code" 라는 educational 메시지.

---

## 0-3. Phase 4 가 **하지 않는** 것 (scope cuts)

자세한 목록은 §7 Out of Scope. 한 줄 요약:

- **A2A 프로토콜 활성화** (server-side `A2AStarletteApplication` + caller-side `RemoteA2aAgent`) — **Phase 6a 로 통합 이월** (resource.md §1 의 "Phase 6a Supervisor 변환 시 핵심 참조" 정렬)
- **Cognito Client A/B** — Phase 6a (Supervisor + sub-agents 도입 시)
- **AgentCore Memory** — 보류 유지 (Phase 5 cross-agent context 패턴 본격화 시 재평가)
- **Change / Supervisor Runtime** — Phase 6a
- **AgentCore NL Policy** 부착 — Phase 5
- **Workflow Orchestrator** — Phase 6b (stretch)
- **EC mall 통합** — Phase 7

→ Phase 4 PR 영향 범위 = `agents/incident/{shared,runtime}/` 신규 + `infra/github-lambda/github_lambda.yaml` 신규 + `data/runbooks/payment-status-check.md` 신규 + Monitor `invoke_runtime.py` 가 sequential pattern 으로 변경 (또는 별 `invoke_sequential.py` 신규).

**Cognito stack / Gateway / Phase 3 IAM Role / Monitor Runtime entrypoint 본문 / Monitor `agentcore_runtime.py` 모두 미터치.**

---

## 0-4. Educational 가치

워크샵 청중이 Phase 4 PR 을 line-by-line 읽었을 때 학습하는 것:

1. **두 번째 Runtime 의 분량** — Phase 3 dba 패턴이 정착되면 새 Runtime 추가는 디렉토리 복제 + agent_name/role 만 변경. 정확히 얼마나 작은지 line count 로 시연. `@app.entrypoint` 패턴 대칭 — Monitor 와 Incident 가 같은 골격.
2. **Monitor `shared/` 가 사실상 공통 helper** — D1 의 결정 — 4개 helper (`auth_local.py`, `mcp_client.py`, `env_utils.py`, `modes.py`) 가 Incident 에서도 직접 import 됨. dba 의 단일 truth 원칙이 multi-agent 로 자연 확장.
3. **GitHub storage Lambda 패턴** — Phase 2 history-mock Lambda 와 동일 골격. SSM SecureString token + Phase 2 의 `<target>___<tool>` namespacing 이 그대로 통함.
4. **Sequential invoke 의 의도적 단순함** — `invoke_runtime.py` 가 Monitor 결과 받고 → Incident 에 alarm 별 invoke. CLI 가 caller 역할. Phase 6a 에서 이게 Supervisor + A2A 로 진화하는 차이를 line-level 비교 가능.
5. **A2A 를 Phase 6a 로 미루는 정당화** — A2A 의 진정한 가치는 caller (Supervisor) 가 등장할 때. server-side 만 활성화 = dead code. resource.md §1 의 "Phase 6a Supervisor 변환 시 핵심 참조" 약속을 그대로 따른다. workshop 청중에게 "premature 활성화 회피" 메시지.

---

## 0-5. 본 문서 구조 (§1 ~ §8)

| 섹션 | 내용 |
|---|---|
| §1 | 의사결정 로그 (D1 ~ D6) |
| §2 | 인벤토리 — AWS 자원 / 코드 파일 / env vars |
| §3 | Incident Agent 상세 (shared + runtime + build context) |
| §4 | GitHub storage 상세 (Lambda + Gateway Target + runbook) |
| §5 | Sequential CLI invoke 상세 (Monitor → Incident, A2A 미사용) |
| §6 | Acceptance 기준 P4-A1 ~ A5 + smoke test |
| §7 | Out of scope + Reference codebase 매핑 |
| §8 | Transition diff 예고 (Phase 4 → 5 → 6a, A2A 통합 활성화 시점) |

---

## 1. 의사결정 로그 (D1 ~ D6)

phase3.md §1 의 의사결정 로그 패턴 따라.

### 1-1. 결정 요약 표

| # | 항목 | 선택 | 대안 | 핵심 근거 |
|---|---|---|---|---|
| **D1** | Incident `shared/` 정책 | **`agent.py` + `prompts/` 만 — 4개 helper 는 monitor `shared/` 직접 import** | (b) 4개 helper 복제 / (c) `agents/_common/` 신규 | dba 의 "single source of truth" 원칙 multi-agent 확장. 중복 회피. (b) 는 prompt 변경 시 두 곳 sync 필요. (c) 는 Phase 3 monitor `shared/` 위치 변경 → 회귀 위험. **Phase 3 build context 평탄화 gotcha 영향**: Incident `deploy_runtime.py` 가 monitor/shared 도 copy (§3-6 참조) |
| **D2** | A2A 도입 시점 | **server + caller 둘 다 Phase 6a 로 통합 이월** | (a) Phase 4 server-side 양쪽 활성화 (Monitor reconfigure 동반) / (b) Phase 4 Incident 만 server-side (비대칭) | resource.md §1 (line 13-14) 가 RemoteA2aAgent 패턴을 "Phase 6a Supervisor 변환 시 핵심 참조" 로 명시. server-side 만 Phase 4 활성화 시 caller 없는 dead code → workshop 청중에게 "premature 회피" 메시지. plan_summary §134 "smoke test" 는 sequential CLI invoke 로 해석 (CLI 가 caller). Phase 3 회귀 0건 + Cognito stack 미터치 |
| **D3** | GitHub Lambda Tool 분량 | **Tool 1개 — `get_runbook(alarm_name)`** | (b) 2개 (+ incidents log read) / (c) 3개 (+ deployments log) | P4-A4 acceptance 의 핵심은 1개 read 검증. Phase 5+ 에서 incidents/deployments 추가 (Change Agent 가 deployments 읽는 시점). premature 회피 |
| **D4** | runbook 호스팅 | **동일 repo `data/runbooks/payment-status-check.md`** | (b) 별 repo `gonsoomoon-ml/aiops-multi-agent-runbooks` / (c) S3 fallback | 워크샵 독해성 — runbook 이 design doc 옆에 있어야 청중이 끝까지 추적 가능. 별 repo 는 GitHub token + cross-repo 권한 추가 부담. (c) S3 는 plan_summary §85 의 fallback — 정상 경로는 GitHub |
| **D5** | Cognito Client B | **Phase 6 로 미룸 — Phase 4 PR 미터치** | (a) Phase 4 placeholder 생성 | Caller (Supervisor) 가 Phase 6 까지 없음. placeholder 자원도 plan/teardown 부담. premature 회피. phase3.md §12-1 표 "Phase 4 또는 Phase 6" 옵션 활용 |
| **D6** | AgentCore Memory | **계속 보류 — Phase 5 재평가** | (a) Phase 4 도입 / (b) dormant flag | Phase 4 = A2A 활성화에 집중. cross-agent context 패턴 (Monitor 진단 → Incident 가 prior incident lookup) 이 본격 의미를 가지려면 Phase 5+ 의 incidents/ log 누적이 선행. plan_summary §171 "Phase 4~5 에서 결정" 약속 + Phase 5 로 이월 |

### 1-2. 결정 간 의존 관계

```
D1 (Incident shared/ 슬림)  — multi-agent 진입의 helper 정책

D2 (A2A → Phase 6a 이월)
 └─→ D5  (Cognito Client B 도 Phase 6a 통합 — caller 와 함께)

D3 (Tool 1개)
 ├─→ D4  (runbook 1개만 → 동일 repo OK)
 └─→ §6 P4-A4 (1개 read 검증)

D6 (Memory 보류)            — Phase 5 로 이월
```

→ D2 + D5 가 "Phase 6a 통합 이월" 묶음. resource.md §1 의 시점 약속 준수.

### 1-3. Phase 3 결정 항목과의 연속성

| Phase 3 결정 | Phase 4 에서의 처리 |
|---|---|
| D1 (단일 deploy 스크립트) | Incident Runtime 도 동일 패턴 — `agents/incident/runtime/deploy_runtime.py` |
| D2 (OAuth2CredentialProvider, 같은 스크립트) | 동일 — Incident Runtime 의 deploy 가 OAuth provider 추가 생성 |
| D3 (Runtime 이름 `aiops_demo_${DEMO_USER}_<agent>`) | 자연 확장 — `_incident` |
| D4 (no session caching) | 동일 — Incident 도 1-shot |
| **D5 (A2A 활성화 시점 = Phase 4)** | **★ Phase 6a 로 재이월** — resource.md §1 의 RemoteA2aAgent 차용 시점 ("Phase 6a Supervisor 변환 시 핵심 참조") 와 정렬. Phase 4 의 multi-agent 호출은 sequential CLI invoke 로 시연 |
| D6 (Memory 보류) | **★ 보류 유지 (Phase 5 로 이월)** |
| D7 (OTEL 포함) | 동일 — Incident 도 동일 OTEL env |
| D8 (C1 검증 = JSON schema diff) | Incident 는 별 verify 불필요 — Monitor 와 동일 패턴 |
| D9 (ECR push = `Runtime.launch()`) | 동일 |
| D10 (단일 폴더 `runtime/`) | Incident 도 동일 — 단, `infra/github-lambda/github_lambda.yaml` 만 별 폴더 (Lambda 가 `agents/` 외부) |

→ Phase 3 의 패턴이 정착됐기에 Phase 4 의 결정은 **6개 (Phase 3 의 60%)**. 새로운 axis 는 D1/D2 (multi-agent 시점에 처음 등장) 와 D3/D4 (GitHub storage 가 처음 등장) 만.

---

## 2. 인벤토리

### 2-1. AWS 자원 (신규)

| # | 자원 | 이름 | 분량 | 생성 도구 |
|---|---|---|---|---|
| 1 | Bedrock AgentCore Runtime | `aiops_demo_${DEMO_USER}_incident` | 1 | `agents/incident/runtime/deploy_runtime.py` |
| 2 | OAuth2CredentialProvider | `aiops_demo_${DEMO_USER}_incident_gateway_provider` | 1 | 위 deploy 스크립트 (boto3) |
| 3 | IAM Role (Incident Runtime) | `AmazonBedrockAgentCoreSDKRuntime-...-aiops_demo_${DEMO_USER}_incident-...` | 1 | toolkit 자동 생성 |
| 4 | IAM inline policy | `Phase4IncidentRuntimeExtras` | 1 | deploy 스크립트 |
| 5 | Lambda function | `aiops-demo-${DEMO_USER}-github-storage` | 1 | `infra/github-lambda/github_lambda.yaml` (CFN) |
| 6 | Lambda IAM Role | `aiops-demo-${DEMO_USER}-github-storage-role` | 1 | 동일 CFN |
| 7 | Gateway Target | `github-storage` | 1 | boto3 (Phase 2 패턴 재사용) |
| 8 | ECR repo | toolkit 자동 (Incident 용) | 1 | `Runtime.launch()` |
| 9 | CloudWatch Log Group | `/aws/bedrock-agentcore/runtimes/...` (Incident) | 1 | toolkit 자동 |

### 2-2. AWS 자원 (carry-over from Phase 3 — **변경 없음**)

| 자원 | 상태 |
|---|---|
| Cognito UserPool + Client C + Resource Server | 그대로 |
| Gateway (`aiops-demo-${DEMO_USER}-gateway-...`) | 그대로 |
| Gateway Target × 2 (history-mock, cloudwatch-wrapper) | 그대로 |
| Lambda × 2 (history-mock, cloudwatch-wrapper) | 그대로 |
| Monitor Runtime (`aiops_demo_${DEMO_USER}_monitor`) | **본문 미터치** — 단, deploy 스크립트는 한 번 더 실행해 `agent_executor.py` 추가 반영 (재배포 필요) |
| Monitor IAM Role + OAuth provider | 그대로 |

→ Phase 3 자원 8/9 무변경. Monitor Runtime 만 재배포 (코드 변경분 반영).

### 2-3. 코드 파일 (신규)

#### `agents/incident/`
| 파일 | 분량 | 역할 |
|---|---|---|
| `agents/incident/__init__.py` | 0 LoC | 패키지 마커 |
| `agents/incident/shared/__init__.py` | 0 LoC | 패키지 마커 |
| `agents/incident/shared/agent.py` | ~30 LoC | `create_agent(tools, system_prompt_filename)` (Strands) — Monitor `shared/agent.py` 와 동일 시그니처 |
| `agents/incident/shared/prompts/system_prompt.md` | ~50 줄 | Incident 진단/runbook lookup prompt |
| `agents/incident/runtime/agentcore_runtime.py` | ~70 LoC | Phase 3 monitor entrypoint 복제, agent_name + helper import 만 변경. `@app.entrypoint` 패턴 그대로 |
| `agents/incident/runtime/deploy_runtime.py` | ~250 LoC | Phase 3 monitor deploy 복제, agent_name + role 변경 |
| `agents/incident/runtime/invoke_runtime.py` | ~80 LoC | Phase 3 monitor invoke 복제 (Incident 단독 invoke — `--alarm <name>`) |
| `agents/incident/runtime/Dockerfile` | toolkit 자동 | — |
| `agents/incident/runtime/requirements.txt` | ~10줄 | Phase 3 monitor 와 동일 |
| `agents/incident/runtime/teardown.sh` | ~30 줄 | Phase 3 monitor teardown 복제 |
| `agents/incident/runtime/README.md` | ~20줄 | 사용법 |

#### `agents/monitor/runtime/`
| 파일 | 분량 | 역할 |
|---|---|---|
| `agents/monitor/runtime/invoke_runtime.py` | (변경) | sequential pattern — Monitor invoke 결과의 real_alarms 추출 후 Incident invoke 순차 호출. §5 참조 |

#### `infra/github-lambda/`
| 파일 | 분량 | 역할 |
|---|---|---|
| `infra/github-lambda/github_lambda.yaml` | ~80줄 | CFN — Lambda + IAM Role + SSM read 권한 |
| `infra/github-lambda/setup_github_target.py` | ~80 LoC | Gateway Target 등록 (Phase 2 패턴 재사용) |
| `infra/github-lambda/teardown.sh` | ~20 줄 | Target → Lambda CFN 삭제 |

#### `data/runbooks/`
| 파일 | 분량 | 역할 |
|---|---|---|
| `data/runbooks/payment-status-check.md` | ~30 줄 | EC2 status check 알람 대응 절차 (Incident 가 read) |
| `data/runbooks/README.md` | ~10줄 | runbook 디렉토리 구조 설명 |

### 2-4. 코드 파일 (변경)

| 파일 | 변경 분량 | 변경 내용 |
|---|---|---|
| `agents/monitor/runtime/invoke_runtime.py` | +50 LoC / -10 LoC | sequential mode 추가 — `--mode live --sequential` 또는 별 함수. Monitor 응답의 real_alarms 추출 + Incident invoke 순차 호출 + 통합 출력. §5 상세 |
| `agents/monitor/runtime/agentcore_runtime.py` | **변경 없음** | Phase 3 entrypoint 본문 carry-over |
| `agents/monitor/runtime/deploy_runtime.py` | **변경 없음** | Phase 3 그대로 |
| `pyproject.toml` | **변경 없음** | a2a-sdk 도 미사용 (Phase 6a 에서 사용 시작) |
| `docs/design/phase4.md` | (이 파일 자체) | — |

### 2-5. Runtime 환경 변수 (`Runtime.launch(env_vars={...})`)

#### Monitor Runtime (변경 없음 — Phase 3 그대로)
```
GATEWAY_URL                  carry-over (Phase 2)
OAUTH_PROVIDER_NAME          carry-over (Phase 3)
COGNITO_GATEWAY_SCOPE        carry-over (Phase 2)
MONITOR_MODEL_ID             carry-over (Phase 3)
DEMO_USER                    carry-over
AWS_REGION                   carry-over
```
→ Monitor 가 Incident 를 호출하지 않으므로 `INCIDENT_RUNTIME_ARN` env 추가 불필요. CLI (`invoke_runtime.py`) 가 caller 역할 — Incident ARN 은 `agents/incident/runtime/.env` 에서 read.

#### Incident Runtime (신규)
```
GATEWAY_URL                  Phase 2 carry-over
OAUTH_PROVIDER_NAME          aiops_demo_${DEMO_USER}_incident_gateway_provider
COGNITO_GATEWAY_SCOPE        Phase 2 carry-over
INCIDENT_MODEL_ID            (모델 분리 — Sonnet 4.6 등)
DEMO_USER                    carry-over
AWS_REGION                   carry-over
```

### 2-6. 의존성 변화 (`pyproject.toml`)

Phase 3 가 이미 `a2a-sdk>=0.3.0` 추가 → **변경 없음 예정** (구현 시 verify).

---

## 3. Incident Agent 상세 (D1)

### 3-1. `agents/incident/shared/agent.py`

Monitor 의 `agents/monitor/shared/agent.py` 와 **동일 시그니처**. 차이는 default prompt 만:

```python
"""Incident Agent — runbook lookup + 진단 추천."""
from pathlib import Path
from strands import Agent

PROMPTS_DIR = Path(__file__).parent / "prompts"


def create_agent(tools, system_prompt_filename: str = "system_prompt.md"):
    prompt = (PROMPTS_DIR / system_prompt_filename).read_text(encoding="utf-8")
    return Agent(
        system_prompt=prompt,
        tools=tools,
    )
```

→ Monitor 와 다른 것은 **`PROMPTS_DIR` 의 위치만** (자기 폴더 내 `prompts/`).

### 3-2. `agents/incident/shared/prompts/system_prompt.md`

Incident agent 의 system prompt — **runbook lookup → 진단 추천** 흐름. plan_summary §138 의 Incident agent 책임:

```markdown
# Incident Agent

당신은 IT 운영 인시던트 분석 전문가입니다. 다음 책임을 가집니다:

1. 입력: alarm 정보 + 현재 상태 (Monitor agent 가 분석한 결과)
2. 행동:
   a. 해당 alarm 에 대응하는 runbook 을 조회 (`get_runbook(alarm_name)`)
   b. runbook 에 있는 진단 절차 + 권장 조치를 적용
   c. 통합 진단 결과 + 권장 조치를 반환
3. 출력 형식: JSON
```json
{
  "alarm": "<alarm name>",
  "runbook_found": true|false,
  "diagnosis": "...",
  "recommended_actions": ["..."],
  "severity": "P1|P2|P3"
}
```

도구 사용 규칙:
- runbook 조회 실패 시 (`runbook_found: false`) — 일반적 진단 절차로 fallback
- runbook 의 권장 조치를 그대로 따르되, alarm 의 metric 값에 맞춰 조정
- 출력은 final 만 — 중간 사고 과정 금지
```

### 3-3. `agents/incident/runtime/agentcore_runtime.py`

Phase 3 의 `agents/monitor/runtime/agentcore_runtime.py` 를 복제. 변경점:

```python
# Monitor (Phase 3)
from agents.monitor.shared.agent import create_agent
from agents.monitor.shared.modes import MODE_CONFIG

# Incident (Phase 4) — D1 결정 적용 (helper 는 monitor shared/ 직접 import)
from agents.incident.shared.agent import create_agent
from agents.monitor.shared.auth_local import ...    # ★ 재사용
from agents.monitor.shared.mcp_client import ...    # ★ 재사용
from agents.monitor.shared.env_utils import ...     # ★ 재사용
```

→ **`agents.monitor.shared.X` import 가 incident 에서 등장**. 워크샵 청중이 보는 educational signal: "shared 가 monitor 전용 이름이 아니라 사실상 공통 helper 임".

### 3-4. Helper 재사용의 함의 (D1 결정 부연)

| helper | 변경 필요 여부 |
|---|---|
| `auth_local.py` | **그대로** — `OAUTH_PROVIDER_NAME` env 만 다르면 OK (Incident 의 .env 에 다른 값) |
| `mcp_client.py` | **그대로** — 환경 감지 (Runtime vs local) 가 동일 |
| `env_utils.py` | **그대로** — `require_env(key)` |
| `modes.py` | Incident 전용 mode 가 다를 수 있음 — Phase 4 에선 `INCIDENT_MODE_CONFIG` 추가 또는 Incident 가 자기 modes.py 생성 결정 (구현 시) |

→ `modes.py` 만 약한 cohesion (mode 정의가 agent 별로 달라질 수 있음). Phase 4 구현 시 (a) Incident 자기 modes.py / (b) monitor modes.py 에 `INCIDENT_MODE_CONFIG` 추가 둘 중 결정.

### 3-5. Incident 의 도구 분기

Incident 가 호출할 도구:
- `github-storage___get_runbook(alarm_name)` — runbook 조회 (필수)
- (옵션) `cloudwatch-wrapper___describe_alarms` — Monitor 가 이미 호출했을 수 있으므로 중복 회피. Phase 4 의 Incident 는 Monitor 의 결과를 그대로 받아 사용 → 호출 불필요

→ Phase 4 의 Incident agent 는 **github-storage Target 만** 사용. mcp_client 의 tool filter (`startswith("github-storage___")`) 로 격리.

### 3-6. Build context 처리 (Phase 3 gotcha §1 적용)

Phase 3 `agentcore_runtime_gotchas.md` §1 — Runtime build context 가 Docker root 밖으로 못 나가서 `agents/{agent}/runtime/` 아래에 `shared/` 를 copy 해야 함. Phase 4 에서 Incident Runtime 이 monitor `shared/` 의 helper 를 import 하기에, Incident `deploy_runtime.py` 는 **두 디렉토리 모두 copy**:

```python
# agents/incident/runtime/deploy_runtime.py 의 build context 준비 단계

PROJECT_ROOT = SCRIPT_DIR.parents[2]
MONITOR_SHARED = PROJECT_ROOT / "agents" / "monitor" / "shared"
INCIDENT_SHARED = PROJECT_ROOT / "agents" / "incident" / "shared"

def copy_shared_into_build_context() -> None:
    # 1. monitor helper (auth_local, mcp_client, env_utils, modes) → /app/shared/
    shutil.copytree(MONITOR_SHARED, SCRIPT_DIR / "shared", dirs_exist_ok=True)
    # 2. incident agent + prompts → /app/incident_shared/ (이름 충돌 회피)
    shutil.copytree(INCIDENT_SHARED, SCRIPT_DIR / "incident_shared", dirs_exist_ok=True)
```

**컨테이너 안 layout (`/app/`)**:
```
/app/
├── agentcore_runtime.py            # entrypoint
├── agent_executor.py               # A2A 어댑터
├── shared/                         # ← monitor helper (auth_local, mcp_client, env_utils, modes)
│   ├── auth_local.py
│   ├── mcp_client.py
│   ├── env_utils.py
│   └── modes.py
└── incident_shared/                # ← incident agent.py + prompts/
    ├── agent.py
    └── prompts/system_prompt.md
```

**Incident `agentcore_runtime.py` 의 import** (컨테이너 path 기준):
```python
# Local 환경 (개발):
from agents.monitor.shared.auth_local import get_local_gateway_token
from agents.incident.shared.agent import create_agent

# 컨테이너 환경:
from shared.auth_local import get_local_gateway_token        # monitor helper
from incident_shared.agent import create_agent               # incident truth
```

→ Phase 3 의 `(SCRIPT_DIR.parent / "shared").is_dir()` 조건부 sys.path 패턴 (Phase 3 `agentcore_runtime_gotchas.md` §2) 을 양 path 에 적용. local 개발 시 `agents/incident/runtime/agentcore_runtime.py` 직접 실행하면 `agents/{monitor,incident}/shared/` 둘 다 sys.path 에 추가하는 분기 필요.

**Educational signal**: Phase 3 의 build context flatten gotcha 가 multi-agent 환경에서 어떻게 확장되는가. "shared 가 monitor 의 것이라는 점이 컨테이너 path 에서 사라진다" — D1 의 educational #3 부연.

**대안 미채택 정당화**:
- Option B (`agents/_common/`) — Phase 3 monitor `shared/` 위치 변경 동반 → P3-A1~A6 회귀 검증 필요. Phase 4 PR 영향 격리 위반.
- Option C (helper 복제) — sync 부담. dba 단일 truth 위반.

→ Option A 선택의 trade-off: 컨테이너 path 의 `shared/` 가 monitor 소유라는 점이 layout 에서만 보임 (코드 import 에선 Phase 4 시점엔 자명, Phase 6a Change Agent 추가 시점에 재고 — §8 Phase 6 transition 에서 다시 평가).

---

## 4. GitHub storage 상세 (D3, D4)

### 4-1. `infra/github-lambda/github_lambda.yaml`

Phase 2 history-mock Lambda 패턴 재사용. CFN:

```yaml
AWSTemplateFormatVersion: "2010-09-09"
Description: Phase 4 — GitHub storage Lambda + IAM Role

Parameters:
  DemoUser:
    Type: String
  GithubTokenSsmPath:
    Type: String
    Default: /aiops-demo/github-token
  GithubRepo:
    Type: String
    Default: gonsoomoon-ml/aiops-multi-agent-demo
  GithubBranch:
    Type: String
    Default: main

Resources:
  GithubStorageLambdaRole:
    Type: AWS::IAM::Role
    Properties:
      RoleName: !Sub "aiops-demo-${DemoUser}-github-storage-role"
      AssumeRolePolicyDocument:
        Version: "2012-10-17"
        Statement:
          - Effect: Allow
            Principal:
              Service: lambda.amazonaws.com
            Action: sts:AssumeRole
      ManagedPolicyArns:
        - arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
      Policies:
        - PolicyName: SsmReadGithubToken
          PolicyDocument:
            Version: "2012-10-17"
            Statement:
              - Effect: Allow
                Action: ssm:GetParameter
                Resource: !Sub "arn:${AWS::Partition}:ssm:${AWS::Region}:${AWS::AccountId}:parameter${GithubTokenSsmPath}"

  GithubStorageLambda:
    Type: AWS::Lambda::Function
    Properties:
      FunctionName: !Sub "aiops-demo-${DemoUser}-github-storage"
      Runtime: python3.12
      Handler: handler.lambda_handler
      Role: !GetAtt GithubStorageLambdaRole.Arn
      Timeout: 15
      MemorySize: 256
      Environment:
        Variables:
          GITHUB_TOKEN_SSM_PATH: !Ref GithubTokenSsmPath
          GITHUB_REPO: !Ref GithubRepo
          GITHUB_BRANCH: !Ref GithubBranch
          DEMO_USER: !Ref DemoUser    # alarm_name → alarm_class 변환에 사용 (§4-2)
      Code:
        ZipFile: |
          # placeholder — `infra/github-lambda/lambda_src/handler.py` 가 실제 구현
          # CFN 배포 후 update-function-code 또는 별 deploy 단계로 코드 교체
          def lambda_handler(event, context):
              return {"error": "placeholder — code not deployed"}

  # Phase 2 GatewayIamRole 에 GithubStorageLambda invoke 권한 추가
  # — Phase 2 stack 미터치 (cross-stack reference via Role name string).
  # — Phase 4 stack teardown 시 Policy 만 삭제, Phase 2 Role 자체는 보존.
  GatewayInvokeGithubLambdaPolicy:
    Type: AWS::IAM::Policy
    Properties:
      PolicyName: !Sub "aiops-demo-${DemoUser}-phase4-gateway-invoke-github"
      Roles:
        - !Sub "aiops-demo-${DemoUser}-phase2-gateway-role"   # Phase 2 의 GatewayIamRole
      PolicyDocument:
        Version: "2012-10-17"
        Statement:
          - Effect: Allow
            Action: lambda:InvokeFunction
            Resource: !GetAtt GithubStorageLambda.Arn

Outputs:
  GithubStorageLambdaArn:
    Value: !GetAtt GithubStorageLambda.Arn
```

**Lambda Permission 패턴 (Phase 2 일관)**: Phase 2 의 `GatewayIamRole` 이 Gateway service 가 assume 하는 Role — 이 Role 에 invoke 권한이 있어야 Gateway 가 Lambda 호출 가능. Phase 4 는 Phase 2 stack 을 미터치한 채 동일 Role 에 추가 inline `AWS::IAM::Policy` 를 attach (cross-stack via Role name string). teardown 시 Phase 4 stack 만 삭제해도 Phase 2 Role 보존.

### 4-2. Lambda 코드 (`infra/github-lambda/lambda_src/handler.py`)

Phase 2 history-mock Lambda 와 동일 dispatch 패턴 (`context.client_context.custom["bedrockAgentCoreToolName"]` 로 분기). Tool 1개:

```python
"""GitHub storage Lambda — data/runbooks/ read."""
import os
import boto3
import urllib.request

def _tool_name(context) -> str:
    cc = getattr(context, "client_context", None)
    custom = getattr(cc, "custom", None) if cc else None
    return (custom or {}).get("bedrockAgentCoreToolName", "")

_token_cache = None

def _get_token() -> str:
    global _token_cache
    if _token_cache:
        return _token_cache
    ssm = boto3.client("ssm")
    path = os.environ["GITHUB_TOKEN_SSM_PATH"]
    resp = ssm.get_parameter(Name=path, WithDecryption=True)
    _token_cache = resp["Parameter"]["Value"]
    return _token_cache

def _fetch_github_file(repo: str, branch: str, path: str) -> str:
    url = f"https://api.github.com/repos/{repo}/contents/{path}?ref={branch}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {_get_token()}",
        "Accept": "application/vnd.github.raw",
    })
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.read().decode("utf-8")

def _alarm_class(alarm_name: str) -> str:
    """alarm_name → runbook key (user prefix 제거).

    Phase 0 의 alarm 이름 패턴: `payment-${DEMO_USER}-<class>` (예: payment-ubuntu-status-check).
    runbook 은 user-agnostic 이므로 file 명은 alarm class 만 — `data/runbooks/payment-<class>.md`.
    """
    demo_user = os.environ.get("DEMO_USER", "ubuntu")
    return alarm_name.replace(f"-{demo_user}-", "-")    # payment-ubuntu-X → payment-X


def lambda_handler(event, context):
    tool = _tool_name(context)
    params = event or {}
    repo = os.environ["GITHUB_REPO"]
    branch = os.environ["GITHUB_BRANCH"]

    if tool.endswith("get_runbook"):
        alarm_name = params.get("alarm_name", "")
        path = f"data/runbooks/{_alarm_class(alarm_name)}.md"   # ← user prefix 제거
        try:
            content = _fetch_github_file(repo, branch, path)
            return {"runbook_found": True, "path": path, "content": content}
        except urllib.error.HTTPError as e:
            return {"runbook_found": False, "path": path, "error": str(e)}

    return {"error": f"unknown tool: {tool!r}"}
```

**`_alarm_class` 의 역할**: 입력 `alarm_name` 은 full alarm 이름 (`payment-ubuntu-status-check` 처럼 user prefix 포함). runbook file 은 user-agnostic 이므로 path 는 `data/runbooks/payment-status-check.md` 로 변환. workshop 청중 (`${DEMO_USER}=alice`) 도 같은 runbook 사용 → 데이터 중복 회피.

→ **분량 ~50 LoC**. Phase 2 history-mock 의 `~80 LoC` 보다 단순.

### 4-3. Gateway Target 등록 — `infra/github-lambda/setup_github_target.py`

Phase 2 의 `infra/cognito-gateway/setup_gateway.py` 의 `step2_create_target` 부분을 그대로 차용. Tool schema:

```python
TOOL_SCHEMA = [
    {
        "name": "get_runbook",
        "description": (
            "Fetch the runbook markdown for a given CloudWatch alarm name. "
            "Returns runbook_found + content (markdown)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "alarm_name": {
                    "type": "string",
                    "description": (
                        "Full CloudWatch alarm name (e.g., 'payment-ubuntu-status-check'). "
                        "The Lambda strips the DEMO_USER prefix and fetches "
                        "data/runbooks/<alarm-class>.md from GitHub "
                        "(e.g., data/runbooks/payment-status-check.md)."
                    ),
                }
            },
            "required": ["alarm_name"],
        },
    },
]
```

→ Phase 2 gotcha 1 (schema strict subset) 적용 — `enum`/`default` 미사용.

### 4-4. `data/runbooks/payment-status-check.md`

```markdown
# Runbook — payment-ubuntu-status-check

## Alarm
- Name: `payment-ubuntu-status-check`
- Severity: P1
- Trigger: EC2 instance status check failure (1 evaluation period)

## 진단 절차
1. `aws ec2 describe-instance-status` 로 instance state + status 확인
2. 'system status check' vs 'instance status check' 구분
3. system check 실패 — AWS 인프라 이슈, AWS Support case
4. instance check 실패 — OS 이슈, reboot 시도

## 권장 조치
- 첫 5분: instance reboot
- 5분 후 미해결: AMI 로 신규 인스턴스 launch + Auto Scaling Group 으로 교체
- 30분 후 미해결: 동료 oncall 에게 escalate

## 참고
- 일반적 원인: kernel panic, EBS volume 문제, 네트워크 인터페이스
- 재발 방지: CloudWatch agent 의 detailed monitoring 활성화
```

→ **분량 ~25줄**. Incident agent 가 read 한 후 진단 시 참조.

### 4-5. SSM token 활용

Phase 2 가 이미 잡은 `.env` 의 `GITHUB_TOKEN_SSM_PATH=/aiops-demo/github-token` 그대로. 토큰 자체는 사용자가 SSM 에 한 번 저장 (dba `setup/store_github_token.sh` 패턴):

```bash
aws ssm put-parameter \
  --name /aiops-demo/github-token \
  --type SecureString \
  --value "<github-token-with-repo-read-scope>" \
  --overwrite
```

→ **Phase 4 deploy 의 prerequisite**. README 에 명시.

---

## 5. Sequential CLI invoke 상세 (D2)

A2A 프로토콜 활성화 (server + caller) 는 resource.md §1 (line 13-14) 의 "Phase 6a Supervisor 변환 시 핵심 참조" 약속에 따라 Phase 6a 로 통합 이월. Phase 4 의 multi-agent 호출은 CLI 가 caller 역할을 맡아 boto3 SIGV4 로 두 Runtime 을 순차 invoke — Phase 3 회귀 0건 + Cognito stack 미터치.

### 5-1. 호출 흐름

```
[CLI: invoke_runtime.py --mode live --sequential]
   │
   ├─→ ① boto3 invoke_agent_runtime(monitor_arn, payload={"mode":"live", "query":...})
   │        SIGV4 + runtimeUserId=DEMO_USER
   │        ↓
   │   Monitor Runtime — alarm 분류 → real_alarms 도출 + diagnosis JSON 반환
   │
   ├─→ ② JSON 파싱 → real_alarms 배열 추출
   │
   ├─→ ③ for each real_alarm in real_alarms:
   │        boto3 invoke_agent_runtime(incident_arn, payload={"alarm_name":...})
   │        SIGV4 + runtimeUserId=DEMO_USER
   │        ↓
   │   Incident Runtime — runbook lookup + 진단 권고 JSON 반환
   │
   └─→ ④ 통합 응답 출력
```

→ A2A 프로토콜 / AgentCard / RemoteA2aAgent / Cognito Client B / Bearer JWT — **0건**. Phase 3 의 SIGV4 invoke 패턴을 두 Runtime 에 그대로 재사용.

### 5-2. `agents/monitor/runtime/invoke_runtime.py` sequential 모드

Phase 3 invoke_runtime.py 에 sequential 분기 추가:

```python
"""invoke_runtime.py — Phase 4 sequential CLI invoke (Monitor → Incident)."""
import json, os, boto3
from pathlib import Path
from dotenv import load_dotenv

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[2]

# Phase 3 carry-over: Monitor 의 .env
load_dotenv(SCRIPT_DIR / ".env", override=True)

# Phase 4 신규: Incident 의 .env 에서 ARN read
INCIDENT_ENV = PROJECT_ROOT / "agents" / "incident" / "runtime" / ".env"
load_dotenv(INCIDENT_ENV, override=False)        # 기존 값 유지

MONITOR_ARN = os.environ["RUNTIME_ARN"]                              # Monitor 의 .env
INCIDENT_ARN = os.environ.get("INCIDENT_RUNTIME_ARN")                # Incident 의 .env (key 명 충돌 방지)
DEMO_USER = os.environ.get("DEMO_USER", "ubuntu")
REGION = os.environ.get("AWS_REGION", "us-west-2")

client = boto3.client("bedrock-agentcore", region_name=REGION)


def _invoke(arn: str, payload: dict) -> dict:
    """단일 Runtime SIGV4 invoke (Phase 3 패턴 그대로)."""
    resp = client.invoke_agent_runtime(
        agentRuntimeArn=arn,
        qualifier="DEFAULT",
        runtimeUserId=DEMO_USER,
        payload=json.dumps(payload).encode(),
    )
    body = b"".join(chunk for chunk in resp["response"]).decode()
    return _extract_json(body)                                       # SSE → final JSON


def _extract_json(stream_text: str) -> dict:
    """SSE stream 의 final JSON 추출 (Phase 3 verify_c1.py 의 fallback 재사용)."""
    # ... 생략 (verify_c1.py 와 동일 로직)


def run_sequential(query: str) -> dict:
    # ① Monitor invoke
    monitor_out = _invoke(MONITOR_ARN, {"mode": "live", "query": query})
    real_alarms = monitor_out.get("real_alarms", [])
    print(f"✅ Monitor: {len(real_alarms)} real alarm(s)")

    # ②~③ each real_alarm → Incident invoke
    incident_responses = []
    for alarm_name in real_alarms:
        incident_out = _invoke(INCIDENT_ARN, {"alarm_name": alarm_name})
        incident_responses.append(incident_out)
        print(f"✅ Incident({alarm_name}): runbook_found={incident_out.get('runbook_found')}")

    # ④ 통합 응답
    return {
        "monitor": monitor_out,
        "incident_responses": incident_responses,
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Phase 4 — sequential Monitor→Incident invoke")
    parser.add_argument("--mode", choices=["past", "live"], default="live")
    parser.add_argument("--sequential", action="store_true", help="Phase 4 multi-agent 흐름")
    parser.add_argument("--query", default=None)
    args = parser.parse_args()

    if args.sequential:
        result = run_sequential(args.query or DEFAULT_LIVE_QUERY)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        # Phase 3 단일 invoke 경로 (변경 없음)
        ...
```

**분량**: +50 LoC / -10 LoC (Phase 3 의 단일 invoke 함수 재사용).

### 5-3. 통합 응답 schema

```json
{
  "monitor": {
    "real_alarms": ["payment-ubuntu-status-check"],
    "diagnoses": [
      {"type": "real-alarm-cluster", "alarm": "payment-ubuntu-status-check", ...}
    ]
  },
  "incident_responses": [
    {
      "alarm": "payment-ubuntu-status-check",
      "runbook_found": true,
      "diagnosis": "EC2 status check 실패 — instance reboot 권장",
      "recommended_actions": ["instance reboot", "5분 후 미해결 시 AMI 재배포", "30분 후 escalate"],
      "severity": "P1"
    }
  ]
}
```

**P4-A3 검증** (§6-1): `incident_responses[].runbook_found = true` (1건 이상) + `incident_responses[].recommended_actions` 의 한 항목에 `reboot` 또는 `escalate` 포함.

### 5-4. Phase 6a 로 미루는 항목 (D2)

| 항목 | Phase 6a 도입 시점 |
|---|---|
| `A2AStarletteApplication` server (Monitor + Incident entrypoint 본문 교체) | Phase 6a |
| `AgentExecutor` + `AgentCard` JSON | Phase 6a |
| `RemoteA2aAgent` caller (Supervisor 가 sub-agent 호출) | Phase 6a |
| Cognito Client A (운영자 CLI → Supervisor) | Phase 6a |
| Cognito Client B (Supervisor → Sub-agent M2M) | Phase 6a |
| JWT inbound auth reconfigure (양 Runtime) | Phase 6a |

→ A2A 의 진정한 educational 가치는 caller (Supervisor) 등장 시 시각화. Phase 4 에서 server-side 만 활성화 = caller 없는 dead code.

### 5-5. Monitor IAM Role 변경 — 없음

Phase 3 의 Monitor IAM Role 에 `InvokeAgentRuntime` 권한 추가 불필요. Monitor 가 Incident 를 호출하지 않으므로. CLI (`invoke_runtime.py`) 는 사용자 IAM 자격증명 (또는 EC2 instance role) 로 두 Runtime 직접 호출 — 사용자 Role 에 `bedrock-agentcore:InvokeAgentRuntime` 권한 prerequisite (Phase 3 까지 이미 설정됨).

→ **Phase 3 IAM Role 미터치** ✓

### 5-6. resource.md §1 정렬 확인

```
resource.md line 13-14:
  Phase 4+ 차용 (예정):
    - host_adk_agent/agent.py:37-100 (RemoteA2aAgent 패턴)
      — Phase 6a Supervisor 변환 시 핵심 참조
```

Phase 4 design 은 RemoteA2aAgent (caller) 와 A2A server-side 를 모두 Phase 6a 로 통합 이월하여 resource.md 의 시점 약속을 직역. plan_summary §134 의 "CLI → Monitor → Incident 순차 A2A 호출" 표현은 **CLI 가 caller, A2A 프로토콜은 dormant** 로 해석 (sequential boto3 invoke).

---

## 6. Acceptance + smoke test

### 6-1. P4-A1 ~ A5

| # | 검증 항목 | 검증 방법 | 상태 (2026-05-08) |
|---|---|---|---|
| **P4-A1** | Phase 3 회귀 없음 | Phase 3 의 P3-A1 ~ A6 전체 재실행 (Monitor invoke 단독 + GitHub Lambda 무관 시나리오). Phase 3 자원 미터치 검증 | ✅ Phase 4 deploy 통과, Phase 2 stack / Gateway / Monitor Runtime 모두 보존 |
| **P4-A2** | Incident Runtime 단일 invoke 동작 | `uv run agents/incident/runtime/invoke_runtime.py --alarm payment-ubuntu-status-check` → JSON 응답 (`runbook_found: true`) | ✅ status-check (P1) + noisy-cpu (P2 fallback) 양쪽 정상 응답 |
| **P4-A3** | Sequential CLI invoke 통합 응답 | `uv run agents/monitor/runtime/invoke_runtime.py --mode live --sequential` → 응답 schema 가 §5-3 형식 (monitor + incident_responses[] 배열, real_alarms 1건 이상에 대해 incident 호출 흔적) | ⏸ **이월 — Step D 미구현, Phase 6a Supervisor + A2A 와 통합 검증** (D5 정렬) |
| **P4-A4** | GitHub Lambda runbook read 성공 | A3 의 응답 `incident_responses[].recommended_actions` 에 `reboot` 또는 `escalate` 1개 이상 포함 (runbook content 가 LLM 응답에 반영됨) | ✅ Step D 미구현 우회 — Incident 단독 invoke 응답으로 동등 검증. status-check 응답에 `reboot instance` + `escalate to oncall` 모두 포함, runbook 의 진단 절차 / 권장 조치 / Severity 일치 |
| **P4-A5** | Phase 4 teardown 후 Phase 3 자원 보존 | `infra/github-lambda/teardown.sh` + `agents/incident/runtime/teardown.sh` 후 — Monitor Runtime / Gateway / Cognito 그대로 | ⏸ pending — 다음 자원 정리 시점에 실측 (review fix A2 fallback discovery / B2 inline policy detach 검증 동반) |

### 6-1-1. 구현 commit 추적 (2026-05-08)

| commit | 범위 |
|---|---|
| `feab3d2` | Step B (`agents/incident/`) + Step C (`infra/github-lambda/`) 본체 + 구현 중 review fix 5건 (handler `_alarm_class` split-based, setup_github_target update 분기, tool description 정확화, teardown `list-gateways` fallback, teardown inline policy detach 검증) + system_prompt Korean diagnosis 강제 규칙 |
| `580aca5` | Step E partial — `data/runbooks/payment-status-check.md` (P4-A4 fetch 대상) |

→ Step D (sequential CLI) 미구현은 **D5 (A2A 활성화 Phase 6a 이월)** 결정과 일관. Phase 6a 에서 Supervisor + A2A 도입 시 sequential CLI 도 함께 진화 (§7-2 Reference codebase 매핑 참조).

### 6-2. smoke test 절차 (요약)

```bash
# 1. SSM token 1회 등록 (사전)
aws ssm put-parameter --name /aiops-demo/github-token --type SecureString \
  --value "$GITHUB_TOKEN" --overwrite

# 2. GitHub Lambda + Target 배포
aws cloudformation deploy --template infra/github-lambda/github_lambda.yaml \
  --stack-name aiops-demo-${DEMO_USER}-phase4-github \
  --parameter-overrides DemoUser=${DEMO_USER} \
  --capabilities CAPABILITY_NAMED_IAM
uv run infra/github-lambda/setup_github_target.py

# 3. Incident Runtime 배포
uv run agents/incident/runtime/deploy_runtime.py

# 4. Monitor Runtime 재배포 (agent_executor.py 추가분 반영)
uv run agents/monitor/runtime/deploy_runtime.py

# 5. P4-A2 — Incident 단독 invoke
uv run agents/incident/runtime/invoke_runtime.py --alarm payment-ubuntu-status-check

# 6. P4-A3 + A4 — sequential CLI invoke
uv run agents/monitor/runtime/invoke_runtime.py --mode live --sequential > /tmp/p4_a3.txt
jq '.incident_responses | length > 0' /tmp/p4_a3.txt              # P4-A3
grep -E "reboot|escalate" /tmp/p4_a3.txt && echo "✅ P4-A4 PASS"   # P4-A4

# 7. teardown 검증 (P4-A5)
bash agents/incident/runtime/teardown.sh
bash infra/github-lambda/teardown.sh
# Monitor Runtime / Gateway / Cognito 가 살아있는지 확인
aws bedrock-agentcore-control list-agent-runtimes | grep monitor
aws bedrock-agentcore-control list-gateways | grep aiops-demo
```

---

## 7. Out of scope + Reference codebase 매핑

### 7-1. Out of scope (Phase 4 가 안 하는 것)

| 항목 | 도입 시점 | 미루는 이유 |
|---|---|---|
| **A2A 프로토콜 (server-side)** — `A2AStarletteApplication`, `AgentExecutor`, AgentCard 노출 | **Phase 6a** | resource.md §1 의 RemoteA2aAgent 차용 시점 ("Phase 6a Supervisor 변환 시 핵심 참조") 와 일관 통합 (D2) |
| **A2A 프로토콜 (caller-side)** — `RemoteA2aAgent`, Bearer JWT | **Phase 6a** | Supervisor 가 sub-agents 호출하는 첫 시점. caller 없는 server-side 활성화 = dead code (D2) |
| Cognito Client A (운영자 CLI → Supervisor) | Phase 6a | Supervisor 와 함께 |
| Cognito Client B (Supervisor → Sub-agent M2M) | Phase 6a | A2A caller 와 함께 |
| AgentCore Memory + Strands hooks | Phase 5 | cross-agent context 본격 패턴화 시점 (D6) |
| Change Agent Runtime | Phase 6a | plan_summary §136 |
| Supervisor Runtime | Phase 6a | plan_summary §136 |
| Workflow Orchestrator | Phase 6b | 비교 측정 stretch |
| AgentCore NL Policy | Phase 5 | Runtime prerequisite 충족 후 다음 단계 |
| `incidents/` log 누적 (GitHub) | Phase 5 | Phase 4 = read only. 누적 write 는 Memory 결정 후 |
| `deployments/` log read | Phase 6a | Change Agent 가 첫 caller |
| EC mall 통합 | Phase 7 | 외부 의존 |
| S3 fallback | Phase 5+ | GitHub 만으로 충분한 시점까지 미룸 |

### 7-2. Reference codebase 매핑

| Phase 4 산출물 | 참조 코드 |
|---|---|
| `agents/incident/runtime/*` | `developer-briefing-agent/managed-agentcore/*` (dba, Phase 3 strict 패턴) |
| `agents/monitor/runtime/invoke_runtime.py` (sequential 모드) | Phase 3 단일 invoke 함수 + 자체 sequential loop (A2A 샘플 미차용 — Phase 6a 에서 RemoteA2aAgent 도입 시 차용) |
| `infra/github-lambda/github_lambda.yaml` | Phase 2 `infra/cognito-gateway/cognito.yaml` (Lambda 부분) + ec-customer-support `lab-03` Lambda 패턴 |
| `infra/github-lambda/lambda_src/handler.py` | Phase 2 `infra/cognito-gateway/lambda_src/history_mock/handler.py` (dispatch 패턴) |
| `infra/github-lambda/setup_github_target.py` | Phase 2 `infra/cognito-gateway/setup_gateway.py:step2_create_target` |
| `data/runbooks/*.md` | (신규 — 청중용 데이터) |
| Incident 의 prompts | A2A 샘플 `monitoring_strands_agent/prompt` (capability 기반 prompt 패턴) |
| GitHub token SSM 저장 | dba `setup/store_github_token.sh` |
| (미차용 — Phase 6a) `host_adk_agent/agent.py:37-100` (RemoteA2aAgent), `monitoring_strands_agent/main.py` (A2AStarletteApplication), `monitoring_strands_agent/agent_executor.py` (AgentExecutor) | resource.md §1 line 13-14 의 시점 약속 준수 |

---

## 8. Transition diff 예고 (Phase 4 → 5 → 6a)

Phase 5 는 **AgentCore NL Policy 부착** + **Memory 결정** + (선택) **incidents/ write**. Phase 6a 는 **Supervisor + A2A 통합 활성화 + Cognito Client A/B + Change Agent**.

### 8-1. Phase 5 핵심 변경 (예고)

| 변경 | Phase 5 분량 (예상) |
|---|---|
| **NL Policy 부착** (Monitor + Incident 양쪽) | 신규 policy YAML × 2, deploy 스크립트 1줄 추가 |
| **Memory 결정** (D6 본격 평가) | 도입 시 Strands hooks (StandupMemoryHooks 패턴) |
| **`incidents/` GitHub Lambda Tool 추가** (선택) | `add_incident_log` Tool — Incident 가 진단 결과 write back |
| **denial smoke test** | NL Policy readonly 가드레일 → write 호출 거부 시연 |

### 8-2. Phase 6a 핵심 변경 — A2A 통합 활성화 (D2)

| 변경 | Phase 6a 분량 (예상) |
|---|---|
| **`A2AStarletteApplication` server** — Monitor + Incident 양쪽 entrypoint 본문 교체 | A2A 샘플 `monitoring_strands_agent/main.py` + `agent_executor.py` 차용. 양 Runtime 재배포 |
| **`AgentCard` JSON 노출** + AgentExecutor | A2A 샘플 패턴 그대로 |
| **Supervisor Runtime 신규** — `agents/supervisor/runtime/` | RemoteA2aAgent caller 패턴 (`host_adk_agent/agent.py:37-100` 차용) |
| **Change Agent Runtime 신규** — `agents/change/runtime/` (Light, Haiku) | Phase 3 dba 패턴 |
| **Cognito Client A** (운영자 CLI → Supervisor) + **Client B** (Supervisor → sub-agents M2M) | Phase 2 `cognito.yaml` 확장 또는 별 stack |
| **JWT inbound auth reconfigure** (양 Runtime) | `Runtime.configure(authorizer_configuration=...)` |
| **Phase 4 sequential CLI 제거** | `invoke_runtime.py --sequential` deprecated → Supervisor 가 동등 역할 |

→ **Phase 4 의 sequential CLI 가 Phase 6a 에서 Supervisor + A2A 로 진화** — workshop 청중이 두 단계를 line-level 비교 가능 (educational 핵심).

### 8-3. Phase 4 결정 중 Phase 5 / Phase 6a 이월

| Phase 4 결정 | 이월 시점 | 처리 |
|---|---|---|
| **D2 — A2A 통합 이월** | **Phase 6a** | server + caller + Cognito Client A/B 동시 도입 |
| **D5 — Cognito Client B 보류** | **Phase 6a** | D2 와 함께 |
| D6 — Memory 보류 유지 | Phase 5 | 본격 결정 (보류/도입/dormant 중) |
| D3 — GitHub Tool 1개 | Phase 5 (선택) | 2개로 확장 (`get_runbook` + `add_incident_log`) |
| D1 — Incident shared/ 슬림 | Phase 6a 재고 | Change/Supervisor 추가 시 `agents/_common/` refactor 검토 |

### 8-4. Phase 4 IAM Role 의 Phase 5 / 6a 영향

| Phase 4 자원 | Phase 5 변경 | Phase 6a 변경 |
|---|---|---|
| Incident Role | NL Policy attach | JWT inbound auth + (선택) `bedrock-agentcore:GetResourceOauth2Token` |
| Monitor Role | NL Policy attach | JWT inbound auth |
| GitHub Lambda Role | `incidents/` write 권한 (D6) | 무변경 |
| Gateway Role | 무변경 | 무변경 |

### 8-5. Phase 4 → 5 transition 의 코드 diff (예상)

```diff
# Phase 5 PR (예상)

# 신규 파일
+ infra/phase5/policies/monitor_readonly.yaml
+ infra/phase5/policies/incident_readonly.yaml
+ infra/phase5/attach_policies.py
+ infra/phase5/teardown.sh
+ docs/design/phase5.md

# 변경 파일 (선택, D6 풀릴 시)
~ agents/incident/shared/prompts/system_prompt.md   # incidents/ write 추가 instruction
~ infra/github-lambda/lambda_src/handler.py                # add_incident_log tool dispatch
~ infra/github-lambda/setup_github_target.py               # tool schema 2개로 확장
~ agents/monitor/runtime/deploy_runtime.py          # Memory hooks (D6 풀릴 시)

# 삭제 파일
- (없음 — Phase 4 자원 전부 보존)
```

### 8-6. Phase 5 → 6a transition 의 코드 diff (예상)

```diff
# Phase 6a PR (예상)

# 신규 파일 — A2A + Supervisor + Change
+ agents/monitor/runtime/agent_executor.py            # A2AStarletteApplication 어댑터
+ agents/incident/runtime/agent_executor.py           # 동일 패턴
+ agents/supervisor/                                  # 신규 Runtime + RemoteA2aAgent caller
+ agents/change/                                       # Light Runtime, Haiku
+ infra/phase6a/cognito_client_ab.yaml                # Client A + B
+ docs/design/phase6a.md

# 변경 파일
~ agents/monitor/runtime/agentcore_runtime.py         # @app.entrypoint → A2AStarletteApplication
~ agents/incident/runtime/agentcore_runtime.py        # 동일
~ agents/monitor/runtime/deploy_runtime.py            # JWT inbound auth + Cognito Client B token 발급 권한
~ agents/incident/runtime/deploy_runtime.py           # 동일

# 삭제 파일
- agents/monitor/runtime/invoke_runtime.py 의 --sequential 모드  # Supervisor 가 동등 역할
```

---

## 9. 워크샵 시퀀스 (Phase 1 → 7)

| Phase | 학습 포인트 (누적) |
|---|---|
| 1 | Strands + 3가지 진단 유형 (offline) |
| 2 | + Gateway + MCP + Lambda Target + Cognito M2M |
| 3 | + AgentCore Runtime + OAuth2CredentialProvider + transition (helper 삭제) |
| **4** | **+ 2nd Runtime (Incident) + GitHub storage + sequential CLI + multi-agent shared/ 재사용 (A2A 미도입)** |
| 5 | + AgentCore NL Policy (readonly) + Memory 결정 + (선택) incidents/ write |
| 6a | + 3rd Runtime (Change Light) + Supervisor + **A2A 통합 활성화 (server+caller)** + Cognito Client A/B |
| 6b | + Workflow orchestrator (stretch) |
| 7 | + EC mall 통합 |

→ **Phase 4 의 의미**: "single Runtime → multi-Runtime 의 첫 진입 + GitHub storage 패턴 + sequential CLI". Phase 3 가 transition 단계였다면 Phase 4 는 multi-agent 의 minimum 시작 — A2A 통합 활성화는 Phase 6a 에서 Supervisor 와 함께 vs Phase 4 의 sequential CLI 와 line-level 비교 가능.
