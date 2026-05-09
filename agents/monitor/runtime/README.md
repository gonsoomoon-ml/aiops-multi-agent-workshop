# Phase 3 — Monitor Agent on AgentCore Runtime

Phase 2 의 local Monitor agent (`agents/monitor/local/run.py`) 를 AgentCore Runtime 으로 동일 코드 옮긴다 (system goal C1). Cognito client_credentials 흐름은 OAuth2CredentialProvider 로 SDK 자동화 (D2) — `cognito_token.py` 통째 삭제.

설계 원본: [`docs/design/phase3.md`](../../../docs/design/phase3.md) (D1~D10 의사결정 + P3-A1~A6 acceptance).

## 사전 조건

- Phase 2 완료 — `infra/cognito-gateway/deploy.sh` 통과 + repo root `.env` 채워진 상태:
  - `COGNITO_USER_POOL_ID`, `COGNITO_DOMAIN`, `COGNITO_CLIENT_C_ID`, `COGNITO_CLIENT_C_SECRET`
  - `GATEWAY_URL` (Phase 2 `setup_gateway.py` 가 boto3 로 채움)
- `aws configure` (또는 `AWS_PROFILE`) — Runtime workload identity 발급에 필요
- Docker daemon 실행 중 (toolkit `Runtime.launch()` 가 `docker buildx` 호출)
- `uv sync` 으로 `bedrock_agentcore_starter_toolkit` 설치 완료

## 파일 구성

| 파일 | 역할 |
|---|---|
| `agentcore_runtime.py` | Runtime 컨테이너 entrypoint — `BedrockAgentCoreApp` + `@app.entrypoint` SSE yield |
| `Dockerfile` | uv-based Python 3.12 + OTEL distro + non-root user |
| `requirements.txt` | strands-agents, boto3, bedrock-agentcore (Runtime 컨테이너용) |
| `.dockerignore` | build context exclude (`__pycache__/`, `.env`, `.bedrock_agentcore.yaml`) |
| `deploy_runtime.py` | 5단계 배포 (build context 복사 → toolkit configure → launch → IAM/OAuth → READY → .env) |
| `invoke_runtime.py` | `boto3 invoke_agent_runtime` 단일 호출 + SSE 파싱 + token usage 출력 |
| `verify_c1.py` | P3-A3 자동 검증 — local vs runtime JSON schema diff (4 assertion × 3 runs = 12 check) |
| `teardown.sh` | Phase 3 자원 reverse 순서 삭제 + Phase 2 자원 보존 negative check |
| `.env` | (gitignored) Runtime metadata — `RUNTIME_ARN`, `RUNTIME_ID`, `OAUTH_PROVIDER_NAME` |
| `shared/` | (gitignored) build 시 `agents/monitor/shared/` 복사본 — Docker build context 안 |

## 실행 순서

```bash
# 1. 배포 (~5-10분 첫 배포, 이후 ~40초 update)
uv run agents/monitor/runtime/deploy_runtime.py

# 2. live mode 호출 (P3-A4)
uv run agents/monitor/runtime/invoke_runtime.py --mode live

# 3. past mode 호출
uv run agents/monitor/runtime/invoke_runtime.py --mode past

# 4. C1 자동 검증 (P3-A3 — local 3회 + runtime 3회 + schema diff)
uv run agents/monitor/runtime/verify_c1.py

# 5. 자원 정리 (P3-A5)
bash agents/monitor/runtime/teardown.sh
```

## CloudWatch 로그

```bash
aws logs tail /aws/bedrock-agentcore/runtimes/aiops_demo_${DEMO_USER}_monitor \
    --follow --region us-west-2
```

## 매커니즘 요약 (워크샵용)

```
[invoke_runtime.py]                                              [Runtime 컨테이너]
   │                                                                │
   ├─ boto3.invoke_agent_runtime(payload={mode, query})              │
   ▼                                                                ▼
   bedrock-agentcore endpoint  ────────────────────────────►  agentcore_runtime.py:monitor_agent()
                                                                    │
                                                          create_mcp_client() — Authorization 헤더 없음
                                                                    │
                                                                    ▼
                                                       Gateway 호출 (MCP streamable HTTP)
                                                                    │
                                          ⇡ AgentCore SDK outbound interceptor
                                          ⇡   bedrock-agentcore:GetResourceOauth2Token
                                          ⇡     resourceCredentialProviderName=OAUTH_PROVIDER_NAME
                                          ⇡     scopes=[gateway/invoke], oauth2Flow=M2M
                                          ⇡   ↓ access_token 자동 inject (Authorization: Bearer ...)
                                                                    │
                                                                    ▼
                                                           Gateway → Lambda (history-mock / cw-wrapper)
```

→ 코드는 `streamablehttp_client(url=GATEWAY_URL)` 호출만 — Cognito token 발급/캐시는 SDK 가 처리.
