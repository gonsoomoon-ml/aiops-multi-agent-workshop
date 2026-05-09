# Monitor A2A Runtime — Phase 6a

Phase 4 `agents/monitor/` 의 **A2A protocol 변형**. workshop 청중이 두 디렉토리를 비교하면 protocol 차이만 파악 가능 (preservation rule).

## Phase 4 monitor 와의 차이

| 측면 | Phase 4 `agents/monitor/` | Phase 6a `agents/monitor_a2a/` |
|---|---|---|
| Protocol | HTTP (`@app.entrypoint`, port 8080) | **A2A** (FastAPI + `A2AServer`, port 9000) |
| Mode | past + live (payload 의 `mode` 키) | live only (Supervisor flow 정합) |
| Inbound auth | SigV4 (IAM `bedrock-agentcore:InvokeAgentRuntime`) | Cognito Bearer JWT (`customJWTAuthorizer.allowedClients=[Client B]`) |
| Caller | sequential CLI / 운영자 직접 | Supervisor `@tool call_monitor` (Phase 6a Step B3) |
| AgentCard | 없음 | `.well-known/agent-card.json` 자동 도출 (Strands `agent.tool_registry`) |

`shared/` 는 Phase 4 monitor/shared/ 와 **완전 동일** (full copy) — `agent.py`, `mcp_client.py`, `auth_local.py`, `env_utils.py`, `modes.py`, `prompts/`, `tools/`. preservation rule 에 따라 Phase 4 모듈이 변경되어도 Phase 6a 코드 영향 없음.

## 사전 조건

1. **Phase 0/2/3/4 deploy 완료**
2. **Phase 6a Step C 선행** — Cognito Client B 발급 (`infra/phase6a/cognito_extras.yaml`)
3. **repo `.env`** — `COGNITO_CLIENT_B_ID` 추가

## 배포

```bash
uv run agents/monitor_a2a/runtime/deploy_runtime.py
```

## 호출

A2A — Cognito Client B Bearer JWT 필요. Supervisor `@tool call_monitor` 가 자동 호출. 단독 디버깅은 Phase 6a Step D 의 Operator CLI 또는 `a2a-sdk` client 코드로.

## teardown

```bash
bash agents/monitor_a2a/runtime/teardown.sh
```

Phase 4 monitor 자원 미터치 — 검증 step 포함.

## Workshop scope limitations

A2A server 패턴 공통 — 자세한 내용 [`agents/change/runtime/README.md` § Workshop scope limitations](../../change/runtime/README.md#workshop-scope-limitations) 참고.

요약:
- Init-time token + MCPClient 1회 fetch → 1시간+ 가동 시 401.
- Strands `concurrent_invocation_mode=THROW` default → 동시 요청 시 두 번째 fail.

Workshop demo (단일 사용자 ≤ 1시간) 전제 OK. 운영 강건성은 후속 phase.
