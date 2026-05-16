#!/usr/bin/env bash
# infra/ec2-simulator/deploy.sh — EC2 simulator + alarms 배포
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$PROJECT_ROOT/infra/ec2-simulator"

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'
log()  { echo -e "${GREEN}[deploy]${NC} $1"; }
fail() { echo -e "${RED}[deploy]${NC} $1"; exit 1; }

# ── AWS 자격증명 사전 검증 ───────────────────────
aws sts get-caller-identity --query Account --output text >/dev/null 2>&1 \
    || fail "AWS 자격증명 미설정. aws configure 또는 export AWS_PROFILE 후 재실행"

# ── .env 자동 생성 (없으면 .env.example 복사) ────
if [[ ! -f "$PROJECT_ROOT/.env" ]]; then
    cp "$PROJECT_ROOT/.env.example" "$PROJECT_ROOT/.env"
    log ".env 미존재 — .env.example에서 자동 생성"
fi

# ── .env 로드 ────────────────────────────────────
set -a
source "$PROJECT_ROOT/.env"
set +a

REGION="${AWS_REGION:-us-east-1}"

# ── DEMO_USER — 동일 AWS 계정에 여러 시연자 deploy 시 충돌 방지용 prefix ──
# 우선순위: .env 의 DEMO_USER > OS $USER > 'ubuntu'. 워크샵 multi-user 시 .env 명시 권장.
DEMO_USER="${DEMO_USER:-${USER:-ubuntu}}"
[[ "$DEMO_USER" =~ ^[a-zA-Z0-9-]{1,16}$ ]] \
    || fail "DEMO_USER='$DEMO_USER' 잘못된 형식. 영문/숫자/하이픈만 ≤16자 (.env 또는 export DEMO_USER=...)"

STACK_EC2="aiops-demo-${DEMO_USER}-ec2-simulator"
STACK_ALARMS="aiops-demo-${DEMO_USER}-alarms"
KEYPAIR_NAME="aiops-demo-${DEMO_USER}-keypair"

# ── 운영자 IP 자동 감지 (C2: 실패 시 fail-fast) ───
if [[ -z "${ALLOWED_SSH_IP:-}" ]]; then
    MY_IP="$(curl -s https://checkip.amazonaws.com)"
    [[ -z "$MY_IP" ]] && fail "IP 자동 감지 실패. ALLOWED_SSH_IP=x.x.x.x/32 export 후 재실행"
    ALLOWED_SSH_IP="${MY_IP}/32"
fi

log "region=$REGION demo_user=$DEMO_USER allowed_ip=$ALLOWED_SSH_IP"
log "stacks: $STACK_EC2 + $STACK_ALARMS / keypair: $KEYPAIR_NAME"

# ── EC2 simulator 스택 ───────────────────────────
log "ec2-simulator 스택 배포..."
aws cloudformation deploy \
    --region "$REGION" \
    --stack-name "$STACK_EC2" \
    --template-file ec2-simulator.yaml \
    --parameter-overrides DemoUser="$DEMO_USER" AllowedSshIp="$ALLOWED_SSH_IP" KeyPairName="$KEYPAIR_NAME" \
    --capabilities CAPABILITY_NAMED_IAM \
    --tags Project=aiops-demo "User=$DEMO_USER"

INSTANCE_ID="$(aws cloudformation describe-stacks --region "$REGION" \
    --stack-name "$STACK_EC2" \
    --query "Stacks[0].Outputs[?OutputKey=='InstanceId'].OutputValue" --output text)"
PUBLIC_IP="$(aws cloudformation describe-stacks --region "$REGION" \
    --stack-name "$STACK_EC2" \
    --query "Stacks[0].Outputs[?OutputKey=='PublicIp'].OutputValue" --output text)"

[[ -z "$INSTANCE_ID" ]] && fail "InstanceId 추출 실패"
log "InstanceId=$INSTANCE_ID PublicIp=$PUBLIC_IP"

# ── alarms 스택 ──────────────────────────────────
log "alarms 스택 배포..."
aws cloudformation deploy \
    --region "$REGION" \
    --stack-name "$STACK_ALARMS" \
    --template-file alarms.yaml \
    --parameter-overrides InstanceId="$INSTANCE_ID" DemoUser="$DEMO_USER" \
    --tags Project=aiops-demo "User=$DEMO_USER"

# ── .env 갱신 ────────────────────────────────────
# DEMO_USER 도 함께 write-back — interactive shell 이 `source .env` 시 deploy 와 동기.
# (write-back 누락 시 후속 `aws describe-*` 명령에서 mismatch — 예: KeyPair NotFound)
if [[ -f "$PROJECT_ROOT/.env" ]]; then
    sed -i "s|^DEMO_USER=.*|DEMO_USER=$DEMO_USER|" "$PROJECT_ROOT/.env"
    sed -i "s|^EC2_INSTANCE_ID=.*|EC2_INSTANCE_ID=$INSTANCE_ID|" "$PROJECT_ROOT/.env"
    sed -i "s|^EC2_PUBLIC_IP=.*|EC2_PUBLIC_IP=$PUBLIC_IP|" "$PROJECT_ROOT/.env"
    log ".env 갱신: DEMO_USER, EC2_INSTANCE_ID, EC2_PUBLIC_IP"
fi

echo ""
log "Phase 0 배포 완료"
echo "  Payment API : http://$PUBLIC_IP:8080/health"
echo "  alarm 2종   : payment-${DEMO_USER}-status-check (real) / payment-${DEMO_USER}-noisy-cpu (noise)"
echo "  검증 시나리오: cat infra/ec2-simulator/README.md   # § 3. 검증"
echo ""
echo "  ⏳ Flask 부팅 ~2-3분 소요. 그 후:"
echo "      curl http://$PUBLIC_IP:8080/health"
echo "  부팅 디버깅: aws ec2 get-console-output --instance-id $INSTANCE_ID --region $REGION --output text | tail -40"

# ── KeyPair PEM 추출 명령 안내 (선택, 데모엔 불필요) ──
KEY_PAIR_ID="$(aws ec2 describe-key-pairs --region "$REGION" \
    --key-names "$KEYPAIR_NAME" \
    --query 'KeyPairs[0].KeyPairId' --output text 2>/dev/null || true)"
if [[ -n "$KEY_PAIR_ID" && "$KEY_PAIR_ID" != "None" ]]; then
    echo ""
    echo "  SSH 시 (선택): "
    echo "      aws ssm get-parameter --name /ec2/keypair/$KEY_PAIR_ID --with-decryption --query Parameter.Value --output text > aiops-demo.pem && chmod 400 aiops-demo.pem"
    echo "      ssh -i aiops-demo.pem ec2-user@$PUBLIC_IP"
fi
