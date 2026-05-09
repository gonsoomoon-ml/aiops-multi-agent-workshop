# Incident A2A Runtime — Phase 6a

Phase 4 `agents/incident/` 의 **A2A protocol 변형** (preservation rule). 기능적으로는 동일 — alarm 1건 받아 runbook 조회 + 진단 JSON 반환. protocol 만 A2A.

## Phase 4 incident 와의 차이

| 측면 | Phase 4 `agents/incident/` | Phase 6a `agents/incident_a2a/` |
|---|---|---|
| Protocol | HTTP (`@app.entrypoint`, port 8080) | **A2A** (FastAPI + `A2AServer`, port 9000) |
| Inbound auth | SigV4 (IAM) | Cognito Bearer JWT (Client C — Phase 2 재사용, Option X) |
| Caller | sequential CLI | Supervisor `@tool call_incident_a2a` |
| `shared/` | `agents/incident/shared/` | full copy 신규 |
| Helper 의존 | `agents/monitor/shared/` | `agents/monitor_a2a/shared/` (격리) |

기능 동등 — 동일 `system_prompt.md`, 동일 도구 (github-storage runbook lookup), 동일 응답 schema (`{alarm, runbook_found, diagnosis, recommended_actions, severity}`).

## 사전 조건

- Phase 0/2/3/4 deploy 완료 (Cognito Client C 가 `.env` 에 존재)
- `agents/monitor_a2a/shared/` 디렉토리 alive (build context helper 출처 — Option A 패턴)
- (Phase 6a Option X — 새 Cognito 자원 추가 0)

## 배포

```bash
uv run agents/incident_a2a/runtime/deploy_runtime.py
```

## teardown

```bash
bash agents/incident_a2a/runtime/teardown.sh
```

Phase 4 incident + 다른 Phase 6a Runtime 보존.

## Workshop scope limitations

본 Runtime 은 **워크샵 demo 전제** (≤ 1시간 세션, 단일 사용자 sequential 호출):

- **Init-time token + MCPClient 1회 fetch** — `agentcore_runtime.py` 가 module init 시점에 1회 OAuth token 획득 + MCPClient 연결. Cognito M2M token 유효기간 (~1h) 초과 시 모든 Gateway tool 호출이 401. 운영 적용 시 token-refresh callback 또는 Agent 주기적 재구성 필요.
- **단일 Agent 인스턴스** — Strands `Agent` default `concurrent_invocation_mode=THROW` — 동시 요청 두 번째에서 `ConcurrencyException` raise. Workshop 단일 사용자 OK, 다중 동시 사용자 시 두 번째 fail. 운영 시 `UNSAFE_REENTRANT` 또는 Agent pool 적용.

→ 본 패턴은 `02-use-cases/A2A-realestate-agentcore-multiagents` reference 와 동일. 워크샵 데모 재현이 목적, 운영 강건성은 후속 phase. `agents/monitor_a2a/runtime/` 도 동일 limitations 적용.
