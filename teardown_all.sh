#!/usr/bin/env bash
# teardown_all.sh — 8개 teardown 을 의존성 역순으로 일괄 실행.
# Phase 5 → 4 → 3 → 2 → 0 순. 자세한 순서는 docs/learn/teardown.md 참조.
#
# 사용:
#   bash teardown_all.sh           # 확인 prompt 후 진행
#   bash teardown_all.sh --yes     # 확인 skip (CI / 스크립트 용)

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

# .env 로드 (DEMO_USER 확인용)
[ -f .env ] && { set -a; source .env; set +a; }
DEMO_USER="${DEMO_USER:?DEMO_USER 미설정 (repo root .env 필요)}"
REGION="${AWS_REGION:-us-west-2}"

YELLOW=$'\033[1;33m'; GREEN=$'\033[0;32m'; RED=$'\033[0;31m'; NC=$'\033[0m'

cat <<EOF
${YELLOW}=== AIOps demo 전체 teardown ===${NC}
  DEMO_USER = $DEMO_USER
  REGION    = $REGION

다음 8개 step 을 의존성 역순으로 실행합니다:
  1. Phase 5 — Supervisor Runtime
  2. Phase 5 — Monitor A2A Runtime
  3. Phase 5 — Incident A2A Runtime
  4. Phase 4 — Incident Runtime
  5. Phase 4 — GitHub Lambda + Gateway Target
  6. Phase 3 — Monitor Runtime
  7. Phase 2 — Cognito + Gateway + 2 Lambda + DEPLOY_BUCKET
  8. Phase 0 — EC2 + alarms

EOF

if [ "${1:-}" != "--yes" ] && [ "${1:-}" != "-y" ]; then
    read -p "진행할까요? (y/N) " -r reply
    [[ "$reply" =~ ^[Yy]$ ]] || { echo "취소됨."; exit 0; }
fi

# 각 step 의 정리 대상 (status 출력 + 끝의 summary 에 사용)
STEP_TITLE=(
    ""  # 1-based index
    "Phase 5 — Supervisor Runtime"
    "Phase 5 — Monitor A2A Runtime"
    "Phase 5 — Incident A2A Runtime"
    "Phase 4 — Incident Runtime"
    "Phase 4 — GitHub Lambda + Gateway Target"
    "Phase 3 — Monitor Runtime"
    "Phase 2 — Cognito + Gateway + 2 Lambda"
    "Phase 0 — EC2 + alarms"
)
# Storage backend dispatch — STORAGE_BACKEND 값에 따라 step 5 의 script 결정
STORAGE_BACKEND="${STORAGE_BACKEND:-s3}"
case "$STORAGE_BACKEND" in
    github) STORAGE_TEARDOWN="infra/github-lambda/teardown.sh"
            STORAGE_REMOVED="GitHub Lambda + Gateway Target 'github-storage' + cross-stack policy" ;;
    s3)     STORAGE_TEARDOWN="infra/s3-lambda/teardown.sh"
            STORAGE_REMOVED="S3 Lambda + S3 bucket + Gateway Target 's3-storage' + cross-stack policy" ;;
    *)      echo "${RED}STORAGE_BACKEND='$STORAGE_BACKEND' 알 수 없음 (github | s3 만 지원)${NC}"; exit 1 ;;
esac
STEP_TITLE[5]="Phase 4 — ${STORAGE_BACKEND^} storage Lambda + Gateway Target"

STEP_SCRIPT=(
    ""
    "agents/supervisor/runtime/teardown.sh"
    "agents/monitor_a2a/runtime/teardown.sh"
    "agents/incident_a2a/runtime/teardown.sh"
    "agents/incident/runtime/teardown.sh"
    "$STORAGE_TEARDOWN"
    "agents/monitor/runtime/teardown.sh"
    "infra/cognito-gateway/teardown.sh"
    "infra/ec2-simulator/teardown.sh"
)
STEP_REMOVED=(
    ""
    "Supervisor Runtime + OAuth provider + ECR repo + IAM Role + CW Log Group"
    "Monitor A2A Runtime + OAuth provider + ECR repo + IAM Role + CW Log Group"
    "Incident A2A Runtime + OAuth provider + ECR repo + IAM Role + CW Log Group"
    "Incident Runtime + OAuth provider + ECR repo + IAM Role + CW Log Group"
    "$STORAGE_REMOVED"
    "Monitor Runtime + OAuth provider + ECR repo + IAM Role + CW Log Group"
    "Gateway + 2 Target + Cognito stack + 2 Lambda + DEPLOY_BUCKET + .env Phase 2"
    "EC2 + 2 alarms (status-check + noisy-cpu) CFN stack"
)

run_step() {
    local n="$1"
    echo
    echo -e "${YELLOW}━━━ [$n/8] ${STEP_TITLE[$n]} ━━━${NC}"
    echo "    \$ bash ${STEP_SCRIPT[$n]}"
    echo

    set +e
    bash "${STEP_SCRIPT[$n]}"
    local rc=$?
    set -e

    echo
    if [ $rc -eq 0 ]; then
        echo -e "${GREEN}✅ Step $n 완료 — 정리 대상: ${STEP_REMOVED[$n]}${NC}"
    else
        echo -e "${RED}❌ Step $n 실패 (exit $rc) — wrapper 중단${NC}"
        exit $rc
    fi
}

for n in 1 2 3 4 5 6 7 8; do
    run_step "$n"
done

cat <<EOF

${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
=== ✅ 전체 teardown 완료 (8/8 step PASS) ===
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}

정리 요약:
EOF

for n in 1 2 3 4 5 6 7 8; do
    printf "  ${GREEN}✅ [%d/8]${NC} %-44s — %s\n" "$n" "${STEP_TITLE[$n]}" "${STEP_REMOVED[$n]}"
done

cat <<EOF

검증 (모두 빈 결과면 정상):

  aws cloudformation list-stacks --region $REGION \\
    --query "StackSummaries[?starts_with(StackName, 'aiops-demo-') && StackStatus != 'DELETE_COMPLETE'].[StackName,StackStatus]" \\
    --output table

  aws bedrock-agentcore-control list-agent-runtimes --region $REGION --output json | grep aiops_demo

EOF
