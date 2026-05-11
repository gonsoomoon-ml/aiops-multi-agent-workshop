"""Phase 2 — AgentCore Gateway 삭제 (boto3, idempotent).

teardown.sh 가 CFN stack 삭제 전에 호출 — Gateway/Target 이 Lambda invoke 권한
보유 중인 동안 정리 필요. 이미 삭제됐으면 silently skip.

ec-customer-support-e2e-agentcore lab-09 패턴
  (https://github.com/gonsoomoon-ml/ec-customer-support-e2e-agentcore)
— 역순 삭제 + target → gateway 사이 3초 wait.
"""
import os
import sys
import time

import boto3

REGION = os.environ.get("AWS_REGION", "us-west-2")
DEMO_USER = os.environ.get("DEMO_USER", "")  # main() 에서 검증
TARGET_DELETE_WAIT_SEC = 3  # lab-09: target DELETING 비동기 — gateway 삭제 전 대기


def main():
    if not DEMO_USER:
        print("환경변수 누락: DEMO_USER", file=sys.stderr)
        sys.exit(1)

    gateway_name = f"aiops-demo-{DEMO_USER}-gateway"
    gw = boto3.client("bedrock-agentcore-control", region_name=REGION)

    gateway = next(
        (g for g in gw.list_gateways().get("items", []) if g.get("name") == gateway_name),
        None,
    )
    if not gateway:
        print(f"Gateway '{gateway_name}' 미존재 (이미 삭제됨)")
        return

    gateway_id = gateway["gatewayId"]
    print(f"Gateway 발견: gatewayId={gateway_id}")

    targets = gw.list_gateway_targets(gatewayIdentifier=gateway_id).get("items", [])
    targets_deleted = 0
    for t in targets:
        target_id = t["targetId"]
        name = t.get("name", target_id)
        try:
            print(f"  GatewayTarget 삭제: name={name} targetId={target_id}")
            gw.delete_gateway_target(gatewayIdentifier=gateway_id, targetId=target_id)
            targets_deleted += 1
        except Exception as e:
            print(f"  ⚠️ Target 삭제 실패 (계속 진행): {e}", file=sys.stderr)

    if targets_deleted > 0:
        print(f"  ⏳ Target DELETING 비동기 처리 대기 ({TARGET_DELETE_WAIT_SEC}초)")
        time.sleep(TARGET_DELETE_WAIT_SEC)

    try:
        print(f"Gateway 삭제: gatewayId={gateway_id}")
        gw.delete_gateway(gatewayIdentifier=gateway_id)
    except Exception as e:
        print(f"⚠️ Gateway 삭제 실패: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
