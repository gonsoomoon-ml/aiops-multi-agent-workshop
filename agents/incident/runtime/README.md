# Phase 4 — Incident Agent on AgentCore Runtime

Phase 3 의 Monitor Runtime 패턴 (`agents/monitor/runtime/`) 을 Incident Agent 에 carry-over. `@app.entrypoint` + OAuth2CredentialProvider 자동 inject + MCPClient → Gateway 호출. 차이점은 agent_name + tool target prefix (`github-storage___`) + payload schema (`{"alarm_name": "..."}`) 만.

설계 원본: [`docs/design/phase4.md`](../../../docs/design/phase4.md) (D1~D6 + P4-A1~A5).

## 사전 조건

- **Phase 2 완료** — `infra/phase2/deploy.sh` 통과 + repo root `.env` 채워진 상태.
- **Phase 3 완료** — Monitor Runtime READY + `aiops_demo_${DEMO_USER}_monitor` alive.
- **Phase 4 Step C 완료 (선결 의존)** — `infra/phase4/github_lambda.yaml` deploy + Gateway Target `github-storage` 등록 + SSM `/aiops-demo/github-token` 에 GitHub PAT 저장.
- AWS 자격 증명 + Docker daemon + `uv sync` 완료.

## 파일 구성

| 파일 | 역할 |
|---|---|
| `agentcore_runtime.py` | Incident entrypoint — `@app.entrypoint` SSE yield. payload `{alarm_name}`. tool filter `github-storage___` |
| `Dockerfile` | toolkit 자동 생성 (configure 첫 실행 시) |
| `requirements.txt` | strands-agents, bedrock-agentcore — Phase 3 monitor 와 동일 |
| `.dockerignore` | build context 제외 — Phase 3 패턴 |
| `deploy_runtime.py` | 5단계 — monitor/shared + incident/shared 둘 다 build context 로 copy (phase4.md §3-6 Option A) |
| `invoke_runtime.py` | 단일 Incident invoke — `--alarm <full alarm name>` |
| `teardown.sh` | Incident 자원 reverse 삭제 + Phase 3 Monitor + Phase 2 Cognito 보존 검증 |
| `.env` | (gitignored) Runtime metadata — `RUNTIME_ARN`, `RUNTIME_ID`, `OAUTH_PROVIDER_NAME`, `INCIDENT_RUNTIME_ARN` |
| `shared/` | (gitignored) build 시 monitor/shared 복사본 — auth_local, mcp_client, env_utils, modes |
| `incident_shared/` | (gitignored) build 시 incident/shared 복사본 — agent.py + prompts/ |

## 실행 순서

```bash
# 1. 배포 (~5-10분 첫 배포, 이후 ~40초)
uv run agents/incident/runtime/deploy_runtime.py

# 2. P4-A2 — Incident 단독 invoke (status-check alarm)
uv run agents/incident/runtime/invoke_runtime.py --alarm payment-${DEMO_USER}-status-check

# 3. P4-A2 — noisy-cpu alarm 도 검증
uv run agents/incident/runtime/invoke_runtime.py --alarm payment-${DEMO_USER}-noisy-cpu

# 4. (Step D 구현 후) P4-A3 + A4 — sequential CLI
uv run agents/monitor/runtime/invoke_runtime.py --mode live --sequential

# 5. 자원 정리 (Phase 3 Monitor + Phase 2 stack 보존)
bash agents/incident/runtime/teardown.sh
```

## CloudWatch 로그

```bash
aws logs tail /aws/bedrock-agentcore/runtimes/aiops_demo_${DEMO_USER}_incident \
    --follow --region us-west-2
```

## Build context 의 두 디렉토리 (phase4.md §3-6)

```
agents/incident/runtime/         ← Docker build context
├── agentcore_runtime.py
├── Dockerfile                    ← toolkit 자동
├── requirements.txt
├── shared/                       ← 빌드 시 monitor/shared 복사 (gitignored)
│   ├── auth_local.py
│   ├── mcp_client.py
│   ├── env_utils.py
│   └── modes.py
└── incident_shared/              ← 빌드 시 incident/shared 복사 (gitignored)
    ├── agent.py
    └── prompts/system_prompt.md
```

컨테이너 안에서 `from shared.mcp_client import ...` (monitor helper) + `from incident_shared.agent import create_agent` (incident truth). 로컬 dev 시는 `agents.monitor.shared.X` + `agents.incident.shared.agent` — `agentcore_runtime.py` 의 `try/except ModuleNotFoundError` 분기.

## A2A 미사용 (Phase 4 D2)

Phase 4 는 **sequential CLI 패턴** — Monitor `invoke_runtime.py --sequential` 가 두 Runtime 을 boto3 SIGV4 로 순차 호출. A2A 프로토콜 (server `A2AStarletteApplication` + caller `RemoteA2aAgent`) 은 Phase 6a 통합 활성화 (`docs/design/resource.md` §1 line 13-14 정렬). 자세한 정당화: `docs/design/phase4.md` §5.
