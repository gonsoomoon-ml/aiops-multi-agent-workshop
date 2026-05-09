"""Gateway MCP client factory — caller 가 token 명시.

Runtime / Local 둘 다 token 획득 경로만 다르고, 본 함수는 단순히 ``Authorization: Bearer``
header 로 주입한다. 환경 자동 감지 magic 을 두지 않아 흐름이 line-by-line 추적 가능.
"""
from datetime import timedelta

from mcp.client.streamable_http import streamablehttp_client
from strands.tools.mcp.mcp_client import MCPClient

from .env_utils import require_env


def create_mcp_client(gateway_token: str) -> MCPClient:
    gateway_url = require_env("GATEWAY_URL")

    def _transport():
        return streamablehttp_client(
            url=gateway_url,
            headers={"Authorization": f"Bearer {gateway_token}"},
            timeout=timedelta(seconds=120),
        )

    return MCPClient(_transport)
