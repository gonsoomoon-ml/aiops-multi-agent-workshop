#!/usr/bin/env bash
# infra/github-lambda/teardown.sh — GitHub Lambda + Gateway Target reverse 삭제 (P4-A5 의 일부).
#
# Phase 2 stack / Gateway / 기존 2 Target 미터치. Phase 3 Monitor / Incident Runtime 도
# 별도 teardown.sh 로 정리 (본 스크립트 범위 밖).
#
# 순서: Target → CFN stack (Policy 자동 detach + Lambda 자동 삭제 + Role 자동 삭제)
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'
log()  { echo -e "${GREEN}[teardown]${NC} $1"; }
warn() { echo -e "${YELLOW}[teardown]${NC} $1"; }
fail() { echo -e "${RED}[teardown]${NC} $1"; exit 1; }

[[ -f "$PROJECT_ROOT/.env" ]] && {
    set -a; source "$PROJECT_ROOT/.env"; set +a
}

REGION="${AWS_REGION:-us-east-1}"
DEMO_USER="${DEMO_USER:-${USER:-ubuntu}}"
STACK="aiops-demo-${DEMO_USER}-github-lambda"
TARGET_NAME="github-storage"

log "region=$REGION demo_user=$DEMO_USER stack=$STACK"

# ── [1/3] Gateway Target 삭제 ──────────────────────
log "[1/3] Gateway Target '$TARGET_NAME' 삭제"

# A2 fallback: GATEWAY_ID 미설정 시 list-gateways 로 자동 복구. .env 손상 시
# orphan Target 회피. 매칭 0건/다수 시 hard fail (수동 개입 강제).
if [[ -z "${GATEWAY_ID:-}" ]]; then
    warn "  GATEWAY_ID 미설정 — list-gateways 로 자동 복구 시도"
    DISCOVERED_IDS=$(aws bedrock-agentcore-control list-gateways --region "$REGION" \
        --query "items[?starts_with(name, 'aiops-demo-${DEMO_USER}-gateway-')].gatewayId" \
        --output text 2>/dev/null || echo "")
    DISCOVERED_COUNT=$(echo "$DISCOVERED_IDS" | wc -w)
    if [[ "$DISCOVERED_COUNT" -eq 1 ]]; then
        GATEWAY_ID="$DISCOVERED_IDS"
        log "  ✓ Gateway 복구: $GATEWAY_ID"
    elif [[ "$DISCOVERED_COUNT" -eq 0 ]]; then
        warn "  (Gateway 미발견 — 이미 삭제됨, Target deletion skip)"
        GATEWAY_ID=""   # Target lookup 건너뛰기 신호
    else
        fail "Gateway 다수 매칭 ($DISCOVERED_COUNT 건) — 모호. 수동으로 GATEWAY_ID 지정"
    fi
fi

if [[ -n "${GATEWAY_ID:-}" ]]; then
    TARGET_ID=$(aws bedrock-agentcore-control list-gateway-targets \
        --region "$REGION" --gateway-identifier "$GATEWAY_ID" \
        --query "items[?name=='${TARGET_NAME}'].targetId" --output text 2>/dev/null || echo "")
    if [[ -n "$TARGET_ID" && "$TARGET_ID" != "None" ]]; then
        aws bedrock-agentcore-control delete-gateway-target \
            --region "$REGION" \
            --gateway-identifier "$GATEWAY_ID" \
            --target-id "$TARGET_ID" >/dev/null
        log "  ✓ Target ${TARGET_ID} 삭제"
    else
        warn "  (Target '$TARGET_NAME' 없음 — skip)"
    fi
fi

# ── [2/3] CFN stack 삭제 (Lambda + Role + cross-stack Policy 한꺼번에) ──
log "[2/3] CFN stack 삭제: $STACK"
if aws cloudformation describe-stacks --stack-name "$STACK" --region "$REGION" >/dev/null 2>&1; then
    aws cloudformation delete-stack --stack-name "$STACK" --region "$REGION"
    log "  ⏳ stack DELETE 진행 중... wait 완료까지 대기"
    aws cloudformation wait stack-delete-complete --stack-name "$STACK" --region "$REGION" \
        || warn "  stack delete wait 실패 (수동 확인 필요)"
    log "  ✓ stack 삭제 완료"
else
    warn "  (stack 없음 — skip)"
fi

# ── Lambda CW Log Group 삭제 (CFN 가 cascade 안 함 — first-invoke 시 auto-create) ──
LAMBDA_LG="/aws/lambda/aiops-demo-${DEMO_USER}-github-storage"
if aws logs delete-log-group --region "$REGION" --log-group-name "$LAMBDA_LG" 2>/dev/null; then
    log "  ✓ Lambda log group ${LAMBDA_LG} 삭제"
fi

# ── [3/3] .env cleanup ─────────────────────────────
if [[ -f "$PROJECT_ROOT/.env" ]]; then
    sed -i.bak '/^GITHUB_STORAGE_LAMBDA_ARN=/d' "$PROJECT_ROOT/.env"
    rm -f "$PROJECT_ROOT/.env.bak"
    log "  ✓ .env 의 GITHUB_STORAGE_LAMBDA_ARN 제거"
fi

# packaged template artifact 정리
rm -f "$PROJECT_ROOT/infra/github-lambda/github_lambda.packaged.yaml"

# ── dependency 보존 확인 ────────────────────────
log "[verify] dependency 보존 확인 (Cognito stack / Gateway)"
PHASE2_STACK="aiops-demo-${DEMO_USER}-cognito-gateway"
if aws cloudformation describe-stacks --stack-name "$PHASE2_STACK" --region "$REGION" >/dev/null 2>&1; then
    log "  ✓ Cognito stack 보존"
else
    warn "  - Cognito stack 미존재 (이미 정리되었거나 wrapper 가 step 7 에서 정리 예정)"
fi

if [[ -n "${GATEWAY_ID:-}" ]]; then
    if aws bedrock-agentcore-control get-gateway --gateway-identifier "$GATEWAY_ID" --region "$REGION" >/dev/null 2>&1; then
        log "  ✓ Gateway 보존"
    else
        warn "  - Gateway 미존재 (이미 정리되었거나 미배포)"
    fi
fi

# B2: cognito-gateway 의 GatewayIamRole 에 github-lambda inline policy 잔존 여부 검증.
# CFN AWS::IAM::Policy 가 stack delete 시 자동 detach 하지만, 워크샵 cleanup 보증으로
# 명시적 grep. 잔존 시 다음 deploy 의 PolicyName 충돌 또는 stale invoke 권한 발생.
GATEWAY_ROLE="aiops-demo-${DEMO_USER}-gateway-role"
INVOKE_POLICY_NAME="aiops-demo-${DEMO_USER}-gateway-invoke-github"
if aws iam list-role-policies --role-name "$GATEWAY_ROLE" \
    --query "PolicyNames" --output text 2>/dev/null | grep -qw "$INVOKE_POLICY_NAME"; then
    fail "GatewayIamRole 에 inline policy '$INVOKE_POLICY_NAME' 잔존 — CFN cleanup 실패. 수동 detach 필요"
else
    log "  ✓ GatewayIamRole 의 inline policy 정상 detach"
fi

log "Phase 4 GitHub Lambda + Target teardown 완료"
log "  NOTE: Incident Runtime 정리는 'bash agents/incident/runtime/teardown.sh'"
