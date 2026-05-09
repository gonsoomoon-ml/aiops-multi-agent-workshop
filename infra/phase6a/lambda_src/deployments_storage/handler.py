"""deployments-storage Lambda — deployments/ read + incidents/ append.

Phase 4 github-storage Lambda 와 동일 dispatch 패턴 (`bedrockAgentCoreToolName`
context.client_context.custom). 차이점은 두 tool — 1 read + 1 write — 와 GitHub PAT
의 scope (write 위해 'repo' full 필요).

Tools (Phase 6a D5/D6):
  - ``get_deployments_log(date)`` — deployments/<date>.log 조회
  - ``append_incident(date, body)`` — incidents/<date>.log 에 body append (file 없으면 생성)

reference:
  - docs/design/phase6a.md §7 (Lambda handler 상세)
  - infra/phase4/lambda_src/github_storage/handler.py (dispatch 패턴 동일)
"""
import base64
import json
import os
import urllib.error
import urllib.request

import boto3

_token_cache: str | None = None


def _tool_name(context) -> str:
    cc = getattr(context, "client_context", None)
    custom = getattr(cc, "custom", None) if cc else None
    return (custom or {}).get("bedrockAgentCoreToolName", "")


def _get_token() -> str:
    """SSM SecureString 으로부터 GitHub PAT 조회 (lazy + cached). 'repo' full scope 필요."""
    global _token_cache
    if _token_cache:
        return _token_cache
    ssm = boto3.client("ssm")
    path = os.environ["GITHUB_TOKEN_SSM_PATH"]
    resp = ssm.get_parameter(Name=path, WithDecryption=True)
    _token_cache = resp["Parameter"]["Value"]
    return _token_cache


def _fetch_github_file(repo: str, branch: str, path: str) -> tuple[str, str | None]:
    """GitHub Contents API — 파일 raw content + sha 반환. 404 는 caller 가 catch.

    Returns:
        (content_str, sha) — sha 는 update 시 If-Match 용. 미존재 (404) 는 raise.
    """
    url = f"https://api.github.com/repos/{repo}/contents/{path}?ref={branch}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {_get_token()}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "aiops-demo-deployments-storage-lambda",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        meta = json.loads(resp.read().decode("utf-8"))
        # base64 decode (vnd.github.raw 와 다른 endpoint)
        content_b64 = meta.get("content", "").replace("\n", "")
        content = base64.b64decode(content_b64).decode("utf-8")
        return content, meta.get("sha")


def _put_github_file(
    repo: str, branch: str, path: str, content: str, message: str, sha: str | None
) -> dict:
    """GitHub Contents API PUT — 파일 create or update.

    sha 미지정 시 create (404 fallback). sha 지정 시 update — concurrent edit 회피.
    """
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    body = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        "branch": branch,
    }
    if sha:
        body["sha"] = sha
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        method="PUT",
        headers={
            "Authorization": f"Bearer {_get_token()}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "aiops-demo-deployments-storage-lambda",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def lambda_handler(event, context):
    tool = _tool_name(context)
    params = event or {}
    repo = os.environ["GITHUB_REPO"]
    branch = os.environ["GITHUB_BRANCH"]

    # === Tool 1: deployments/<date>.log read ============================
    if tool.endswith("get_deployments_log"):
        date = params.get("date", "")
        if not date:
            return {"deployments_found": False, "error": "date 누락 (YYYY-MM-DD)"}

        path = f"deployments/{date}.log"
        try:
            content, _sha = _fetch_github_file(repo, branch, path)
            return {"deployments_found": True, "path": path, "content": content}
        except urllib.error.HTTPError as e:
            return {
                "deployments_found": False,
                "path": path,
                "status": e.code,
                "error": str(e),
            }
        except urllib.error.URLError as e:
            return {"deployments_found": False, "path": path, "error": f"URL error: {e}"}

    # === Tool 2: incidents/<date>.log append ============================
    if tool.endswith("append_incident"):
        date = params.get("date", "")
        body = params.get("body", "")
        if not date or not body:
            return {"appended": False, "error": "date 또는 body 누락"}

        path = f"incidents/{date}.log"
        try:
            existing, sha = _fetch_github_file(repo, branch, path)
            new_content = existing.rstrip() + "\n\n" + body.strip() + "\n"
            commit_message = f"Phase 6a Change Agent — incident append {date}"
            result = _put_github_file(repo, branch, path, new_content, commit_message, sha)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                # 첫 incident — 파일 새로 생성
                new_content = body.strip() + "\n"
                commit_message = f"Phase 6a Change Agent — incident create {date}"
                try:
                    result = _put_github_file(repo, branch, path, new_content, commit_message, None)
                except urllib.error.HTTPError as e2:
                    return {"appended": False, "path": path, "status": e2.code, "error": str(e2)}
            else:
                return {"appended": False, "path": path, "status": e.code, "error": str(e)}

        return {
            "appended": True,
            "path": path,
            "commit_sha": result.get("commit", {}).get("sha"),
            "html_url": result.get("content", {}).get("html_url"),
        }

    return {"error": f"unknown tool: {tool!r}"}
