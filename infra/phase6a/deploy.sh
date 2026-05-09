#!/usr/bin/env bash
# infra/phase6a/deploy.sh — Phase 6a infra 배포.
#
# 배치 순서:
#   1. cognito_extras stack (Cognito Client A + B + OperatorUser + 새 ResourceServer)
#   2. cognito client_secret 캡처 + admin_set_user_password (boto3, deploy.sh 안에서)
#   3. deployments_lambda stack (Lambda + Role + cross-stack policy)
#   4. setup_deployments_target.py (boto3 — Gateway Target 추가)
#   5. .env 갱신 (COGNITO_CLIENT_A/B_*, DEPLOYMENTS_STORAGE_LAMBDA_ARN, OPERATOR_USERNAME)
#   6. .env.operator 작성 (OPERATOR_PASSWORD 별 파일, gitignored)
#
# Phase 0/2/3/4 자원 미터치. Phase 4 의 GitHub PAT (`/aiops-demo/github-token`) 재사용
# (단 'repo' full scope 필요 — incidents/ append).
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
COGNITO_STACK="aiops-demo-${DEMO_USER}-phase6a-cognito-extras"
LAMBDA_STACK="aiops-demo-${DEMO_USER}-phase6a-deployments"
DEPLOY_BUCKET="aiops-demo-${DEMO_USER}-deploy-${ACCOUNT_ID}-${REGION}"

log "region=$REGION demo_user=$DEMO_USER account=$ACCOUNT_ID"
log "cognito stack:  $COGNITO_STACK"
log "lambda stack:   $LAMBDA_STACK"

# ── 1. Phase 0/2/4 prerequisite 확인 ──────────────
log "Phase 2/4 prerequisite 검증"
PHASE2_STACK="aiops-demo-${DEMO_USER}-phase2-cognito"
PHASE4_STACK="aiops-demo-${DEMO_USER}-phase4-github"
aws cloudformation describe-stacks --stack-name "$PHASE2_STACK" --region "$REGION" >/dev/null 2>&1 \
    || fail "Phase 2 stack '$PHASE2_STACK' 미존재"
aws cloudformation describe-stacks --stack-name "$PHASE4_STACK" --region "$REGION" >/dev/null 2>&1 \
    || warn "Phase 4 stack '$PHASE4_STACK' 미존재 — Phase 6a 자체는 진행 가능, 단 incident_a2a runtime 의 github-storage tool 호출 시 영향"
[[ -n "${GATEWAY_ID:-}" ]] || fail ".env 에 GATEWAY_ID 미설정"

SSM_PATH="${GITHUB_TOKEN_SSM_PATH:-/aiops-demo/github-token}"
aws ssm get-parameter --name "$SSM_PATH" --region "$REGION" --with-decryption >/dev/null 2>&1 \
    || fail "SSM '$SSM_PATH' 미설정"

aws s3api head-bucket --bucket "$DEPLOY_BUCKET" --region "$REGION" 2>/dev/null \
    || fail "DEPLOY_BUCKET '$DEPLOY_BUCKET' 미존재 (Phase 2 가 만든 bucket 재사용)"

# ── 2. Phase 2 의 UserPoolId query ───────────────
log "Phase 2 cognito stack 에서 UserPoolId / Domain query"
USER_POOL_ID="$(aws cloudformation describe-stacks --region "$REGION" --stack-name "$PHASE2_STACK" \
    --query "Stacks[0].Outputs[?OutputKey=='UserPoolId'].OutputValue" --output text)"
COGNITO_DOMAIN="$(aws cloudformation describe-stacks --region "$REGION" --stack-name "$PHASE2_STACK" \
    --query "Stacks[0].Outputs[?OutputKey=='Domain'].OutputValue" --output text)"
[[ -n "$USER_POOL_ID" ]] || fail "Phase 2 UserPoolId query 실패"
log "  UserPoolId: $USER_POOL_ID"
log "  Domain:     $COGNITO_DOMAIN"

# ── 3. Operator email 결정 ────────────────────────
# 우선순위: env OPERATOR_USER_EMAIL > git config user.email > 합성 placeholder
OPERATOR_EMAIL="${OPERATOR_USER_EMAIL:-}"
if [[ -z "$OPERATOR_EMAIL" ]]; then
    OPERATOR_EMAIL="$(git config --global user.email 2>/dev/null || echo "")"
fi
if [[ -z "$OPERATOR_EMAIL" ]]; then
    OPERATOR_EMAIL="${DEMO_USER}@aiops-demo.local"
    warn "  OPERATOR_USER_EMAIL 미설정 + git user.email 미설정 → placeholder '$OPERATOR_EMAIL' 사용 (alert 발송 안 함)"
fi
log "  Operator email: $OPERATOR_EMAIL"

# ── 4. CFN deploy: cognito_extras ─────────────────
log "[1/4] CFN deploy: $COGNITO_STACK (Cognito Client A + B + OperatorUser)"
aws cloudformation deploy \
    --region "$REGION" \
    --template-file cognito_extras.yaml \
    --stack-name "$COGNITO_STACK" \
    --capabilities CAPABILITY_NAMED_IAM \
    --parameter-overrides \
        "DemoUser=${DEMO_USER}" \
        "UserPoolId=${USER_POOL_ID}" \
        "OperatorUserEmail=${OPERATOR_EMAIL}"

CLIENT_A_ID="$(aws cloudformation describe-stacks --region "$REGION" --stack-name "$COGNITO_STACK" \
    --query "Stacks[0].Outputs[?OutputKey=='ClientAId'].OutputValue" --output text)"
CLIENT_B_ID="$(aws cloudformation describe-stacks --region "$REGION" --stack-name "$COGNITO_STACK" \
    --query "Stacks[0].Outputs[?OutputKey=='ClientBId'].OutputValue" --output text)"
AGENT_INVOKE_SCOPE="$(aws cloudformation describe-stacks --region "$REGION" --stack-name "$COGNITO_STACK" \
    --query "Stacks[0].Outputs[?OutputKey=='AgentInvokeScope'].OutputValue" --output text)"
OPERATOR_USERNAME="$(aws cloudformation describe-stacks --region "$REGION" --stack-name "$COGNITO_STACK" \
    --query "Stacks[0].Outputs[?OutputKey=='OperatorUserName'].OutputValue" --output text)"

# ── 5. Cognito client_secret 캡처 (Client B 만 — A 는 GenerateSecret:false) ─
log "  Client B secret 조회 (boto3)"
CLIENT_B_SECRET="$(aws cognito-idp describe-user-pool-client \
    --region "$REGION" \
    --user-pool-id "$USER_POOL_ID" \
    --client-id "$CLIENT_B_ID" \
    --query "UserPoolClient.ClientSecret" --output text)"
[[ -n "$CLIENT_B_SECRET" && "$CLIENT_B_SECRET" != "None" ]] || fail "Client B secret 조회 실패"
log "  ✓ Client A: $CLIENT_A_ID (no secret)"
log "  ✓ Client B: $CLIENT_B_ID (secret captured)"

# ── 6. Operator 비밀번호 설정 (admin_set_user_password) ─
log "[2/4] Operator user 비밀번호 설정"
OPERATOR_PASSWORD="$(openssl rand -base64 16 | tr -d '/+=' | head -c 20)Aa1!"  # complexity 보강
aws cognito-idp admin-set-user-password \
    --region "$REGION" \
    --user-pool-id "$USER_POOL_ID" \
    --username "$OPERATOR_USERNAME" \
    --password "$OPERATOR_PASSWORD" \
    --permanent
log "  ✓ Permanent password set for $OPERATOR_USERNAME"

# ── 7. CFN package + deploy: deployments_lambda ──
log "[3/4] CFN package + deploy: $LAMBDA_STACK"
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

# ── 8. boto3 setup — Gateway Target ───────────────
log "[4/4] boto3: Gateway Target 'deployments-storage' 등록"
DEMO_USER="$DEMO_USER" \
AWS_REGION="$REGION" \
GATEWAY_ID="$GATEWAY_ID" \
DEPLOYMENTS_STORAGE_LAMBDA_ARN="$DEPLOYMENTS_STORAGE_LAMBDA_ARN" \
    uv run python "$PROJECT_ROOT/infra/phase6a/setup_deployments_target.py"

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
update_env COGNITO_USER_POOL_ID "$USER_POOL_ID"
update_env COGNITO_DOMAIN "$COGNITO_DOMAIN"
update_env COGNITO_CLIENT_A_ID "$CLIENT_A_ID"
update_env COGNITO_CLIENT_B_ID "$CLIENT_B_ID"
update_env COGNITO_CLIENT_B_SECRET "$CLIENT_B_SECRET"
update_env COGNITO_AGENT_INVOKE_SCOPE "$AGENT_INVOKE_SCOPE"
update_env OPERATOR_USERNAME "$OPERATOR_USERNAME"
update_env DEPLOYMENTS_STORAGE_LAMBDA_ARN "$DEPLOYMENTS_STORAGE_LAMBDA_ARN"

# ── 10. .env.operator 작성 (gitignored) ───────────
OPERATOR_ENV_FILE="$PROJECT_ROOT/.env.operator"
cat > "$OPERATOR_ENV_FILE" <<EOF
# Phase 6a — Operator user credentials (gitignored)
# Operator CLI (Phase 6a Step D) 가 본 파일 read.
# 이 파일은 git 추적 안 됨 (.gitignore '.env*'). 워크샵 청중 본인의 비밀번호.
OPERATOR_USERNAME=$OPERATOR_USERNAME
OPERATOR_PASSWORD=$OPERATOR_PASSWORD
EOF
chmod 600 "$OPERATOR_ENV_FILE"
log "  ✓ .env.operator 작성 (chmod 600)"

log ""
log "Phase 6a infra 배포 완료"
log "  Cognito Client A:  $CLIENT_A_ID  (operator USER_PASSWORD_AUTH)"
log "  Cognito Client B:  $CLIENT_B_ID  (Supervisor M2M)"
log "  Operator user:     $OPERATOR_USERNAME  (password in .env.operator)"
log "  Lambda ARN:        $DEPLOYMENTS_STORAGE_LAMBDA_ARN"
log "  Gateway Target:    deployments-storage"
log ""
log "다음 단계:"
log "  1. Phase 6a Step B Runtime 배포 (4 agents):"
log "     uv run agents/change/runtime/deploy_runtime.py"
log "     uv run agents/monitor_a2a/runtime/deploy_runtime.py"
log "     uv run agents/incident_a2a/runtime/deploy_runtime.py"
log "     uv run agents/supervisor/runtime/deploy_runtime.py"
log "  2. Phase 6a Step E (deployments/ seed content)"
log "  3. Phase 6a Step D (Operator CLI) — end-to-end smoke"
