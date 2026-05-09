# Change Agent Runtime — Phase 6a

24h 배포 이력 read + incident log append 를 담당하는 sub-agent. **A2A protocol Runtime** (Phase 4 의 HTTP Monitor/Incident 와 다름).

## 구조

```
agents/change/
├── shared/
│   ├── agent.py              # create_agent(tools, system_prompt_filename) — Phase 4 incident 동일
│   └── prompts/
│       └── system_prompt.md  # 한국어 — JSON 응답 schema + regression_likelihood 판단 정책
└── runtime/
    ├── agentcore_runtime.py  # A2AServer.to_fastapi_app() — port 9000 root
    ├── deploy_runtime.py     # toolkit configure(protocol="A2A", authorizer_configuration=...)
    ├── teardown.sh           # reverse 6단계 + Phase 4 자원 보존 검증
    ├── requirements.txt
    └── Dockerfile            # EXPOSE 9000
```

## 사전 조건

1. **Phase 0/2/3/4 deploy 완료** — Cognito UserPool + Gateway + 3 Lambda alive
2. **Phase 6a Step C 선행** — `infra/phase6a/`:
   - `cognito_extras.yaml` deploy (Client A + Client B + 신규 ResourceServer)
   - `deployments_lambda.yaml` deploy (deployments-storage Lambda + Gateway Target)
3. **Phase 6a Step B2 선행** — `agents/monitor_a2a/shared/` 디렉토리 존재 (build context Option A 의 helper 출처)
4. **repo `.env`** — 다음 키 존재:
   - `DEMO_USER`, `AWS_REGION`, `GATEWAY_URL`, `COGNITO_GATEWAY_SCOPE`
   - `COGNITO_USER_POOL_ID`, `COGNITO_DOMAIN`
   - `COGNITO_CLIENT_C_ID`, `COGNITO_CLIENT_C_SECRET` (Phase 2 — Gateway M2M)
   - `COGNITO_CLIENT_B_ID` (Phase 6a Step C — A2A inbound audience)

## 배포

```bash
uv run agents/change/runtime/deploy_runtime.py
```

5단계 흐름:
1. `monitor_a2a/shared` + `change/shared` → 빌드 컨텍스트 복사
2. `Runtime.configure(protocol="A2A", authorizer_configuration=customJWTAuthorizer)`
3. `Runtime.launch` — Docker 빌드 → ECR push → Runtime 생성 (~5-10분)
4. IAM `Phase6aChangeRuntimeExtras` + OAuth provider (Gateway 호출용)
5. READY 대기 + `runtime/.env` 저장 (RUNTIME_ARN + CHANGE_RUNTIME_ARN)

## 호출

A2A Runtime 은 `bedrock-agentcore:invoke_agent_runtime` (HTTP) 가 아닌 A2A JSON-RPC 호출. 본 Runtime 은 다음 두 경로로 호출됨:

1. **Supervisor `@tool call_change`** (Phase 6a Step B3) — `a2a.client.A2AClient.send_message()`. Cognito Client B Bearer JWT 자동 주입 (OAuth provider).
2. **Operator CLI 단독 호출** (Phase 6a Step D) — Cognito Client A user JWT 로 직접 Change A2A endpoint 호출 가능 (단독 디버깅용).

단순 IAM SigV4 호출 예시 (admin 디버깅 — 02-a2a-agent-sigv4 reference 참조):
```bash
# Bearer 가 아닌 SigV4 로 직접 invoke 하려면 customJWTAuthorizer 를 임시 제거하거나
# 별 Runtime 으로 deploy. 본 Runtime 은 Bearer-only.
```

## A2A Wire

- **endpoint**: `https://bedrock-agentcore.{region}.amazonaws.com/runtimes/{quote(arn)}/invocations/`
- **discovery**: `GET <endpoint>.well-known/agent-card.json` (skill 자동 도출 — `agent.tool_registry` 의 도구마다 1 skill)
- **invoke**: `POST <endpoint>` JSON-RPC `message/send`

## payload 예 (caller 가 보낼 message text)

```json
{"alarm_name": "payment-ubuntu-status-check", "severity": "P1", "diagnosis": "EC2 인스턴스 응답 없음 — instance reboot 권장"}
```

→ 응답: JSON (system_prompt 의 schema). `regression_likelihood`, `incident_appended`, `severity_adjusted` 등.

## teardown

```bash
bash agents/change/runtime/teardown.sh
```

Phase 0/2/3/4 자원 + Phase 6a 의 다른 Runtime (monitor_a2a, incident_a2a, supervisor) 보존. 자기 Runtime + IAM Role + ECR + OAuth provider + Log Group 만 삭제.

## reference

- `docs/design/phase6a.md` — §4 (Change Agent), §5 (A2A 활성화), §7 (deployments-storage Lambda)
- `docs/research/a2a_intro.md` — A2A 프로토콜 직관적 설명
- `agents/incident/` — Phase 4 동일 패턴 (HTTP) — Phase 6a Change 가 protocol 만 바뀐 변형으로 비교 가능
