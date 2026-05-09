"""github-storage Lambda — data/runbooks/ read from GitHub.

Phase 2 history-mock Lambda 와 동일 dispatch 패턴:
  - tool 식별자: ``context.client_context.custom["bedrockAgentCoreToolName"]``
    (event 가 아닌 Lambda invoke metadata, 형식 ``<target>___<tool>``)
  - input: ``event`` 자체가 inputSchema.properties 의 값 dict (wrapper 없음)

Tools (Phase 4 D3):
  - ``get_runbook(alarm_name)`` — data/runbooks/<alarm-class>.md 조회

reference:
  - docs/design/phase4.md §4-2
  - phase2 lambda/history_mock/handler.py (dispatch 패턴 동일)
"""
import os
import urllib.error
import urllib.request

import boto3

# 모듈 전역 token cache — Lambda warm container 재사용 시 SSM 호출 절약
_token_cache: str | None = None


def _tool_name(context) -> str:
    cc = getattr(context, "client_context", None)
    custom = getattr(cc, "custom", None) if cc else None
    return (custom or {}).get("bedrockAgentCoreToolName", "")


def _get_token() -> str:
    """SSM SecureString 으로부터 GitHub PAT 조회 (lazy + cached)."""
    global _token_cache
    if _token_cache:
        return _token_cache
    ssm = boto3.client("ssm")
    path = os.environ["GITHUB_TOKEN_SSM_PATH"]
    resp = ssm.get_parameter(Name=path, WithDecryption=True)
    _token_cache = resp["Parameter"]["Value"]
    return _token_cache


def _alarm_class(alarm_name: str) -> str:
    """alarm_name → runbook key (user token 제거).

    Phase 0 alarm 패턴: ``<prefix>-${DEMO_USER}-<class>`` (예: payment-ubuntu-status-check).
    **second segment 가 DEMO_USER 와 일치할 때만** 제거 — substring replace 우회로
    user token 이 class 안에 우연히 재등장해도 영향 없음 (예: DEMO_USER='db' +
    alarm 'payment-db-db-failover' → 'payment-db-failover'; second segment 불일치
    alarm 은 그대로 반환).

    Examples:
        >>> os.environ["DEMO_USER"] = "ubuntu"
        >>> _alarm_class("payment-ubuntu-status-check")
        'payment-status-check'
    """
    demo_user = os.environ.get("DEMO_USER", "ubuntu")
    parts = alarm_name.split("-", 2)
    if len(parts) >= 3 and parts[1] == demo_user:
        return f"{parts[0]}-{parts[2]}"
    return alarm_name


def _fetch_github_file(repo: str, branch: str, path: str) -> str:
    """GitHub Contents API 로 파일 raw content fetch (Bearer + raw Accept)."""
    url = f"https://api.github.com/repos/{repo}/contents/{path}?ref={branch}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {_get_token()}",
            "Accept": "application/vnd.github.raw",
            "User-Agent": "aiops-demo-github-storage-lambda",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.read().decode("utf-8")


def lambda_handler(event, context):
    tool = _tool_name(context)
    params = event or {}
    repo = os.environ["GITHUB_REPO"]
    branch = os.environ["GITHUB_BRANCH"]

    if tool.endswith("get_runbook"):
        alarm_name = params.get("alarm_name", "")
        if not alarm_name:
            return {"runbook_found": False, "error": "alarm_name 누락"}

        path = f"data/runbooks/{_alarm_class(alarm_name)}.md"
        try:
            content = _fetch_github_file(repo, branch, path)
            return {"runbook_found": True, "path": path, "content": content}
        except urllib.error.HTTPError as e:
            return {
                "runbook_found": False,
                "path": path,
                "status": e.code,
                "error": str(e),
            }
        except urllib.error.URLError as e:
            return {"runbook_found": False, "path": path, "error": f"URL error: {e}"}

    return {"error": f"unknown tool: {tool!r}"}
