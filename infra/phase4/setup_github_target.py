"""Phase 4 — Gateway Target 'github-storage' 추가 (boto3, idempotent).

Phase 2 setup_gateway.py 의 create_target 패턴 정확 차용. Phase 2 Gateway 에 새 Target
하나만 추가 — Gateway / Cognito / 다른 Target 미터치.

deploy.sh 가 CFN outputs 를 환경변수로 주입한 뒤 호출:
    GATEWAY_ID                       (Phase 2 .env carry-over)
    GITHUB_STORAGE_LAMBDA_ARN        (Phase 4 CFN output)

reference:
    - docs/design/phase4.md §4-3 (Tool schema)
    - infra/phase2/setup_gateway.py:create_target (보존 패턴)
"""
import os
import sys

import boto3

REGION = os.environ.get("AWS_REGION", "us-west-2")
TARGET_NAME = "github-storage"

GITHUB_TOOL_SCHEMA = [
    {
        "name": "get_runbook",
        "description": (
            "Fetch the runbook markdown for a given CloudWatch alarm. "
            "Input: full alarm name (e.g., 'payment-ubuntu-status-check'). "
            "The Lambda removes the DEMO_USER token (the segment between dashes) "
            "and fetches runbooks/<alarm-class>.md from GitHub "
            "(e.g., runbooks/payment-status-check.md). "
            "Returns: runbook_found (bool), path, content (markdown) — or "
            "runbook_found:false + status/error on miss."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["alarm_name"],
            "properties": {
                "alarm_name": {
                    "type": "string",
                    "description": "Full alarm name with embedded DEMO_USER token (e.g., 'payment-ubuntu-status-check')",
                },
            },
        },
    },
]


def _client():
    return boto3.client("bedrock-agentcore-control", region_name=REGION)


def create_or_update_target(gw, gateway_id: str, lambda_arn: str):
    """Target 이 없으면 create, 있으면 update — lambdaArn + schema 강제 동기화.

    이전 reuse-only 패턴은 stack delete→recreate 시 stale lambdaArn 잔존으로 silent
    fail. update 분기로 재배포 시에도 lambdaArn + GITHUB_TOOL_SCHEMA 가 항상 최신.
    """
    print(f"\n=== Phase 4 — GatewayTarget '{TARGET_NAME}' 추가/갱신 ===")

    target_config = {
        "mcp": {
            "lambda": {
                "lambdaArn": lambda_arn,
                "toolSchema": {"inlinePayload": GITHUB_TOOL_SCHEMA},
            }
        }
    }
    cred_configs = [{"credentialProviderType": "GATEWAY_IAM_ROLE"}]

    existing = next(
        (
            t
            for t in gw.list_gateway_targets(gatewayIdentifier=gateway_id).get("items", [])
            if t.get("name") == TARGET_NAME
        ),
        None,
    )
    if existing:
        target_id = existing["targetId"]
        print(f"  이미 존재: targetId={target_id} — lambdaArn + schema 동기화")
        resp = gw.update_gateway_target(
            gatewayIdentifier=gateway_id,
            targetId=target_id,
            name=TARGET_NAME,
            targetConfiguration=target_config,
            credentialProviderConfigurations=cred_configs,
        )
        print(f"  ✅ targetId={target_id} 갱신 완료")
        return resp

    resp = gw.create_gateway_target(
        gatewayIdentifier=gateway_id,
        name=TARGET_NAME,
        targetConfiguration=target_config,
        credentialProviderConfigurations=cred_configs,
    )
    print(f"  ✅ targetId={resp['targetId']}")
    return resp


def main():
    required = ["GATEWAY_ID", "GITHUB_STORAGE_LAMBDA_ARN"]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        print(f"환경변수 누락: {missing}", file=sys.stderr)
        print("deploy.sh 가 CFN outputs + Phase 2 .env 를 export 한 뒤 호출하세요.", file=sys.stderr)
        sys.exit(1)

    gw = _client()
    create_or_update_target(
        gw,
        gateway_id=os.environ["GATEWAY_ID"],
        lambda_arn=os.environ["GITHUB_STORAGE_LAMBDA_ARN"],
    )

    print(f"\n✅ Phase 4 — github-storage Target 등록 완료 (Gateway 무변경, Target 1건 추가)")


if __name__ == "__main__":
    main()
