#!/usr/bin/env bash
# teardown.sh — Phase 5 Monitor A2A Runtime + 의존 자원 reverse 순서 삭제.
# Phase 0/2/3/4 자원 + 다른 Phase 5 자원 (incident_a2a, change, supervisor) 미터치.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

# .env 로드: repo root 단일 (Phase 3/4 second-pass parity — MONITOR_A2A_ prefix)
[ -f "$PROJECT_ROOT/.env" ] && { set -a; source "$PROJECT_ROOT/.env"; set +a; }

REGION="${AWS_REGION:-us-east-1}"
DEMO_USER="${DEMO_USER:?DEMO_USER 미설정 (repo root .env 필요)}"
AGENT_NAME="aiops_demo_${DEMO_USER}_monitor_a2a"
OAUTH_PROVIDER_NAME="${MONITOR_A2A_OAUTH_PROVIDER_NAME:-${AGENT_NAME}_gateway_provider}"
RUNTIME_ID="${MONITOR_A2A_RUNTIME_ID:-}"
ECR_REPO="bedrock-agentcore-${AGENT_NAME}"
# Log Group prefix — 실제 이름은 ${AGENT_NAME}-<runtime_id>-DEFAULT 형식.
# Runtime ID 가 매 deploy 마다 바뀌므로 prefix 로 매칭하여 redeploy 흔적까지 정리.
LOG_GROUP_PREFIX="/aws/bedrock-agentcore/runtimes/${AGENT_NAME}-"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

echo -e "${YELLOW}=== Phase 5 Monitor A2A teardown — ${AGENT_NAME} ===${NC}"

RUNTIME_ID="${RUNTIME_ID:-$(aws bedrock-agentcore-control list-agent-runtimes --region "$REGION" \
    --query "agentRuntimes[?agentRuntimeName=='${AGENT_NAME}'].agentRuntimeId" --output text 2>/dev/null || echo '')}"
if [ -n "${RUNTIME_ID:-}" ] && [ "$RUNTIME_ID" != "None" ]; then
    ROLE_ARN="${ROLE_ARN:-$(aws bedrock-agentcore-control get-agent-runtime --region "$REGION" \
        --agent-runtime-id "$RUNTIME_ID" --query 'roleArn' --output text 2>/dev/null || echo '')}"
fi

echo -e "${YELLOW}[1/6] Runtime 삭제${NC}"
if [ -n "${RUNTIME_ID:-}" ] && [ "$RUNTIME_ID" != "None" ]; then
    aws bedrock-agentcore-control delete-agent-runtime --region "$REGION" --agent-runtime-id "$RUNTIME_ID" || true
    echo -e "  ${GREEN}✓ Runtime ${RUNTIME_ID} 삭제 요청${NC}"
else
    echo -e "  (Runtime 없음 — skip)"
fi

echo -e "${YELLOW}[2/6] Runtime DELETED 대기${NC}"
if [ -n "${RUNTIME_ID:-}" ] && [ "$RUNTIME_ID" != "None" ]; then
    for i in $(seq 1 12); do
        STATUS=$(aws bedrock-agentcore-control get-agent-runtime --region "$REGION" \
            --agent-runtime-id "$RUNTIME_ID" --query 'status' --output text 2>/dev/null || echo "NOT_FOUND")
        if [ "$STATUS" = "NOT_FOUND" ] || [ "$STATUS" = "DELETED" ]; then echo -e "  ${GREEN}✓ ${STATUS}${NC}"; break; fi
        echo -e "  [${i}/12] ${STATUS}"; sleep 5
    done
fi

echo -e "${YELLOW}[3/6] OAuth2CredentialProvider 삭제${NC}"
if aws bedrock-agentcore-control delete-oauth2-credential-provider --region "$REGION" --name "$OAUTH_PROVIDER_NAME" 2>/dev/null; then
    echo -e "  ${GREEN}✓ ${OAUTH_PROVIDER_NAME} 삭제${NC}"
else
    echo -e "  (provider 없음 — skip)"
fi

echo -e "${YELLOW}[4/6] ECR Repository 삭제${NC}"
if aws ecr describe-repositories --region "$REGION" --repository-names "$ECR_REPO" >/dev/null 2>&1; then
    aws ecr delete-repository --region "$REGION" --repository-name "$ECR_REPO" --force >/dev/null
    echo -e "  ${GREEN}✓ ${ECR_REPO} 삭제${NC}"
else
    echo -e "  (ECR repo 없음 — skip)"
fi

echo -e "${YELLOW}[5/6] IAM Role 삭제${NC}"
ROLE_NAME="${ROLE_ARN:+${ROLE_ARN##*/}}"
if [ -n "$ROLE_NAME" ] && [ "$ROLE_NAME" != "None" ] && aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
    for POLICY in $(aws iam list-role-policies --role-name "$ROLE_NAME" --query 'PolicyNames' --output text); do
        aws iam delete-role-policy --role-name "$ROLE_NAME" --policy-name "$POLICY"
    done
    for POLICY_ARN in $(aws iam list-attached-role-policies --role-name "$ROLE_NAME" --query 'AttachedPolicies[].PolicyArn' --output text); do
        aws iam detach-role-policy --role-name "$ROLE_NAME" --policy-arn "$POLICY_ARN"
    done
    aws iam delete-role --role-name "$ROLE_NAME"
    echo -e "  ${GREEN}✓ Role ${ROLE_NAME} 삭제${NC}"
else
    echo -e "  (Role 없음 — skip)"
fi

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

if [ -f "${PROJECT_ROOT}/.env" ]; then
    sed -i.bak '/^MONITOR_A2A_RUNTIME_NAME=/d; /^MONITOR_A2A_RUNTIME_ARN=/d; /^MONITOR_A2A_RUNTIME_ID=/d; /^MONITOR_A2A_OAUTH_PROVIDER_NAME=/d; /^# Phase 5 — Monitor A2A Runtime/d' "${PROJECT_ROOT}/.env"
    rm -f "${PROJECT_ROOT}/.env.bak"
    echo -e "  ${GREEN}✓ repo root .env 의 Phase 5 (MONITOR_A2A_) entry cleanup${NC}"
fi

echo -e "${YELLOW}[verify] dependency 보존 확인 (monitor HTTP Runtime)${NC}"
MONITOR_HTTP_ID=$(aws bedrock-agentcore-control list-agent-runtimes --region "$REGION" \
    --query "agentRuntimes[?agentRuntimeName=='aiops_demo_${DEMO_USER}_monitor'].agentRuntimeId" --output text 2>/dev/null || echo "")
if [ -n "$MONITOR_HTTP_ID" ] && [ "$MONITOR_HTTP_ID" != "None" ]; then
    echo -e "  ${GREEN}✓ monitor (HTTP) Runtime 보존 (${MONITOR_HTTP_ID})${NC}"
else
    echo -e "  - monitor (HTTP) Runtime 미존재 (이미 정리되었거나 미배포)"
fi

echo -e "${GREEN}=== ✅ Phase 5 Monitor A2A teardown 완료 ===${NC}"
