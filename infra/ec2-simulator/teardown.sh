#!/usr/bin/env bash
# infra/ec2-simulator/teardown.sh — Phase 0 리소스 일괄 삭제
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

GREEN='\033[0;32m'
NC='\033[0m'
log() { echo -e "${GREEN}[teardown]${NC} $1"; }

if [[ -f "$PROJECT_ROOT/.env" ]]; then
    set -a
    source "$PROJECT_ROOT/.env"
    set +a
fi

REGION="${AWS_REGION:-us-west-2}"
DEMO_USER="${DEMO_USER:-${USER:-ubuntu}}"
STACK_EC2="aiops-demo-${DEMO_USER}-phase0-ec2"
STACK_ALARMS="aiops-demo-${DEMO_USER}-phase0-alarms"

log "demo_user=$DEMO_USER  → stacks: $STACK_ALARMS + $STACK_EC2"

log "alarms 스택 삭제..."
aws cloudformation delete-stack --region "$REGION" --stack-name "$STACK_ALARMS" || true
aws cloudformation wait stack-delete-complete --region "$REGION" --stack-name "$STACK_ALARMS" 2>/dev/null || true

log "ec2-simulator 스택 삭제..."
aws cloudformation delete-stack --region "$REGION" --stack-name "$STACK_EC2" || true
aws cloudformation wait stack-delete-complete --region "$REGION" --stack-name "$STACK_EC2" 2>/dev/null || true

if [[ -f "$PROJECT_ROOT/.env" ]]; then
    sed -i "s|^EC2_INSTANCE_ID=.*|EC2_INSTANCE_ID=|" "$PROJECT_ROOT/.env"
    sed -i "s|^EC2_PUBLIC_IP=.*|EC2_PUBLIC_IP=|" "$PROJECT_ROOT/.env"
fi

log "Phase 0 정리 완료"
