# AIOps Multi-Agent Demo

> AWS Bedrock AgentCore Runtime + Strands + A2A 프로토콜 기반 AIOps 멀티에이전트 인시던트 대응 워크샵.
> CloudWatch alarm 발화 → Monitor → Incident → Supervisor 협업 → 진단 리포트 생성 시나리오.

---

## 시스템 목표

| #  | 능력 | 검증 기준 |
|----|---|---|
| **C1** | Strands 로컬 → AgentCore Runtime 동일 코드 승격 | 로컬 == Runtime 응답 |
| **C2** | Gateway + MCP 로 도구 외부화 | Agent 코드에 도구 import 0건 |
| **C3** | A2A 프로토콜로 독립 Runtime 간 호출 | Supervisor → sub-agent AgentCard 호출 |
| **C4** *(stretched)* | AgentCore NL Policy 가드레일 | readonly enforcement 거부 시연 |

---

## 시나리오 — "결제 서비스 P1 장애 대응"

```
T-0     운영자가 stop_instance.sh 실행 → 결제 EC2 정지
T+30s   실 CloudWatch alarm fire (payment-${DEMO_USER}-status-check)
T+1m    Monitor 진단: live alarm noise vs real, 7일 history 패턴 분석
T+3m    Incident 진단: runbook 매칭 → P1 escalate, 티켓 초안
T+5m    Supervisor 종합 → 진단 리포트 자동 commit
```

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

| Phase | 핵심 산출물 | Narrative | 상태 |
|-------|---|---|---|
| **0** | EC2 시뮬레이터 + CloudWatch alarm 2종 (real + noise) + 카오스 스크립트 | [`docs/learn/phase0.md`](docs/learn/phase0.md) | ✅ |
| **1** | 로컬 Monitor Agent (Strands) + 3가지 진단 유형 (Rule 폐기 / Threshold 상향 / Time window 제외) | [`docs/learn/phase1.md`](docs/learn/phase1.md) | ✅ |
| **2** | AgentCore Gateway + MCP 도구 외부화 (CloudWatch + history mock Lambda) | [`docs/learn/phase2.md`](docs/learn/phase2.md) | ✅ |
| **3** | Monitor Agent → AgentCore Runtime 승격 | [`docs/learn/phase3.md`](docs/learn/phase3.md) | ✅ |
| **4** | Incident Runtime + storage Lambda (`STORAGE_BACKEND=s3` default / `github` 선택) + sequential CLI | [`docs/learn/phase4.md`](docs/learn/phase4.md) | ✅ |
| **5** | Supervisor + Monitor A2A + Incident A2A — A2A 활성화 (`serve_a2a` + LazyExecutor) | [`docs/learn/phase5.md`](docs/learn/phase5.md) | ✅ |
| **6** | EC mall 통합 — alarm 추가만으로 동일 시나리오 재현 (외부 의존) | — | 🚧 |

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
