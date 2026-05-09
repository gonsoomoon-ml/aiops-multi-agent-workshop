# Supervisor Agent Runtime — Phase 6a

**Multi-agent orchestrator** — 운영자 (Operator CLI) 의 진입을 받아 sub-agent 3개 (monitor_a2a, incident_a2a, change) 를 routing/호출 후 통합 응답.

## 구조

```
agents/supervisor/
├── shared/
│   ├── agent.py              # create_supervisor_agent(tools, system_prompt_filename)
│   └── prompts/
│       └── system_prompt.md  # 한국어 — sub-agent 호출 정책 + JSON 응답 schema
└── runtime/
    ├── agentcore_runtime.py  # @app.entrypoint (HTTP) + @tool × 3 wrapping a2a.client
    ├── deploy_runtime.py     # toolkit configure(protocol="HTTP") + Cognito Client A authorizer
    ├── invoke_runtime.py     # admin SIGV4 디버깅 (정상 경로는 Operator CLI)
    ├── teardown.sh           # reverse 6단계 + sub-agent 보존 검증
    ├── requirements.txt
    └── Dockerfile            # EXPOSE 8080
```

## 핵심 패턴 — Strands `sub_agents` 미지원의 회피

Strands `Agent.__init__` 에 `sub_agents=` 파라미터가 **없음** (research 확인). 대신 sub-agent 를 *도구로 노출* — `@tool` 함수 3개가 a2a.client.A2AClient 호출을 wrap:

```python
@tool
async def call_monitor_a2a(query: str) -> str: ...

@tool
async def call_incident_a2a(query: str) -> str: ...

@tool
async def call_change(query: str) -> str: ...

agent = create_supervisor_agent(
    tools=[call_monitor_a2a, call_incident_a2a, call_change],
    system_prompt_filename="system_prompt.md",
)
```

LLM 이 system_prompt 의 routing 정책 따라 어떤 tool 을 부를지 결정. tool 안에서 A2A hop 발생.

## Auth

| 방향 | 검증 | OAuth provider | scope/audience |
|---|---|---|---|
| inbound (Operator → Supervisor) | AgentCore customJWTAuthorizer | (Cognito Client A user JWT) | allowedClients=[Client A] |
| outbound (Supervisor → 3 sub-agent) | 각 sub-agent 의 customJWTAuthorizer | `requires_access_token(provider_name=A2A_OAUTH_PROVIDER_NAME, auth_flow="M2M")` | Client B M2M 토큰의 `aud` ↔ sub-agent 의 `allowedClients=[Client B]` |

## 사전 조건

1. **Phase 0/2/3/4 deploy 완료**
2. **Phase 6a Step C 완료** — Cognito Client A + Client B 발급 (`infra/phase6a/cognito_extras.yaml`)
3. **Phase 6a Step B1 (change) + B2 (monitor_a2a + incident_a2a) Runtime deploy 완료** — 각 `runtime/.env` 에 ARN 작성됨
4. **repo `.env`** 에:
   - `COGNITO_USER_POOL_ID`, `COGNITO_DOMAIN`
   - `COGNITO_CLIENT_A_ID` (operator USER_PASSWORD_AUTH)
   - `COGNITO_CLIENT_B_ID`, `COGNITO_CLIENT_B_SECRET` (Supervisor M2M)

## 배포

```bash
uv run agents/supervisor/runtime/deploy_runtime.py
```

6단계:
1. supervisor/shared → 빌드 컨텍스트 복사
2. sub-agent ARN cross-load (3개의 runtime/.env)
3. `Runtime.configure(protocol="HTTP", customJWTAuthorizer[ClientA])`
4. `Runtime.launch` — Docker → ECR → Runtime
5. IAM `Phase6aSupervisorRuntimeExtras` + OAuth provider (Client B)
6. READY 대기 + `runtime/.env` 저장

## 호출

**정상 경로** — Operator CLI (Phase 6a Step D):
```bash
python agents/operator/cli.py --query "현재 상황 진단해줘"
```

**admin 디버깅** — SIGV4 (단, customJWTAuthorizer 활성화 상태에선 401):
```bash
uv run agents/supervisor/runtime/invoke_runtime.py --query "..."
```

## payload 스키마

```json
{"query": "<자연어 운영자 질의>"}
```

## 응답 (system_prompt 정의 schema)

```json
{
  "summary": "<한국어 1-3 문장>",
  "monitor": "<plain text 또는 null>",
  "incidents": [{"alarm": "...", "diagnosis": "...", "severity": "...", "regression_likelihood": "...", "incident_logged": true}],
  "next_steps": ["<영어 동사구>"]
}
```

## reference

- `docs/design/phase6a.md` — §1 (D8: @tool wrapping a2a.client), §3 (Supervisor 상세), §5 (A2A 활성화)
- `docs/research/a2a_intro.md` — A2A 직관 + Supervisor 시나리오 다이어그램
- `02-use-cases/A2A-realestate-agentcore-multiagents/realestate_coordinator/agent.py:325-361` — Strands supervisor + Cognito M2M reference
