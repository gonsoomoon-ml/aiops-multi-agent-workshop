#!/usr/bin/env bash
# stop_instance.sh — EC2 시뮬레이터 stop → payment-${DEMO_USER}-status-check alarm fire
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
if [[ -f "$PROJECT_ROOT/.env" ]]; then
    set -a; source "$PROJECT_ROOT/.env"; set +a
fi

REGION="${AWS_REGION:-us-west-2}"
PROJECT_TAG="${PROJECT_TAG:-aiops-demo}"
DEMO_USER="${DEMO_USER:-${USER:-ubuntu}}"

INSTANCE_ID="${1:-$(aws ec2 describe-instances --region "$REGION" \
    --filters "Name=tag:Project,Values=$PROJECT_TAG" \
              "Name=tag:User,Values=$DEMO_USER" \
              "Name=instance-state-name,Values=running" \
    --query 'Reservations[0].Instances[0].InstanceId' \
    --output text)}"

if [[ -z "$INSTANCE_ID" || "$INSTANCE_ID" == "None" ]]; then
    echo "[chaos] Project=$PROJECT_TAG User=$DEMO_USER region=$REGION running EC2 미발견" >&2
    exit 1
fi

echo "[chaos] EC2 stop: $INSTANCE_ID (region=$REGION)"
aws ec2 stop-instances --region "$REGION" --instance-ids "$INSTANCE_ID" >/dev/null
echo "[chaos] stop 명령 전송 — alarm 발화까지 ~2분 대기"
echo "[chaos] 복원: bash infra/phase0/chaos/start_instance.sh"
