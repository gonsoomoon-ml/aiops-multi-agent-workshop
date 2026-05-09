#!/usr/bin/env bash
# infra/phase6a/deploy.sh — Phase 6a infra 배포 (Option X — no new Cognito).
#
# Phase 0/2/3/4 자원 미터치 + 새 Cognito 자원 추가 0 (Option X). Phase 4 의 GitHub PAT
# (`/aiops-demo/github-token`) 재사용 (단 'repo' full scope 필요 — incidents/ append).
#
# 배포 순서:
#   1. deployments_lambda CFN stack (Lambda + Role + cross-stack policy)
#   2. setup_deployments_target.py (boto3 — Gateway Target 추가)
#   3. .env 갱신 (DEPLOYMENTS_STORAGE_LAMBDA_ARN)
#
# reference: infra/phase4/deploy.sh (cfn package + boto3 setup 패턴 정확 차용)
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$PROJECT_ROOT/infra/phase6a"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'
log()  { echo -e "${GREEN}[deploy]${NC} $1"; }
warn() { echo -e "${YELLOW}[deploy]${NC} $1"; }
fail() { echo -e "${RED}[deploy]${NC} $1"; exit 1; }

# ── 사전 검증 ─────────────────────────────────────
aws sts get-caller-identity --query Account --output text >/dev/null 2>&1 \
    || fail "AWS 자격증명 미설정"

[[ -f "$PROJECT_ROOT/.env" ]] || fail ".env 미존재"
set -a; source "$PROJECT_ROOT/.env"; set +a

REGION="${AWS_REGION:-us-west-2}"
DEMO_USER="${DEMO_USER:-${USER:-ubuntu}}"
[[ "$DEMO_USER" =~ ^[a-zA-Z0-9-]{1,16}$ ]] \
    || fail "DEMO_USER='$DEMO_USER' 잘못된 형식"

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
LAMBDA_STACK="aiops-demo-${DEMO_USER}-phase6a-deployments"
DEPLOY_BUCKET="aiops-demo-${DEMO_USER}-deploy-${ACCOUNT_ID}-${REGION}"

log "region=$REGION demo_user=$DEMO_USER account=$ACCOUNT_ID"
log "lambda stack:  $LAMBDA_STACK"

# ── 1. Phase 0/2/4 prerequisite 확인 ──────────────
log "Phase 2/4 prerequisite 검증"
PHASE2_STACK="aiops-demo-${DEMO_USER}-phase2-cognito"
PHASE4_STACK="aiops-demo-${DEMO_USER}-phase4-github"
aws cloudformation describe-stacks --stack-name "$PHASE2_STACK" --region "$REGION" >/dev/null 2>&1 \
    || fail "Phase 2 stack '$PHASE2_STACK' 미존재"
aws cloudformation describe-stacks --stack-name "$PHASE4_STACK" --region "$REGION" >/dev/null 2>&1 \
    || warn "Phase 4 stack '$PHASE4_STACK' 미존재 — Phase 6a 자체는 진행 가능, 단 incident_a2a runtime 의 github-storage tool 호출 시 영향"
[[ -n "${GATEWAY_ID:-}" ]] || fail ".env 에 GATEWAY_ID 미설정"
[[ -n "${COGNITO_CLIENT_C_ID:-}" ]] || fail ".env 에 COGNITO_CLIENT_C_ID 미설정 (Phase 2 deploy 산출물)"

SSM_PATH="${GITHUB_TOKEN_SSM_PATH:-/aiops-demo/github-token}"
aws ssm get-parameter --name "$SSM_PATH" --region "$REGION" --with-decryption >/dev/null 2>&1 \
    || fail "SSM '$SSM_PATH' 미설정"

aws s3api head-bucket --bucket "$DEPLOY_BUCKET" --region "$REGION" 2>/dev/null \
    || fail "DEPLOY_BUCKET '$DEPLOY_BUCKET' 미존재 (Phase 2 가 만든 bucket 재사용)"

# ── 2. CFN package + deploy: deployments_lambda ──
log "[1/3] CFN package + deploy: $LAMBDA_STACK"
aws cloudformation package \
    --template-file deployments_lambda.yaml \
    --s3-bucket "$DEPLOY_BUCKET" \
    --s3-prefix "phase6a-deployments" \
    --region "$REGION" \
    --output-template-file deployments_lambda.packaged.yaml >/dev/null

aws cloudformation deploy \
    --region "$REGION" \
    --template-file deployments_lambda.packaged.yaml \
    --stack-name "$LAMBDA_STACK" \
    --capabilities CAPABILITY_NAMED_IAM \
    --parameter-overrides "DemoUser=${DEMO_USER}"

DEPLOYMENTS_STORAGE_LAMBDA_ARN="$(aws cloudformation describe-stacks --region "$REGION" --stack-name "$LAMBDA_STACK" \
    --query "Stacks[0].Outputs[?OutputKey=='DeploymentsStorageLambdaArn'].OutputValue" --output text)"
[[ -n "$DEPLOYMENTS_STORAGE_LAMBDA_ARN" ]] || fail "Lambda ARN 캡처 실패"
log "  ✓ Lambda ARN: $DEPLOYMENTS_STORAGE_LAMBDA_ARN"

# ── 3. boto3 setup — Gateway Target ───────────────
log "[2/3] boto3: Gateway Target 'deployments-storage' 등록"
DEMO_USER="$DEMO_USER" \
AWS_REGION="$REGION" \
GATEWAY_ID="$GATEWAY_ID" \
DEPLOYMENTS_STORAGE_LAMBDA_ARN="$DEPLOYMENTS_STORAGE_LAMBDA_ARN" \
    uv run python "$PROJECT_ROOT/infra/phase6a/setup_deployments_target.py"

# ── 4. .env 갱신 ─────────────────────────────────
log "[3/3] .env 갱신"
update_env() {
    local key="$1" val="$2"
    if grep -qE "^${key}=" "$PROJECT_ROOT/.env"; then
        sed -i "s|^${key}=.*|${key}=${val}|" "$PROJECT_ROOT/.env"
    else
        echo "${key}=${val}" >> "$PROJECT_ROOT/.env"
    fi
}
update_env DEPLOYMENTS_STORAGE_LAMBDA_ARN "$DEPLOYMENTS_STORAGE_LAMBDA_ARN"

log ""
log "Phase 6a infra 배포 완료 (Option X — no new Cognito)"
log "  Lambda ARN:        $DEPLOYMENTS_STORAGE_LAMBDA_ARN"
log "  Gateway Target:    deployments-storage"
log "  Auth (sub-agents): Phase 2 Client C 재사용 (allowedClients=[$COGNITO_CLIENT_C_ID])"
log "  Auth (operator):   SigV4 IAM (Phase 4 패턴)"
log ""
log "다음 단계:"
log "  1. Phase 6a Step B Runtime 배포 (4 agents):"
log "     uv run agents/change/runtime/deploy_runtime.py"
log "     uv run agents/monitor_a2a/runtime/deploy_runtime.py"
log "     uv run agents/incident_a2a/runtime/deploy_runtime.py"
log "     uv run agents/supervisor/runtime/deploy_runtime.py"
log "  2. End-to-end smoke (Operator CLI):"
log "     python agents/operator/cli.py --query \"현재 상황 진단해줘\""
