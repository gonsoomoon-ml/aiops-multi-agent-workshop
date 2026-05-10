#!/usr/bin/env bash
# teardown.sh — Phase 6a Incident A2A Runtime + 의존 자원 reverse 순서 삭제.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

# .env 로드: repo root (DEMO_USER + COGNITO_*) → runtime-local (RUNTIME_ID 등 — deploy 가 작성)
[ -f "$PROJECT_ROOT/.env" ] && { set -a; source "$PROJECT_ROOT/.env"; set +a; }
[ -f "${SCRIPT_DIR}/.env" ] && { set -a; source "${SCRIPT_DIR}/.env"; set +a; }

REGION="${AWS_REGION:-us-west-2}"
DEMO_USER="${DEMO_USER:?DEMO_USER 미설정 (repo root .env 필요)}"
AGENT_NAME="aiops_demo_${DEMO_USER}_incident_a2a"
OAUTH_PROVIDER_NAME="${AGENT_NAME}_gateway_provider"
ECR_REPO="bedrock-agentcore-${AGENT_NAME}"
LOG_GROUP="/aws/bedrock-agentcore/runtimes/${AGENT_NAME}"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

echo -e "${YELLOW}=== Phase 6a Incident A2A teardown — ${AGENT_NAME} ===${NC}"

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

echo -e "${YELLOW}[6/6] CW Log Group 삭제${NC}"
if aws logs delete-log-group --region "$REGION" --log-group-name "$LOG_GROUP" 2>/dev/null; then
    echo -e "  ${GREEN}✓ ${LOG_GROUP} 삭제${NC}"
else
    echo -e "  (Log Group 없음 — skip)"
fi

if [ -f "${SCRIPT_DIR}/.env" ]; then
    sed -i.bak '/^RUNTIME_ARN=/d; /^RUNTIME_ID=/d; /^RUNTIME_NAME=/d; /^OAUTH_PROVIDER_NAME=/d; /^INCIDENT_A2A_RUNTIME_ARN=/d; /^# Phase 6a Runtime/d' "${SCRIPT_DIR}/.env"
    rm -f "${SCRIPT_DIR}/.env.bak"
    echo -e "  ${GREEN}✓ ${SCRIPT_DIR}/.env cleanup${NC}"
fi

echo -e "${YELLOW}[verify] dependency 보존 확인 (incident HTTP Runtime)${NC}"
INCIDENT_HTTP_ID=$(aws bedrock-agentcore-control list-agent-runtimes --region "$REGION" \
    --query "agentRuntimes[?agentRuntimeName=='aiops_demo_${DEMO_USER}_incident'].agentRuntimeId" --output text 2>/dev/null || echo "")
[ -n "$INCIDENT_HTTP_ID" ] && [ "$INCIDENT_HTTP_ID" != "None" ] \
    && echo -e "  ${GREEN}✓ incident (HTTP) Runtime 보존 (${INCIDENT_HTTP_ID})${NC}" \
    || echo -e "  - incident (HTTP) Runtime 미존재 (이미 정리되었거나 미배포)"

echo -e "${GREEN}=== ✅ Phase 6a Incident A2A teardown 완료 ===${NC}"
