"""Phase 6a — Gateway Target 'deployments-storage' 추가 (boto3, idempotent).

Phase 4 setup_github_target.py 의 create_or_update_target 패턴 정확 차용 (A1 fix
포함 — Target 존재 시 update). Phase 2 Gateway 에 새 Target 1건 추가, 기존 Target
(history-mock, cloudwatch-wrapper, github-storage) 미터치.

deploy.sh 가 CFN outputs 를 환경변수로 주입한 뒤 호출:
    GATEWAY_ID                          (Phase 2 .env carry-over)
    DEPLOYMENTS_STORAGE_LAMBDA_ARN      (Phase 6a CFN output)

reference:
    - docs/design/phase6a.md §7-3 (Tool schema)
    - infra/phase4/setup_github_target.py (create-or-update 패턴)
"""
import os
import sys

import boto3

REGION = os.environ.get("AWS_REGION", "us-west-2")
TARGET_NAME = "deployments-storage"

DEPLOYMENTS_TOOL_SCHEMA = [
    {
        "name": "get_deployments_log",
        "description": (
            "Read deployments/<date>.log from the project's GitHub repository. "
            "Used by the Change Agent to inspect the last 24h of deployment events "
            "when assessing regression likelihood for an incident. "
            "Input: date (YYYY-MM-DD). "
            "Returns: deployments_found (bool), path, content (raw log markdown) — "
            "or deployments_found:false + status/error on miss (e.g., 404 if no "
            "deployments occurred that day)."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["date"],
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Deployment date in YYYY-MM-DD (e.g., '2026-05-09').",
                },
            },
        },
    },
    {
        "name": "append_incident",
        "description": (
            "Append an incident record to incidents/<date>.log on GitHub. "
            "Creates the file if it does not exist. Used by the Change Agent to "
            "persist incident summaries for cross-day audit. "
            "Input: date (YYYY-MM-DD), body (markdown — alarm + diagnosis + severity + "
            "regression assessment). "
            "Returns: appended (bool), path, commit_sha, html_url."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["date", "body"],
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Incident date in YYYY-MM-DD (typically today).",
                },
                "body": {
                    "type": "string",
                    "description": (
                        "Incident summary in markdown. 1-2 paragraphs. Korean acceptable. "
                        "Include alarm name, severity, diagnosis, regression_likelihood, "
                        "suspected_deployment if any."
                    ),
                },
            },
        },
    },
]


def _client():
    return boto3.client("bedrock-agentcore-control", region_name=REGION)


def create_or_update_target(gw, gateway_id: str, lambda_arn: str):
    """Target create-or-update — Phase 4 의 A1 fix 패턴 동일."""
    print(f"\n=== Phase 6a — GatewayTarget '{TARGET_NAME}' 추가/갱신 ===")

    target_config = {
        "mcp": {
            "lambda": {
                "lambdaArn": lambda_arn,
                "toolSchema": {"inlinePayload": DEPLOYMENTS_TOOL_SCHEMA},
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
    required = ["GATEWAY_ID", "DEPLOYMENTS_STORAGE_LAMBDA_ARN"]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        print(f"환경변수 누락: {missing}", file=sys.stderr)
        print("deploy.sh 가 CFN outputs + Phase 2 .env 를 export 한 뒤 호출.", file=sys.stderr)
        sys.exit(1)

    gw = _client()
    create_or_update_target(
        gw,
        gateway_id=os.environ["GATEWAY_ID"],
        lambda_arn=os.environ["DEPLOYMENTS_STORAGE_LAMBDA_ARN"],
    )

    print(f"\n✅ Phase 6a — deployments-storage Target 등록 완료")
    print(f"   (Gateway 무변경, 기존 3 Target 무변경, 신규 Target 1건)")


if __name__ == "__main__":
    main()
