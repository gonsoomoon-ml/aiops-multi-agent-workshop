# Operator CLI — Phase 6a 정상 진입점

워크샵 청중 (운영자) 가 Supervisor Runtime 을 호출하는 **end-to-end 정상 경로**. Phase 4 의 sequential CLI / `invoke_runtime.py` (boto3 SIGV4) 와 다르게, **Cognito Client A 의 user JWT** 로 인증 — Supervisor 의 `customJWTAuthorizer` 가 통과시킴.

## 아키텍처

```
워크샵 청중 (Operator)
   │
   │ 1. Cognito Client A — USER_PASSWORD_AUTH
   │    (boto3 cognito-idp.initiate_auth)
   ▼
   IdToken (JWT, 60분 만료)
   │
   │ 2. HTTPS POST + Authorization: Bearer
   │    https://bedrock-agentcore.{region}.amazonaws.com/runtimes/{arn}/invocations
   ▼
   Supervisor Runtime
     ├─ AgentCore customJWTAuthorizer (allowedClients=[Client A]) → 검증 통과
     ├─ Strands Agent + system_prompt (한국어 routing 정책)
     └─ @tool × 3 → A2A hop (Cognito Client B M2M Bearer)
          ├─ monitor_a2a Runtime
          ├─ incident_a2a Runtime
          └─ change Runtime
   │
   │ 3. SSE 스트림 (text/event-stream)
   ▼
   stdout — Supervisor 의 통합 응답 JSON streaming
```

## 사전 조건

1. **Phase 0/2/3/4 deploy 완료**
2. **Phase 6a Step C 완료** — `bash infra/phase6a/deploy.sh` 통과:
   - 결과로 `.env` 갱신: `COGNITO_USER_POOL_ID`, `COGNITO_CLIENT_A_ID`, `OPERATOR_USERNAME`, ...
   - 결과로 `.env.operator` 작성 (gitignored): `OPERATOR_PASSWORD`
3. **Phase 6a Step B Runtime 4개 deploy 완료** — change → monitor_a2a → incident_a2a → supervisor 순:
   ```bash
   uv run agents/change/runtime/deploy_runtime.py
   uv run agents/monitor_a2a/runtime/deploy_runtime.py
   uv run agents/incident_a2a/runtime/deploy_runtime.py
   uv run agents/supervisor/runtime/deploy_runtime.py    # ← 마지막 (sub-agent ARN cross-load)
   ```

## 사용법

```bash
# 기본 — 현재 상황 진단
python agents/operator/cli.py --query "현재 상황 진단해줘"

# alarm 1건 명시
python agents/operator/cli.py --query "alarm payment-ubuntu-status-check 진단"

# 24h 배포 회귀 단독 질의
python agents/operator/cli.py --query "최근 24시간 배포 중 의심스러운 변경 있는지"

# 명시 session id (멀티턴 시나리오 — 32+ chars 권장)
python agents/operator/cli.py --query "..." --session-id 550e8400-e29b-41d4-a716-446655440000
```

## 응답 형식

Supervisor `system_prompt.md` 의 schema:

```json
{
  "summary": "<한국어 1-3 문장 — 운영자가 바쁜 와중에 보는 핵심 의사결정 지원>",
  "monitor": "<call_monitor_a2a 응답 plain text 또는 null>",
  "incidents": [
    {
      "alarm": "payment-ubuntu-status-check",
      "diagnosis": "<한국어 1-2 문장>",
      "severity": "P1|P2|P3",
      "regression_likelihood": "high|medium|low",
      "incident_logged": true
    }
  ],
  "next_steps": ["<영어 동사구>", ...]
}
```

`summary` 는 한국어 (사람이 읽음), `next_steps` 는 영어 동사구 (자동화 후속 시스템이 파싱).

## 디버깅

### Cognito 인증 실패 (`NotAuthorizedException`)

```
❌ Cognito 인증 실패: NotAuthorizedException ...
```

→ `.env.operator` 의 비밀번호가 stale. `bash infra/phase6a/deploy.sh` 재실행하면 새 비밀번호 발급. 또는 직접:
```bash
aws cognito-idp admin-set-user-password \
  --user-pool-id "$COGNITO_USER_POOL_ID" \
  --username "$OPERATOR_USERNAME" \
  --password "<new password>" --permanent
```

### Runtime 401/403

→ Supervisor Runtime 의 `customJWTAuthorizer.allowedClients` 가 `COGNITO_CLIENT_A_ID` 와 매칭 안 됨. Phase 6a Step C 와 Phase 6a Supervisor deploy 사이에 Client A 가 재발급된 경우 → Supervisor 재배포 필요 (`uv run agents/supervisor/runtime/deploy_runtime.py`).

### Runtime 500 (sub-agent 호출 실패)

→ Supervisor 가 sub-agent 호출 시 401 반환. 보통 monitor_a2a / incident_a2a / change Runtime 의 Inbound Authorizer 가 Client B 와 매칭 안 됨. 4 Runtime 모두 동일 Client B id 를 보고 있는지 확인:
```bash
grep COGNITO_CLIENT_B_ID .env
for r in change monitor_a2a incident_a2a; do
  aws bedrock-agentcore-control get-agent-runtime \
    --region us-west-2 \
    --agent-runtime-id "$(aws bedrock-agentcore-control list-agent-runtimes \
      --region us-west-2 \
      --query "agentRuntimes[?agentRuntimeName=='aiops_demo_${USER}_${r}'].agentRuntimeId" \
      --output text)" \
    --query 'authorizerConfiguration.customJWTAuthorizer.allowedClients'
done
```

## reference

- `docs/design/phase6a.md` §8 (Operator CLI 상세)
- `docs/research/a2a_intro.md` §6 (시나리오 다이어그램)
- `agents/supervisor/runtime/agentcore_runtime.py` — Supervisor 측 entrypoint
