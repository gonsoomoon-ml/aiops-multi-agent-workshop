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

# ── 단계 1: 의존성 ────────────────────────────────
echo "=== 단계 1/3: Python 의존성 (uv sync) ==="

if ! command -v uv &>/dev/null; then
    fail "'uv'를 찾을 수 없습니다. 설치: curl -LsSf https://astral.sh/uv/install.sh | sh"
fi

uv sync
pass "의존성 설치 완료"
echo ""

# ── 단계 2: .env ──────────────────────────────────
echo "=== 단계 2/3: .env 파일 ==="

if [[ -f .env ]]; then
    warn ".env 이미 존재 (덮어쓰지 않음)"
else
    cp .env.example .env
    pass ".env 생성 완료"
    info ".env 파일에서 AWS_ACCOUNT_ID, GITHUB_REPO 등을 채우세요"
fi

# AWS_REGION 확인
echo ""
echo -n "  AWS 리전 입력 (기본값: us-west-2): "
read -r aws_region
aws_region="${aws_region:-us-west-2}"

if grep -q "^AWS_REGION=" .env 2>/dev/null; then
    sed -i "s|^AWS_REGION=.*|AWS_REGION=$aws_region|" .env
fi
pass "AWS_REGION=$aws_region"
echo ""

# ── 단계 3: GitHub PAT → SSM ──────────────────────
echo "=== 단계 3/3: GitHub PAT 저장 ==="
echo ""
echo "  GitHub PAT 보관 방법:"
echo "  1) AWS SSM Parameter Store SecureString (권장)"
echo "  s) 건너뛰기 — 나중에 setup/store_github_token.sh 실행"
echo ""
echo -n "  선택 [1/s]: "
read -r choice

case "$choice" in
    1)
        if [[ -f setup/store_github_token.sh ]]; then
            bash setup/store_github_token.sh
        else
            fail "setup/store_github_token.sh 미존재"
        fi
        ;;
    s|S|"")
        warn "건너뜀 — 나중에 setup/store_github_token.sh 실행 가능"
        ;;
    *)
        warn "알 수 없는 선택 — 건너뜀"
        ;;
esac
echo ""

# ── 완료 ──────────────────────────────────────────
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}  부트스트랩 완료${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
info "다음 단계:"
echo "  Phase 0: bash infra/phase0/deploy.sh    # EC2 시뮬레이터 + alarms"
echo "  Phase 1: uv run python -m agents.monitor.local.run"
echo ""
