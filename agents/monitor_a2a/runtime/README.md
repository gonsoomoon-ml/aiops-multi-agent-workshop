# Monitor A2A Runtime — Phase 5

Phase 4 `agents/monitor/` 의 **A2A protocol 변형**. workshop 청중이 두 디렉토리를 비교하면 protocol 차이만 파악 가능 (preservation rule).

## Phase 4 monitor 와의 차이

| 측면 | Phase 4 `agents/monitor/` | Phase 5 `agents/monitor_a2a/` |
|---|---|---|
| Protocol | HTTP (`@app.entrypoint`, port 8080) | **A2A** (FastAPI + `A2AServer`, port 9000) |
| Mode | past + live (payload 의 `mode` 키) | live only (Supervisor flow 정합) |
| Inbound auth | SigV4 (IAM `bedrock-agentcore:InvokeAgentRuntime`) | Cognito Bearer JWT (`customJWTAuthorizer.allowedClients=[Client]` — Phase 2 재사용, Option X) |
| Caller | sequential CLI / 운영자 직접 | Supervisor `@tool call_monitor_a2a` |
| AgentCard | 없음 | `.well-known/agent-card.json` 자동 도출 (Strands `agent.tool_registry`) |

`shared/` 는 **monitor_a2a 자체에 없음** — Phase 4 `agents/monitor/shared/` 를 직접 재사용 (Option G — 2026-05-09 review). monitor_a2a 디렉토리에는 `runtime/` 만 존재 — 청중에게 **"Phase 4 monitor 위에 A2A wrap 만 추가"** 메시지 명확. preservation rule 정합 (Phase 4 read-only — 수정 0, import + build context copy 만).

## 사전 조건

1. **Phase 0/2/3/4 deploy 완료** — Cognito Client 가 Phase 2 의 산출물로 `.env` 에 존재
2. (Phase 5 Option X — 새 Cognito 자원 추가 0)

## 배포

```bash
uv run agents/monitor_a2a/runtime/deploy_runtime.py
```

## 호출

A2A — Cognito Client Bearer JWT 필요 (Phase 2 재사용 — Option X). Supervisor `@tool call_monitor_a2a` 가 자동 호출. 단독 디버깅은 `agents/supervisor/runtime/invoke_runtime.py` 또는 `a2a-sdk` client 코드로.

## teardown

```bash
bash agents/monitor_a2a/runtime/teardown.sh
```

Phase 4 monitor 자원 미터치 — 검증 step 포함.

## Workshop scope limitations

본 Runtime 은 **워크샵 demo 전제** (≤ 1시간 세션, 단일 사용자 sequential 호출):

- **Init-time token + MCPClient 1회 fetch** — `agentcore_runtime.py` 가 module init 시점에 1회 OAuth token 획득 + MCPClient 연결. Cognito M2M token 유효기간 (~1h) 초과 시 모든 Gateway tool 호출이 401. 운영 적용 시 token-refresh callback 또는 Agent 주기적 재구성 필요.
- **단일 Agent 인스턴스** — Strands `Agent` default `concurrent_invocation_mode=THROW` — 동시 요청 두 번째에서 `ConcurrencyException` raise. Workshop 단일 사용자 OK, 다중 동시 사용자 시 두 번째 fail. 운영 시 `UNSAFE_REENTRANT` 또는 Agent pool 적용.

→ 본 패턴은 `02-use-cases/A2A-realestate-agentcore-multiagents` reference 와 동일. 워크샵 데모 재현이 목적, 운영 강건성은 후속 phase. `agents/incident_a2a/runtime/` 도 동일 limitations 적용.
