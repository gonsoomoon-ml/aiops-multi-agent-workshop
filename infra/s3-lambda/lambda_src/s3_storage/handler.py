"""s3-storage Lambda — data/runbooks/ read from S3.

GitHub backend (`infra/github-lambda/lambda_src/github_storage/handler.py`) 와
**byte-level 동형** dispatch + 동일 응답 shape. S3 bucket layout:
``data/runbooks/<class>.md`` (GitHub repo path 와 1:1 매핑).

Tools (Phase 4 D3 와 동일):
  - ``get_runbook(alarm_name)`` — data/runbooks/<alarm-class>.md 조회

차이점 (vs github):
  - boto3 S3 GetObject (vs GitHub Contents API)
  - bucket name = env ``S3_BUCKET`` (CFN output 으로 주입)
  - SSM token 불필요 (Lambda IAM Role 이 직접 GetObject 권한)
  - 응답 shape 동일 → Incident Agent 코드 무변경 가능 (TOOL_TARGET_PREFIX 만 분기)

reference:
  - infra/github-lambda/lambda_src/github_storage/handler.py (형제 backend)
  - docs/design/phase4.md §4 (storage 추상화)
"""
import os

import boto3
from botocore.exceptions import ClientError

# 모듈 전역 client cache — Lambda warm container 재사용 시 boto3 init 절감
_s3_client = None


def _tool_name(context) -> str:
    cc = getattr(context, "client_context", None)
    custom = getattr(cc, "custom", None) if cc else None
    return (custom or {}).get("bedrockAgentCoreToolName", "")


def _get_s3():
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client("s3")
    return _s3_client


def _alarm_class(alarm_name: str) -> str:
    """alarm_name → runbook key (user token 제거).

    github handler 의 _alarm_class 와 byte-level 동일. second segment 가 DEMO_USER 와
    일치할 때만 제거 — substring replace 우회.

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


def _fetch_s3_object(bucket: str, key: str) -> str:
    """S3 GetObject → utf-8 decoded body."""
    resp = _get_s3().get_object(Bucket=bucket, Key=key)
    return resp["Body"].read().decode("utf-8")


def lambda_handler(event, context):
    tool = _tool_name(context)
    params = event or {}
    bucket = os.environ["S3_BUCKET"]

    if tool.endswith("get_runbook"):
        alarm_name = params.get("alarm_name", "")
        if not alarm_name:
            return {"runbook_found": False, "error": "alarm_name 누락"}

        key = f"data/runbooks/{_alarm_class(alarm_name)}.md"
        try:
            content = _fetch_s3_object(bucket, key)
            return {"runbook_found": True, "path": key, "content": content}
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in ("NoSuchKey", "404"):
                return {"runbook_found": False, "path": key, "status": 404, "error": "not found"}
            return {"runbook_found": False, "path": key, "status": "error", "error": str(e)}

    return {"error": f"unknown tool: {tool!r}"}
