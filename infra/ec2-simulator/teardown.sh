#!/usr/bin/env bash
# infra/ec2-simulator/teardown.sh — Phase 0 리소스 일괄 삭제
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'
log()  { echo -e "${GREEN}[teardown]${NC} $1"; }
warn() { echo -e "${YELLOW}[teardown]${NC} $1"; }
fail() { echo -e "${RED}[teardown]${NC} $1"; exit 1; }

if [[ -f "$PROJECT_ROOT/.env" ]]; then
    set -a
    source "$PROJECT_ROOT/.env"
    set +a
fi

REGION="${AWS_REGION:-us-east-1}"
DEMO_USER="${DEMO_USER:-${USER:-ubuntu}}"
STACK_EC2="aiops-demo-${DEMO_USER}-ec2-simulator"
STACK_ALARMS="aiops-demo-${DEMO_USER}-alarms"

# delete + wait + verify (idempotent — 이미 삭제된 stack 도 안전)
delete_stack() {
    local stack="$1"
    if ! aws cloudformation describe-stacks --region "$REGION" --stack-name "$stack" >/dev/null 2>&1; then
        warn "  (stack '$stack' 없음 — skip)"
        return 0
    fi
    aws cloudformation delete-stack --region "$REGION" --stack-name "$stack"
    aws cloudformation wait stack-delete-complete --region "$REGION" --stack-name "$stack" 2>/dev/null || true
    # post-verify: stack 잔존 시 fail
    if aws cloudformation describe-stacks --region "$REGION" --stack-name "$stack" --query 'Stacks[0].StackStatus' --output text 2>/dev/null | grep -qv "DELETE_COMPLETE"; then
        fail "  ❌ stack '$stack' 삭제 실패 (DELETE_FAILED 또는 잔존). 'aws cloudformation describe-stack-events --stack-name $stack' 로 원인 확인"
    fi
    log "  ✓ stack '$stack' 삭제 완료"
}

log "demo_user=$DEMO_USER  → stacks: $STACK_ALARMS + $STACK_EC2"

log "[1/2] alarms 스택 삭제..."
delete_stack "$STACK_ALARMS"

log "[2/2] ec2-simulator 스택 삭제..."
delete_stack "$STACK_EC2"

if [[ -f "$PROJECT_ROOT/.env" ]]; then
    sed -i "s|^EC2_INSTANCE_ID=.*|EC2_INSTANCE_ID=|" "$PROJECT_ROOT/.env"
    sed -i "s|^EC2_PUBLIC_IP=.*|EC2_PUBLIC_IP=|" "$PROJECT_ROOT/.env"
    log "  ✓ .env 의 EC2_INSTANCE_ID / EC2_PUBLIC_IP 비움"
fi

log "Phase 0 정리 완료"
