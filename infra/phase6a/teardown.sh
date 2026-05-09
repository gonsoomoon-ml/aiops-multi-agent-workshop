#!/usr/bin/env bash
# infra/phase6a/teardown.sh — Phase 6a infra reverse 삭제.
#
# 순서:
#   1. Gateway Target 'deployments-storage' 삭제
#   2. deployments_lambda CFN stack 삭제 (Lambda + Role + cross-stack policy 자동 detach)
#   3. cognito_extras CFN stack 삭제 (Client A + B + OperatorUser + 새 ResourceServer)
#   4. .env / .env.operator cleanup
#
# Phase 0/2/3/4 자원 + Phase 6a Runtime 자원 (agents/change, monitor_a2a, incident_a2a,
# supervisor) 미터치. Runtime teardown 은 각 agent 의 teardown.sh 별도.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'
log()  { echo -e "${GREEN}[teardown]${NC} $1"; }
warn() { echo -e "${YELLOW}[teardown]${NC} $1"; }
fail() { echo -e "${RED}[teardown]${NC} $1"; exit 1; }

[[ -f "$PROJECT_ROOT/.env" ]] && { set -a; source "$PROJECT_ROOT/.env"; set +a; }

REGION="${AWS_REGION:-us-west-2}"
DEMO_USER="${DEMO_USER:-${USER:-ubuntu}}"
COGNITO_STACK="aiops-demo-${DEMO_USER}-phase6a-cognito-extras"
LAMBDA_STACK="aiops-demo-${DEMO_USER}-phase6a-deployments"
TARGET_NAME="deployments-storage"

log "region=$REGION demo_user=$DEMO_USER"

# ── [1/4] Gateway Target 'deployments-storage' 삭제 ───
log "[1/4] Gateway Target '$TARGET_NAME' 삭제"
if [[ -z "${GATEWAY_ID:-}" ]]; then
    warn "  GATEWAY_ID 미설정 — list-gateways 로 자동 복구"
    DISCOVERED_IDS=$(aws bedrock-agentcore-control list-gateways --region "$REGION" \
        --query "items[?starts_with(name, 'aiops-demo-${DEMO_USER}-gateway-')].gatewayId" \
        --output text 2>/dev/null || echo "")
    DISCOVERED_COUNT=$(echo "$DISCOVERED_IDS" | wc -w)
    if [[ "$DISCOVERED_COUNT" -eq 1 ]]; then
        GATEWAY_ID="$DISCOVERED_IDS"
        log "  ✓ Gateway 복구: $GATEWAY_ID"
    elif [[ "$DISCOVERED_COUNT" -eq 0 ]]; then
        warn "  Gateway 미발견 — Target 삭제 skip"
    else
        fail "Gateway 다수 매칭 — 모호. 수동 GATEWAY_ID 지정"
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
        warn "  (Target 없음 — skip)"
    fi
fi

# ── [2/4] deployments_lambda stack 삭제 ──────────
log "[2/4] CFN stack 삭제: $LAMBDA_STACK"
if aws cloudformation describe-stacks --stack-name "$LAMBDA_STACK" --region "$REGION" >/dev/null 2>&1; then
    aws cloudformation delete-stack --stack-name "$LAMBDA_STACK" --region "$REGION"
    aws cloudformation wait stack-delete-complete --stack-name "$LAMBDA_STACK" --region "$REGION" \
        || warn "  stack delete wait 실패"
    log "  ✓ stack 삭제 완료"
else
    warn "  (stack 없음 — skip)"
fi

# ── [3/4] cognito_extras stack 삭제 ──────────────
log "[3/4] CFN stack 삭제: $COGNITO_STACK"
if aws cloudformation describe-stacks --stack-name "$COGNITO_STACK" --region "$REGION" >/dev/null 2>&1; then
    aws cloudformation delete-stack --stack-name "$COGNITO_STACK" --region "$REGION"
    aws cloudformation wait stack-delete-complete --stack-name "$COGNITO_STACK" --region "$REGION" \
        || warn "  stack delete wait 실패"
    log "  ✓ stack 삭제 완료"
else
    warn "  (stack 없음 — skip)"
fi

# ── [4/4] .env / .env.operator cleanup ───────────
log "[4/4] .env cleanup"
if [[ -f "$PROJECT_ROOT/.env" ]]; then
    sed -i.bak \
        -e '/^COGNITO_CLIENT_A_ID=/d' \
        -e '/^COGNITO_CLIENT_B_ID=/d' \
        -e '/^COGNITO_CLIENT_B_SECRET=/d' \
        -e '/^COGNITO_AGENT_INVOKE_SCOPE=/d' \
        -e '/^OPERATOR_USERNAME=/d' \
        -e '/^DEPLOYMENTS_STORAGE_LAMBDA_ARN=/d' \
        "$PROJECT_ROOT/.env"
    rm -f "$PROJECT_ROOT/.env.bak"
    log "  ✓ .env 의 Phase 6a 항목 제거"
fi

if [[ -f "$PROJECT_ROOT/.env.operator" ]]; then
    rm -f "$PROJECT_ROOT/.env.operator"
    log "  ✓ .env.operator 삭제"
fi

# packaged template artifact 정리
rm -f "$PROJECT_ROOT/infra/phase6a/deployments_lambda.packaged.yaml"

# ── 보존 검증 ────────────────────────────────────
log "[verify] Phase 0/2/4 자원 보존 검증"
PHASE2_STACK="aiops-demo-${DEMO_USER}-phase2-cognito"
PHASE4_STACK="aiops-demo-${DEMO_USER}-phase4-github"
for STACK_VERIFY in "$PHASE2_STACK" "$PHASE4_STACK"; do
    if aws cloudformation describe-stacks --stack-name "$STACK_VERIFY" --region "$REGION" >/dev/null 2>&1; then
        log "  ✓ $STACK_VERIFY 보존"
    else
        warn "  $STACK_VERIFY 미존재 (이미 정리되었거나 미배포)"
    fi
done

# Phase 2 GatewayIamRole 의 phase6a inline policy 잔존 검증 (Phase 4 패턴)
PHASE2_GATEWAY_ROLE="aiops-demo-${DEMO_USER}-phase2-gateway-role"
PHASE6A_POLICY_NAME="aiops-demo-${DEMO_USER}-phase6a-gateway-invoke-deployments"
if aws iam list-role-policies --role-name "$PHASE2_GATEWAY_ROLE" \
    --query "PolicyNames" --output text 2>/dev/null | grep -qw "$PHASE6A_POLICY_NAME"; then
    fail "Phase 2 Role 에 phase6a inline policy '$PHASE6A_POLICY_NAME' 잔존 — CFN cleanup 실패"
else
    log "  ✓ Phase 2 Role 의 phase6a inline policy 정상 detach"
fi

# Phase 4 의 phase4 policy 보존 확인 (preservation)
PHASE4_POLICY_NAME="aiops-demo-${DEMO_USER}-phase4-gateway-invoke-github"
if aws iam list-role-policies --role-name "$PHASE2_GATEWAY_ROLE" \
    --query "PolicyNames" --output text 2>/dev/null | grep -qw "$PHASE4_POLICY_NAME"; then
    log "  ✓ Phase 4 의 inline policy '$PHASE4_POLICY_NAME' 보존 (preservation rule)"
fi

log "Phase 6a infra teardown 완료"
log "  NOTE: Phase 6a Runtime 정리는 각 agent 의 teardown.sh 로 별도"
log "    bash agents/supervisor/runtime/teardown.sh"
log "    bash agents/change/runtime/teardown.sh"
log "    bash agents/monitor_a2a/runtime/teardown.sh"
log "    bash agents/incident_a2a/runtime/teardown.sh"
