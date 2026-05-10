#!/usr/bin/env bash
# infra/github-lambda/deploy.sh — GitHub Lambda CFN + Gateway Target (boto3) 배포.
#
# Phase 2 + Phase 3 가 alive 라고 가정. Phase 2 stack / Gateway / 기존 2 Target 미터치.
# 본 스크립트가 추가하는 것:
#   - Phase 4 CFN stack (`aiops-demo-${DEMO_USER}-github-lambda`) — Lambda + Role + cross-stack policy
#   - Gateway Target `github-storage` (Phase 2 Gateway 에 1건 추가)
#
# 사전 prerequisite (별도):
#   - SSM SecureString `/aiops-demo/github-token` 에 GitHub PAT (repo:read scope) 저장
#       aws ssm put-parameter --name /aiops-demo/github-token --type SecureString \
#           --value "$GITHUB_TOKEN" --overwrite
#
# reference:
#   - infra/cognito-gateway/deploy.sh (cfn package + setup_gateway 패턴)
#   - docs/design/phase4.md §6-2 (smoke test 절차)
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$PROJECT_ROOT/infra/github-lambda"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'
log()  { echo -e "${GREEN}[deploy]${NC} $1"; }
warn() { echo -e "${YELLOW}[deploy]${NC} $1"; }
fail() { echo -e "${RED}[deploy]${NC} $1"; exit 1; }

# ── 사전 검증 ────────────────────────────────────
aws sts get-caller-identity --query Account --output text >/dev/null 2>&1 \
    || fail "AWS 자격증명 미설정"

[[ -f "$PROJECT_ROOT/.env" ]] || fail ".env 미존재"

set -a
source "$PROJECT_ROOT/.env"
set +a

REGION="${AWS_REGION:-us-west-2}"
DEMO_USER="${DEMO_USER:-${USER:-ubuntu}}"
[[ "$DEMO_USER" =~ ^[a-zA-Z0-9-]{1,16}$ ]] \
    || fail "DEMO_USER='$DEMO_USER' 잘못된 형식 (영문/숫자/하이픈만 ≤16자)"

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
STACK="aiops-demo-${DEMO_USER}-github-lambda"
DEPLOY_BUCKET="aiops-demo-${DEMO_USER}-deploy-${ACCOUNT_ID}-${REGION}"   # Phase 2 와 공유

log "region=$REGION demo_user=$DEMO_USER account=$ACCOUNT_ID"
log "stack=$STACK / deploy bucket=$DEPLOY_BUCKET (Phase 2 와 공유)"

# ── 1. Phase 2/3 prerequisite 확인 ───────────────
log "Phase 2/3 prerequisite 검증"
PHASE2_STACK="aiops-demo-${DEMO_USER}-cognito-gateway"
aws cloudformation describe-stacks --stack-name "$PHASE2_STACK" --region "$REGION" >/dev/null 2>&1 \
    || fail "Phase 2 stack '$PHASE2_STACK' 미존재 — Phase 2 deploy 먼저 실행"
[[ -n "${GATEWAY_ID:-}" ]] \
    || fail ".env 에 GATEWAY_ID 미설정 — Phase 2 setup_gateway.py 출력 캡처 필요"

# SSM token 존재 확인 (값은 안 보이게)
SSM_PATH="${GITHUB_TOKEN_SSM_PATH:-/aiops-demo/github-token}"
aws ssm get-parameter --name "$SSM_PATH" --region "$REGION" --with-decryption >/dev/null 2>&1 \
    || fail "SSM '$SSM_PATH' 미설정 — README 의 prerequisite 절차 (aws ssm put-parameter --name $SSM_PATH ...) 먼저 실행"

# ── 2. DEPLOY_BUCKET 존재 확인 (Phase 2 가 만든 bucket 재사용) ─
aws s3api head-bucket --bucket "$DEPLOY_BUCKET" --region "$REGION" 2>/dev/null \
    || fail "DEPLOY_BUCKET '$DEPLOY_BUCKET' 미존재 — Phase 2 deploy.sh 가 만들었어야 함"

# ── 3. cfn package (Lambda Code 디렉토리 → S3 업로드) ─
log "cfn package — github_storage Lambda zip + S3 업로드"
aws cloudformation package \
    --template-file github_lambda.yaml \
    --s3-bucket "$DEPLOY_BUCKET" \
    --s3-prefix "github-lambda" \
    --region "$REGION" \
    --output-template-file github_lambda.packaged.yaml >/dev/null

# ── 4. CFN deploy (Lambda + Role + cross-stack policy) ──
log "CFN deploy: $STACK"
aws cloudformation deploy \
    --region "$REGION" \
    --template-file github_lambda.packaged.yaml \
    --stack-name "$STACK" \
    --capabilities CAPABILITY_NAMED_IAM \
    --parameter-overrides "DemoUser=${DEMO_USER}"

# ── 5. CFN outputs 캡처 ──────────────────────────
log "CFN outputs 캡처"
GITHUB_STORAGE_LAMBDA_ARN="$(aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK" \
    --query "Stacks[0].Outputs[?OutputKey=='GithubStorageLambdaArn'].OutputValue" --output text)"
[[ -n "$GITHUB_STORAGE_LAMBDA_ARN" ]] || fail "Lambda ARN 캡처 실패"

# ── 6. boto3 setup — Gateway Target 'github-storage' ──
log "boto3: Gateway Target 'github-storage' 등록"
DEMO_USER="$DEMO_USER" \
AWS_REGION="$REGION" \
GATEWAY_ID="$GATEWAY_ID" \
GITHUB_STORAGE_LAMBDA_ARN="$GITHUB_STORAGE_LAMBDA_ARN" \
    uv run python "$PROJECT_ROOT/infra/github-lambda/setup_github_target.py"

# ── 7. .env 갱신 ─────────────────────────────────
log ".env 갱신"
update_env() {
    local key="$1" val="$2"
    if grep -qE "^${key}=" "$PROJECT_ROOT/.env"; then
        sed -i "s|^${key}=.*|${key}=${val}|" "$PROJECT_ROOT/.env"
    else
        echo "${key}=${val}" >> "$PROJECT_ROOT/.env"
    fi
}
update_env GITHUB_STORAGE_LAMBDA_ARN "$GITHUB_STORAGE_LAMBDA_ARN"

log "Phase 4 GitHub Lambda + Target 배포 완료"
log "  Lambda ARN: $GITHUB_STORAGE_LAMBDA_ARN"
log "  Gateway Target: github-storage"
log "  검증: P4-A4 (Incident invoke 시 runbook content 응답 포함)"
