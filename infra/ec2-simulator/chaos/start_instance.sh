#!/usr/bin/env bash
# start_instance.sh — EC2 시뮬레이터 재시작 (카오스 복원)
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
if [[ -f "$PROJECT_ROOT/.env" ]]; then
    set -a; source "$PROJECT_ROOT/.env"; set +a
fi

REGION="${AWS_REGION:-us-east-1}"
PROJECT_TAG="${PROJECT_TAG:-aiops-demo}"
DEMO_USER="${DEMO_USER:-${USER:-ubuntu}}"

INSTANCE_ID="${1:-$(aws ec2 describe-instances --region "$REGION" \
    --filters "Name=tag:Project,Values=$PROJECT_TAG" \
              "Name=tag:User,Values=$DEMO_USER" \
              "Name=instance-state-name,Values=stopped" \
    --query 'Reservations[0].Instances[0].InstanceId' \
    --output text)}"

if [[ -z "$INSTANCE_ID" || "$INSTANCE_ID" == "None" ]]; then
    echo "[chaos] Project=$PROJECT_TAG User=$DEMO_USER region=$REGION stopped EC2 미발견" >&2
    exit 1
fi

echo "[chaos] EC2 start: $INSTANCE_ID (region=$REGION)"
aws ec2 start-instances --region "$REGION" --instance-ids "$INSTANCE_ID" >/dev/null
aws ec2 wait instance-running --region "$REGION" --instance-ids "$INSTANCE_ID"
echo "[chaos] running 상태 확인 — Flask 부팅 ~30초 + alarm 'payment-${DEMO_USER}-status-check' OK 복원까지 추가 ~1분"
echo "[chaos] 모니터링: 'aws cloudwatch describe-alarms --alarm-names payment-${DEMO_USER}-status-check --region $REGION'"
