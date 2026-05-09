"""Local 환경 전용 — boto3 로 OAuth provider 명시 호출.

Runtime 환경에서는 ``bedrock_agentcore`` SDK 가 outbound MCP 호출 시 OAuth2CredentialProvider
를 자동 inspect → token 자동 inject (phase3.md §5-1). Local 환경에는 이 자동 메커니즘이
없으므로, ``mcp_client.py`` 가 환경 감지 후 이 helper 로 token 명시 획득 → Authorization
header 수동 주입 (phase3.md §7-6 (a-2-i)).

reference: A2A monitoring_strands_agent/utils.py:27-48 — workload_token 인자 생략 (local
IAM 자격증명으로 대체. boto3 API 가 optional 처리한다고 가정 — P3-A6 (c) 에서 검증).
"""
import os

import boto3

from .env_utils import require_env


def get_local_gateway_token() -> str:
    """Local IAM 자격증명으로 OAuth provider 호출 → Cognito access_token 반환."""
    region = os.environ.get("AWS_REGION") or "us-west-2"
    provider_name = require_env("OAUTH_PROVIDER_NAME")

    agentcore = boto3.client("bedrock-agentcore", region_name=region)
    response = agentcore.get_resource_oauth2_token(
        resourceCredentialProviderName=provider_name,
        scopes=[require_env("COGNITO_GATEWAY_SCOPE")],
        oauth2Flow="M2M",
    )
    return response["accessToken"]
