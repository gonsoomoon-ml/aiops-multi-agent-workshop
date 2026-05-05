"""Gateway MCP client factory.

Phase 2: token helper 의존 (PHASE 2 ONLY).
Phase 3: helper 제거 + AgentCore Identity 자동 주입으로 evolve.
"""
from datetime import timedelta

from mcp.client.streamable_http import streamablehttp_client
from strands.tools.mcp.mcp_client import MCPClient

from agents.monitor.shared.auth.cognito_token import (
    get_gateway_access_token,  # PHASE 2 ONLY
)
from agents.monitor.shared.env_utils import require_env


def create_mcp_client() -> MCPClient:
    gateway_url = require_env("GATEWAY_URL")

    def _transport():
        token = get_gateway_access_token()  # PHASE 2 ONLY
        return streamablehttp_client(
            url=gateway_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=timedelta(seconds=120),
        )

    return MCPClient(_transport)
