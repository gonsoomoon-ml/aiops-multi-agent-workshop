# Incident A2A Runtime — Phase 6a

Phase 4 `agents/incident/` 의 **A2A protocol 변형** (preservation rule). 기능적으로는 동일 — alarm 1건 받아 runbook 조회 + 진단 JSON 반환. protocol 만 A2A.

## Phase 4 incident 와의 차이

| 측면 | Phase 4 `agents/incident/` | Phase 6a `agents/incident_a2a/` |
|---|---|---|
| Protocol | HTTP (`@app.entrypoint`, port 8080) | **A2A** (FastAPI + `A2AServer`, port 9000) |
| Inbound auth | SigV4 (IAM) | Cognito Bearer JWT (Client B) |
| Caller | sequential CLI | Supervisor `@tool call_incident` |
| `shared/` | `agents/incident/shared/` | full copy 신규 |
| Helper 의존 | `agents/monitor/shared/` | `agents/monitor_a2a/shared/` (격리) |

기능 동등 — 동일 `system_prompt.md`, 동일 도구 (github-storage runbook lookup), 동일 응답 schema (`{alarm, runbook_found, diagnosis, recommended_actions, severity}`).

## 사전 조건

- Phase 0/2/3/4 deploy 완료
- Phase 6a Step C 완료 (Cognito Client B)
- Phase 6a Step B2 (monitor_a2a 신규) 완료 — build context helper 출처
- repo `.env` 에 `COGNITO_CLIENT_B_ID`

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

A2A server 패턴 공통 — 자세한 내용 [`agents/change/runtime/README.md` § Workshop scope limitations](../../change/runtime/README.md#workshop-scope-limitations) 참고.

요약:
- Init-time token + MCPClient 1회 fetch → 1시간+ 가동 시 401.
- Strands `concurrent_invocation_mode=THROW` default → 동시 요청 시 두 번째 fail.

Workshop demo (단일 사용자 ≤ 1시간) 전제 OK. 운영 강건성은 후속 phase.
