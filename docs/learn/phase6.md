# Phase 6 — Cross-Account Monitoring

> Phase 6 는 **다른 AWS 계정의 CloudWatch Alarm** 을 기존 Monitor Agent 가 분석할 수 있도록 **STS AssumeRole 기반 cross-account 접근**을 구성. cloudwatch_wrapper Lambda 가 Target Account 의 IAM Role 을 assume 하여 원격 계정의 alarm 을 읽고 분류.

---

## 1. 왜 필요한가   *(~3 min read)*

엔터프라이즈 환경에서 모니터링 대상은 단일 계정에 국한되지 않음. 운영팀은 여러 AWS 계정 (dev / staging / prod / shared-services) 의 alarm 을 **하나의 Agent** 로 통합 분석해야 함.


| 동기 | Phase 5 까지의 범위 | Phase 6 에서 추가로 다루는 내용 |
|---|---|---|
| **Multi-account 가시성** | 단일 계정 내 alarm 조회 | Target Account 의 alarm 을 cross-account AssumeRole 로 통합 조회 |
| **중앙 집중 운영** | 단일 계정 모니터링 시나리오 | 하나의 Agent (Lambda) 가 N개 계정 alarm 을 통합 분석하는 패턴 |
| **최소 권한 원칙** | Lambda Role 에 자기 계정 CloudWatch 권한 부여 | Target Account Role 에 필요한 권한만 위임 + trust policy 로 호출자 제한 |
| **Enterprise IAM 패턴 학습** | 단일 계정 IAM 구성 | STS AssumeRole + trust policy + ExternalId 패턴 실습 |


---

## 2. 진행 (Hands-on)   *(설정 ~15 min / 검증 ~5 min)*

### 2-1. 사전 확인

- **Phase 2 완료** (Cognito stack + Gateway alive — `GATEWAY_URL` / `COGNITO_*` in `.env`)
- **Phase 5 완료** (Supervisor + 2 sub-agent Runtime READY) — 또는 최소 Phase 2 local agent 동작
- **Target Account** 접근 가능 (AWS CLI profile 또는 별도 자격증명)
- Target Account 에 CloudWatch Alarm 이 존재 (모니터링 대상)

### 2-2. Target Account 정보 확인

#### Step A — Target Account 접근 정보 확인

모니터링 대상은 **Food Order 데모 애플리케이션**입니다.

**Sample Web App**: [https://demo.my-awsome-app.xyz/](https://demo.my-awsome-app.xyz/)

![Food Order 데모 앱 프론트엔드](../assets/workshop_setup/demo_app.png)

**아키텍처 구성**

![Food Order 데모 앱 아키텍처](../assets/workshop_setup/demo_app_architecture.png)

아래 정보를 환경변수로 설정하세요. `TARGET_ACCOUNT_ID` 는 행사 당일 진행자에게 전달받으세요.

| 항목 | 값 | 비고 |
|---|---|---|
| `TARGET_ACCOUNT_ID` | 행사 당일 진행자 제공 | 보안상 사전 비공개 |
| `TARGET_ROLE_NAME` | `foodorder-dev-workshop-readonly` | 미리 생성됨 |
| `EXTERNAL_ID` | `aiops-workshop-2026` | 미리 생성됨 |

```bash
# ⚠️ TARGET_ACCOUNT_ID 는 행사 진행자에게 전달받은 실제 값으로 교체하세요
TARGET_ACCOUNT_ID="<행사 진행자에게 전달받은 Account ID>"
TARGET_ROLE_NAME="foodorder-dev-workshop-readonly"
EXTERNAL_ID="aiops-workshop-2026"
TARGET_ROLE_ARN="arn:aws:iam::${TARGET_ACCOUNT_ID}:role/${TARGET_ROLE_NAME}"
```

AssumeRole 동작 확인 (수동 테스트):

```bash
aws sts assume-role \
  --role-arn "$TARGET_ROLE_ARN" \
  --role-session-name workshop-participant \
  --external-id "$EXTERNAL_ID"
```

정상 시 `Credentials` (AccessKeyId, SecretAccessKey, SessionToken) 가 반환됩니다. 에러 발생 시 행사 진행자에게 문의하세요.

### 2-3. Deploy — Agent Account (Lambda 가 있는 계정)

#### Step B — Lambda Role 에 AssumeRole 권한 추가

Agent 계정에서 실행 (Step A 에서 설정한 환경변수 유지):

```bash
DEMO_USER="${DEMO_USER:-ubuntu}"

cat > /tmp/assume-role-policy.json << EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "sts:AssumeRole",
      "Resource": "${TARGET_ROLE_ARN}"
    }
  ]
}
EOF

aws iam put-role-policy \
  --role-name "aiops-demo-${DEMO_USER}-cloudwatch-wrapper-role" \
  --policy-name "cross-account-assume" \
  --policy-document file:///tmp/assume-role-policy.json
```

#### Step C — Lambda 환경변수에 Target Role ARN 설정

```bash
aws lambda update-function-configuration \
  --function-name "aiops-demo-${DEMO_USER}-cloudwatch-wrapper" \
  --environment "Variables={DEMO_USER=${DEMO_USER},CROSS_ACCOUNT_ROLE_ARN=${TARGET_ROLE_ARN},EXTERNAL_ID=${EXTERNAL_ID}}" \
  --region "${AWS_REGION:-us-west-2}"
```

#### Step D — Lambda 코드 업데이트 (AssumeRole 로직 추가)

기존 handler 를 백업한 뒤, cross-account 지원 버전으로 교체합니다:

```bash
cd /workshop/aiops-multi-agent-workshop/infra/cognito-gateway/lambda/cloudwatch_wrapper

# 기존 파일 백업
cp handler.py handler.py.bak

# cross-account 버전 생성
cat > handler.py << 'EOF'
"""cloudwatch-wrapper Lambda — Cross-account support (Phase 6)."""
import os

import boto3

DEMO_USER = os.environ["DEMO_USER"]
ALARM_PREFIX = f"payment-{DEMO_USER}-"
CROSS_ACCOUNT_ROLE_ARN = os.environ.get("CROSS_ACCOUNT_ROLE_ARN")
EXTERNAL_ID = os.environ.get("EXTERNAL_ID")


def _get_cw_client():
    """Cross-account role 설정 시 AssumeRole, 미설정 시 로컬 계정."""
    if CROSS_ACCOUNT_ROLE_ARN:
        sts = boto3.client("sts")
        params = {
            "RoleArn": CROSS_ACCOUNT_ROLE_ARN,
            "RoleSessionName": "aiops-monitor-cross-account",
        }
        if EXTERNAL_ID:
            params["ExternalId"] = EXTERNAL_ID
        creds = sts.assume_role(**params)["Credentials"]
        return boto3.client(
            "cloudwatch",
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
        )
    return boto3.client("cloudwatch")


cw = _get_cw_client()


def _tool_name(context) -> str:
    cc = getattr(context, "client_context", None)
    custom = getattr(cc, "custom", None) if cc else None
    return (custom or {}).get("bedrockAgentCoreToolName", "")


def _classification(alarm_arn: str) -> str | None:
    resp = cw.list_tags_for_resource(ResourceARN=alarm_arn)
    for tag in resp.get("Tags", []):
        if tag["Key"] == "Classification":
            return tag["Value"]
    return None


def _ts(value) -> str | None:
    return value.isoformat() if value else None


def lambda_handler(event, context):
    tool = _tool_name(context)
    params = event or {}

    if tool.endswith("list_live_alarms"):
        resp = cw.describe_alarms(AlarmNamePrefix=ALARM_PREFIX)
        alarms = []
        for a in resp.get("MetricAlarms", []):
            alarms.append({
                "name": a["AlarmName"],
                "state": a["StateValue"],
                "state_reason": a.get("StateReason", ""),
                "metric_name": a.get("MetricName"),
                "namespace": a.get("Namespace"),
                "threshold": a.get("Threshold"),
                "classification": _classification(a["AlarmArn"]),
                "updated": _ts(a.get("StateUpdatedTimestamp")),
            })
        return {"alarms": alarms}

    if tool.endswith("get_live_alarm_history"):
        if "alarm_name" not in params:
            return {"error": "alarm_name is required"}
        resp = cw.describe_alarm_history(
            AlarmName=params["alarm_name"],
            HistoryItemType=params.get("type", "StateUpdate"),
            MaxRecords=int(params.get("max", 20)),
        )
        return {
            "history": [{
                "ts": _ts(h["Timestamp"]),
                "summary": h["HistorySummary"],
                "type": h["HistoryItemType"],
            } for h in resp.get("AlarmHistoryItems", [])]
        }

    return {"error": f"unknown tool: {tool!r}"}
EOF
```

> **원복 방법**: `cp handler.py.bak handler.py` 로 즉시 Phase 5 이전 상태로 복원 가능.

Lambda 코드 배포 (CFN re-deploy):

```bash
cd /workshop/aiops-multi-agent-workshop
bash infra/cognito-gateway/deploy.sh
```

> **참고**: `deploy.sh` 는 idempotent — Gateway/Target 기존 자원 재사용, Lambda 코드만 업데이트.

#### Step E — `.env` 갱신

```bash
# .env 에 cross-account 설정 추가
cat >> .env << EOF
CROSS_ACCOUNT_ROLE_ARN=${TARGET_ROLE_ARN}
TARGET_ACCOUNT_ID=${TARGET_ACCOUNT_ID}
EOF
source .env
```

### 2-4. 검증

#### Supervisor 를 통한 Target Account alarm 분석

Phase 5 에서 배포한 Supervisor Runtime 에 질문하여 cross-account alarm 을 분석합니다:

```bash
set -a; source .env; set +a
uv run agents/supervisor/runtime/invoke_runtime.py --query "Target Account의 현재 알람 상태를 분석하고 진단해줘"
```

기대: Supervisor 가 Monitor A2A → cloudwatch_wrapper Lambda → (AssumeRole) → Target Account CloudWatch 경로로 alarm 을 조회하고, Incident A2A 를 통해 진단 결과까지 통합 반환.

```json
{
  "summary": "Target Account 알람 분석 결과...",
  "monitor": "라이브 알람 N개 중 real M개...",
  "incidents": [...],
  "next_steps": [...]
}
```

#### AssumeRole 성공 확인

Lambda 가 정상적으로 AssumeRole 하는지 CloudWatch Logs 에서 확인:

```bash
aws logs tail "/aws/lambda/aiops-demo-${DEMO_USER}-cloudwatch-wrapper" \
  --since 5m --region "${AWS_REGION:-us-west-2}"
```

에러 없이 alarm 응답이 반환되면 성공.

#### STS 호출 확인 (CloudTrail)

Target Account 의 CloudTrail 에서 AssumeRole 이벤트 확인:

```bash
aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=EventName,AttributeValue=AssumeRole \
  --max-results 5 --region "${AWS_REGION:-us-west-2}"
```

#### 통과 기준

- Lambda 가 Target Account alarm 을 정상 조회
- Agent 가 cross-account alarm 에 대해 noise/real 분류 수행
- CloudTrail 에 AssumeRole 이벤트 기록 확인
- `CROSS_ACCOUNT_ROLE_ARN` 미설정 시 기존 동작 (자기 계정) 유지 (하위 호환)

### 2-5. 다음 단계 또는 정리

**정리 — Target Account Role 삭제**:

```bash
# Target Account 에서 실행
aws iam delete-role-policy --role-name aiops-cross-account-monitoring-role --policy-name cloudwatch-read
aws iam delete-role --role-name aiops-cross-account-monitoring-role
```

**정리 — Agent Account 원복**:

```bash
# Lambda 환경변수에서 cross-account 설정 제거
aws lambda update-function-configuration \
  --function-name "aiops-demo-${DEMO_USER}-cloudwatch-wrapper" \
  --environment "Variables={DEMO_USER=${DEMO_USER}}" \
  --region "${AWS_REGION:-us-west-2}"

# Lambda Role 에서 cross-account policy 제거
aws iam delete-role-policy \
  --role-name "aiops-demo-${DEMO_USER}-cloudwatch-wrapper-role" \
  --policy-name "cross-account-assume"
```

**완전 정리** (모든 phase 자원 일괄):

```bash
bash teardown_all.sh
```

---

## 3. 무엇을 만드나   *(~3 min read)*

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Agent Account                                       │
│                                                                             │
│  ┌──────────────┐       ┌──────────────────┐       ┌─────────────────────┐  │
│  │ Strands Agent│──MCP─▶│ AgentCore Gateway│──────▶│ cloudwatch_wrapper  │  │
│  │ (local/      │ Bearer│ (CUSTOM_JWT)     │ IAM   │ Lambda              │  │
│  │  Runtime)    │  JWT  │                  │invoke │                     │  │
│  └──────────────┘       └──────────────────┘       └──────────┬──────────┘  │
│                                                               │             │
│                                                    sts:AssumeRole           │
│                                                               │             │
└───────────────────────────────────────────────────────────────┼─────────────┘
                                                                │
                                                                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Target Account                                      │
│                                                                             │
│  ┌──────────────────────────────────────────────┐                           │
│  │ IAM Role: aiops-cross-account-monitoring-role│                           │
│  │  - Trust: Agent Account Lambda Role          │                           │
│  │  - Condition: ExternalId match               │                           │
│  │  - Policy: cloudwatch:Describe*/ListTags*    │                           │
│  └──────────────────────────────┬───────────────┘                           │
│                                 │                                           │
│                                 ▼                                           │
│  ┌──────────────────────────────────────────────┐                           │
│  │ CloudWatch Alarms                            │                           │
│  │  └─ payment-*-status-check, payment-*-cpu... │                           │
│  └──────────────────────────────────────────────┘                           │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

**핵심**: 기존 Agent 인프라 (Gateway + Lambda) 는 그대로 — Lambda 내부에 AssumeRole 한 줄 추가로 cross-account 확장. `CROSS_ACCOUNT_ROLE_ARN` 환경변수 유무로 동작 분기 (하위 호환 유지).

---

## 4. 어떻게 동작   *(~10 min read)*

### IAM 자원 (2개 계정에 걸침)


| 계정 | 자원 | 역할 |
|---|---|---|
| **Agent Account** | `cloudwatch-wrapper-role` + inline policy `cross-account-assume` | Lambda 가 Target Role 을 assume 할 수 있는 권한 |
| **Target Account** | `aiops-cross-account-monitoring-role` + trust policy + `cloudwatch-read` policy | Agent 에게 CloudWatch 읽기 권한 위임 |


### Cross-Account IAM 신뢰 관계


| 구성 요소 | 값 | 설명 |
|---|---|---|
| Trust Principal | `arn:aws:iam::<AGENT_ACCOUNT>:role/aiops-demo-${DEMO_USER}-cloudwatch-wrapper-role` | 이 Role 만 assume 가능 |
| ExternalId | `aiops-workshop-2026` (행사 진행자 제공) | confused deputy 방지 |
| Permission | `cloudwatch:DescribeAlarms`, `DescribeAlarmHistory`, `ListTagsForResource` | 최소 권한 |


### 시퀀스 다이어그램

```
Agent       Gateway     Lambda          STS             Target CW
  │            │           │              │                 │
  │  MCP call  │           │              │                 │
  ├───────────▶│           │              │                 │
  │            │  invoke   │              │                 │
  │            ├──────────▶│              │                 │
  │            │           │              │                 │
  │            │           │ AssumeRole   │                 │
  │            │           ├─────────────▶│                 │
  │            │           │ temp creds   │                 │
  │            │           │◀─────────────┤                 │
  │            │           │              │                 │
  │            │           │  DescribeAlarms (temp creds)   │
  │            │           ├────────────────────────────────▶│
  │            │           │  alarms response               │
  │            │           │◀────────────────────────────────┤
  │            │           │              │                 │
  │            │  response │              │                 │
  │            │◀──────────┤              │                 │
  │  tool result           │              │                 │
  │◀───────────┤           │              │                 │
```

### Lambda 코드 변경점 (diff)

기존 Phase 2 코드와의 차이:

```diff
+ CROSS_ACCOUNT_ROLE_ARN = os.environ.get("CROSS_ACCOUNT_ROLE_ARN")
+ EXTERNAL_ID = os.environ.get("EXTERNAL_ID")
+
+ def _get_cw_client():
+     if CROSS_ACCOUNT_ROLE_ARN:
+         sts = boto3.client("sts")
+         params = {
+             "RoleArn": CROSS_ACCOUNT_ROLE_ARN,
+             "RoleSessionName": "aiops-monitor-cross-account",
+         }
+         if EXTERNAL_ID:
+             params["ExternalId"] = EXTERNAL_ID
+         creds = sts.assume_role(**params)["Credentials"]
+         return boto3.client(
+             "cloudwatch",
+             aws_access_key_id=creds["AccessKeyId"],
+             aws_secret_access_key=creds["SecretAccessKey"],
+             aws_session_token=creds["SessionToken"],
+         )
+     return boto3.client("cloudwatch")
+
- cw = boto3.client("cloudwatch")
+ cw = _get_cw_client()
```

### 보안 고려사항


| 항목 | 설명 |
|---|---|
| **ExternalId** | confused deputy 문제 방지 — Lambda 가 의도하지 않은 계정의 role 을 assume 하는 것을 차단 |
| **최소 권한** | Target Role 에 CloudWatch read 만 부여 (write/delete 불가) |
| **Trust 범위** | 특정 Lambda Role ARN 만 허용 (계정 전체 `root` 가 아님) |
| **임시 자격증명** | AssumeRole 결과는 1시간 TTL 임시 토큰 — 영구 키 노출 위험 없음 |
| **하위 호환** | `CROSS_ACCOUNT_ROLE_ARN` 미설정 시 기존 동작 유지 |


### Multi-Account 확장 패턴

N개 계정을 모니터링해야 할 경우:

```python
# 환경변수: CROSS_ACCOUNT_ROLES=role_arn_1,role_arn_2,...
roles = os.environ.get("CROSS_ACCOUNT_ROLES", "").split(",")
for role_arn in roles:
    cw = _get_cw_client_for(role_arn)
    alarms += _fetch_alarms(cw)
```

→ 본 Phase 6 는 단일 Target Account 로 패턴 학습. 복수 계정은 동일 패턴 반복.

---

## 5. References


| 자료 | 용도 |
|---|---|
| [AWS STS AssumeRole](https://docs.aws.amazon.com/STS/latest/APIReference/API_AssumeRole.html) | AssumeRole API 레퍼런스 |
| [Cross-account IAM roles](https://docs.aws.amazon.com/IAM/latest/UserGuide/tutorial_cross-account-with-roles.html) | AWS 공식 cross-account 튜토리얼 |
| [Confused deputy problem](https://docs.aws.amazon.com/IAM/latest/UserGuide/confused-deputy.html) | ExternalId 사용 이유 |
| [`infra/cognito-gateway/cognito.yaml`](../../infra/cognito-gateway/cognito.yaml) | CloudWatchWrapperLambdaRole 원본 |
| [`infra/cognito-gateway/lambda/cloudwatch_wrapper/handler.py`](../../infra/cognito-gateway/lambda/cloudwatch_wrapper/handler.py) | Lambda 코드 원본 |
| [`docs/learn/phase2.md`](phase2.md) | Gateway + Lambda 기본 구조 (Phase 6 의 기반) |
