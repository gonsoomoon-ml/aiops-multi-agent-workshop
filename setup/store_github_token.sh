#!/usr/bin/env bash
set -euo pipefail

# AIOps Demo — GitHub PAT를 AWS SSM Parameter Store SecureString에 저장
# 5단계: AWS creds → IAM 권한 → 토큰 입력 → SSM 저장 → readback + GitHub API 검증

PARAM_NAME="${GITHUB_TOKEN_SSM_PATH:-/aiops-demo/github-token}"

# ── 색상 ──────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

pass() { echo -e "${GREEN}[통과]${NC} $1"; }
fail() { echo -e "${RED}[실패]${NC} $1"; exit 1; }
warn() { echo -e "${YELLOW}[주의]${NC} $1"; }
info() { echo -e "       $1"; }

# ── 단계 1/5: AWS 자격 증명 ───────────────────────
echo ""
echo "=== 단계 1/5: AWS 자격 증명 확인 ==="
if ! identity=$(aws sts get-caller-identity --output json 2>&1); then
    fail "AWS 자격 증명 미설정. 'aws configure' 먼저 실행하세요."
fi

account=$(echo "$identity" | python3 -c "import sys,json; print(json.load(sys.stdin)['Account'])")
arn=$(echo "$identity" | python3 -c "import sys,json; print(json.load(sys.stdin)['Arn'])")
pass "인증: $arn (계정 $account)"

# ── 단계 2/5: IAM 권한 ────────────────────────────
echo ""
echo "=== 단계 2/5: IAM 권한 확인 ==="

# ssm:GetParameter (이미 존재 시) or 권한 확인
if aws ssm get-parameter --name "$PARAM_NAME" --with-decryption >/dev/null 2>&1; then
    pass "ssm:GetParameter + kms:Decrypt (파라미터 이미 존재 — overwrite 됩니다)"
else
    error_msg=$(aws ssm get-parameter --name "$PARAM_NAME" --with-decryption 2>&1 || true)
    if echo "$error_msg" | grep -q "ParameterNotFound"; then
        pass "ssm:GetParameter 권한 OK (파라미터 미생성)"
    elif echo "$error_msg" | grep -q "AccessDenied"; then
        fail "권한 부족. 필요 권한:
       - ssm:GetParameter
       - ssm:PutParameter
       - kms:Encrypt / Decrypt (SecureString)"
    else
        warn "ssm:GetParameter — 예상치 못한 응답 — 계속 진행"
        info "$error_msg"
    fi
fi

# ── 단계 3/5: 토큰 입력 ───────────────────────────
echo ""
echo "=== 단계 3/5: GitHub PAT 입력 ==="

if [[ "${1:-}" == "--token" && -n "${2:-}" ]]; then
    token="$2"
    info "--token 인자에서 토큰 수신"
else
    echo -n "GitHub Personal Access Token (ghp_... / ghs_...): "
    read -rs token
    echo ""
fi

if [[ -z "$token" ]]; then
    fail "토큰이 비어있음"
fi

if [[ ! "$token" =~ ^gh[ps]_ ]]; then
    warn "토큰이 'ghp_' 또는 'ghs_'로 시작하지 않음 — 진짜 GitHub PAT인가요?"
fi

pass "토큰 수신 (${#token}자)"

# ── 단계 4/5: SSM 저장 ────────────────────────────
echo ""
echo "=== 단계 4/5: SSM Parameter Store 저장 ==="

if aws ssm put-parameter \
    --name "$PARAM_NAME" \
    --type SecureString \
    --value "$token" \
    --overwrite \
    --tags "Key=Project,Value=aiops-demo" \
    --output json >/dev/null 2>&1; then
    pass "SecureString 저장 완료: $PARAM_NAME"
else
    # --tags는 첫 생성 시만 — 이미 존재 시 재시도 (--tags 없이)
    if aws ssm put-parameter \
        --name "$PARAM_NAME" \
        --type SecureString \
        --value "$token" \
        --overwrite \
        --output json >/dev/null 2>&1; then
        pass "SecureString 갱신 완료: $PARAM_NAME"
    else
        fail "저장 실패. ssm:PutParameter / kms:Encrypt 권한 확인"
    fi
fi

# ── 단계 5/5: 검증 ────────────────────────────────
echo ""
echo "=== 단계 5/5: 검증 ==="

# 5a: SSM readback
readback=$(aws ssm get-parameter \
    --name "$PARAM_NAME" \
    --with-decryption \
    --query "Parameter.Value" \
    --output text 2>&1) || fail "SSM readback 실패"

if [[ "$readback" == "$token" ]]; then
    pass "SSM readback 일치"
else
    fail "SSM readback 값이 저장값과 불일치"
fi

# 5b: GitHub API 인증 확인
echo ""
github_user=$(curl -sf -H "Authorization: Bearer $token" \
    -H "Accept: application/vnd.github+json" \
    https://api.github.com/user 2>&1) || fail "GitHub API 호출 실패. 토큰 유효성 확인"

username=$(echo "$github_user" | python3 -c "import sys,json; print(json.load(sys.stdin).get('login',''))" 2>/dev/null)

if [[ -n "$username" ]]; then
    pass "GitHub 인증 — 사용자: $username"
else
    fail "GitHub API 응답 비정상"
fi

echo ""
echo -e "${GREEN}=== 5단계 모두 통과 ===${NC}"
echo ""
info "토큰이 SSM에 안전하게 저장됨: $PARAM_NAME"
info "Lambda / Agent에서 boto3로 GetParameter(WithDecryption=True)로 읽음"
echo ""
