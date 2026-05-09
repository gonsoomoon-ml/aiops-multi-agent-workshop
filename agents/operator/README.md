# Operator CLI — Phase 6a 정상 진입점

워크샵 청중 (운영자) 가 Supervisor Runtime 을 호출하는 **end-to-end 정상 경로**. Phase 4 의 sequential CLI / `invoke_runtime.py` 와 동일한 **SigV4 IAM 인증** (Phase 6a Option X — Cognito 신규 자원 0).

## 아키텍처

```
워크샵 청중 (Operator)
   │
   │ 1. AWS 자격증명 (aws configure)
   │    boto3.client("bedrock-agentcore").invoke_agent_runtime
   │    (자동 SigV4 서명)
   ▼
   Supervisor Runtime (HTTP, no customJWTAuthorizer)
     ├─ Strands Agent + system_prompt (한국어 routing 정책)
     └─ @tool × 3 → A2A hop (Cognito Client C M2M Bearer)
          ├─ monitor_a2a Runtime  (allowedClients=[Client C])
          ├─ incident_a2a Runtime (allowedClients=[Client C])
          └─ change Runtime       (allowedClients=[Client C])
   │
   │ 2. SSE 스트림 (text/event-stream)
   ▼
   stdout — Supervisor 의 통합 응답 JSON streaming
```

**핵심**: AgentCore `customJWTAuthorizer.allowedClients` 는 토큰의 **`aud` (= client_id) 만 검증, scope 미검증**. Phase 2 가 만든 Client C 의 토큰 (Gateway scope) 이 sub-agent A2A inbound 에도 통과. Phase 6a 가 추가하는 Cognito 자원 = 0.

## 사전 조건

1. **Phase 0/2/3/4 deploy 완료**
2. **Phase 6a Step C 완료** — `bash infra/phase6a/deploy.sh` 통과:
   - deployments-storage Lambda + Gateway Target 생성
   - `.env` 에 `DEPLOYMENTS_STORAGE_LAMBDA_ARN` 추가
3. **Phase 6a Step B Runtime 4개 deploy 완료**:
   ```bash
   uv run agents/change/runtime/deploy_runtime.py
   uv run agents/monitor_a2a/runtime/deploy_runtime.py
   uv run agents/incident_a2a/runtime/deploy_runtime.py
   uv run agents/supervisor/runtime/deploy_runtime.py    # ← sub-agent ARN cross-load
   ```
4. **AWS 자격증명** (사용자 IAM Role 에 `bedrock-agentcore:InvokeAgentRuntime` 권한 필요)

## 사용법

```bash
# 기본 — 현재 상황 진단
python agents/operator/cli.py --query "현재 상황 진단해줘"

# alarm 1건 명시
python agents/operator/cli.py --query "alarm payment-ubuntu-status-check 진단"

# 24h 배포 회귀 단독 질의
python agents/operator/cli.py --query "최근 24시간 배포 중 의심스러운 변경 있는지"
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

### `bedrock-agentcore:InvokeAgentRuntime` 권한 부족

```
AccessDeniedException: User: arn:aws:iam::xxx:user/yyy is not authorized to perform: bedrock-agentcore:InvokeAgentRuntime
```

→ 사용자 IAM 에 `bedrock-agentcore:InvokeAgentRuntime` 추가 필요. 워크샵 환경의 Admin 권한 가지면 자동 통과.

### Supervisor Runtime 500 (sub-agent 호출 실패)

→ 보통 sub-agent (monitor_a2a / incident_a2a / change) 의 customJWTAuthorizer.allowedClients 가 Client C 와 매칭 안 됨. 4 Runtime 모두 동일 Client C id 를 보고 있는지:
```bash
grep COGNITO_CLIENT_C_ID .env
for r in change monitor_a2a incident_a2a; do
  RID=$(aws bedrock-agentcore-control list-agent-runtimes --region us-west-2 \
    --query "agentRuntimes[?agentRuntimeName=='aiops_demo_${USER}_${r}'].agentRuntimeId" \
    --output text)
  aws bedrock-agentcore-control get-agent-runtime --region us-west-2 \
    --agent-runtime-id "$RID" \
    --query 'authorizerConfiguration.customJWTAuthorizer.allowedClients'
done
```

### Supervisor 의 OAuth provider Bearer 발급 실패

→ Supervisor Runtime 의 IAM Role 에 `bedrock-agentcore:GetResourceOauth2Token` + Cognito client secret read 권한 필요. `Phase6aSupervisorRuntimeExtras` inline policy 가 이미 부착됨 (deploy_runtime.py 4단계).

## reference

- `docs/design/phase6a.md` §8 (Operator CLI) — Option X refactor 후
- `docs/research/a2a_intro.md` §6 (시나리오 다이어그램)
- `agents/supervisor/runtime/agentcore_runtime.py` — Supervisor 측 entrypoint
- `agents/incident/runtime/invoke_runtime.py` — Phase 4 SigV4 invoke 패턴 (본 CLI 의 직접 reference)
