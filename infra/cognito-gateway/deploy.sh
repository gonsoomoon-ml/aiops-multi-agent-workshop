#!/usr/bin/env bash
# infra/cognito-gateway/deploy.sh — Cognito + 2 Lambda + IAM (CFN) + Gateway + 2 Target (boto3)
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$PROJECT_ROOT/infra/cognito-gateway"

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'
log()  { echo -e "${GREEN}[deploy]${NC} $1"; }
fail() { echo -e "${RED}[deploy]${NC} $1"; exit 1; }

# ── 사전 검증 ────────────────────────────────────
aws sts get-caller-identity --query Account --output text >/dev/null 2>&1 \
    || fail "AWS 자격증명 미설정"

[[ -f "$PROJECT_ROOT/.env" ]] || fail ".env 미존재. cp .env.example .env 후 재실행"

set -a
source "$PROJECT_ROOT/.env"
set +a

REGION="${AWS_REGION:-us-east-1}"
DEMO_USER="${DEMO_USER:-${USER:-ubuntu}}"
[[ "$DEMO_USER" =~ ^[a-zA-Z0-9-]{1,16}$ ]] \
    || fail "DEMO_USER='$DEMO_USER' 잘못된 형식 (영문/숫자/하이픈만 ≤16자)"

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
STACK="aiops-demo-${DEMO_USER}-cognito-gateway"
DEPLOY_BUCKET="aiops-demo-${DEMO_USER}-deploy-${ACCOUNT_ID}-${REGION}"

log "region=$REGION demo_user=$DEMO_USER account=$ACCOUNT_ID"
log "stack=$STACK / deploy bucket=$DEPLOY_BUCKET"

# ── 0. DEPLOY_BUCKET 보장 (idempotent) ───────────
if ! aws s3api head-bucket --bucket "$DEPLOY_BUCKET" --region "$REGION" 2>/dev/null; then
    log "DEPLOY_BUCKET 생성: s3://$DEPLOY_BUCKET"
    aws s3 mb "s3://$DEPLOY_BUCKET" --region "$REGION"
    aws s3api put-public-access-block --bucket "$DEPLOY_BUCKET" \
        --public-access-block-configuration "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"
else
    log "DEPLOY_BUCKET 이미 존재 (재사용)"
fi

# ── 1. data/mock 복사 (Lambda zip 에 포함) ───────
DATA_DIR="$PROJECT_ROOT/infra/cognito-gateway/lambda/history_mock/data"
COPY_DIR="$DATA_DIR/mock"
log "data/mock/phase1 → Lambda 디렉토리 복사"
rm -rf "$DATA_DIR"
mkdir -p "$COPY_DIR"
touch "$DATA_DIR/__init__.py"          # data/ Python package
touch "$COPY_DIR/__init__.py"          # data/mock/ Python package
cp -r "$PROJECT_ROOT/data/mock/phase1" "$COPY_DIR/phase1"

# ── 2. cfn package (Lambda Code 디렉토리 zip + S3 업로드) ─
log "cfn package — Lambda Code 디렉토리 zip + S3 업로드"
aws cloudformation package \
    --template-file "$PROJECT_ROOT/infra/cognito-gateway/cognito.yaml" \
    --s3-bucket "$DEPLOY_BUCKET" \
    --s3-prefix "cognito-gateway" \
    --region "$REGION" \
    --output-template-file "$PROJECT_ROOT/infra/cognito-gateway/cognito.packaged.yaml" >/dev/null

# ── 3. CFN deploy (Cognito + Lambda + IAM 통합) ──
log "CFN deploy: $STACK"
aws cloudformation deploy \
    --region "$REGION" \
    --template-file "$PROJECT_ROOT/infra/cognito-gateway/cognito.packaged.yaml" \
    --stack-name "$STACK" \
    --capabilities CAPABILITY_NAMED_IAM \
    --parameter-overrides "DemoUser=${DEMO_USER}"

# ── 4. CFN outputs 환경변수 export ──────────────
log "CFN outputs 캡처"
get_output() {
    aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK" \
        --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}
export COGNITO_USER_POOL_ID="$(get_output UserPoolId)"
export COGNITO_DOMAIN="$(get_output Domain)"
export COGNITO_CLIENT_ID="$(get_output ClientId)"
export COGNITO_GATEWAY_SCOPE="$(get_output ResourceServerScope)"
export GATEWAY_IAM_ROLE_ARN="$(get_output GatewayIamRoleArn)"
export LAMBDA_HISTORY_MOCK_ARN="$(get_output LambdaHistoryMockArn)"
export LAMBDA_CLOUDWATCH_WRAPPER_ARN="$(get_output LambdaCloudWatchWrapperArn)"

# Cognito Client Secret 별도 조회 (CFN output 미노출)
export COGNITO_CLIENT_SECRET="$(aws cognito-idp describe-user-pool-client \
    --region "$REGION" \
    --user-pool-id "$COGNITO_USER_POOL_ID" \
    --client-id "$COGNITO_CLIENT_ID" \
    --query 'UserPoolClient.ClientSecret' --output text)"

# ── 5. boto3 setup — Gateway + 2 Target ─────────
log "boto3: Gateway + GatewayTarget × 2 생성"
TMP_OUT="$(mktemp)"
trap 'rm -f "$TMP_OUT"' EXIT
DEMO_USER="$DEMO_USER" AWS_REGION="$REGION" \
    uv run python "$PROJECT_ROOT/infra/cognito-gateway/setup_gateway.py" \
    | tee "$TMP_OUT"

GATEWAY_ID="$(grep '^GATEWAY_ID=' "$TMP_OUT" | cut -d= -f2-)"
GATEWAY_URL="$(grep '^GATEWAY_URL=' "$TMP_OUT" | cut -d= -f2-)"
[[ -n "$GATEWAY_ID" && -n "$GATEWAY_URL" ]] \
    || fail "setup_gateway.py 출력에서 GATEWAY_ID/URL 캡처 실패"

# ── 6. .env 갱신 ─────────────────────────────────
log ".env 갱신"
update_env() {
    local key="$1" val="$2"
    if grep -qE "^${key}=" "$PROJECT_ROOT/.env"; then
        # | 가 값에 들어갈 가능성 낮음 — sed 구분자로 사용
        sed -i "s|^${key}=.*|${key}=${val}|" "$PROJECT_ROOT/.env"
    else
        echo "${key}=${val}" >> "$PROJECT_ROOT/.env"
    fi
}
update_env COGNITO_USER_POOL_ID         "$COGNITO_USER_POOL_ID"
update_env COGNITO_DOMAIN               "$COGNITO_DOMAIN"
update_env COGNITO_CLIENT_ID          "$COGNITO_CLIENT_ID"
update_env COGNITO_CLIENT_SECRET      "$COGNITO_CLIENT_SECRET"
update_env COGNITO_GATEWAY_SCOPE        "$COGNITO_GATEWAY_SCOPE"
update_env GATEWAY_ID                   "$GATEWAY_ID"
update_env GATEWAY_URL                  "$GATEWAY_URL"
update_env LAMBDA_HISTORY_MOCK_ARN      "$LAMBDA_HISTORY_MOCK_ARN"
update_env LAMBDA_CLOUDWATCH_WRAPPER_ARN "$LAMBDA_CLOUDWATCH_WRAPPER_ARN"

log "Phase 2 deploy 완료"
log "  Gateway URL: $GATEWAY_URL"
log "  Lambda (history_mock):  $LAMBDA_HISTORY_MOCK_ARN"
log "  Lambda (cloudwatch):    $LAMBDA_CLOUDWATCH_WRAPPER_ARN"
log "  검증: acceptance criteria (docs/design/phase2.md §8)"
