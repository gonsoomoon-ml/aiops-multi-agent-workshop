#!/usr/bin/env bash
set -euo pipefail

# ── 색상 ──────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

pass() { echo -e "${GREEN}[완료]${NC} $1"; }
fail() { echo -e "${RED}[실패]${NC} $1"; exit 1; }
info() { echo -e "${BLUE}[정보]${NC} $1"; }
warn() { echo -e "${YELLOW}[건너뜀]${NC} $1"; }

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_ROOT"

echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  AIOps Multi-Agent Demo — 부트스트랩${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# ── 단계 1: 의존성 + AWS 자격증명 ─────────────────
echo "=== 단계 1/5: Python 의존성 (uv sync) + AWS 자격증명 ==="

if ! command -v uv &>/dev/null; then
    fail "'uv'를 찾을 수 없습니다. 설치: curl -LsSf https://astral.sh/uv/install.sh | sh"
fi

aws sts get-caller-identity --query Account --output text >/dev/null 2>&1 \
    || fail "AWS 자격증명 미설정. 'aws configure' 또는 'export AWS_PROFILE=...' 후 재실행"

uv sync
pass "의존성 설치 완료"
pass "AWS 자격증명 검증 완료"
echo ""

# ── 단계 2: .env ──────────────────────────────────
echo "=== 단계 2/5: .env 파일 ==="

if [[ -f .env ]]; then
    warn ".env 이미 존재 (덮어쓰지 않음 — 기존 값 유지)"
else
    cp .env.example .env
    pass ".env 생성 완료"
fi
echo ""

# 헬퍼: .env entry 가 있으면 sed 갱신, 없으면 append (단계 3-4 공통)
update_env() {
    local key="$1" val="$2"
    if grep -q "^${key}=" .env 2>/dev/null; then
        sed -i "s|^${key}=.*|${key}=${val}|" .env
    else
        echo "${key}=${val}" >> .env
    fi
}

# 헬퍼: .env 에서 기존 값 추출 (없으면 빈 문자열). set -e + pipefail 안전.
read_env() {
    grep "^$1=" .env 2>/dev/null | head -1 | cut -d= -f2- || echo ""
}

# ── 단계 3: AWS_REGION + DEMO_USER ────────────────
echo "=== 단계 3/5: AWS_REGION + DEMO_USER ==="

# AWS_REGION (기존 .env 값 우선 → us-east-1 fallback)
existing_region="$(read_env AWS_REGION)"
default_region="${existing_region:-us-east-1}"
echo -n "  AWS 리전 입력 (Enter 만 누르면 기본값 '$default_region' 적용): "
read -r aws_region
aws_region="${aws_region:-$default_region}"
update_env AWS_REGION "$aws_region"
pass "AWS_REGION=$aws_region"

# DEMO_USER (기존 .env > OS $USER > ubuntu — 워크샵 multi-user 시 unique 값 필수)
existing_user="$(read_env DEMO_USER)"
default_user="${existing_user:-${USER:-ubuntu}}"
echo ""
echo "  DEMO_USER — 동일 AWS 계정에 여러 시연자가 deploy 시 충돌 방지용 prefix."
echo "  예: alice / bob / 사번. 영문/숫자/하이픈만, ≤16자."
echo -n "  DEMO_USER 입력 (Enter 만 누르면 기본값 '$default_user' 적용): "
read -r demo_user
demo_user="${demo_user:-$default_user}"
if [[ ! "$demo_user" =~ ^[a-zA-Z0-9-]{1,16}$ ]]; then
    fail "DEMO_USER='$demo_user' 잘못된 형식 (영문/숫자/하이픈만 ≤16자)"
fi
update_env DEMO_USER "$demo_user"
pass "DEMO_USER=$demo_user"
echo ""

# ── 단계 4: Storage backend ───────────────────────
echo "=== 단계 4/5: Storage backend (Phase 4 runbook 데이터) ==="
echo ""

# 기존 .env 의 STORAGE_BACKEND → choice 번호로 매핑 (1=s3 / 2=github)
existing_backend="$(read_env STORAGE_BACKEND)"
case "$existing_backend" in
    s3)     default_choice="1" ;;
    github) default_choice="2" ;;
    *)      default_choice="1" ;;
esac

echo "  옵션:"
echo "  1) s3      — S3 bucket (default — corp 환경 호환, PAT 불필요)"
echo "  2) github  — GitHub repo data/runbooks/ + PAT (청중이 fork 가능)"
echo "  s) 건너뛰기 — 나중에 수동 설정 (Phase 4 진입 전 결정)"
echo ""
echo -n "  선택 [1/2/s] (Enter 만 누르면 기본값 '$default_choice' 적용): "
read -r backend_choice
backend_choice="${backend_choice:-$default_choice}"

case "$backend_choice" in
    1)
        # S3 backend — github 섹션 (header + entries) 통째로 제거
        update_env STORAGE_BACKEND "s3"
        sed -i '/^GITHUB_REPO=/d; /^GITHUB_TOKEN_SSM_PATH=/d' .env
        # multi-line sed: '# ====' + '# GitHub ...' + '# ====' + 다음 빈 줄 (총 4줄)
        sed -i '/^# ============================================================$/{N;/\n# GitHub (STORAGE_BACKEND=github 시/{N;N;d}}' .env
        # s3 entries 가 .env 에 없으면 추가 (re-run 친화)
        grep -q "^STORAGE_BUCKET_NAME=" .env || echo "STORAGE_BUCKET_NAME=" >> .env
        grep -q "^S3_STORAGE_LAMBDA_ARN=" .env || echo "S3_STORAGE_LAMBDA_ARN=" >> .env
        pass "STORAGE_BACKEND=s3 (github 섹션 제거)"
        info "S3 bucket 은 Phase 4 진입 시 'bash infra/s3-lambda/deploy.sh' 가 CFN 으로 자동 생성"
        info "(GitHub PAT 불필요 — Lambda IAM Role 이 직접 GetObject 권한 보유)"
        ;;
    2)
        # GitHub backend — s3 섹션 (header + entries) 통째로 제거
        update_env STORAGE_BACKEND "github"
        sed -i '/^STORAGE_BUCKET_NAME=/d; /^S3_STORAGE_LAMBDA_ARN=/d' .env
        sed -i '/^# ============================================================$/{N;/\n# S3 (STORAGE_BACKEND=s3 시/{N;N;d}}' .env
        grep -q "^GITHUB_REPO=" .env || echo "GITHUB_REPO=<YOUR_GITHUB_USER>/aiops-demo-data" >> .env
        grep -q "^GITHUB_TOKEN_SSM_PATH=" .env || echo "GITHUB_TOKEN_SSM_PATH=/aiops-demo/github-token" >> .env
        pass "STORAGE_BACKEND=github (s3 섹션 제거)"
        echo ""
        info "GitHub PAT → SSM 저장 (5단계 검증)"
        if [[ -f setup/store_github_token.sh ]]; then
            bash setup/store_github_token.sh
        else
            fail "setup/store_github_token.sh 미존재"
        fi
        ;;
    s|S)
        warn "Storage backend 미설정 — Phase 4 전 .env 의 STORAGE_BACKEND 수동 설정 필요"
        ;;
    *)
        warn "알 수 없는 선택 ($backend_choice) — 건너뜀"
        ;;
esac
echo ""

# ── 단계 5: X-Ray Transaction Search destination ──
echo "=== 단계 5/5: X-Ray Transaction Search destination ==="
echo "  AgentCore Runtime trace 가 GenAI Observability dashboard 에 적재되려면"
echo "  X-Ray trace segment destination 이 'CloudWatchLogs' 여야 함 (account+region 단위 1회)."
echo "  Phase 3/4/5 의 4개 Runtime deploy 마다 'Failed to enable observability ...'"
echo "  warning 이 반복되는 원인 — 미리 1회 설정으로 회피."

current_dest="$(aws xray get-trace-segment-destination --region "$aws_region" --query 'Destination' --output text 2>/dev/null || echo '')"
if [ "$current_dest" = "CloudWatchLogs" ]; then
    pass "이미 CloudWatchLogs (skip — idempotent)"
elif aws xray update-trace-segment-destination --destination CloudWatchLogs --region "$aws_region" >/dev/null 2>&1; then
    pass "X-Ray destination → CloudWatchLogs 설정"
else
    warn "X-Ray destination 설정 실패 — IAM 권한 부족 가능 (xray:UpdateTraceSegmentDestination)"
    echo "    수동 재시도: aws xray update-trace-segment-destination --destination CloudWatchLogs --region $aws_region"
    echo "    영향: Agent 동작 정상, 단 GenAI Observability dashboard trace 비어 보일 수 있음"
fi
echo ""

# ── 완료 ──────────────────────────────────────────
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}  부트스트랩 완료${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
info "생성/갱신된 환경변수 확인: cat .env (또는 에디터로 열어 점검)"
echo "  주요 entry: AWS_REGION / DEMO_USER / STORAGE_BACKEND / GITHUB_REPO / GITHUB_TOKEN_SSM_PATH"
echo "  Phase 별 deploy.sh 가 추가로 채울 entry: GATEWAY_ID / RUNTIME_ARN / EC2_INSTANCE_ID 등"
echo ""
info "다음 단계: README.md §Quickstart §2 (Phase 별 진행)"
echo "  Phase 0 deploy: bash infra/ec2-simulator/deploy.sh"
echo ""
