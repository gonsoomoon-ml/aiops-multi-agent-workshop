#!/usr/bin/env bash
# infra/s3-lambda/deploy.sh — S3 storage Lambda + Gateway Target (boto3) 배포.
#
# GitHub backend (`infra/github-lambda/deploy.sh`) 의 형제. cognito-gateway alive 가정.
# cognito-gateway stack / Gateway / 기존 Target 미터치.
#
# 본 스크립트가 추가하는 것:
#   - CFN stack (`aiops-demo-${DEMO_USER}-s3-lambda`) — S3 bucket + Lambda + Role + cross-stack policy
#   - data/runbooks/ 의 .md 파일들을 s3://<bucket>/data/runbooks/ 로 sync
#   - Gateway Target `s3-storage` (cognito-gateway Gateway 에 1건 추가)
#
# 사전 prerequisite:
#   - cognito-gateway deploy 완료 (.env 에 GATEWAY_ID 존재)
#   - data/runbooks/*.md 가 repo 에 존재 (seed 대상)
#
# reference:
#   - infra/github-lambda/deploy.sh (형제 backend)
#   - infra/cognito-gateway/deploy.sh (cfn package + setup_gateway 패턴)
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$PROJECT_ROOT/infra/s3-lambda"

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

REGION="${AWS_REGION:-us-east-1}"
DEMO_USER="${DEMO_USER:-${USER:-ubuntu}}"
[[ "$DEMO_USER" =~ ^[a-zA-Z0-9-]{1,16}$ ]] \
    || fail "DEMO_USER='$DEMO_USER' 잘못된 형식 (영문/숫자/하이픈만 ≤16자)"

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
STACK="aiops-demo-${DEMO_USER}-s3-lambda"
DEPLOY_BUCKET="aiops-demo-${DEMO_USER}-deploy-${ACCOUNT_ID}-${REGION}"   # cognito-gateway 와 공유
DATA_DIR="$PROJECT_ROOT/data/runbooks"

log "region=$REGION demo_user=$DEMO_USER account=$ACCOUNT_ID"
log "stack=$STACK / deploy bucket=$DEPLOY_BUCKET (cognito-gateway 와 공유)"

# ── 1. cognito-gateway prerequisite 확인 ──────────
log "cognito-gateway prerequisite 검증"
COGNITO_STACK="aiops-demo-${DEMO_USER}-cognito-gateway"
aws cloudformation describe-stacks --stack-name "$COGNITO_STACK" --region "$REGION" >/dev/null 2>&1 \
    || fail "cognito-gateway stack '$COGNITO_STACK' 미존재 — cognito-gateway deploy 먼저 실행"
[[ -n "${GATEWAY_ID:-}" ]] \
    || fail ".env 에 GATEWAY_ID 미설정 — cognito-gateway setup_gateway.py 출력 캡처 필요"

# ── 2. seed 데이터 존재 확인 ──────────────────────
[[ -d "$DATA_DIR" ]] || fail "data/runbooks/ 디렉토리 미존재 — seed 대상 0건"
SEED_COUNT="$(find "$DATA_DIR" -name "*.md" | wc -l)"
[[ "$SEED_COUNT" -gt 0 ]] || warn "data/runbooks/ 에 .md 0건 — bucket 만 생성, content 없음"

# ── 3. DEPLOY_BUCKET 존재 확인 ────────────────────
aws s3api head-bucket --bucket "$DEPLOY_BUCKET" --region "$REGION" 2>/dev/null \
    || fail "DEPLOY_BUCKET '$DEPLOY_BUCKET' 미존재 — cognito-gateway deploy.sh 가 만들었어야 함"

# ── 4. cfn package ───────────────────────────────
log "cfn package — s3_storage Lambda zip + S3 업로드"
aws cloudformation package \
    --template-file s3_lambda.yaml \
    --s3-bucket "$DEPLOY_BUCKET" \
    --s3-prefix "s3-lambda" \
    --region "$REGION" \
    --output-template-file s3_lambda.packaged.yaml >/dev/null

# ── 5. CFN deploy ────────────────────────────────
log "CFN deploy: $STACK"
aws cloudformation deploy \
    --region "$REGION" \
    --template-file s3_lambda.packaged.yaml \
    --stack-name "$STACK" \
    --capabilities CAPABILITY_NAMED_IAM \
    --parameter-overrides "DemoUser=${DEMO_USER}"

# ── 6. CFN outputs 캡처 ──────────────────────────
log "CFN outputs 캡처"
S3_STORAGE_LAMBDA_ARN="$(aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK" \
    --query "Stacks[0].Outputs[?OutputKey=='S3StorageLambdaArn'].OutputValue" --output text)"
STORAGE_BUCKET_NAME="$(aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK" \
    --query "Stacks[0].Outputs[?OutputKey=='StorageBucketName'].OutputValue" --output text)"
[[ -n "$S3_STORAGE_LAMBDA_ARN" ]] || fail "Lambda ARN 캡처 실패"
[[ -n "$STORAGE_BUCKET_NAME" ]] || fail "Bucket name 캡처 실패"

# ── 7. data/runbooks/ → s3://<bucket>/data/runbooks/ sync ─
log "data/runbooks/ → s3://$STORAGE_BUCKET_NAME/data/runbooks/ sync ($SEED_COUNT 파일)"
aws s3 sync "$DATA_DIR" "s3://$STORAGE_BUCKET_NAME/data/runbooks/" \
    --region "$REGION" --exact-timestamps

# ── 8. boto3 setup — Gateway Target 's3-storage' ──
log "boto3: Gateway Target 's3-storage' 등록"
DEMO_USER="$DEMO_USER" \
AWS_REGION="$REGION" \
GATEWAY_ID="$GATEWAY_ID" \
S3_STORAGE_LAMBDA_ARN="$S3_STORAGE_LAMBDA_ARN" \
    uv run python "$PROJECT_ROOT/infra/s3-lambda/setup_s3_target.py"

# ── 9. .env 갱신 ─────────────────────────────────
log ".env 갱신"
update_env() {
    local key="$1" val="$2"
    if grep -qE "^${key}=" "$PROJECT_ROOT/.env"; then
        sed -i "s|^${key}=.*|${key}=${val}|" "$PROJECT_ROOT/.env"
    else
        echo "${key}=${val}" >> "$PROJECT_ROOT/.env"
    fi
}
update_env S3_STORAGE_LAMBDA_ARN "$S3_STORAGE_LAMBDA_ARN"
update_env STORAGE_BUCKET_NAME   "$STORAGE_BUCKET_NAME"

log "S3 Lambda + Target 배포 완료"
log "  Lambda ARN: $S3_STORAGE_LAMBDA_ARN"
log "  S3 bucket : $STORAGE_BUCKET_NAME"
log "  Gateway Target: s3-storage"
log ""
log "  NOTE: Incident Agent 를 S3 backend 로 향하게 하려면 STORAGE_BACKEND=s3 설정 +"
log "        agents/incident{,_a2a}/runtime/agentcore_runtime.py 의 TOOL_TARGET_PREFIX 가"
log "        env 기반인지 확인 (Phase 4 review 시 점검)."
