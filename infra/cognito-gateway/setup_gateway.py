"""Phase 2 — AgentCore Gateway 생성 (boto3, educational step-by-step).

ec-customer-support-e2e-agentcore lab-03 패턴 차용
  (https://github.com/gonsoomoon-ml/ec-customer-support-e2e-agentcore).
표준 AWS 자원 (Cognito, Lambda, IAM Role) 은 cognito.yaml CFN 이 담당.
이 스크립트는 AgentCore 자원만.

Idempotent: 같은 이름의 Gateway/Target 있으면 기존 ID 재사용.

deploy.sh 가 CFN outputs 를 환경변수로 주입한 뒤 호출:
    GATEWAY_IAM_ROLE_ARN
    COGNITO_USER_POOL_ID
    COGNITO_CLIENT_ID
    COGNITO_GATEWAY_SCOPE
    LAMBDA_HISTORY_MOCK_ARN
    LAMBDA_CLOUDWATCH_WRAPPER_ARN

3개의 검증 레이어 (Gateway CUSTOM_JWT authorizer):
    들어오는 JWT
      ↓ Gateway authorizer
      ① 서명 검증     ← discoveryUrl (UserPoolId 로부터)
      ② audience 검증 ← allowedClients=[Client ID]
      ③ scope 검증    ← allowedScopes=[<resource-server>/invoke]
      → 통과 시 Target 호출

출력: GATEWAY_ID + GATEWAY_URL (deploy.sh 가 .env 갱신 시 캡처).
"""
import os
import sys
import time

import boto3

REGION = os.environ.get("AWS_REGION", "us-west-2")
DEMO_USER = os.environ.get("DEMO_USER", "")  # main() 의 required 검증에서 빈 값 거부

GATEWAY_NAME = f"aiops-demo-{DEMO_USER}-gateway"
TARGET_HISTORY = "history-mock"
TARGET_CLOUDWATCH = "cloudwatch-wrapper"

CW_TOOL_SCHEMA = [
    {
        "name": "list_live_alarms",
        "description": (
            "라이브 CloudWatch 알람 목록과 상태 + classification (real|noise) 라벨 조회. "
            f"payment-{DEMO_USER}-* prefix."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "get_live_alarm_history",
        "description": (
            "특정 라이브 알람의 최근 상태 전이 history (RCA 단서). "
            "페어: 과거 mock 데이터는 get_past_alarm_history."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["alarm_name"],
            "properties": {
                "alarm_name": {"type": "string"},
                "type": {
                    "type": "string",
                    "description": "StateUpdate (기본) | ConfigurationUpdate | Action",
                },
                "max": {
                    "type": "integer",
                    "description": "최대 반환 개수 (기본 20)",
                },
            },
        },
    },
]

HISTORY_TOOL_SCHEMA = [
    {
        "name": "get_past_alarms_metadata",
        "description": (
            "과거 5개 알람 metadata 조회 (mock). 페어: 라이브는 list_live_alarms. "
            "CloudWatch DescribeAlarms 와 동일 PascalCase + 합성 필드 (Tags.Classification, ack, action_taken). "
            "ground truth 분류는 노출 안 됨."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "get_past_alarm_history",
        "description": (
            "과거 알람 history 이벤트 (시간 윈도우 필터). 24 events. "
            "페어: 라이브는 get_live_alarm_history. "
            "HistorySummary 텍스트로 fire/recovery 패턴 + ack/action_taken 으로 noise 신호 추론 가능."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "최근 며칠 분 history 반환 (기본 7, 7 이상이면 전체).",
                },
            },
        },
    },
]


def _client():
    return boto3.client("bedrock-agentcore-control", region_name=REGION)


def wait_for_gateway_ready(gw, gateway_id: str, max_wait: int = 90, poll: int = 3) -> None:
    """Gateway 가 READY 상태 될 때까지 대기 (Target 추가 전 필수).

    create_gateway 직후엔 CREATING — Target 추가 시 ValidationException. 본 함수가
    get_gateway 폴링 → READY 확인 후 반환. 이미 READY 면 즉시 반환 (idempotent).
    """
    print(f"  ⏳ Gateway READY 대기 (max {max_wait}s)")
    deadline = time.monotonic() + max_wait
    status = "UNKNOWN"
    while time.monotonic() < deadline:
        detail = gw.get_gateway(gatewayIdentifier=gateway_id)
        status = detail.get("status", "UNKNOWN")
        if status == "READY":
            print(f"  ✅ Gateway READY")
            return
        if status in ("FAILED", "DELETING", "DELETED"):
            raise RuntimeError(f"Gateway 비정상 상태: {status}")
        time.sleep(poll)
    raise RuntimeError(f"Gateway READY 타임아웃 ({max_wait}s, 현재={status})")


def create_gateway(gw, role_arn, pool_id, client_id, scope):
    print("\n=== Step 1: AgentCore Gateway 생성 ===")
    existing = next(
        (g for g in gw.list_gateways().get("items", []) if g.get("name") == GATEWAY_NAME),
        None,
    )
    if existing:
        print(f"  이미 존재: gatewayId={existing['gatewayId']} (재사용)")
        detail = gw.get_gateway(gatewayIdentifier=existing["gatewayId"])
        return detail

    discovery_url = (
        f"https://cognito-idp.{REGION}.amazonaws.com/{pool_id}/.well-known/openid-configuration"
    )
    resp = gw.create_gateway(
        name=GATEWAY_NAME,
        roleArn=role_arn,
        protocolType="MCP",
        authorizerType="CUSTOM_JWT",
        authorizerConfiguration={
            "customJWTAuthorizer": {
                "discoveryUrl": discovery_url,
                "allowedClients": [client_id],
                "allowedScopes": [scope],
            }
        },
    )
    print(f"  ✅ gatewayId={resp['gatewayId']}")
    print(f"  ✅ gatewayUrl={resp['gatewayUrl']}")
    return resp


def create_or_update_target(gw, gateway_id, name, lambda_arn, tool_schema):
    """Target 이 없으면 create, 있으면 update — lambdaArn + schema 강제 동기화.

    이전 reuse-only 패턴은 stack delete→recreate 시 stale lambdaArn 잔존으로 silent
    fail. update 분기로 재배포 시에도 lambdaArn + tool_schema 가 항상 최신.
    sibling: github-lambda / s3-lambda 의 setup_*_target.py 와 동형.
    """
    print(f"\n=== Step 2: GatewayTarget '{name}' 추가/갱신 ===")

    target_config = {
        "mcp": {
            "lambda": {
                "lambdaArn": lambda_arn,
                "toolSchema": {"inlinePayload": tool_schema},
            }
        }
    }
    cred_configs = [{"credentialProviderType": "GATEWAY_IAM_ROLE"}]

    existing = next(
        (
            t
            for t in gw.list_gateway_targets(gatewayIdentifier=gateway_id).get("items", [])
            if t.get("name") == name
        ),
        None,
    )
    if existing:
        target_id = existing["targetId"]
        print(f"  이미 존재: targetId={target_id} — lambdaArn + schema 동기화")
        resp = gw.update_gateway_target(
            gatewayIdentifier=gateway_id,
            targetId=target_id,
            name=name,
            targetConfiguration=target_config,
            credentialProviderConfigurations=cred_configs,
        )
        print(f"  ✅ targetId={target_id} 갱신 완료")
        return resp

    resp = gw.create_gateway_target(
        gatewayIdentifier=gateway_id,
        name=name,
        targetConfiguration=target_config,
        credentialProviderConfigurations=cred_configs,
    )
    print(f"  ✅ targetId={resp['targetId']}")
    return resp


def main():
    required = [
        "DEMO_USER",
        "GATEWAY_IAM_ROLE_ARN",
        "COGNITO_USER_POOL_ID",
        "COGNITO_CLIENT_ID",
        "COGNITO_GATEWAY_SCOPE",
        "LAMBDA_HISTORY_MOCK_ARN",
        "LAMBDA_CLOUDWATCH_WRAPPER_ARN",
    ]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        print(f"환경변수 누락: {missing}", file=sys.stderr)
        print("deploy.sh 가 CFN outputs 를 export 한 뒤 호출하세요.", file=sys.stderr)
        sys.exit(1)

    gw = _client()
    gateway = create_gateway(
        gw,
        role_arn=os.environ["GATEWAY_IAM_ROLE_ARN"],
        pool_id=os.environ["COGNITO_USER_POOL_ID"],
        client_id=os.environ["COGNITO_CLIENT_ID"],
        scope=os.environ["COGNITO_GATEWAY_SCOPE"],
    )
    gateway_id = gateway["gatewayId"]
    gateway_url = gateway["gatewayUrl"]

    # Target 추가 전 Gateway READY 대기 — CREATING 상태에서 Target 추가 시 ValidationException
    wait_for_gateway_ready(gw, gateway_id)

    create_or_update_target(
        gw, gateway_id, TARGET_CLOUDWATCH,
        lambda_arn=os.environ["LAMBDA_CLOUDWATCH_WRAPPER_ARN"],
        tool_schema=CW_TOOL_SCHEMA,
    )
    create_or_update_target(
        gw, gateway_id, TARGET_HISTORY,
        lambda_arn=os.environ["LAMBDA_HISTORY_MOCK_ARN"],
        tool_schema=HISTORY_TOOL_SCHEMA,
    )

    # deploy.sh 가 stdout 에서 캡처해 .env 에 기록
    print(f"\nGATEWAY_ID={gateway_id}")
    print(f"GATEWAY_URL={gateway_url}")


if __name__ == "__main__":
    main()
