#!/usr/bin/env bash
# infra/s3-lambda/teardown.sh — S3 Lambda + Gateway Target reverse 삭제.
#
# GitHub backend (`infra/github-lambda/teardown.sh`) 의 형제. cognito-gateway
# stack / Gateway / 기존 Target 미터치.
#
# 순서: Target → S3 bucket 비우기 (CFN 자동 delete 위해) → CFN stack delete
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

REGION="${AWS_REGION:-us-west-2}"
DEMO_USER="${DEMO_USER:-${USER:-ubuntu}}"
STACK="aiops-demo-${DEMO_USER}-s3-lambda"
TARGET_NAME="s3-storage"

log "region=$REGION demo_user=$DEMO_USER stack=$STACK"

# ── [1/4] Gateway Target 삭제 ──────────────────────
log "[1/4] Gateway Target '$TARGET_NAME' 삭제"

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
        GATEWAY_ID=""
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

# ── [2/4] S3 bucket 비우기 (versioned) — CFN delete 전제 ─
log "[2/4] S3 bucket 비우기 (모든 version + delete-marker 포함)"
BUCKET_NAME="${STORAGE_BUCKET_NAME:-aiops-demo-${DEMO_USER}-storage-$(aws sts get-caller-identity --query Account --output text 2>/dev/null)-${REGION}}"
if aws s3api head-bucket --bucket "$BUCKET_NAME" --region "$REGION" 2>/dev/null; then
    # versioning 활성 bucket — current + noncurrent 모두 제거 (s3 rm 으로는 noncurrent 미삭제)
    aws s3api list-object-versions --bucket "$BUCKET_NAME" --region "$REGION" \
        --query '{Objects: Versions[].{Key: Key, VersionId: VersionId}}' --output json 2>/dev/null \
        | python3 -c "
import json, subprocess, sys
data = json.load(sys.stdin)
objs = data.get('Objects') or []
if objs:
    # batch delete (max 1000 per call)
    for i in range(0, len(objs), 1000):
        batch = {'Objects': objs[i:i+1000]}
        subprocess.run(['aws', 's3api', 'delete-objects', '--bucket', '$BUCKET_NAME', '--region', '$REGION', '--delete', json.dumps(batch)], check=True, stdout=subprocess.DEVNULL)
print(f'  removed {len(objs)} object versions')
" 2>/dev/null || warn "  version 정리 중 일부 실패 (계속)"

    aws s3api list-object-versions --bucket "$BUCKET_NAME" --region "$REGION" \
        --query '{Objects: DeleteMarkers[].{Key: Key, VersionId: VersionId}}' --output json 2>/dev/null \
        | python3 -c "
import json, subprocess, sys
data = json.load(sys.stdin)
objs = data.get('Objects') or []
if objs:
    for i in range(0, len(objs), 1000):
        batch = {'Objects': objs[i:i+1000]}
        subprocess.run(['aws', 's3api', 'delete-objects', '--bucket', '$BUCKET_NAME', '--region', '$REGION', '--delete', json.dumps(batch)], check=True, stdout=subprocess.DEVNULL)
print(f'  removed {len(objs)} delete-markers')
" 2>/dev/null || true

    log "  ✓ bucket 비움: $BUCKET_NAME"
else
    warn "  (bucket '$BUCKET_NAME' 없음 — skip)"
fi

# ── [3/4] CFN stack 삭제 ─────────────────────────
log "[3/4] CFN stack 삭제: $STACK"
if aws cloudformation describe-stacks --stack-name "$STACK" --region "$REGION" >/dev/null 2>&1; then
    aws cloudformation delete-stack --stack-name "$STACK" --region "$REGION"
    log "  ⏳ stack DELETE 진행 중... wait 완료까지 대기"
    aws cloudformation wait stack-delete-complete --stack-name "$STACK" --region "$REGION" \
        || warn "  stack delete wait 실패 (수동 확인 필요)"
    log "  ✓ stack 삭제 완료"
else
    warn "  (stack 없음 — skip)"
fi

# ── [4/4] .env cleanup + packaged template ────────
if [[ -f "$PROJECT_ROOT/.env" ]]; then
    sed -i.bak '/^S3_STORAGE_LAMBDA_ARN=/d; /^STORAGE_BUCKET_NAME=/d' "$PROJECT_ROOT/.env"
    rm -f "$PROJECT_ROOT/.env.bak"
    log "  ✓ .env 의 S3_STORAGE_LAMBDA_ARN / STORAGE_BUCKET_NAME 제거"
fi
rm -f "$PROJECT_ROOT/infra/s3-lambda/s3_lambda.packaged.yaml"

# ── dependency 보존 확인 ────────────────────────
log "[verify] dependency 보존 확인 (Cognito stack / Gateway)"
COGNITO_STACK="aiops-demo-${DEMO_USER}-cognito-gateway"
if aws cloudformation describe-stacks --stack-name "$COGNITO_STACK" --region "$REGION" >/dev/null 2>&1; then
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

# cognito-gateway GatewayIamRole 에 s3-lambda inline policy 잔존 여부 검증
GATEWAY_ROLE="aiops-demo-${DEMO_USER}-gateway-role"
INVOKE_POLICY_NAME="aiops-demo-${DEMO_USER}-gateway-invoke-s3"
if aws iam list-role-policies --role-name "$GATEWAY_ROLE" \
    --query "PolicyNames" --output text 2>/dev/null | grep -qw "$INVOKE_POLICY_NAME"; then
    fail "GatewayIamRole 에 inline policy '$INVOKE_POLICY_NAME' 잔존 — CFN cleanup 실패. 수동 detach 필요"
else
    log "  ✓ GatewayIamRole 의 inline policy 정상 detach"
fi

log "S3 Lambda + Target teardown 완료"
