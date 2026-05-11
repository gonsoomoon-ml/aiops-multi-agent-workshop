#!/usr/bin/env bash
# teardown.sh — Phase 3 자원 reverse 순서 삭제 (P3-A5).
# Phase 2 (Cognito stack, Gateway, Lambda) 는 미터치.
# reference: phase3.md §9.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

# .env 로드: repo root 단일 (Phase 2 자원 + Phase 3 metadata 모두 MONITOR_ prefix 로 보관)
[ -f "$PROJECT_ROOT/.env" ] && { set -a; source "$PROJECT_ROOT/.env"; set +a; }

REGION="${AWS_REGION:-us-west-2}"
DEMO_USER="${DEMO_USER:?DEMO_USER 미설정 (repo root .env 필요)}"
AGENT_NAME="aiops_demo_${DEMO_USER}_monitor"
OAUTH_PROVIDER_NAME="${MONITOR_OAUTH_PROVIDER_NAME:-${AGENT_NAME}_gateway_provider}"
RUNTIME_ID="${MONITOR_RUNTIME_ID:-}"
ECR_REPO="bedrock-agentcore-${AGENT_NAME}"
LOG_GROUP="/aws/bedrock-agentcore/runtimes/${AGENT_NAME}"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

echo -e "${YELLOW}=== Phase 3 teardown — ${AGENT_NAME} ===${NC}"

# ── [1/6] Runtime 삭제 ──────────────────────────────────────────
echo -e "${YELLOW}[1/6] Runtime 삭제${NC}"
RUNTIME_ID="${RUNTIME_ID:-$(aws bedrock-agentcore-control list-agent-runtimes --region "$REGION" \
    --query "agentRuntimes[?agentRuntimeName=='${AGENT_NAME}'].agentRuntimeId" --output text 2>/dev/null || echo '')}"
if [ -n "${RUNTIME_ID:-}" ] && [ "$RUNTIME_ID" != "None" ]; then
    aws bedrock-agentcore-control delete-agent-runtime --region "$REGION" --agent-runtime-id "$RUNTIME_ID" || true
    echo -e "  ${GREEN}✓ Runtime ${RUNTIME_ID} 삭제 요청${NC}"
else
    echo -e "  (Runtime 없음 — skip)"
fi

# ── [2/6] Runtime DELETED 대기 ──────────────────────────────────
echo -e "${YELLOW}[2/6] Runtime DELETED 대기 (max 60s)${NC}"
if [ -n "${RUNTIME_ID:-}" ] && [ "$RUNTIME_ID" != "None" ]; then
    for i in $(seq 1 12); do
        STATUS=$(aws bedrock-agentcore-control get-agent-runtime --region "$REGION" \
            --agent-runtime-id "$RUNTIME_ID" --query 'status' --output text 2>/dev/null || echo "NOT_FOUND")
        if [ "$STATUS" = "NOT_FOUND" ] || [ "$STATUS" = "DELETED" ]; then
            echo -e "  ${GREEN}✓ Runtime ${STATUS}${NC}"
            break
        fi
        echo -e "  [${i}/12] ${STATUS}"
        sleep 5
    done
fi

# ── [3/6] OAuth2CredentialProvider 삭제 ─────────────────────────
echo -e "${YELLOW}[3/6] OAuth2CredentialProvider 삭제${NC}"
if aws bedrock-agentcore-control delete-oauth2-credential-provider \
    --region "$REGION" --name "$OAUTH_PROVIDER_NAME" 2>/dev/null; then
    echo -e "  ${GREEN}✓ ${OAUTH_PROVIDER_NAME} 삭제${NC}"
else
    echo -e "  (provider 없음 — skip)"
fi

# ── [4/6] ECR Repo 삭제 (images 포함, --force) ──────────────────
echo -e "${YELLOW}[4/6] ECR Repository 삭제${NC}"
if aws ecr describe-repositories --region "$REGION" --repository-names "$ECR_REPO" >/dev/null 2>&1; then
    aws ecr delete-repository --region "$REGION" --repository-name "$ECR_REPO" --force >/dev/null
    echo -e "  ${GREEN}✓ ${ECR_REPO} (images + repo) 삭제${NC}"
else
    echo -e "  (ECR repo 없음 — skip)"
fi

# ── [5/6] IAM Role 삭제 (inline + managed detach) ────────────────
echo -e "${YELLOW}[5/6] IAM Role 삭제${NC}"
ROLE_ARN="${ROLE_ARN:-$(aws bedrock-agentcore-control get-agent-runtime --region "$REGION" \
    --agent-runtime-id "${RUNTIME_ID:-}" --query 'roleArn' --output text 2>/dev/null || echo '')}"
ROLE_NAME="${ROLE_ARN:+${ROLE_ARN##*/}}"
if [ -n "$ROLE_NAME" ] && [ "$ROLE_NAME" != "None" ] && aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
    for POLICY in $(aws iam list-role-policies --role-name "$ROLE_NAME" --query 'PolicyNames' --output text); do
        aws iam delete-role-policy --role-name "$ROLE_NAME" --policy-name "$POLICY"
        echo -e "  detached inline: $POLICY"
    done
    for POLICY_ARN in $(aws iam list-attached-role-policies --role-name "$ROLE_NAME" --query 'AttachedPolicies[].PolicyArn' --output text); do
        aws iam detach-role-policy --role-name "$ROLE_NAME" --policy-arn "$POLICY_ARN"
        echo -e "  detached managed: $POLICY_ARN"
    done
    aws iam delete-role --role-name "$ROLE_NAME"
    echo -e "  ${GREEN}✓ Role ${ROLE_NAME} 삭제${NC}"
else
    echo -e "  (Role 없음 — skip)"
fi

# ── [6/6] CW Log Group 삭제 ──────────────────────────────────────
echo -e "${YELLOW}[6/6] CW Log Group 삭제${NC}"
if aws logs delete-log-group --region "$REGION" --log-group-name "$LOG_GROUP" 2>/dev/null; then
    echo -e "  ${GREEN}✓ ${LOG_GROUP} 삭제${NC}"
else
    echo -e "  (Log Group 없음 — skip)"
fi

# ── .env cleanup — repo root .env 의 Phase 3 (MONITOR_) entry 만 제거 ──
if [ -f "${PROJECT_ROOT}/.env" ]; then
    sed -i.bak '/^MONITOR_RUNTIME_ARN=/d; /^MONITOR_RUNTIME_ID=/d; /^MONITOR_RUNTIME_NAME=/d; /^MONITOR_OAUTH_PROVIDER_NAME=/d; /^# Phase 3 — Monitor Runtime/d' "${PROJECT_ROOT}/.env"
    rm -f "${PROJECT_ROOT}/.env.bak"
    echo -e "  ${GREEN}✓ repo root .env 의 Phase 3 (MONITOR_) entry cleanup${NC}"
fi

# ── dependency 보존 확인 (negative check) ─────────────────────
echo -e "${YELLOW}[verify] dependency 보존 확인 (Gateway / Cognito stack)${NC}"
GATEWAY_COUNT=$(aws bedrock-agentcore-control list-gateways --region "$REGION" \
    --query "length(items[?contains(name, 'aiops-demo-${DEMO_USER}-gateway')])" --output text 2>/dev/null || echo "0")
if [ "$GATEWAY_COUNT" != "0" ] && [ "$GATEWAY_COUNT" != "None" ]; then
    echo -e "  ${GREEN}✓ Gateway 보존 (${GATEWAY_COUNT}건)${NC}"
else
    echo -e "  - Gateway 미존재 (이미 정리되었거나 미배포)"
fi
if aws cloudformation describe-stacks --stack-name "aiops-demo-${DEMO_USER}-cognito-gateway" --region "$REGION" >/dev/null 2>&1; then
    echo -e "  ${GREEN}✓ Cognito stack 보존${NC}"
else
    echo -e "  - Cognito stack 미존재 (이미 정리되었거나 미배포)"
fi

echo -e "${GREEN}=== ✅ Phase 3 teardown 완료 ===${NC}"
