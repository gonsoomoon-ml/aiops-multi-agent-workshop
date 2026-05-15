#!/usr/bin/env bash
set -euo pipefail

# ── AIOps Multi-Agent Workshop — Prerequisite Setup ──
# Run as ec2-user via SSM Session Manager.
# Installs required SW and configures participant user for sudo-free usage.

GREEN='\033[0;32m'; RED='\033[0;31m'; BLUE='\033[0;34m'; NC='\033[0m'
pass() { echo -e "${GREEN}[✅]${NC} $1"; }
fail() { echo -e "${RED}[❌]${NC} $1"; exit 1; }
info() { echo -e "${BLUE}[ℹ]${NC} $1"; }

PARTICIPANT_USER="participant"
PARTICIPANT_HOME="/home/${PARTICIPANT_USER}"

echo ""
echo -e "${BLUE}══════════════════════════════════════════${NC}"
echo -e "${BLUE}  AIOps Workshop — Prerequisite Setup${NC}"
echo -e "${BLUE}  (Run as ec2-user via SSM)${NC}"
echo -e "${BLUE}══════════════════════════════════════════${NC}"
echo ""

# ── Preflight: must run with sudo capability ──────
CURRENT_USER=$(whoami)
if [[ "$CURRENT_USER" != "ec2-user" && "$CURRENT_USER" != "ssm-user" && "$CURRENT_USER" != "root" ]]; then
    fail "This script must be run as ec2-user or ssm-user (via SSM). Current user: $CURRENT_USER"
fi

# ── 1. uv (install for participant) ──────────────
echo "=== 1/6: uv (Python package manager) ==="
if sudo -u "$PARTICIPANT_USER" -i bash -c 'command -v uv' &>/dev/null; then
    UV_VER=$(sudo -u "$PARTICIPANT_USER" -i bash -c 'uv --version')
    pass "uv already installed ($UV_VER)"
else
    sudo -u "$PARTICIPANT_USER" -i bash -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
    pass "uv installed"
fi
echo ""

# ── 2. Python 3.12+ (via uv, for participant) ────
echo "=== 2/6: Python 3.12+ ==="
if sudo -u "$PARTICIPANT_USER" -i bash -c 'uv python find 3.12' &>/dev/null; then
    PY_VER=$(sudo -u "$PARTICIPANT_USER" -i bash -c 'uv run --python 3.12 python --version')
    pass "Python 3.12 already available ($PY_VER)"
else
    sudo -u "$PARTICIPANT_USER" -i bash -c 'uv python install 3.12'
    pass "Python 3.12 installed"
fi
echo ""

# ── 3. Docker ─────────────────────────────────────
echo "=== 3/6: Docker ==="
if command -v docker &>/dev/null; then
    pass "Docker already installed ($(docker --version))"
else
    sudo dnf install -y docker
    pass "Docker installed"
fi
sudo systemctl enable docker &>/dev/null
sudo systemctl start docker &>/dev/null
# Add participant to docker group for sudo-free usage
if ! id -nG "$PARTICIPANT_USER" | grep -qw docker; then
    sudo usermod -aG docker "$PARTICIPANT_USER"
    pass "Added $PARTICIPANT_USER to docker group"
else
    pass "$PARTICIPANT_USER already in docker group"
fi
pass "Docker daemon running ($(docker --version))"
echo ""

# ── 4. SSM Session Manager Plugin ────────────────
echo "=== 4/6: SSM Session Manager Plugin ==="
if command -v session-manager-plugin &>/dev/null; then
    pass "SSM plugin already installed ($(session-manager-plugin --version 2>&1))"
else
    ARCH=$(uname -m)
    case "$ARCH" in
        aarch64) SSM_ARCH="linux_arm64" ;;
        *)       SSM_ARCH="linux_64bit" ;;
    esac
    curl -s "https://s3.amazonaws.com/session-manager-downloads/plugin/latest/${SSM_ARCH}/session-manager-plugin.rpm" -o /tmp/session-manager-plugin.rpm
    sudo dnf install -y /tmp/session-manager-plugin.rpm
    rm -f /tmp/session-manager-plugin.rpm
    pass "SSM plugin installed ($(session-manager-plugin --version 2>&1))"
fi
echo ""

# ── 5. Verify base tools ─────────────────────────
echo "=== 5/6: Verify base tools ==="
command -v aws &>/dev/null || fail "AWS CLI not found"
command -v git &>/dev/null || fail "Git not found"
command -v jq &>/dev/null  || fail "jq not found"
aws sts get-caller-identity --query Account --output text &>/dev/null || fail "AWS credentials not configured"
pass "AWS CLI $(aws --version | awk '{print $1}')"
pass "Git $(git --version)"
pass "jq $(jq --version)"
pass "AWS credentials valid"
echo ""

# ── 6. IAM Policy Attachments ────────────────────
echo "=== 6/6: IAM Policy Attachments ==="

ROLE_ARN=$(aws sts get-caller-identity --query Arn --output text)
ROLE_NAME=$(echo "$ROLE_ARN" | grep -oP '(?<=assumed-role/)[^/]+')

if [[ -z "$ROLE_NAME" ]]; then
    fail "Cannot determine IAM role name from: $ROLE_ARN"
fi
info "Role: $ROLE_NAME"

POLICIES=(
    "arn:aws:iam::aws:policy/AmazonEC2FullAccess"
    "arn:aws:iam::aws:policy/CloudWatchFullAccess"
    "arn:aws:iam::aws:policy/AmazonSSMFullAccess"
    "arn:aws:iam::aws:policy/AmazonBedrockFullAccess"
    "arn:aws:iam::aws:policy/BedrockAgentCoreFullAccess"
    "arn:aws:iam::aws:policy/AWSLambda_FullAccess"
    "arn:aws:iam::aws:policy/AmazonS3FullAccess"
)

ATTACHED=$(aws iam list-attached-role-policies --role-name "$ROLE_NAME" --query 'AttachedPolicies[].PolicyArn' --output text)

for POLICY_ARN in "${POLICIES[@]}"; do
    POLICY_NAME=$(basename "$POLICY_ARN")
    if echo "$ATTACHED" | grep -q "$POLICY_ARN"; then
        pass "$POLICY_NAME (already attached)"
    else
        aws iam attach-role-policy --role-name "$ROLE_NAME" --policy-arn "$POLICY_ARN"
        pass "$POLICY_NAME (attached)"
    fi
done
echo ""

# ── Summary ───────────────────────────────────────
echo -e "${BLUE}══════════════════════════════════════════${NC}"
echo -e "${GREEN}  Prerequisite setup complete!${NC}"
echo -e "${BLUE}══════════════════════════════════════════${NC}"
echo ""
info "participant user can now use docker/uv/python3.12 without sudo"
info "(Code Server terminal needs restart for docker group to take effect)"
info "Next: open Code Server terminal → cd /workshop/aiops-multi-agent-workshop && bash bootstrap.sh"
echo ""
