"""Local 환경 전용 — Cognito Bearer JWT 획득 (2-mode dispatch).

본 디렉토리 helper 흐름 (`shared/__init__.py` map 참조):
  ``env_utils.require_env`` (env 검증) → **본 파일** (token 획득)
  → ``mcp_client.create_mcp_client`` (token 헤더 주입) → ``agent.create_agent`` (tools 주입).

AgentCore Gateway 는 ``customJWTAuthorizer`` 로 보호 — 호출자가 Cognito Bearer JWT 를
``Authorization: Bearer <token>`` 헤더로 함께 보내야 함::

    Strands Agent (local) ──MCP request──> Gateway (CUSTOM_JWT)
                           Authorization:           ↓
                           Bearer <token>           ① 서명 검증 (Cognito discoveryUrl)
                                    ↑               ② audience 검증 (allowedClients=[ClientId])
                                    │               ③ scope 검증 (allowedScopes=[<rs>/invoke])
                                    │
                                이 token 을
                                어디서 받나?

→ 이 ``<token>`` 을 받는 게 본 helper 의 역할.

## 2-mode dispatch (env 기반 자동 분기)

| 조건 | 경로 | 시점 |
|---|---|---|
| ``OAUTH_PROVIDER_NAME`` 설정 (Phase 3+ deploy 후) | AgentCore Identity 경유 — boto3 ``get_resource_oauth2_token`` | Phase 3 정상 경로 |
| ``OAUTH_PROVIDER_NAME`` 미설정 (Phase 2 standalone) | Cognito token endpoint 직접 호출 — urllib + Basic auth | Phase 2 단독 검증 |

Runtime 환경에서는 ``bedrock_agentcore`` SDK 가 outbound MCP 호출 시 OAuth2CredentialProvider
를 자동 inspect → token 자동 inject (phase3.md §5-1). Local 환경에는 이 자동 메커니즘이
없으므로, ``mcp_client.py`` 가 환경 감지 후 이 helper 로 token 명시 획득 → Authorization
header 수동 주입 (phase3.md §7-6 (a-2-i)).

reference: A2A monitoring_strands_agent/utils.py:27-48
(https://github.com/awslabs/amazon-bedrock-agentcore-samples — 02-use-cases/A2A-multi-agent-incident-response/)
— workload_token 인자 생략 (local IAM 자격증명으로 대체. boto3 API 가 optional
처리한다고 가정 — P3-A6 (c) 에서 검증).
"""
import base64
import json
import os
import urllib.parse
import urllib.request

import boto3

from _shared_debug import dprint, redact_jwt

from .env_utils import require_env


def _fetch_token_via_provider() -> str:
    """Phase 3+ 정상 경로 — AgentCore Identity 의 OAuth provider 호출.

    Provider 가 내부적으로 Cognito 호출 + token 캐싱. clientSecret 직접 다룸 0
    (provider 등록 시 한 번만 입력).
    """
    region = os.environ.get("AWS_REGION") or "us-east-1"
    provider_name = require_env("OAUTH_PROVIDER_NAME")

    dprint("Monitor → AgentCore Identity", f"via provider (provider={provider_name})", color="cyan")
    agentcore = boto3.client("bedrock-agentcore", region_name=region)
    response = agentcore.get_resource_oauth2_token(
        resourceCredentialProviderName=provider_name,
        scopes=[require_env("COGNITO_GATEWAY_SCOPE")],
        oauth2Flow="M2M",
    )
    token = response["accessToken"]
    dprint("AgentCore Identity → Monitor", f"JWT {redact_jwt(token)}", color="green")
    return token


def _fetch_token_direct() -> str:
    """Phase 2 standalone fallback — Cognito token endpoint 직접 호출.

    OAuth provider 등록 전 (Phase 3 미배포) 단독 검증용. clientId/clientSecret 직접
    HTTP Basic auth 로 전송 — Phase 3+ 의 provider 추상화와 동일 결과 (Cognito JWT).
    """
    region = os.environ.get("AWS_REGION") or "us-east-1"
    domain = require_env("COGNITO_DOMAIN")
    client_id = require_env("COGNITO_CLIENT_ID")
    client_secret = require_env("COGNITO_CLIENT_SECRET")
    scope = require_env("COGNITO_GATEWAY_SCOPE")

    url = f"https://{domain}.auth.{region}.amazoncognito.com/oauth2/token"
    dprint("Monitor → Cognito", f"direct token request (url={url}, client_id={client_id}, scope={scope})", color="cyan")
    body = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "scope": scope,
    }).encode("utf-8")
    creds = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {creds}",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        token = json.load(resp)["access_token"]
    dprint("Cognito → Monitor", f"JWT {redact_jwt(token)}", color="green")
    return token


def get_local_gateway_token() -> str:
    """Cognito Bearer JWT 획득 — env 기반 자동 dispatch (provider vs direct).

    OAUTH_PROVIDER_NAME env 가 설정되어 있으면 AgentCore Identity 경유 (Phase 3+ 정상
    경로). 없으면 Cognito 직접 호출 (Phase 2 standalone). 두 경로 모두 동일 JWT 반환
    → caller 무관.
    """
    if os.environ.get("OAUTH_PROVIDER_NAME"):
        return _fetch_token_via_provider()
    return _fetch_token_direct()
