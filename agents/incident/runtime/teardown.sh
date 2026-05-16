#!/usr/bin/env bash
# teardown.sh — Phase 4 Incident Runtime + 의존 자원 reverse 순서 삭제 (P4-A5 의 일부).
# Phase 3 Monitor Runtime / Phase 2 Cognito stack / Gateway / Lambda × 2 미터치.
# GitHub Lambda 는 별 teardown (`infra/github-lambda/teardown.sh`) — 본 스크립트 범위 밖.
# reference: phase4.md §6-2 + phase3.md §9 (Monitor teardown 동일 골격).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

# .env 로드: repo root 단일 (Phase 4 metadata 는 INCIDENT_ prefix 로 통합 보관)
[ -f "$PROJECT_ROOT/.env" ] && { set -a; source "$PROJECT_ROOT/.env"; set +a; }

REGION="${AWS_REGION:-us-east-1}"
DEMO_USER="${DEMO_USER:?DEMO_USER 미설정 (repo root .env 필요)}"
AGENT_NAME="aiops_${DEMO_USER}_incident"
OAUTH_PROVIDER_NAME="${INCIDENT_OAUTH_PROVIDER_NAME:-${AGENT_NAME}_gateway_provider}"
RUNTIME_ID="${INCIDENT_RUNTIME_ID:-}"
ECR_REPO="bedrock-agentcore-${AGENT_NAME}"
# Log Group prefix — 실제 이름은 ${AGENT_NAME}-<runtime_id>-DEFAULT 형식.
# Runtime ID 가 매 deploy 마다 바뀌므로 prefix 로 매칭하여 redeploy 흔적까지 정리.
LOG_GROUP_PREFIX="/aws/bedrock-agentcore/runtimes/${AGENT_NAME}-"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

echo -e "${YELLOW}=== Phase 4 Incident teardown — ${AGENT_NAME} ===${NC}"

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

# ── [6/6] CW Log Group 삭제 ─────────────────────────────────────
echo -e "${YELLOW}[6/6] CW Log Group 삭제 (prefix 매칭 — redeploy 흔적 포함)${NC}"
DELETED_COUNT=0
for LG in $(aws logs describe-log-groups --region "$REGION" \
    --log-group-name-prefix "$LOG_GROUP_PREFIX" \
    --query 'logGroups[].logGroupName' --output text 2>/dev/null); do
    if aws logs delete-log-group --region "$REGION" --log-group-name "$LG" 2>/dev/null; then
        echo -e "  ${GREEN}✓ ${LG} 삭제${NC}"
        DELETED_COUNT=$((DELETED_COUNT + 1))
    fi
done
[ "$DELETED_COUNT" -eq 0 ] && echo -e "  (Log Group 없음 — skip)"

# ── .env cleanup — repo root .env 의 Phase 4 (INCIDENT_) entry 만 제거 ──
if [ -f "${PROJECT_ROOT}/.env" ]; then
    sed -i.bak '/^INCIDENT_RUNTIME_ARN=/d; /^INCIDENT_RUNTIME_ID=/d; /^INCIDENT_RUNTIME_NAME=/d; /^INCIDENT_OAUTH_PROVIDER_NAME=/d; /^# Phase 4 — Incident Runtime/d' "${PROJECT_ROOT}/.env"
    rm -f "${PROJECT_ROOT}/.env.bak"
    echo -e "  ${GREEN}✓ repo root .env 의 Phase 4 (INCIDENT_) entry cleanup${NC}"
fi

# ── dependency 보존 확인 (negative check, P4-A5) ──────────────
echo -e "${YELLOW}[verify] dependency 보존 확인 (Monitor Runtime / Cognito stack)${NC}"
MONITOR_ID=$(aws bedrock-agentcore-control list-agent-runtimes --region "$REGION" \
    --query "agentRuntimes[?agentRuntimeName=='aiops_${DEMO_USER}_monitor'].agentRuntimeId" \
    --output text 2>/dev/null || echo "")
if [ -n "$MONITOR_ID" ] && [ "$MONITOR_ID" != "None" ]; then
    echo -e "  ${GREEN}✓ Monitor Runtime 보존 (${MONITOR_ID})${NC}"
else
    echo -e "  - Monitor Runtime 미존재 (이미 정리되었거나 미배포)"
fi
if aws cloudformation describe-stacks --stack-name "aiops-demo-${DEMO_USER}-cognito-gateway" --region "$REGION" >/dev/null 2>&1; then
    echo -e "  ${GREEN}✓ Cognito stack 보존${NC}"
else
    echo -e "  - Cognito stack 미존재 (이미 정리되었거나 미배포)"
fi

echo -e "${GREEN}=== ✅ Phase 4 Incident teardown 완료 ===${NC}"
echo -e "${YELLOW}NOTE: Storage Lambda + Target 은 backend 별 teardown:${NC}"
echo -e "${YELLOW}  - STORAGE_BACKEND=s3:     bash infra/s3-lambda/teardown.sh${NC}"
echo -e "${YELLOW}  - STORAGE_BACKEND=github: bash infra/github-lambda/teardown.sh${NC}"
