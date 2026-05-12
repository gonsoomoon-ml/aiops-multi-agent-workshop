# AIOps Multi-Agent Workshop

> AWS Bedrock AgentCore Runtime + Strands + A2A 프로토콜 기반 AIOps 멀티에이전트 워크샵.
> CloudWatch alarm → 운영자 query → Supervisor (LLM orchestrator) → Monitor / Incident sub-agent (A2A) → 통합 진단 JSON.

---

## 시나리오 — "결제 서비스 P1 장애 대응"

```
T-0       운영자가 stop_instance.sh 실행 → 결제 EC2 정지
T+30s     CloudWatch alarm 발화 (payment-${DEMO_USER}-status-check, real)
T+1m      운영자: invoke_runtime.py --query "현재 상황 진단해줘"
            └─ Supervisor Runtime 진입 (HTTP, SigV4)
T+1m~2m   Supervisor LLM (orchestrator) — system_prompt 만 보고 routing:
            ├─ call_monitor_a2a   → 라이브 alarm 분류 (real 1 + noise 1, Tags.Classification)
            └─ call_incident_a2a  → real alarm 의 runbook 매칭 + P1 진단 + 권장 조치
T+2m      Supervisor 통합 JSON stdout:
            { summary, monitor, incidents, next_steps }
          (실측: 48초 / 7,045 tokens — phase5.md:228)

(stretched, Phase 6+) Change Agent → 통합 JSON → GitHub 진단 리포트 commit
```

---

## 여정 요약 — 6 phase 가 3 act 로 진화

| Act | Phase | 추가되는 layer | 핵심 학습 / 시스템 목표 |
|---|---|---|---|
| **I. 기반 + 로컬 baseline** | 0-1 | EC2 + 라이브 alarm 2종 (real + noise) + 첫 Strands Agent (mock) | Agent 결정성 + prompt 영향력 (AWS 의존 0 — 회귀 baseline) |
| **II. AWS managed 승격** | 2-3 | Gateway + MCP + Cognito JWT + Runtime container | **C2** (도구 외부화 — `@tool` → Lambda behind Gateway) / **C1** (local == Runtime 동일 코드) |
| **III. Multi-agent + A2A** | 4-5 | Incident Runtime + storage 추상화 (S3/GitHub) + Supervisor + A2A 프로토콜 | sequential CLI (Phase 4) → **C3** LLM-driven routing (Phase 5 — `serve_a2a` + LazyExecutor) |

---

## 시스템 목표

| #  | 능력 | 구현 Phase | 검증 기준 |
|----|---|---|---|
| **C1** | Strands 로컬 → AgentCore Runtime 동일 코드 승격 | Phase 3 | `agents/monitor/local/run.py --mode past` vs `agents/monitor/runtime/invoke_runtime.py --mode past` 가 동일 분류 (`from shared.agent import create_agent` 공유 — structural invariant) |
| **C2** | Gateway + MCP 로 도구 외부화 | Phase 2 | Agent 모듈에 boto3 / Lambda client import 0건 — 모든 도구는 MCP `<target>___<tool>` |
| **C3** | A2A 프로토콜로 sub-agent 분리 + LLM-driven routing | Phase 5 | Supervisor LLM 이 system_prompt 만 보고 `call_monitor_a2a` / `call_incident_a2a` 호출 시점 결정 (hardcoded 분기 0건) |
| **C4** *(stretched)* | AgentCore NL Policy 가드레일 | Phase 6+ | readonly 위반 query 차단 + 정책 메시지 반환 |

---

## 학습할 기술

**Strands SDK**
- **Strands Agent SDK** — `BedrockModel` + `@tool` + `MCPClient` + `stream_async`
- **Strands hooks** — `BeforeModelCallEvent` / `AfterModelCallEvent` / `BeforeToolCallEvent` 로 pre-call 시점 + LLM duration + TTFT 측정

**AWS Bedrock AgentCore**
- **AgentCore Runtime** *(Phase 3)* — 컨테이너 배포, 로컬 코드 그대로 서비스화
- **AgentCore Gateway** — MCP 도구 외부화 + Cognito JWT 3-layer 검증
- **AgentCore Identity** *(Phase 3)* — OAuth2 provider 자동 token inject

**프로토콜 + 오케스트레이션**
- **MCP 프로토콜** — streamable HTTP + `<target>___<tool>` namespacing
- **A2A 프로토콜** *(Phase 5)* — `serve_a2a` + `LazyExecutor` AWS canonical 패턴
- **`@tool` wrapping a2a.client** *(Phase 5)* — Strands `Agent` 가 `sub_agents` 미지원 → sub-agent 를 도구로 노출, LLM 이 routing 결정 (caller-as-LLM-tool)
- **Multi-agent orchestration** — Sequential CLI *(Phase 4)* → A2A 그래프 진화 *(Phase 5)*

**인증 + 인프라**
- **JWT M2M 인증** — Cognito ResourceServer + scope + `customJWTAuthorizer`
- **CFN + boto3 하이브리드** — 표준 자원은 IaC, AgentCore 자원은 SDK step-by-step
- **Cross-stack IAM** *(Phase 4)* — storage Lambda stack 이 cognito-gateway 의 GatewayIamRole 에 inline policy 부착 (stack 간 dependency 격리)
- **Storage backend 추상화** *(Phase 4)* — `STORAGE_BACKEND=s3/github` env 분기, Lambda 응답 shape byte-level 동형 → Agent 코드 변경 X 로 backend swap

**성능 + 관측**
- **Prompt caching** — `cache_tools="default"` + `SystemContentBlock` cachePoint (Layer 1+2) → single invocation 내 즉시 hit + 5분 warm TTL
- **Warm container reuse** *(Phase 3+)* — `runtimeSessionId` 반복으로 같은 microVM 재사용 → TTFT 단축 (prompt cache 와 분리된 caching layer)
- **Debug mode** — env `DEBUG=1` 로 phase 횡단 trace (auth / MCP / tool / TTFT / cache), `agent_name` parameter 로 multi-agent 라벨 격리

---

## 사전 요구사항

- **AWS 계정** (us-west-2 region)
- **Bedrock model access** — Claude Sonnet 4.6 / Haiku 4.5 활성화
- **AgentCore Runtime quota** — 5개 (Monitor + Incident + Monitor A2A + Incident A2A + Supervisor)
- **Python 3.12+** + [`uv`](https://github.com/astral-sh/uv)
- **Docker** — AgentCore Runtime 컨테이너 빌드
- **GitHub Personal Access Token** — `repo` scope (runbook + diagnosis read/write)

---

## Quickstart

### 1. 부트스트랩 (1회)

```bash
bash bootstrap.sh
```

`uv sync` + AWS 자격증명 사전 검증 + `.env` (AWS_REGION / DEMO_USER / STORAGE_BACKEND 결정 — **default `s3`, PAT 불필요**) + (`STORAGE_BACKEND=github` 선택 시에만 추가) GitHub PAT → SSM SecureString 5단계 검증.

### 2. Phase 별 학습 + deploy

각 phase 의 narrative 는 `docs/learn/phase{N}.md`. **순서대로** 읽고 해당 phase 의 deploy 명령 실행. 각 narrative 에 "무엇 (what it is)" + "어떻게 동작 (how it works)" + 검증 (P{N}-A1~A5) 포함.

| Phase | 이름 | 핵심 산출물 | Narrative | 예상 소요 | 상태 |
|-------|---|---|---|---|---|
| **0** | 기반 인프라 | EC2 시뮬레이터 + CloudWatch alarm 2종 (real + noise) + 카오스 스크립트 | [`docs/learn/phase0.md`](docs/learn/phase0.md) | 30 분 | ✅ |
| **1** | Strands Agent (local, mock) | 로컬 Monitor Agent (Strands) + 3가지 진단 유형 (Rule 폐기 / Threshold 상향 / Time window 제외) | [`docs/learn/phase1.md`](docs/learn/phase1.md) | 40 분 | ✅ |
| **2** | AgentCore Gateway + MCP + Debug mode | AgentCore Gateway + MCP 도구 외부화 (CloudWatch + history mock Lambda) + FlowHook 기반 Debug trace (DEBUG=1) | [`docs/learn/phase2.md`](docs/learn/phase2.md) | 60 분 | ✅ |
| **3** | AgentCore Runtime — Monitor | Monitor Agent → AgentCore Runtime 승격 | [`docs/learn/phase3.md`](docs/learn/phase3.md) | 60 분 | ✅ |
| **4** | AgentCore Runtime — Incident + Storage | Incident Runtime + storage Lambda (`STORAGE_BACKEND=s3` default / `github` 선택) + sequential CLI | [`docs/learn/phase4.md`](docs/learn/phase4.md) | 60 분 | ✅ |
| **5** | AgentCore A2A — Supervisor + 2 sub-agents | Supervisor + Monitor A2A + Incident A2A — A2A 활성화 (`serve_a2a` + LazyExecutor) | [`docs/learn/phase5.md`](docs/learn/phase5.md) | 90 분 | ✅ |
| **6** | EC Mall 통합 | EC mall 통합 — alarm 추가만으로 동일 시나리오 재현 (외부 의존) | — | — | 🚧 |

> ✅ = narrative 작성 완료 / 🚧 = 작성 대기 — 미완성 시 `docs/design/phase{N}.md` (의사결정 로그) + 코드 직접 참조.

**Stretched** (시간 여유 / 후속 자료):
- **Policy** — AgentCore NL Policy readonly enforcement + 거부 시연
- **Change Agent** — deployments-storage Lambda + Supervisor 3-agent topology 복원

---

## Teardown / Reset

전체 자원 일괄 삭제 (의존성 역순 8 step):

```bash
bash teardown_all.sh           # 확인 prompt 후 진행
bash teardown_all.sh --yes     # skip
```

step 별 분해 + idempotent 보장 + 검증 명령은 [`docs/learn/teardown.md`](docs/learn/teardown.md) 참조.

---

## 폴더 구조

```
aiops-multi-agent-workshop/
├── agents/                      # Strands Agent + AgentCore Runtime 코드
│   ├── monitor/                 #   Phase 1-3: 로컬 + Runtime
│   ├── incident/                #   Phase 4: Incident Runtime + shared
│   ├── monitor_a2a/             #   Phase 5: A2A 프로토콜 활성 (Option G — Phase 4 shared/ 직접 import)
│   ├── incident_a2a/            #   Phase 5: 동일 패턴
│   └── supervisor/              #   Phase 5: A2A caller (HTTP inbound, A2A outbound)
├── infra/                       # CFN 신규 자원이 있는 phase 만 디렉토리
│   ├── ec2-simulator/           #   Phase 0
│   ├── cognito-gateway/         #   Phase 2
│   └── github-lambda/           #   Phase 4
├── data/                        # GitHub repo 가 보유할 데이터 (이 repo 가 곧 GitHub data store)
│   ├── runbooks/                #   Incident Agent 가 read 하는 진단 절차 markdown
│   └── mock/phase1/             #   Phase 1 mock alarm history (history mock Lambda 가 vendor)
├── docs/
│   ├── learn/                   #   Phase 별 narrative (workshop 청중용) + teardown
│   ├── design/                  #   Phase 별 의사결정 로그 (D1~D10)
│   └── research/                #   A2A / AgentCore 학습 노트 + POC mini-projects
├── tests/                       # mock_data ground truth 검증 (pytest)
├── setup/                       # one-off setup helper (GitHub PAT → SSM)
├── bootstrap.sh                 # dev 환경 + .env + SSM token 일괄
└── teardown_all.sh              # 8 step 자원 일괄 삭제
```

---

## Reference

| 자료 | 용도 |
|---|---|
| [`docs/design/plan_summary.md`](docs/design/plan_summary.md) | 전체 시스템 목표 + 아키텍처 + 컴포넌트 인벤토리 + 의존·전제 |
| `docs/design/phase{2,3,4,6a}.md` | Phase 별 의사결정 로그 (D1~D10) — 설계 시점 trade-off 기록 |
| [`docs/research/a2a_intro.md`](docs/research/a2a_intro.md) | A2A 프로토콜 직관적 학습 |
| [`docs/research/agentcore_new_feature.md`](docs/research/agentcore_new_feature.md) | AgentCore 신규 기능 노트 |
| [`docs/research/poc/`](docs/research/poc/) | 별도 mini-project — agent_registry / bedrock_mantle_iam / managed_harness |
| [`CLAUDE.md`](CLAUDE.md) | 본 프로젝트의 코드 작성 / 리뷰 / 문서화 컨벤션 |

---

## 라이선스

[LICENSE](LICENSE)
