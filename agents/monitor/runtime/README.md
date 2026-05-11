# Phase 3 — Monitor Agent on AgentCore Runtime

Phase 2 의 local Monitor agent (`agents/monitor/local/run.py`) 를 AgentCore Runtime 으로 동일 코드 옮긴다 (system goal C1). Cognito client_credentials 흐름은 OAuth2CredentialProvider 로 SDK 자동화 (D2) — `cognito_token.py` 통째 삭제.

설계 원본: [`docs/design/phase3.md`](../../../docs/design/phase3.md) (D1~D10 의사결정 + P3-A1~A6 acceptance).

## 사전 조건

- Phase 2 완료 — `infra/cognito-gateway/deploy.sh` 통과 + repo root `.env` 채워진 상태:
  - `COGNITO_USER_POOL_ID`, `COGNITO_DOMAIN`, `COGNITO_CLIENT_ID`, `COGNITO_CLIENT_SECRET`
  - `GATEWAY_URL` (Phase 2 `setup_gateway.py` 가 boto3 로 채움)
- `aws configure` (또는 `AWS_PROFILE`) — Runtime workload identity 발급에 필요
- Docker daemon 실행 중 (toolkit `Runtime.launch()` 가 `docker buildx` 호출)
- `uv sync` 으로 `bedrock_agentcore_starter_toolkit` 설치 완료

## 파일 구성

| 파일 | 역할 |
|---|---|
| `agentcore_runtime.py` | Runtime 컨테이너 entrypoint — `BedrockAgentCoreApp` + `@app.entrypoint` SSE yield |
| `Dockerfile` | uv-based Python 3.12 + OTEL distro + non-root user |
| `requirements.txt` | `strands-agents`, `strands-agents-tools`, `bedrock-agentcore>=1.4.0` (boto3 / aws-otel-distro 는 transitive 또는 Dockerfile 별도 install) |
| `.dockerignore` | build context exclude (`__pycache__/`, `.env`, `.bedrock_agentcore.yaml`) |
| `deploy_runtime.py` | 5단계 배포 (build context 복사 → toolkit configure → launch → IAM/OAuth → READY → .env) |
| `invoke_runtime.py` | `boto3 invoke_agent_runtime` 단일 호출 + SSE 파싱 + token usage 출력 |
| `teardown.sh` | Phase 3 자원 reverse 순서 삭제 + Phase 2 자원 보존 negative check |
| `.env` | (gitignored) Runtime metadata — `RUNTIME_ARN`, `RUNTIME_ID`, `OAUTH_PROVIDER_NAME` |
| `shared/` | (gitignored) build 시 `agents/monitor/shared/` 복사본 — Docker build context 안 |
| `_shared_debug/` | (gitignored) build 시 repo root `_shared_debug/` 복사본 — DEBUG=1 시 FlowHook / TTFT / dump_stream_event 활성 |

## 실행 순서

```bash
# 1. 배포 (~5-10분 첫 배포, 이후 ~40초 update)
uv run agents/monitor/runtime/deploy_runtime.py

# 2. live mode 호출 (P3-A4)
uv run agents/monitor/runtime/invoke_runtime.py --mode live

# 3. past mode 호출
uv run agents/monitor/runtime/invoke_runtime.py --mode past

# 4. C1 검증 (수동) — local vs Runtime 출력 비교
#   같은 mode 로 양쪽 실행 후 답변 텍스트 / token 분포 / cache 동작 동일 확인.
#   single source of truth: agents/monitor/{local,runtime}/ 모두
#   `from shared.agent import create_agent` — import 경로가 C1 의 structural 증명.
uv run agents/monitor/local/run.py --mode past
uv run agents/monitor/runtime/invoke_runtime.py --mode past

# 5. 자원 정리 (P3-A5)
bash agents/monitor/runtime/teardown.sh
```

## CloudWatch 로그

```bash
aws logs tail /aws/bedrock-agentcore/runtimes/aiops_demo_${DEMO_USER}_monitor \
    --follow --region "${AWS_REGION:-us-west-2}"
```

## Debug 모드 (선택)

`deploy_runtime.py` 가 호스트 `DEBUG` env 를 container `env_vars` 로 forward. 활성화 시 CloudWatch 로그에 FlowHook trace + TTFT + LLM call duration + cache 통계 출력:

```bash
DEBUG=1 uv run agents/monitor/runtime/deploy_runtime.py
```

자세한 trace 의미: [`docs/learn/debug_mode.md`](../../../docs/learn/debug_mode.md).

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
