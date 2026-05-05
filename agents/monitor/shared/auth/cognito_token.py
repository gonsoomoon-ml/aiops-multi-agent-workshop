"""Cognito client_credentials → access_token. PHASE 2 ONLY.

Phase 3 PR 에서 이 파일 통째 삭제 + ``mcp_client.py`` 의 token helper 호출도
함께 제거 (AgentCore Identity 자동 주입).
"""
import os
import time

import requests

from agents.monitor.shared.env_utils import require_env

_cache = {"token": None, "expires_at": 0.0}


def get_gateway_access_token() -> str:
    now = time.time()
    if _cache["token"] and now < _cache["expires_at"] - 60:
        return _cache["token"]

    domain = require_env("COGNITO_DOMAIN")
    region = os.environ.get("AWS_REGION", "us-west-2")
    client_id = require_env("COGNITO_CLIENT_C_ID")
    client_secret = require_env("COGNITO_CLIENT_C_SECRET")
    scope = require_env("COGNITO_GATEWAY_SCOPE")

    resp = requests.post(
        f"https://{domain}.auth.{region}.amazoncognito.com/oauth2/token",
        data={"grant_type": "client_credentials", "scope": scope},
        auth=(client_id, client_secret),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=10,
    )
    resp.raise_for_status()
    payload = resp.json()
    _cache["token"] = payload["access_token"]
    _cache["expires_at"] = now + int(payload.get("expires_in", 3600))
    return _cache["token"]
