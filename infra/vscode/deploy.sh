#!/bin/bash
set -e
################################################################################
#                                                                              #
#   VSCode Server on EC2 - 간소화 배포 스크립트                                  #
#   Simplified deployment script                                               #
#                                                                              #
#   사용법:                                                                     #
#     배포: bash deploy.sh                                                      #
#     삭제: bash deploy.sh --delete <stack-name>                                #
#                                                                              #
#   주의: Workshop Studio 등 제한된 환경에서는 cloudformation:CreateChangeSet  #
#         이 explicit deny 되어 `aws cloudformation deploy` 가 막힙니다.        #
#         본 스크립트는 change set 을 쓰지 않는 create-stack / update-stack     #
#         직접 API 로 배포하여 이 deny 를 우회합니다.                           #
#                                                                              #
################################################################################

GREEN='\033[0;32m'; RED='\033[0;31m'; CYAN='\033[0;36m'; YELLOW='\033[1;33m'; NC='\033[0m'
BOLD='\033[1m'
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TEMPLATE="$SCRIPT_DIR/cloudformation.yaml"

# --delete 모드 처리
if [ "${1:-}" = "--delete" ]; then
    STACK_NAME="${2:-}"
    if [ -z "$STACK_NAME" ]; then
        echo -e "${RED}사용법: bash deploy.sh --delete <stack-name>${NC}"
        exit 1
    fi
    echo -e "${CYAN}스택 삭제 중 / Deleting stack: $STACK_NAME ...${NC}"
    aws cloudformation delete-stack --stack-name "$STACK_NAME"
    echo -e "${YELLOW}삭제 요청 완료. 완료까지 수 분 소요됩니다.${NC}"
    echo "  상태 확인: aws cloudformation describe-stacks --stack-name $STACK_NAME --query 'Stacks[0].StackStatus'"
    exit 0
fi

echo ""
echo -e "${CYAN}=================================================================${NC}"
echo -e "${CYAN}   VSCode Server on EC2 - 배포 / Deployment${NC}"
echo -e "${CYAN}=================================================================${NC}"
echo ""

###############################################################################
#  [1/5] 사전 점검 / Pre-flight checks                                        #
###############################################################################
echo -e "${CYAN}[1/5] 사전 점검 / Pre-flight checks...${NC}"

if ! command -v aws &>/dev/null; then
    echo -e "${RED}오류: AWS CLI를 찾을 수 없습니다 / ERROR: aws CLI not found${NC}"
    exit 1
fi

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text 2>/dev/null || echo "")
if [ -z "$ACCOUNT_ID" ]; then
    echo -e "${RED}오류: AWS 자격 증명을 확인할 수 없습니다 / ERROR: Cannot verify AWS credentials${NC}"
    exit 1
fi
# 리전 고정 — ws-default-policy 가 us-east-1 외 리전에서 CloudFormation 을 deny 하므로 고정.
REGION="us-east-1"
echo "  Account: $ACCOUNT_ID"
echo "  Region:  $REGION (고정)"

if [ ! -f "$TEMPLATE" ]; then
    echo -e "${RED}오류: CloudFormation 템플릿을 찾을 수 없습니다: $TEMPLATE${NC}"
    exit 1
fi

###############################################################################
#  [2/5] 사용자 입력 / User Input                                              #
###############################################################################
echo ""
echo -e "${CYAN}[2/5] 설정 입력 / Configuration...${NC}"
echo ""

# Alias (DEMO_USER) — 다른 워크샵 스택과 동일한 prefix 규약 (aiops-demo-${alias}-<component>)
read -p "  Alias (영문/숫자/하이픈 ≤16자, 예: gildong): " ALIAS
if [[ ! "$ALIAS" =~ ^[a-zA-Z0-9-]{1,16}$ ]]; then
    echo -e "${RED}오류: Alias는 영문/숫자/하이픈만 ≤16자${NC}"
    exit 1
fi
STACK_NAME="aiops-demo-${ALIAS}-vscode"
echo -e "  ${GREEN}Stack Name: $STACK_NAME${NC}"

# Password
while true; do
    read -sp "  VSCode 비밀번호 (8자 이상): " VSCODE_PASSWORD
    echo ""
    if [ ${#VSCODE_PASSWORD} -ge 8 ]; then
        read -sp "  비밀번호 확인: " VSCODE_PASSWORD_CONFIRM
        echo ""
        if [ "$VSCODE_PASSWORD" = "$VSCODE_PASSWORD_CONFIRM" ]; then
            break
        else
            echo -e "  ${RED}비밀번호가 일치하지 않습니다${NC}"
        fi
    else
        echo -e "  ${RED}8자 이상 입력해주세요${NC}"
    fi
done

# Instance Type
echo ""
echo -e "  ${BOLD}인스턴스 타입 선택:${NC}"
INSTANCE_TYPES=(
    "t3.2xlarge:x86_64 Intel, 8 vCPU, 32GB (기본값)"
    "t3.xlarge:x86_64 Intel, 4 vCPU, 16GB"
    "t3.large:x86_64 Intel, 2 vCPU, 8GB"
    "m7i.2xlarge:x86_64 Intel, 8 vCPU, 32GB"
    "m7i.xlarge:x86_64 Intel, 4 vCPU, 16GB"
    "m7g.2xlarge:ARM64 Graviton, 8 vCPU, 32GB"
    "m7g.xlarge:ARM64 Graviton, 4 vCPU, 16GB"
    "t4g.2xlarge:ARM64 Graviton, 8 vCPU, 32GB"
    "t4g.xlarge:ARM64 Graviton, 4 vCPU, 16GB"
)
for i in "${!INSTANCE_TYPES[@]}"; do
    ITYPE="${INSTANCE_TYPES[$i]%%:*}"
    IDESC="${INSTANCE_TYPES[$i]##*:}"
    printf "    %2d) %-16s %s\n" $((i+1)) "$ITYPE" "$IDESC"
done
echo ""
read -p "  번호 입력 [1]: " ITYPE_CHOICE
ITYPE_CHOICE="${ITYPE_CHOICE:-1}"

if [[ "$ITYPE_CHOICE" =~ ^[0-9]+$ ]] && [ "$ITYPE_CHOICE" -ge 1 ] && [ "$ITYPE_CHOICE" -le "${#INSTANCE_TYPES[@]}" ]; then
    INSTANCE_TYPE="${INSTANCE_TYPES[$((ITYPE_CHOICE-1))]%%:*}"
else
    INSTANCE_TYPE="t3.2xlarge"
fi
echo -e "  ${GREEN}인스턴스: $INSTANCE_TYPE${NC}"

# EBS Size
echo ""
read -p "  EBS 볼륨 크기 (GB) [20]: " EBS_SIZE
EBS_SIZE="${EBS_SIZE:-20}"

###############################################################################
#  [3/5] VPC 선택 / Select VPC                                               #
###############################################################################
echo ""
echo -e "${CYAN}[3/5] VPC 선택... (Public Subnet은 CloudFormation이 자동 탐색)${NC}"

echo ""
echo -e "  ${BOLD}VPC 선택:${NC}"
VPC_LIST_JSON=$(aws ec2 describe-vpcs --region "$REGION" --output json 2>/dev/null)
VPC_DISPLAY=$(echo "$VPC_LIST_JSON" | python3 -c "
import json, sys
vpcs = json.load(sys.stdin).get('Vpcs', [])
def sort_key(v):
    is_default = v.get('IsDefault', False)
    name = next((t['Value'] for t in v.get('Tags', []) if t['Key'] == 'Name'), '')
    return (0 if is_default else 1, name)
vpcs.sort(key=sort_key)
for v in vpcs:
    name = next((t['Value'] for t in v.get('Tags', []) if t['Key'] == 'Name'), '')
    default_mark = ' [Default]' if v.get('IsDefault') else ''
    label = (name + default_mark) if name else ('(이름 없음)' + default_mark)
    print('{}\t{}\t{}'.format(v['VpcId'], v.get('CidrBlock',''), label))
")

if [ -z "$VPC_DISPLAY" ]; then
    echo -e "${RED}오류: 사용 가능한 VPC가 없습니다${NC}"
    exit 1
fi

declare -a VPC_IDS=()
i=1
while IFS=$'\t' read -r vid cidr label; do
    printf "    %2d) %-22s %-18s %s\n" "$i" "$vid" "$cidr" "$label"
    VPC_IDS+=("$vid")
    i=$((i+1))
done <<< "$VPC_DISPLAY"

echo ""
read -p "  번호 입력 [1]: " VPC_CHOICE
VPC_CHOICE="${VPC_CHOICE:-1}"

if [[ "$VPC_CHOICE" =~ ^[0-9]+$ ]] && [ "$VPC_CHOICE" -ge 1 ] && [ "$VPC_CHOICE" -le "${#VPC_IDS[@]}" ]; then
    VPC_ID="${VPC_IDS[$((VPC_CHOICE-1))]}"
else
    echo -e "${RED}오류: 잘못된 선택입니다${NC}"
    exit 1
fi
echo -e "  ${GREEN}VPC: $VPC_ID${NC}"
echo -e "  ${YELLOW}Public Subnet은 CloudFormation 배포 시 자동 탐색됩니다${NC}"

###############################################################################
#  [4/5] 설정 확인 / Confirm                                                  #
###############################################################################
echo ""
echo -e "${CYAN}[4/5] 설정 확인 / Confirm...${NC}"
echo ""
echo -e "  ${BOLD}┌─────────────────────────────────────────────┐${NC}"
echo -e "  ${BOLD}│  배포 설정 요약                               │${NC}"
echo -e "  ${BOLD}├─────────────────────────────────────────────┤${NC}"
echo "  │  Stack Name:    $STACK_NAME"
echo "  │  Account:       $ACCOUNT_ID"
echo "  │  Region:        $REGION"
echo "  │  VPC:           $VPC_ID"
echo "  │  Subnet:        (Public Subnet 자동 탐색)"
echo "  │  Instance Type: $INSTANCE_TYPE"
echo "  │  EBS Size:      ${EBS_SIZE}GB"
echo "  │  Password:      $(printf '*%.0s' $(seq 1 ${#VSCODE_PASSWORD}))"
echo -e "  ${BOLD}└─────────────────────────────────────────────┘${NC}"
echo ""
read -p "  배포를 시작할까요? (y/n) [y]: " CONFIRM
CONFIRM="${CONFIRM:-y}"
[ "$CONFIRM" != "y" ] && [ "$CONFIRM" != "Y" ] && { echo "  취소되었습니다."; exit 0; }

###############################################################################
#  [5/5] CloudFormation 배포 / Deploy                                         #
#                                                                             #
#  change set 기반 `aws cloudformation deploy` 대신 create-stack/update-stack #
#  직접 API 사용 — CreateChangeSet explicit deny 환경(Workshop Studio) 우회.  #
###############################################################################
echo ""
echo -e "${CYAN}[5/5] CloudFormation 배포 중... (약 3-5분)${NC}"
echo ""

# SG 에서 8888 허용 IP — 0.0.0.0/0 (전체 개방).
# IP 자동 감지는 프록시/VPN 환경에서 실제 브라우저 egress IP 와 달라 접속 차단 위험 → 전체 개방.
# 특정 IP 로 제한하려면 ALLOWED_IP=x.x.x.x/32 export 후 재실행.
ALLOWED_IP="${ALLOWED_IP:-0.0.0.0/0}"
echo -e "  ${GREEN}허용 IP (8888): $ALLOWED_IP${NC}"

# 공통 파라미터 (create/update 동일하게 사용)
PARAMS=(
    "ParameterKey=VpcId,ParameterValue=$VPC_ID"
    "ParameterKey=AllowedIp,ParameterValue=$ALLOWED_IP"
    "ParameterKey=InstanceType,ParameterValue=$INSTANCE_TYPE"
    "ParameterKey=VSCodePassword,ParameterValue=$VSCODE_PASSWORD"
    "ParameterKey=EBSVolumeSize,ParameterValue=$EBS_SIZE"
)

# 스택 존재 여부 감지 — 존재하면 update, 아니면 create
EXISTING_STATUS=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" --region "$REGION" \
    --query "Stacks[0].StackStatus" --output text 2>/dev/null || echo "")

if [ -z "$EXISTING_STATUS" ]; then
    # ── 신규 생성 ────────────────────────────────────
    echo -e "  ${CYAN}새 스택 생성 / create-stack...${NC}"
    aws cloudformation create-stack \
        --stack-name "$STACK_NAME" \
        --template-body "file://$TEMPLATE" \
        --capabilities CAPABILITY_NAMED_IAM \
        --parameters "${PARAMS[@]}" \
        --region "$REGION" >/dev/null

    echo -e "  ${YELLOW}생성 완료 대기 중... (stack-create-complete)${NC}"
    aws cloudformation wait stack-create-complete \
        --stack-name "$STACK_NAME" --region "$REGION"
else
    # ── 기존 스택 업데이트 ───────────────────────────
    echo -e "  ${CYAN}기존 스택 업데이트 / update-stack (현재: $EXISTING_STATUS)...${NC}"

    # update-stack 은 변경사항 없을 때 "No updates are to be performed" 로 실패 →
    # 정상 케이스로 처리하여 스크립트 중단 방지.
    set +e
    UPDATE_OUT=$(aws cloudformation update-stack \
        --stack-name "$STACK_NAME" \
        --template-body "file://$TEMPLATE" \
        --capabilities CAPABILITY_NAMED_IAM \
        --parameters "${PARAMS[@]}" \
        --region "$REGION" 2>&1)
    UPDATE_RC=$?
    set -e

    if [ $UPDATE_RC -ne 0 ]; then
        if echo "$UPDATE_OUT" | grep -q "No updates are to be performed"; then
            echo -e "  ${YELLOW}변경사항 없음 — 기존 스택 그대로 사용${NC}"
        else
            echo -e "${RED}오류: update-stack 실패${NC}"
            echo "$UPDATE_OUT"
            exit 1
        fi
    else
        echo -e "  ${YELLOW}업데이트 완료 대기 중... (stack-update-complete)${NC}"
        aws cloudformation wait stack-update-complete \
            --stack-name "$STACK_NAME" --region "$REGION"
    fi
fi

###############################################################################
#  결과 출력 / Output Results                                                  #
###############################################################################
echo ""
OUTPUTS=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" --region "$REGION" \
    --query "Stacks[0].Outputs" --output json 2>/dev/null || echo "[]")

parse_output() {
    echo "$OUTPUTS" | python3 -c "import json,sys;o={i['OutputKey']:i['OutputValue'] for i in json.load(sys.stdin)};print(o.get('$1','N/A'))" 2>/dev/null || echo "N/A"
}

VSCODE_URL=$(parse_output "VSCodeURL")
INSTANCE_ID=$(parse_output "InstanceId")
SSM_CMD=$(parse_output "SSMCommand")
ROLE_NAME=$(parse_output "IAMRoleName")

echo -e "${GREEN}=================================================================${NC}"
echo -e "${GREEN}   배포 완료 / Deployment Complete${NC}"
echo -e "${GREEN}=================================================================${NC}"
echo ""
echo -e "  ${BOLD}┌─────────────────────────────────────────────────┐${NC}"
echo -e "  ${BOLD}│  접속 방법                                       │${NC}"
echo -e "  ${BOLD}├─────────────────────────────────────────────────┤${NC}"
echo -e "  │                                                 │"
echo -e "  │  ${GREEN}VSCode Server (브라우저)${NC}"
echo -e "  │  URL: ${BOLD}${VSCODE_URL}${NC}"
echo -e "  │  비밀번호: 설정한 비밀번호                       │"
echo -e "  │                                                 │"
echo -e "  │  ${GREEN}SSM Session Manager (터미널)${NC}"
echo -e "  │  $SSM_CMD"
echo -e "  │                                                 │"
echo -e "  ${BOLD}└─────────────────────────────────────────────────┘${NC}"
echo ""
echo -e "  ${YELLOW}EC2 UserData 설치 완료까지 약 5-10분 소요됩니다.${NC}"
echo -e "  ${YELLOW}설치 로그: aws ssm start-session --target $INSTANCE_ID${NC}"
echo -e "  ${YELLOW}          cat /var/log/user-data.log${NC}"
echo ""
echo -e "  ${BOLD}IAM Role: $ROLE_NAME${NC}"
echo -e "  AdministratorAccess 추가:"
echo "    aws iam attach-role-policy \\"
echo "      --role-name $ROLE_NAME \\"
echo "      --policy-arn arn:aws:iam::aws:policy/AdministratorAccess"
echo ""
echo -e "  ${BOLD}스택 삭제:${NC}"
echo "    bash deploy.sh --delete $STACK_NAME    # aiops-demo-${ALIAS}-vscode"
echo ""
