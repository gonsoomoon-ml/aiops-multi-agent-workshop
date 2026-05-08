#!/usr/bin/env bash
# teardown.sh — Phase 4 Incident Runtime + 의존 자원 reverse 순서 삭제 (P4-A5 의 일부).
# Phase 3 Monitor Runtime / Phase 2 Cognito stack / Gateway / Lambda × 2 미터치.
# GitHub Lambda 는 별 teardown (`infra/phase4/teardown.sh`) — 본 스크립트 범위 밖.
# reference: phase4.md §6-2 + phase3.md §9 (Monitor teardown 동일 골격).
set -euo pipefail

REGION="${AWS_REGION:-us-west-2}"
DEMO_USER="${DEMO_USER:?DEMO_USER 미설정}"
AGENT_NAME="aiops_demo_${DEMO_USER}_incident"
OAUTH_PROVIDER_NAME="${AGENT_NAME}_gateway_provider"
ECR_REPO="bedrock-agentcore-${AGENT_NAME}"
LOG_GROUP="/aws/bedrock-agentcore/runtimes/${AGENT_NAME}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

echo -e "${YELLOW}=== Phase 4 Incident teardown — ${AGENT_NAME} ===${NC}"

if [ -f "${SCRIPT_DIR}/.env" ]; then
    set -a; source "${SCRIPT_DIR}/.env"; set +a
fi

# ── [0/6] ROLE_ARN 사전 캡처 (race condition 회피) ──────────────
# Runtime 삭제 후엔 get-agent-runtime 가 실패 → ROLE_ARN 조회 불가능. 삭제 전 캡처
# 필수 (그렇지 않으면 step [5] 에서 IAM Role 정리 skip 되어 orphan Role 잔존).
RUNTIME_ID="${RUNTIME_ID:-$(aws bedrock-agentcore-control list-agent-runtimes --region "$REGION" \
    --query "agentRuntimes[?agentRuntimeName=='${AGENT_NAME}'].agentRuntimeId" --output text 2>/dev/null || echo '')}"
if [ -n "${RUNTIME_ID:-}" ] && [ "$RUNTIME_ID" != "None" ]; then
    ROLE_ARN="${ROLE_ARN:-$(aws bedrock-agentcore-control get-agent-runtime --region "$REGION" \
        --agent-runtime-id "$RUNTIME_ID" --query 'roleArn' --output text 2>/dev/null || echo '')}"
fi

# ── [1/6] Runtime 삭제 ──────────────────────────────────────────
echo -e "${YELLOW}[1/6] Runtime 삭제${NC}"
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

# ── [4/6] ECR Repo 삭제 ─────────────────────────────────────────
echo -e "${YELLOW}[4/6] ECR Repository 삭제${NC}"
if aws ecr describe-repositories --region "$REGION" --repository-names "$ECR_REPO" >/dev/null 2>&1; then
    aws ecr delete-repository --region "$REGION" --repository-name "$ECR_REPO" --force >/dev/null
    echo -e "  ${GREEN}✓ ${ECR_REPO} (images + repo) 삭제${NC}"
else
    echo -e "  (ECR repo 없음 — skip)"
fi

# ── [5/6] IAM Role 삭제 ─────────────────────────────────────────
# ROLE_ARN 은 step [0] 에서 사전 캡처됨 (Runtime 삭제 후 lookup 불가)
echo -e "${YELLOW}[5/6] IAM Role 삭제${NC}"
ROLE_NAME="${ROLE_ARN##*/}"
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

# ── [6/6] CW Log Group 삭제 ─────────────────────────────────────
echo -e "${YELLOW}[6/6] CW Log Group 삭제${NC}"
if aws logs delete-log-group --region "$REGION" --log-group-name "$LOG_GROUP" 2>/dev/null; then
    echo -e "  ${GREEN}✓ ${LOG_GROUP} 삭제${NC}"
else
    echo -e "  (Log Group 없음 — skip)"
fi

# ── .env cleanup ────────────────────────────────────────────────
if [ -f "${SCRIPT_DIR}/.env" ]; then
    sed -i.bak '/^RUNTIME_ARN=/d; /^RUNTIME_ID=/d; /^RUNTIME_NAME=/d; /^OAUTH_PROVIDER_NAME=/d; /^INCIDENT_RUNTIME_ARN=/d; /^# Phase 4 Runtime/d' "${SCRIPT_DIR}/.env"
    rm -f "${SCRIPT_DIR}/.env.bak"
    echo -e "  ${GREEN}✓ ${SCRIPT_DIR}/.env 의 Phase 4 Incident entry cleanup${NC}"
fi

# ── Phase 3 자원 보존 검증 (negative check, P4-A5) ──────────────
echo -e "${YELLOW}[verify] Phase 3 자원 보존 검증${NC}"
MONITOR_ID=$(aws bedrock-agentcore-control list-agent-runtimes --region "$REGION" \
    --query "agentRuntimes[?agentRuntimeName=='aiops_demo_${DEMO_USER}_monitor'].agentRuntimeId" \
    --output text 2>/dev/null || echo "")
if [ -n "$MONITOR_ID" ] && [ "$MONITOR_ID" != "None" ]; then
    echo -e "  ${GREEN}✓ Phase 3 Monitor Runtime 보존 (${MONITOR_ID})${NC}"
else
    echo -e "  ${RED}❌ Phase 3 Monitor Runtime 미발견 — Phase 3 redeploy 필요${NC}"
fi
if aws cloudformation describe-stacks --stack-name "aiops-demo-${DEMO_USER}-phase2-cognito" --region "$REGION" >/dev/null 2>&1; then
    echo -e "  ${GREEN}✓ Phase 2 Cognito stack 보존${NC}"
else
    echo -e "  ${RED}❌ Phase 2 Cognito stack 삭제됨${NC}"
fi

echo -e "${GREEN}=== ✅ Phase 4 Incident teardown 완료 ===${NC}"
echo -e "${YELLOW}NOTE: GitHub Lambda + Target 은 'bash infra/phase4/teardown.sh' 로 별도 정리${NC}"
