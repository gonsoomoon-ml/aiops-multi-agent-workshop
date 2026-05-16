#!/usr/bin/env bash
# infra/phase6/deploy.sh — Phase 6 Cross-Account Monitoring 배포
# cognito.yaml 패치 + handler.py 교체 + deploy.sh 패치 → CFN 재배포
set -euo pipefail

GREEN='\033[0;32m'; RED='\033[0;31m'; NC='\033[0m'
log()  { echo -e "${GREEN}[phase6]${NC} $1"; }
fail() { echo -e "${RED}[phase6]${NC} $1"; exit 1; }

PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
COGNITO_DIR="$PROJECT_ROOT/infra/cognito-gateway"
COGNITO_YAML="$COGNITO_DIR/cognito.yaml"
DEPLOY_SH="$COGNITO_DIR/deploy.sh"
HANDLER="$COGNITO_DIR/lambda/cloudwatch_wrapper/handler.py"

# ── 0. 환경변수 확인 ──────────────────────────────
cd "$PROJECT_ROOT"
set -a; source .env 2>/dev/null || true; set +a

[[ -z "${SOURCE_LAMBDA_ARN:-}" ]] && fail "SOURCE_LAMBDA_ARN not set in .env"
[[ -z "${SOURCE_ACCESS_KEY_ID:-}" ]] && fail "SOURCE_ACCESS_KEY_ID not set in .env"
[[ -z "${SOURCE_SECRET_ACCESS_KEY:-}" ]] && fail "SOURCE_SECRET_ACCESS_KEY not set in .env"

log "SOURCE_LAMBDA_ARN=$SOURCE_LAMBDA_ARN"
log "SOURCE_REGION=${SOURCE_REGION:-ap-northeast-2}"

# ── 1. cognito.yaml — Parameters 추가 ────────────
if ! grep -q "SourceLambdaArn" "$COGNITO_YAML"; then
    log "cognito.yaml: Parameters 추가"
    sed -i '/^  DemoUser:/i\
  SourceLambdaArn:\
    Type: String\
    Default: ""\
  SourceAccessKeyId:\
    Type: String\
    Default: ""\
  SourceSecretAccessKey:\
    Type: String\
    Default: ""\
    NoEcho: true\
  SourceRegion:\
    Type: String\
    Default: "ap-northeast-2"' "$COGNITO_YAML"
else
    log "cognito.yaml: Parameters 이미 존재 (skip)"
fi

# ── 2. cognito.yaml — Lambda 환경변수 추가 ────────
if ! grep -q "SOURCE_LAMBDA_ARN" "$COGNITO_YAML"; then
    log "cognito.yaml: Lambda 환경변수 추가"
    sed -i '/DEMO_USER: !Ref DemoUser/a\
          SOURCE_LAMBDA_ARN: !Ref SourceLambdaArn\
          SOURCE_ACCESS_KEY_ID: !Ref SourceAccessKeyId\
          SOURCE_SECRET_ACCESS_KEY: !Ref SourceSecretAccessKey\
          SOURCE_REGION: !Ref SourceRegion' "$COGNITO_YAML"
else
    log "cognito.yaml: Lambda 환경변수 이미 존재 (skip)"
fi

# ── 3. deploy.sh — parameter-overrides 확장 ──────
if ! grep -q "SourceLambdaArn" "$DEPLOY_SH"; then
    log "deploy.sh: parameter-overrides 확장"
    sed -i 's|--parameter-overrides "DemoUser=${DEMO_USER}"|--parameter-overrides \\\
        "DemoUser=${DEMO_USER}" \\\
        "SourceLambdaArn=${SOURCE_LAMBDA_ARN:-}" \\\
        "SourceAccessKeyId=${SOURCE_ACCESS_KEY_ID:-}" \\\
        "SourceSecretAccessKey=${SOURCE_SECRET_ACCESS_KEY:-}" \\\
        "SourceRegion=${SOURCE_REGION:-ap-northeast-2}"|' "$DEPLOY_SH"
else
    log "deploy.sh: parameter-overrides 이미 확장됨 (skip)"
fi

# ── 4. handler.py 교체 ───────────────────────────
log "handler.py: 백업 + 교체"
[[ -f "$HANDLER.bak" ]] || cp "$HANDLER" "$HANDLER.bak"

cat > "$HANDLER" << 'HANDLER_EOF'
import json
import os
import boto3

LAMBDA_ARN = os.environ["SOURCE_LAMBDA_ARN"]
SOURCE_REGION = os.environ.get("SOURCE_REGION", "ap-northeast-2")

lambda_client = boto3.client(
    "lambda",
    region_name=SOURCE_REGION,
    aws_access_key_id=os.environ["SOURCE_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["SOURCE_SECRET_ACCESS_KEY"],
)


def _call_proxy(action: str, params: dict = None) -> dict:
    resp = lambda_client.invoke(
        FunctionName=LAMBDA_ARN,
        InvocationType="RequestResponse",
        Payload=json.dumps({"action": action, "params": params or {}}),
    )
    return json.loads(resp["Payload"].read())


def _tool_name(context) -> str:
    cc = getattr(context, "client_context", None)
    custom = getattr(cc, "custom", None) if cc else None
    return (custom or {}).get("bedrockAgentCoreToolName", "")


def lambda_handler(event, context):
    tool = _tool_name(context)
    params = event or {}

    if tool.endswith("list_live_alarms"):
        return _call_proxy("list_alarms")

    if tool.endswith("get_live_alarm_history"):
        if "alarm_name" not in params:
            return {"error": "alarm_name is required"}
        return _call_proxy("get_alarm_history", {
            "alarm_name": params["alarm_name"],
            "type": params.get("type", "StateUpdate"),
            "max": params.get("max", 20),
        })

    return {"error": f"unknown tool: {tool!r}"}
HANDLER_EOF

# ── 5. CFN 재배포 ────────────────────────────────
log "CFN 재배포 실행"
bash "$DEPLOY_SH"

log "Phase 6 배포 완료 ✓"
