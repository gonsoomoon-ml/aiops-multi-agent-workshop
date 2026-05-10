# Phase 2 — Gateway + MCP 도구 외부화

> 이 문서는 Phase 2 implementation 전에 합의된 design 이다. Phase 0 audit 와 동일한 형식.
> SoT 는 `plan_summary.md`. 이 문서는 Phase 2 한정 상세.

## 1. 목표 + Acceptance

### 1-1. 목표

Monitor Agent 가 사용하는 도구(`alarm_history`, `cloudwatch_describe_alarms`)를 **Strands tool import 방식 → AgentCore Gateway + MCP streamable-http** 로 외부화. agent 코드에 도구 import 0건 (시스템 목표 C2).

### 1-2. Acceptance criteria

| ID | 항목 | 검증 방법 |
|---|---|---|
| P2-A1 | `agents/monitor/shared/agent.py` 에 도구 본체 import 0건 | `grep -r "from .tools" agents/monitor/` → 결과 없음 |
| P2-A2 | Monitor Agent 가 MCPClient (streamable-http) 로 Gateway 호출 | runtime log 에 MCP request 흔적 |
| P2-A3 | Gateway → history mock Lambda Target → 응답 shape = Phase 1 mock 동일 | `agents/monitor/local/run.py` 출력이 Phase 1 5/5 결과와 동일 |
| P2-A4 | Gateway → CloudWatch native Target → Phase 0 라이브 알람 2개 (`payment-ubuntu-{status-check,noisy-cpu}`) 반환 | Monitor 출력에 두 알람 모두 등장 + `Tags.Classification` 라벨 활용 |
| P2-A5 | Monitor 가 `noisy-cpu` 를 noise 로, `status-check` 를 real 로 분류 (라이브 데이터) | 출력의 "실제로 봐야 할 알람" 섹션에 `status-check` 만 등장 |

### 1-3. 비범위 (out of scope)

- **Monitor Agent Runtime 승격** — Phase 3 (이번엔 로컬 유지, Gateway 만 외부)
- **GitHub Lambda Target** — Phase 5 (NL Policy readonly 거부 시연 시 도입)
- **Incident / Change / Supervisor** — Phase 4~6
- **C1 검증** (로컬 = Runtime 응답) — Phase 3 (Runtime 승격 시점)

### 1-4. 산출물 인벤토리 (예상 — design 진입 시점 기록)

> 갱신 이력: 초기 설계 (2 CFN stacks) → Smithy 폐기 후 Intent Lambda wrapper 통일 → Hybrid (CFN + boto3, ec-customer-support 패턴) 채택. 확정치는 Section 7-7 참조.

| 카테고리 | 항목 | 수 |
|---|---|---|
| AgentCore | Gateway | 1 (boto3 `setup_gateway.py` 로 생성, educational) |
| AgentCore | Gateway Target | 2 (cloudwatch_wrapper + history_mock Lambda — boto3 setup) |
| Lambda | 함수 (cloudwatch_wrapper + history_mock) | 2 |
| Cognito | UserPool + Domain + ResourceServer + Client | 4 (Phase 4+ 와 공유 예정 — Phase 2 = Client 만) |
| IAM | Gateway execution role + Lambda execution role × 2 | 3 |
| S3 | DEPLOY_BUCKET (phase-shared) | 1 |
| CloudFormation | 새 스택 | **1** (cognito.yaml 통합 — UserPool + Lambda + IAM Role) |
| boto3 setup | `setup_gateway.py` + `cleanup_gateway.py` | 2 (Gateway/Target 생성·삭제 — educational, ec-customer-support 패턴) |
| Strands | Monitor Agent tool refactor | 1 (`agent.py` caller 주입 + `mcp_client.py` 신규 + `auth/cognito_token.py` transitional) |

### 1-5. 의존

- ✅ Phase 0 라이브 (EC2 + 알람 2개 + tag `Classification`)
- ✅ Phase 1 mock 데이터 (`data/mock/phase1/alarm_history.py`) — Lambda 가 같은 데이터 노출
- 베이스 코드:
  - A2A 샘플 `cloudformation/cognito.yaml` — UserPool + Client M2M scope 패턴
  - A2A 샘플 `monitoring_strands_agent/utils.py` — MCPClient streamable-http 호출 패턴 (Phase 3 OAuth2 패턴 reference)
  - **ec-customer-support-e2e-agentcore `notebooks/lab-03-agentcore-gateway.ipynb`** — boto3 step-by-step Gateway/Target 생성 패턴 (Section 3 hybrid design 의 educational core)
  - 신규: 2 Lambda 함수 (cloudwatch_wrapper + history_mock — Section 4 + 5)

## 2. 인증·데이터 흐름

### 2-1. Phase 2 한정 흐름 (Monitor 로컬, Gateway 외부)

```
Monitor Agent (local Python, dev machine)
    │
    │ ① Cognito Client 자격증명 (.env: CLIENT_ID + CLIENT_SECRET)
    ▼
Cognito UserPool token endpoint
    │
    │ ② access_token (JWT, scope=gateway/invoke)
    ▼
Monitor Agent (token 메모리 캐시)
    │
    │ ③ MCP streamable-http POST + Authorization: Bearer <jwt>
    ▼
AgentCore Gateway
    │  - CustomJWTAuthorizer: Cognito DiscoveryUrl + AllowedClients=[Client]
    │  - 토큰 검증: scope에 `<resource-server>/invoke` 포함 여부
    │
    ├─ Target 1 (Smithy → AWS SigV4) → CloudWatch API
    │     - cloudwatch:DescribeAlarms
    │     - cloudwatch:DescribeAlarmHistory
    │
    └─ Target 2 (Lambda invoke) → history mock Lambda
          - Phase 1 mock 데이터 (5 alarms × 24 events) Lambda 핸들러로 wrap
```

### 2-2. Phase 3 이후 변형 (참고)

Phase 3 에서 Monitor 를 AgentCore Runtime 으로 승격하면:
- ① Cognito client_credentials 직접 호출 코드 **제거**
- 새로 `AWS::BedrockAgentCore::OAuth2CredentialProvider` **CFN native 자원** 추가 (CredentialProviderVendor=`CustomOauth2`, ClientId/Secret = Cognito Client). 2026-05 시점 GA — A2A 샘플(2025-04)의 Lambda Custom Resource 패턴은 더 이상 불필요.
- Runtime 코드가 `bedrock_agentcore_client.get_resource_oauth2_token(workloadIdentityToken=..., resourceCredentialProviderName=<provider>, scopes=[], oauth2Flow="M2M")` 호출 → access token 자동 획득
- 호출 패턴은 A2A 샘플 `monitoring_strands_agent/utils.py:27-48` 그대로 (Lambda Custom Resource 부분만 CFN 자원으로 대체)

→ Phase 2 의 Cognito POST helper 는 "임시 발판" → Phase 3 transition 시 helper 통째 삭제 + OAuth2CredentialProvider CFN 자원 추가 (template 한 자원, ~10줄).

### 2-3. Cognito stack 도입 범위 (decision)

**Phase 2 = Client 만** (minimum). Client A/B 는 Phase 4 에서 stack update 로 추가.

### 2-4. Cognito UserPool 이름 (decision)

**`aiops-demo-${DEMO_USER}-userpool`** — Phase 0 패턴 따라 multi-user prefix 포함.

### 2-5. Gateway 인증 설정

| 항목 | 값 |
|---|---|
| Gateway 이름 | `aiops-demo-${DEMO_USER}-gateway` |
| Authorizer | Cognito UserPool (OIDC) |
| Audience | Cognito Client |
| Required scope | `gateway/invoke` (UserPool resource server 정의) |
| Endpoint | `https://<gateway-id>.gateway.bedrock-agentcore.<region>.amazonaws.com/mcp` |

### 2-6. Token 캐시 정책 (decision)

**메모리 캐시 1h** (JWT 기본 만료). 매 호출마다 `now < expires_at - 60s` 체크 → 통과 시 재사용. helper 함수 1개 안에 캡슐화 → Phase 3 transition 시 helper 통째 삭제.

### 2-7. Gateway → Target 인증

| Target | Gateway 가 호출 시 사용 |
|---|---|
| CloudWatch native | Gateway execution Role (IAM, SigV4 자동) |
| history mock Lambda | Gateway execution Role (Lambda invoke 권한) |

→ Gateway IAM Role 1개에 두 Target 의 권한 통합 (Phase 0 의 IAM Role 1개 통합 패턴 동일).

### 2-8. 의도된 비대칭 (Phase 2 → 3)

Phase 2 Monitor 코드:
```python
# 임시 (Phase 3 에서 제거):
token = requests.post(cognito_token_url, data={
    "grant_type": "client_credentials",
    "client_id": COGNITO_CLIENT_ID,
    "client_secret": COGNITO_CLIENT_SECRET,
    "scope": "gateway/invoke",
}).json()["access_token"]

mcp_client = MCPClient(transport=StreamableHttpTransport(
    url=GATEWAY_URL,
    headers={"Authorization": f"Bearer {token}"},
))
```

Phase 3 변경:
```python
# Runtime 환경에서 AgentCore Identity 가 자동 주입
mcp_client = MCPClient(transport=StreamableHttpTransport(url=GATEWAY_URL))
# token 코드 통째 제거
```

→ Phase 2 PR 에서 token 코드를 별도 helper 함수로 분리해두면 Phase 3 에서 helper 만 삭제하면 됨.

## 3. Gateway + Cognito 인프라 상세

> **Research 결과** (`A2A-multi-agent-incident-response/cloudformation/{cognito,monitoring_agent}.yaml` 기준):
> - AgentCore Gateway 는 CFN 지원됨 (`AWS::BedrockAgentCore::Gateway` + `AWS::BedrockAgentCore::GatewayTarget`)
> - "AgentCore Identity Provider" 별도 자원 없음 — `OAuth2CredentialProvider` 가 실체 (Lambda Custom Resource 로 생성, Runtime 전용)
> - Phase 2 (Monitor 로컬) 에선 `OAuth2CredentialProvider` 불필요 — Phase 3 Runtime 승격 시 추가

### 3-1. 배포 단위 — Hybrid (CFN + boto3, ec-customer-support 패턴)

**핵심 결정 (2026-05-04)**: AgentCore 자원 (Gateway, GatewayTarget) 은 boto3 step-by-step 으로 생성 — educational 가치. 표준 AWS 자원 (Cognito, Lambda, IAM) 은 CFN.

| 단위 | 자원 | 배포 방식 | 이유 |
|---|---|---|---|
| **Stack 1 — `cognito.yaml`** (CFN) | UserPool + Domain + ResourceServer + Client + 2 Lambda 함수 + 2 Lambda execution role + Gateway IAM Role | **CFN** | 표준 AWS 자원 — declarative + idempotent + rollback. ec-customer-support 의 "사전 setup" 패턴 |
| **Step 2 — `setup_gateway.py`** (boto3) | Gateway + GatewayTarget × 2 (CloudWatch wrapper + history mock) | **boto3** (`bedrock-agentcore-control` client) | **AgentCore 학습 핵심** — step 별 print + 응답 가시화. ec-customer-support 의 lab-03 패턴 차용 |

→ 진입점: `bash infra/cognito-gateway/deploy.sh` 가 (1) CFN stack deploy → (2) `setup_gateway.py` 호출 → (3) `.env` 갱신 단일 흐름.

**Educational 가치 명시**:
- audience 가 `setup_gateway.py` 한 줄씩 따라가며 AgentCore Gateway 학습
- 각 step print 로 가시화 (Step 1 = Gateway 생성 + GatewayId 출력, Step 2 = CloudWatch Wrapper Target 추가, Step 3 = History Mock Target 추가)
- yaml 안에 묻힌 spec 학습 부담 회피
- 사용자 own codebase (ec-customer-support) 와 동일 mental model

> **Stack 이름 변경**: 이전 design `aiops-demo-${DEMO_USER}-cognito-gateway` 와 `-phase2-gateway` 였으나, hybrid 채택 후 단일 stack: `aiops-demo-${DEMO_USER}-cognito-gateway` (Cognito + Lambda + IAM 통합). Gateway 는 CFN stack 외 (boto3 자원 — `aws cloudformation describe-stacks` 으로 조회 안 됨, 대신 `aws bedrock-agentcore list-gateways`).

### 3-2. Cognito stack 자원 (CFN)

CFN 스택 이름: `aiops-demo-${DEMO_USER}-cognito-gateway`

| 자원 | 이름 | 핵심 속성 |
|---|---|---|
| `AWS::Cognito::UserPool` | `aiops-demo-${DEMO_USER}-userpool` | passwordless (M2M 만 사용), MFA off |
| `AWS::Cognito::UserPoolDomain` | `aiops-demo-${DEMO_USER}` | (region-account 단위 unique) |
| `AWS::Cognito::UserPoolResourceServer` | identifier = `aiops-demo-${DEMO_USER}-resource-server`, name=`Gateway Invoke` | scope `invoke` (full name = `aiops-demo-${DEMO_USER}-resource-server/invoke`) |
| `AWS::Cognito::UserPoolClient` (Client) | `aiops-demo-${DEMO_USER}-client` | `AllowedOAuthFlows=client_credentials`, `AllowedOAuthScopes=<resource-server-id>/invoke`, `GenerateSecret=true` |

> ResourceServer Identifier 명명: A2A 샘플은 `${StackName}-resource-server` (cognito.yaml:63). 우리도 동일 패턴 사용 (multi-user prefix 자동 포함).

**Outputs**:
- `UserPoolId`, `Domain`, `ClientId` (CFN output)
- `ClientSecret` — CFN output 으로는 secret 노출 X. **deploy.sh 가 stack deploy 후 `aws cognito-idp describe-user-pool-client` 로 별도 조회**해 `.env` 갱신 (A2A 샘플은 Lambda Custom Resource 로 Secrets Manager 에 저장하지만 우리는 `.env` 만 — minimum)

### 3-3-A. CFN stack 추가 자원 (cognito.yaml 안에 통합)

cognito.yaml 가 표준 AWS 자원 모두 담당 — Section 3-2 의 Cognito 자원 + 아래:

| 자원 | CFN 타입 | 핵심 속성 |
|---|---|---|
| Lambda 함수 (history mock) | `AWS::Lambda::Function` | name `aiops-demo-${DEMO_USER}-history-mock`, Runtime=python3.13, mock 데이터 vendor (Section 5) |
| Lambda 함수 (CloudWatch wrapper) | `AWS::Lambda::Function` | name `aiops-demo-${DEMO_USER}-cloudwatch-wrapper`, intent-shaped (Section 4) |
| Lambda execution role × 2 | `AWS::IAM::Role` | history-mock = logs only / cloudwatch-wrapper = CloudWatch Describe* + logs (Section 4-4) |
| Gateway IAM Role | `AWS::IAM::Role` | trust: `bedrock-agentcore.amazonaws.com`, lambda:InvokeFunction 만 (Section 3-4) |

**CFN Outputs** (deploy.sh 가 `setup_gateway.py` 에 주입):
- `LambdaHistoryMockArn`, `LambdaCloudWatchWrapperArn`
- `GatewayIamRoleArn`
- (Cognito outputs: `UserPoolId`, `Domain`, `ClientId`, `ResourceServerScope`)

### 3-3-B. boto3 step (`setup_gateway.py`) — AgentCore 자원

`setup_gateway.py` outline (ec-customer-support lab-03 패턴):

```python
# infra/cognito-gateway/setup_gateway.py
"""
Phase 2 — AgentCore Gateway 생성 (boto3 step-by-step, educational).

ec-customer-support-e2e-agentcore lab-03 패턴 차용 — audience 가 한 줄씩 따라가며 학습.
표준 AWS 자원 (Cognito, Lambda, IAM Role) 은 cognito.yaml CFN stack 이 담당.

Idempotent: 이미 같은 이름의 Gateway/Target 있으면 기존 ID 재사용.
"""
import boto3, os, sys
from typing import Optional

REGION = os.environ.get("AWS_REGION", "us-west-2")
DEMO_USER = os.environ["DEMO_USER"]

gateway_client = boto3.client("bedrock-agentcore-control", region_name=REGION)

def step1_create_gateway(role_arn, cognito_pool_id, client_id, scope) -> dict:
    print("\n=== Step 1: AgentCore Gateway 생성 ===")
    name = f"aiops-demo-{DEMO_USER}-gateway"
    # idempotent: list_gateways 후 매칭
    existing = next((g for g in gateway_client.list_gateways()["items"] if g["name"] == name), None)
    if existing:
        print(f"  이미 존재: gatewayId={existing['gatewayId']} (재사용)")
        return existing
    discovery_url = f"https://cognito-idp.{REGION}.amazonaws.com/{cognito_pool_id}/.well-known/openid-configuration"
    resp = gateway_client.create_gateway(
        name=name,
        roleArn=role_arn,
        protocolType="MCP",
        protocolConfiguration={"mcp": {"version": "2025-11-25"}},
        authorizerType="CUSTOM_JWT",
        authorizerConfiguration={"customJWTAuthorizer": {
            "discoveryUrl": discovery_url,
            "allowedClients": [client_id],
            "allowedScopes": [scope],
        }},
    )
    print(f"  ✅ gatewayId={resp['gatewayId']}, gatewayUrl={resp['gatewayUrl']}")
    return resp

def step2_create_target(gateway_id, name, lambda_arn, tool_schema) -> dict:
    print(f"\n=== Step 2: GatewayTarget '{name}' 추가 ===")
    # idempotent: list_gateway_targets 후 매칭
    existing = next((t for t in gateway_client.list_gateway_targets(gatewayIdentifier=gateway_id)["items"] if t["name"] == name), None)
    if existing:
        print(f"  이미 존재: targetId={existing['targetId']} (재사용)")
        return existing
    resp = gateway_client.create_gateway_target(
        gatewayIdentifier=gateway_id,
        name=name,
        targetConfiguration={"mcp": {"lambda": {
            "lambdaArn": lambda_arn,
            "toolSchema": {"inlinePayload": tool_schema},
        }}},
        credentialProviderConfigurations=[{"credentialProviderType": "GATEWAY_IAM_ROLE"}],
    )
    print(f"  ✅ targetId={resp['targetId']}")
    return resp

def main():
    # CFN outputs 를 환경변수로 주입 (deploy.sh 가 처리)
    role_arn = os.environ["GATEWAY_IAM_ROLE_ARN"]
    pool_id = os.environ["COGNITO_USER_POOL_ID"]
    client_id = os.environ["COGNITO_CLIENT_ID"]
    scope = os.environ["COGNITO_GATEWAY_SCOPE"]
    lambda_cw = os.environ["LAMBDA_CLOUDWATCH_WRAPPER_ARN"]
    lambda_history = os.environ["LAMBDA_HISTORY_MOCK_ARN"]

    gw = step1_create_gateway(role_arn, pool_id, client_id, scope)
    step2_create_target(gw["gatewayId"], "cloudwatch-wrapper", lambda_cw, CW_TOOL_SCHEMA)
    step2_create_target(gw["gatewayId"], "history-mock",       lambda_history, HISTORY_TOOL_SCHEMA)

    # 최종 출력 — deploy.sh 가 .env 갱신 시 사용
    print(f"\nGATEWAY_ID={gw['gatewayId']}")
    print(f"GATEWAY_URL={gw['gatewayUrl']}")

if __name__ == "__main__":
    main()
```

> **OAuth2CredentialProvider 미포함** — Phase 2 Monitor 로컬은 `get_resource_oauth2_token()` 안 씀 (Cognito token endpoint 직접 POST). Phase 3 Runtime 승격 시 `setup_oauth_provider.py` (boto3) 또는 hybrid 추가 — 같은 educational 패턴.

**Tool schema 정의** (Section 4-3 + 5-6 의 InlinePayload 구조 그대로):
- `CW_TOOL_SCHEMA` = `list_live_alarms` + `get_live_alarm_history` (Section 4-3)
- `HISTORY_TOOL_SCHEMA` = `get_past_alarms_metadata` + `get_past_alarm_history` (Section 5-6)

→ Python literal list[dict] 로 setup_gateway.py 안에 정의 (yaml 변환 없음 — boto3 가 그대로 받음).

### 3-4. IAM Role 권한 (Gateway execution)

Role 이름: `aiops-demo-${DEMO_USER}-gateway-role`

Trust policy: `bedrock-agentcore.amazonaws.com` assume

Inline policy (single, minimum) — **Lambda invoke 만**:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "InvokeWrapperLambdas",
      "Effect": "Allow",
      "Action": "lambda:InvokeFunction",
      "Resource": [
        "arn:aws:lambda:${REGION}:${ACCOUNT}:function:aiops-demo-${DEMO_USER}-cloudwatch-wrapper",
        "arn:aws:lambda:${REGION}:${ACCOUNT}:function:aiops-demo-${DEMO_USER}-history-mock"
      ]
    }
  ]
}
```

> Smithy 폐기로 Gateway 가 CloudWatch SigV4 직접 호출 안 함 → CloudWatch 권한은 **wrapper Lambda 의 execution role** 로 이동 (Section 4-4). 책임 분리 깔끔.

각 Lambda 의 execution role 은 자기 책임 영역만:
- `cloudwatch-wrapper` Lambda: CloudWatch Describe* (Section 4-4)
- `history-mock` Lambda: 권한 거의 없음 (Section 5)

### 3-5. .env 변수 + Secret 처리

deploy.py / deploy.sh 가 채우는 .env 변수:

```
# Phase 2: Cognito
COGNITO_USER_POOL_ID=
COGNITO_DOMAIN=
COGNITO_CLIENT_ID=
COGNITO_CLIENT_SECRET=    # ← Cognito describe-user-pool-client 로 별도 조회

# Phase 2: Gateway
GATEWAY_ID=
GATEWAY_URL=
LAMBDA_HISTORY_MOCK_ARN=
```

**Secret 처리 옵션**:

| 옵션 | 위치 | 비교 |
|---|---|---|
| **(가)** `.env` 만 (gitignore 의존) — minimum | local file | Phase 0 patten 일관 (.env 만 사용). 단, 다중 dev machine 시 secret 공유 어려움 |
| (나) SSM SecureString | `/aiops-demo/cognito-client-secret` | Phase 0 GitHub PAT 와 동일 패턴. dev machine 어디서나 boto3 로 조회 |

**제 추천: (가)** — Phase 2 는 single dev machine 가정. `.env` 가 이미 gitignore + Phase 0 EC2 IP 등 다른 자원 정보 함께 있으므로 일관.

## 4. Target 1 — CloudWatch wrapper Lambda (Intent shape)

> **Smithy 폐기 결정 (2026-05-04)**: CloudWatch service Smithy 노출 시 ~100 operation 이 LLM tool list 에 들어가 token 비용 + 도구 선택 정확도 + 시간 상관 일관성 모두 약화. **Intent Lambda wrapper** 패턴으로 통일 — production AIOps 산업 표준.

### 4-1. Phase 2 노출 도구 (LLM 시점, 2개)

| 도구 명 | 의도 | 내부 호출 (Lambda) |
|---|---|---|
| `list_live_alarms` | 라이브 알람 목록 + 상태 + classification 라벨 | `cloudwatch:DescribeAlarms(AlarmNamePrefix="payment-")` 1회 |
| `get_live_alarm_history` | 특정 라이브 알람의 최근 상태 전이 (RCA 단서) | `cloudwatch:DescribeAlarmHistory(AlarmName=...)` 1회 |

→ Phase 2 minimum: 단일 알람 분류·진단까지. 시간 상관 RCA 는 Phase 3+ 에서 동일 명명 패턴 (`<verb>_live_<noun>`) 으로 도구 추가 (예: `investigate_live_alarm`, `fetch_live_metrics_window`).

> **명명 컨벤션 (전체 phase 일관)**: `<verb>_<past|live>_<noun>`. mock 도구 (`get_past_alarms_metadata`, `get_past_alarm_history`) 와 live 도구 (`list_live_alarms`, `get_live_alarm_history`) 가 페어 단어 (`past`/`live`) 만 다른 매트릭스 — LLM disambiguation 신호 최강. Phase 1 frozen baseline 의 도구 명도 이 컨벤션에 맞춰 rename (Section 6-2 + 6-7 참조).

### 4-2. Lambda 함수 outline

```python
# aiops-demo-${DEMO_USER}-cloudwatch-wrapper
import boto3, json

cw = boto3.client("cloudwatch")
DEMO_USER = os.environ["DEMO_USER"]   # 자원 prefix 매칭

def lambda_handler(event, context):
    tool = event["tool_name"]   # AgentCore Gateway 가 Lambda invoke 시 도구명 전달 (정확 구조 implementation 시 확인)
    params = event.get("input", {})

    if tool == "list_live_alarms":
        resp = cw.describe_alarms(AlarmNamePrefix=f"payment-{DEMO_USER}-")
        return {
            "alarms": [{
                "name": a["AlarmName"],
                "state": a["StateValue"],
                "state_reason": a.get("StateReason", ""),
                "metric_name": a.get("MetricName"),
                "namespace": a.get("Namespace"),
                "threshold": a.get("Threshold"),
                "classification": _get_tag(a, "Classification"),  # real | noise
                "updated": a.get("StateUpdatedTimestamp", "").isoformat() if a.get("StateUpdatedTimestamp") else None,
            } for a in resp["MetricAlarms"]]
        }

    elif tool == "get_live_alarm_history":
        resp = cw.describe_alarm_history(
            AlarmName=params["alarm_name"],
            HistoryItemType=params.get("type", "StateUpdate"),
            MaxRecords=params.get("max", 20),
        )
        return {
            "history": [{
                "ts": h["Timestamp"].isoformat(),
                "summary": h["HistorySummary"],
                "type": h["HistoryItemType"],
            } for h in resp["AlarmHistoryItems"]]
        }

    return {"error": f"unknown tool {tool}"}

def _get_tag(alarm, key):
    return next((t["Value"] for t in alarm.get("Tags", []) if t["Key"] == key), None)
```

> 응답 shape 는 LLM 친화적 — `StateUpdatedTimestamp` 같은 verbose 필드 제거, `classification` 을 top-level 로 끌어올림.

### 4-3. ToolSchema (InlinePayload)

```yaml
GatewayTargetCloudWatch:
  Type: AWS::BedrockAgentCore::GatewayTarget
  Properties:
    GatewayIdentifier: !Ref Gateway
    Name: cloudwatch-wrapper
    TargetConfiguration:
      Mcp:
        Lambda:
          LambdaArn: !GetAtt CloudWatchWrapperLambda.Arn
          ToolSchema:
            InlinePayload:
              - Name: list_live_alarms
                Description: "라이브 CloudWatch 알람 목록과 상태 + classification (real|noise) 라벨 조회. payment-${DEMO_USER}-* prefix."
                InputSchema:
                  Type: object
                  Properties: {}
              - Name: get_live_alarm_history
                Description: "특정 라이브 알람의 최근 상태 전이 history (RCA 단서). 페어: 과거 mock 데이터는 get_past_alarm_history."
                InputSchema:
                  Type: object
                  Required: [alarm_name]
                  Properties:
                    alarm_name: { Type: string }
                    type:       { Type: string, Enum: [StateUpdate, ConfigurationUpdate, Action] }
                    max:        { Type: integer, Default: 20 }
```

### 4-4. Lambda 실행 권한 (IAM Role)

CloudWatch wrapper Lambda 의 **자체 execution Role** (Gateway role 과 분리):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {"Effect": "Allow", "Action": ["cloudwatch:DescribeAlarms", "cloudwatch:DescribeAlarmHistory"], "Resource": "*"},
    {"Effect": "Allow", "Action": ["logs:CreateLogGroup","logs:CreateLogStream","logs:PutLogEvents"], "Resource": "*"}
  ]
}
```

→ Gateway IAM Role 은 두 Lambda 만 invoke (Section 3-4 갱신).

### 4-5. Phase 0 라이브 알람과의 연결

`list_live_alarms` 호출 시 기대 응답:
```json
{
  "alarms": [
    {"name": "payment-ubuntu-status-check", "state": "OK", "classification": "real", "metric_name": "StatusCheckFailed", ...},
    {"name": "payment-ubuntu-noisy-cpu",    "state": "OK", "classification": "noise", "metric_name": "CPUUtilization", ...}
  ]
}
```

→ Acceptance P2-A4/A5 매핑: Monitor 가 `classification: noise` 인 알람을 자동 noise 라벨링, `real` 만 "실제로 봐야 할 알람" 으로 분류.

### 4-6. Phase 3+ 확장 hook

같은 Lambda 에 도구 추가만으로 RCA 확장 가능:
- `investigate_alarm` (alarm + 관련 metric + log + state) — chain 1회 호출
- `fetch_metrics_window` (시간 윈도우 일관성 보장)
- `correlate_events` (CloudTrail summary)

ToolSchema InlinePayload 에 entry 추가 + Lambda 함수에 if-branch 추가만. CFN 변경 작음.

## 5. Target 2 — history mock Lambda

### 5-1. 목표

Phase 1 `data/mock/phase1/alarm_history.py` (5 alarms × 24 events × 3 진단 유형 — LLM 5/5 정확도 검증된 자료) 를 **Lambda 함수로 노출**하여 Gateway 경유로 호출 가능하게 함. 응답 shape = Phase 1 module 의 public accessor 와 동일 (acceptance P2-A3).

핵심 가치: agent 코드의 `from data.mock.phase1.alarm_history import ...` import 문을 제거하고 (P2-A1), 도구를 Gateway 뒤에 두어 Phase 3 Runtime 승격 시 도구 호출 경로 변경 0.

### 5-2. 노출 도구 (2개, Phase 1 public API 와 동일)

| 도구 명 | 의도 | 내부 호출 (Lambda) | 응답 shape |
|---|---|---|---|
| `get_past_alarms_metadata` | 5개 mock 알람 metadata (ground truth `_*` 필드 strip) | `get_past_alarms_metadata()` | `List[Dict]` — Phase 1 동일 (CW PascalCase, `Tags.Classification` 포함) |
| `get_past_alarm_history` | mock history 이벤트 (시간 윈도우 필터) | `get_past_alarm_history(days=N)` | `List[Dict]` — `Timestamp`/`HistorySummary`/`HistoryItemType`/`AlarmName`/synthesized `ack`/`action_taken` 포함 |

→ `get_ground_truth()` 는 **노출 안 함** (테스트 전용 — agent 가 ground truth 보면 학습 무의미).
→ **명명 컨벤션 일관**: `get_past_*` (mock) ↔ `get_live_*` (live) 페어. 페어 단어 (`past`/`live`) 만 다른 매트릭스 — LLM disambiguation 신호 최강.
→ **Phase 1 frozen baseline 영향**: `data/mock/phase1/alarm_history.py` 의 Python 함수 이름도 같이 rename (`get_alarms_metadata` → `get_past_alarms_metadata`, `get_history` → `get_past_alarm_history`). Phase 1 baseline 의 frozen contract 는 데이터 + 출력 + LLM 5/5 정확도 — 이름은 contract 외 (rename 후 1회 재검증으로 5/5 유지 확인).

### 5-3. Lambda 코드 outline

```python
# infra/cognito-gateway/lambda/history_mock/handler.py
import os, sys

# vendored data/mock — Lambda zip에 함께 패키징됨
from data.mock.phase1.alarm_history import get_past_alarms_metadata, get_past_alarm_history


def lambda_handler(event, context):
    tool = event.get("tool_name")            # Gateway → Lambda 의 정확 event shape implementation 시 확인
    params = event.get("input", {})

    if tool == "get_past_alarms_metadata":
        return {"alarms": get_past_alarms_metadata()}

    elif tool == "get_past_alarm_history":
        days = int(params.get("days", 7))
        return {"events": get_past_alarm_history(days=days)}

    return {"error": f"unknown tool: {tool}"}
```

> 응답이 그대로 LLM 프롬프트에 들어가므로 Phase 1 의 PascalCase + 한글 라벨 (`_diagnosis_type`) 정책 그대로 유지. Phase 1 system prompt + Phase 1 mock + Phase 2 Lambda → 출력이 5/5 정확도 그대로 재현되는 게 P2-A3 의 검증 신호.

### 5-4. mock data 출처 — DRY 결정 (vendoring)

| 옵션 | 설명 | 비교 |
|---|---|---|
| **(가)** Vendoring (Lambda zip 에 `data/mock/phase1/` 복사) — **제 추천** | deploy 시 zip build 가 `data/mock/phase1/` 디렉토리를 zip 에 추가 | 단일 진실 원천 (`data/mock/phase1/alarm_history.py`) 유지. Lambda 와 Phase 1 unit test 가 같은 모듈 import |
| (나) Copy fork | Lambda 디렉토리에 `alarm_history.py` 복사본 | DRY 위배. mock 변경 시 두 파일 동기화 필요 |
| (다) S3 데이터 | mock 데이터를 JSON 으로 S3 업로드 + Lambda 가 fetch | overengineering. 자료가 ~14KB literal Python 인데 RPC 추가 |

**(가) 권장 이유**:
1. `data/mock/phase1/` 는 향후 단위 테스트 / Phase 1 시연용으로도 유효
2. `cfn package` 가 `CodeUri: ./lambda/history_mock` 을 zip 시 우리는 build script (`make_zip.sh` 또는 `deploy.sh` 안 inline) 가 `cp -r data/mock/phase1 lambda/history_mock/` 1줄로 처리
3. Phase 1 unit test (`tests/test_monitor.py`) 와 Lambda 가 import path 동일

### 5-5. 패키징 (cfn package)

```yaml
HistoryMockLambda:
  Type: AWS::Lambda::Function
  Properties:
    FunctionName: !Sub aiops-demo-${DemoUser}-history-mock
    Runtime: python3.13
    Handler: handler.lambda_handler
    Code: ./lambda/history_mock        # cfn package 가 zip + S3 업로드 후 S3Bucket/S3Key 로 치환
    Role: !GetAtt HistoryMockLambdaRole.Arn
    Timeout: 10
    MemorySize: 128                    # 고정 mock 데이터, 메모리 부담 적음
```

deploy.sh 흐름:
```bash
# 0. DEPLOY_BUCKET 보장 (idempotent — Phase 2 첫 deploy 시 1회 생성, 이후 skip)
DEPLOY_BUCKET="aiops-demo-${DEMO_USER}-deploy-${ACCOUNT_ID}-${REGION}"
if ! aws s3api head-bucket --bucket "$DEPLOY_BUCKET" 2>/dev/null; then
    aws s3 mb "s3://$DEPLOY_BUCKET" --region "$REGION"
    aws s3api put-public-access-block --bucket "$DEPLOY_BUCKET" \
        --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
fi

# 1. data/mock 를 Lambda 디렉토리에 vendor
rm -rf infra/cognito-gateway/lambda/history_mock/data/mock
cp -r data/mock/phase1 infra/cognito-gateway/lambda/history_mock/data/mock/

# 2. cfn package — Code: ./local/path 를 zip + DEPLOY_BUCKET 업로드 후 S3Bucket/S3Key 로 치환
aws cloudformation package \
    --template-file infra/cognito-gateway/cognito.yaml \
    --s3-bucket "$DEPLOY_BUCKET" \
    --s3-prefix "cognito-gateway" \
    --output-template-file infra/cognito-gateway/cognito.packaged.yaml

# 3. CFN deploy (cognito.yaml 가 UserPool + Lambda + IAM Role 통합)
aws cloudformation deploy --template-file infra/cognito-gateway/cognito.packaged.yaml \
    --stack-name "aiops-demo-${DEMO_USER}-cognito-gateway" \
    --capabilities CAPABILITY_NAMED_IAM \
    --parameter-overrides DemoUser="${DEMO_USER}"

# 4. CFN outputs 환경변수 export
export COGNITO_USER_POOL_ID=$(aws cloudformation describe-stacks --stack-name "..." --query 'Stacks[0].Outputs[?OutputKey==`UserPoolId`].OutputValue' --output text)
export COGNITO_CLIENT_ID=...
export COGNITO_GATEWAY_SCOPE=...
export GATEWAY_IAM_ROLE_ARN=...
export LAMBDA_HISTORY_MOCK_ARN=...
export LAMBDA_CLOUDWATCH_WRAPPER_ARN=...
# Cognito Client Secret 별도 조회 (CFN output 미노출)
export COGNITO_CLIENT_SECRET=$(aws cognito-idp describe-user-pool-client --user-pool-id "$COGNITO_USER_POOL_ID" --client-id "$COGNITO_CLIENT_ID" --query 'UserPoolClient.ClientSecret' --output text)

# 5. boto3 setup — AgentCore Gateway + 2 GatewayTarget (educational, step-by-step)
uv run python infra/cognito-gateway/setup_gateway.py    # GATEWAY_ID + GATEWAY_URL 출력

# 6. .env 갱신 (위 환경변수들 + setup_gateway.py 출력 캡처)
```

### 5-5-1. DEPLOY_BUCKET 명명 + 라이프사이클

| 속성 | 값 | 이유 |
|---|---|---|
| 이름 | `aiops-demo-${DEMO_USER}-deploy-${ACCOUNT_ID}-${REGION}` | S3 bucket 명은 글로벌 unique → account+region suffix 로 충돌 방지. multi-user prefix 도 포함 (Phase 0 패턴 일관) |
| 생성 시점 | **Phase 2 첫 deploy.sh 실행 시 idempotent 생성** | 별도 bootstrap 스크립트 분리 안 함 (minimum). `head-bucket` 으로 존재 체크 → 없으면 `s3 mb` |
| 보안 설정 | Public access block 4종 모두 ON | 코드 zip 노출 방지 |
| 범위 | **Phase 2/4/5/6 공유** (phase-agnostic 이름) | Phase 4+ Lambda 도 같은 bucket 사용 |
| teardown | **stack 삭제 후 bucket 비우기 + 삭제 자동 수행** (deploy step 0 와 대칭) | 다음 phase deploy 시 step 0 가 idempotent 재생성하므로 안전. demo 종료 시 bucket leak 없음. teardown.sh 가 단일 cleanup 경로 (lifecycle 제거로 단순화 — Section 5-5-2 자동 정리만으로 leak 방지 충분) |

### 5-5-2. teardown.sh outline

```bash
# infra/cognito-gateway/teardown.sh
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
[[ -f "$PROJECT_ROOT/.env" ]] && { set -a; source "$PROJECT_ROOT/.env"; set +a; }

REGION="${AWS_REGION:-us-west-2}"
DEMO_USER="${DEMO_USER:-${USER:-ubuntu}}"
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
DEPLOY_BUCKET="aiops-demo-${DEMO_USER}-deploy-${ACCOUNT_ID}-${REGION}"

# 1. boto3 자원 먼저 삭제 (Gateway + GatewayTarget × 2) — CFN stack 이 Lambda invoke 권한 보유 중일 때 삭제 필요
uv run python infra/cognito-gateway/cleanup_gateway.py || true   # idempotent: 이미 삭제됐으면 skip

# 2. CFN stack 삭제 (cognito.yaml — UserPool + Lambda + IAM Role 통합)
aws cloudformation delete-stack --region "$REGION" --stack-name "aiops-demo-${DEMO_USER}-cognito-gateway" || true
aws cloudformation wait stack-delete-complete --region "$REGION" --stack-name "aiops-demo-${DEMO_USER}-cognito-gateway" 2>/dev/null || true

# 3. DEPLOY_BUCKET 비우기 + 삭제 (deploy step 0 와 대칭)
if aws s3api head-bucket --bucket "$DEPLOY_BUCKET" 2>/dev/null; then
    aws s3 rm "s3://$DEPLOY_BUCKET" --recursive
    aws s3 rb "s3://$DEPLOY_BUCKET"
fi

# 3. .env 갱신 — Phase 2 변수 비움
sed -i 's|^COGNITO_USER_POOL_ID=.*|COGNITO_USER_POOL_ID=|' "$PROJECT_ROOT/.env"
# ... (COGNITO_DOMAIN, COGNITO_CLIENT_ID/SECRET, GATEWAY_ID, GATEWAY_URL, LAMBDA_*_ARN)
```

> Phase 4/5/6 와 동시 진행 시 Phase 2 teardown 만 단독 호출하면 다른 phase 의 deploy 가 깨질 수 있음. 일반 demo 흐름 (Phase 2 단독 cleanup) 에선 무관. 향후 phase 간 의존이 생기면 `infra/teardown.sh` (전 phase 통합) 추가 검토.

## 6. Monitor Agent refactor

### 6-0. 폴더 구조 결정 (Phase 1 frozen baseline + current 진화)

전체 phase 흐름 (1 → 7) 을 고려해 **분리 권장**: Phase 1 demo 는 영구 frozen baseline, Phase 2+ 는 단일 `run.py` 로 진화.

**근거**:
- Phase 1 demo (mock 직접 import) = offline + AWS 의존 0 → educational baseline 으로 영구 가치 (신규 audience 즉시 LLM 5/5 재현, 회귀 격리 검증)
- Phase 2 demo (Gateway MCP + Cognito helper) = Phase 3 Runtime 으로 가는 scaffolding → frozen 부적절 (helper 도 transitional)
- 다른 agent (Incident/Change/Supervisor, Phase 4+) 는 Gateway+Runtime 시대에 도입 → single demo 만 보유 (Monitor 와 자연스러운 비대칭)

**audience-friendly 원칙 준수**: phase prefix (`run_phase2.py`) 금지. semantic name (`run_local_import.py`) 만 사용.

```
agents/monitor/                              (evolves through phases)
├── shared/
│   ├── agent.py                             # caller 가 tools + system_prompt_path 주입 (단일 진실 원천)
│   ├── prompts/
│   │   ├── system_prompt_past.md            # past 2 tools — Phase 1 baseline + Phase 2 mode=past 공유
│   │   └── system_prompt_live.md            # live 2 tools — Phase 2 mode=live 전용
│   ├── tools/                               # Phase 1 frozen demo가 import (보존)
│   │   └── alarm_history.py
│   ├── auth/                                # Phase 2 transitional (Phase 3에서 통째 삭제)
│   │   └── cognito_token.py
│   └── mcp_client.py                        # Phase 2 신규 (Phase 3에서 token 라인 simplify)
├── local/
│   ├── run_local_import.py                  # Phase 1 frozen baseline (offline, AWS 의존 0)
│   └── run.py                               # current production demo (Phase 2: Gateway MCP, Phase 3: Runtime, ...)
└── runtime/                                 (Phase 3에서 추가)
    └── entry.py
```

**호출 명령**:
```bash
# Phase 1 frozen baseline (어느 phase 가 와도 동작 — offline)
uv run python -m agents.monitor.local.run_local_import

# current production demo (Phase 2 = Gateway MCP)
uv run python -m agents.monitor.local.run
```

### 6-1. 3-state 비교 (Phase 1 baseline / Phase 2 current / Phase 3 current)

| 측면 | Phase 1 baseline (frozen) | **Phase 2 current** (이번) | Phase 3 current (다음) |
|---|---|---|---|
| 진입 파일 | `local/run_local_import.py` (영구 보존) | **`local/run.py`** (신규) | `local/run.py` (Phase 2 → 3 evolve) |
| system_prompt | `prompts/system_prompt_past.md` (2 past tools) | `prompts/system_prompt_past.md` (mode=past) / `prompts/system_prompt_live.md` (mode=live) | (진화 — Runtime 호출 form) |
| 도구 출처 | `from agents.monitor.shared.tools.alarm_history import ...` (Strands `@tool` mock) | **MCPClient streamable-http → Gateway** (4 도구) | 동일 (변경 없음) |
| `agent.py` 도구 import | **없음** (caller 주입) | **없음** (caller 주입) | **없음** |
| 인증 | 없음 (로컬 직접 import) | **Cognito client_credentials → Bearer token (1h cache helper)** | AgentCore Identity 자동 주입 (helper 제거) |
| MCPClient | 사용 안 함 | `agents/monitor/shared/mcp_client.py` (transport callable) | 동일 (token 인자 제거) |
| 실행 환경 | 로컬 Python (offline) | **로컬 Python (Gateway 호출)** | AgentCore Runtime |
| AWS 의존 | 0 | Cognito + Gateway + 2 Lambda + Phase 0 EC2 | + Runtime |

→ Phase 2 변경 = **`agents/monitor/shared/agent.py` 의 도구 import 제거 + 신규 `local/run.py` 가 Gateway MCP 호출**. Phase 1 baseline 은 unchanged.

### 6-2. 파일 단위 변경

| 파일 | Phase 2 변경 |
|---|---|
| `agents/monitor/shared/agent.py` | **refactor** — `create_agent(tools, system_prompt_path)` 시그니처 (caller 주입). Phase 1 baseline 도 같은 함수 호출 |
| `agents/monitor/shared/tools/alarm_history.py` | **보존** (Phase 1 frozen baseline 가 import) |
| `agents/monitor/shared/tools/__init__.py` | **보존** |
| `agents/monitor/shared/prompts/system_prompt.md` (현재 Phase 1 single prompt) | **rename → `system_prompt_past.md`** — past mode 전용 (2 past tools). baseline + Phase 2 mode=past 가 공유 |
| `agents/monitor/shared/prompts/system_prompt_live.md` | **신규** — live mode 전용 (2 live tools, Phase 2 mode=live 전용) |
| `agents/monitor/shared/tools/alarm_history.py` (Strands @tool) | **rename** — `get_alarm_history` (현재 wrapper 함수) → `get_past_alarm_history` 로 함수·@tool 동시 rename. 내부에서 `data.mock.phase1.alarm_history.{get_past_alarms_metadata, get_past_alarm_history}` import |
| `data/mock/phase1/alarm_history.py` (Python 함수) | **rename** — `get_alarms_metadata` → `get_past_alarms_metadata`, `get_history` → `get_past_alarm_history`. 함수 시그니처·반환 shape 그대로 (이름만 변경) |
| `agents/monitor/shared/auth/__init__.py` | **신규** (빈) |
| `agents/monitor/shared/auth/cognito_token.py` | **신규** — Cognito client_credentials POST + 1h cache (Phase 2 transitional, Phase 3 PR 에서 통째 삭제) |
| `agents/monitor/shared/mcp_client.py` | **신규** — `create_mcp_client()` factory (gateway_url + token 결합한 transport callable) |
| `agents/monitor/local/run_local_import.py` | **신규** — 현재 `local/run.py` 를 이 이름으로 rename (Phase 1 frozen baseline). 내부에서 `tools=[get_past_alarm_history]` + `system_prompt_filename="system_prompt_past.md"` 주입 |
| `agents/monitor/local/run.py` | **신규** (이전 run.py 는 rename 됨) — Gateway MCPClient lifecycle (`with mcp_client:`) + `--mode {past,live}` 분기. mode 별로 (a) tools 부분 집합 주입 (b) `system_prompt_filename` 선택 (`system_prompt_past.md` / `system_prompt_live.md`) |
| `tests/test_monitor.py` | unit test 는 mock 직접 호출 유지 (`shared/tools/alarm_history.py` 보존). 함수 import 명만 rename (`get_alarm_history` → `get_past_alarm_history`, `get_alarms_metadata` → `get_past_alarms_metadata`, `get_history` → `get_past_alarm_history`). E2E test 는 Phase 2 Gateway 의존 (별도 marker) |
| `pyproject.toml` | `requests >= 2` 추가 (Phase 2 transitional, Phase 3 에서 제거) |

### 6-3. `agent.py` refactor outline

```python
# agents/monitor/shared/agent.py
"""Monitor Agent factory — model/prompt 만 담당. 도구는 caller 가 주입.

caller (run_local_import.py / run.py / Phase 3 runtime/entry.py) 가
tools 와 system_prompt 파일명을 결정. agent.py 는 어느 phase 인지 모름.
"""
import os
from pathlib import Path

from strands import Agent
from strands.handlers.callback_handler import null_callback_handler
from strands.models import BedrockModel

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def _load_system_prompt(filename: str) -> str:
    return (_PROMPTS_DIR / filename).read_text(encoding="utf-8")


def create_agent(
    tools: list | None = None,
    system_prompt_filename: str = "system_prompt_past.md",
) -> Agent:
    """
    Args:
        tools: caller 가 주입하는 도구 list. Phase 1 baseline = [get_past_alarm_history] (mock @tool wrapper).
            Phase 2 current = MCPClient.list_tools_sync() 결과 (4 도구).
        system_prompt_filename: prompts/ 안의 파일명. Phase 1 baseline =
            "system_prompt_past.md", Phase 2 mode=past = 같은 파일 공유, mode=live = "system_prompt_live.md".
    """
    model_id = os.environ.get("MONITOR_MODEL_ID", "global.anthropic.claude-sonnet-4-6")
    region = os.environ.get("AWS_REGION", "us-west-2")

    return Agent(
        model=BedrockModel(model_id=model_id, region_name=region),
        tools=tools or [],
        system_prompt=_load_system_prompt(system_prompt_filename),
        callback_handler=null_callback_handler,   # Phase 1 검증된 패턴 유지 (이중 출력/reasoning leak 차단)
    )
```

→ **agent.py 의 import 에 `tools/` 도, `data/mock` 도 없음** (P2-A1 통과).
→ **Phase 1 → Phase 2 변경점은 caller 주입 시그니처 추가**. `callback_handler`, `BedrockModel` import 경로, prompts 디렉토리 위치는 Phase 1 그대로 (LLM 5/5 회귀 방지).
→ **단일 진실 원천**: Phase 1 baseline / Phase 2 current / Phase 3 Runtime 모두 같은 `create_agent()` 호출 (시스템 목표 C1 적합).

### 6-4. `mcp_client.py` (factory)

```python
# agents/monitor/shared/mcp_client.py
"""Gateway MCP client factory.
Phase 2: token helper 의존 (PHASE 2 ONLY).
Phase 3: helper 제거, AgentCore Identity 자동 주입."""
import os
from datetime import timedelta

from strands.tools.mcp.mcp_client import MCPClient
from mcp.client.streamable_http import streamablehttp_client

from agents.monitor.shared.auth.cognito_token import get_gateway_access_token  # PHASE 2 ONLY


def create_mcp_client() -> MCPClient:
    gateway_url = os.environ["GATEWAY_URL"]

    def _transport():
        token = get_gateway_access_token()   # PHASE 2 ONLY (Phase 3 에서 이 줄과 import 모두 삭제)
        return streamablehttp_client(
            url=gateway_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=timedelta(seconds=120),
        )

    return MCPClient(_transport)
```

### 6-5. `auth/cognito_token.py` (Phase 2 transitional helper)

```python
# agents/monitor/shared/auth/cognito_token.py
"""Cognito client_credentials → access_token. PHASE 2 ONLY — Phase 3 PR 에서 파일 통째 삭제."""
import os
import time
import requests   # uv add requests (Phase 2 신규 의존)

_cache = {"token": None, "expires_at": 0.0}


def get_gateway_access_token() -> str:
    now = time.time()
    if _cache["token"] and now < _cache["expires_at"] - 60:
        return _cache["token"]

    domain = os.environ["COGNITO_DOMAIN"]
    region = os.environ.get("AWS_REGION", "us-west-2")
    client_id = os.environ["COGNITO_CLIENT_ID"]
    client_secret = os.environ["COGNITO_CLIENT_SECRET"]
    scope = os.environ["COGNITO_GATEWAY_SCOPE"]   # e.g. "aiops-demo-ubuntu-resource-server/invoke"

    resp = requests.post(
        f"https://{domain}.auth.{region}.amazoncognito.com/oauth2/token",
        data={
            "grant_type": "client_credentials",
            "scope": scope,
        },
        auth=(client_id, client_secret),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=10,
    )
    resp.raise_for_status()
    payload = resp.json()
    _cache["token"] = payload["access_token"]
    _cache["expires_at"] = now + int(payload.get("expires_in", 3600))
    return _cache["token"]
```

→ 의존: `requests` (Phase 2 신규). Phase 3 PR 시 `pyproject.toml` 에서도 의존 제거 가능.

### 6-6. `local/run_local_import.py` (Phase 1 frozen baseline)

현재 `local/run.py` 를 이 이름으로 **rename** + `create_agent()` caller 주입 시그니처로 갱신. **AWS 의존 0** — offline 으로 영구 동작.

```python
# agents/monitor/local/run_local_import.py
"""Phase 1 frozen baseline — mock 직접 import demo (offline, AWS 의존 0).

영구 보존 — 신규 audience 의 educational entry point + 회귀 격리 검증용.
어느 phase 가 와도 동작 가능 (shared/agent.py 시그니처와 shared/tools/alarm_history.py 보존되는 한).
"""
import argparse, asyncio, os
from dotenv import load_dotenv

from agents.monitor.shared.agent import create_agent
from agents.monitor.shared.tools.alarm_history import get_past_alarm_history   # @tool wrapper, rename 됨

# 기존 _stream_response, _print_token_usage, DEFAULT_QUERY 그대로 유지 (Phase 1 검증된 출력 패턴)


async def _amain(query: str) -> None:
    agent = create_agent(
        tools=[get_past_alarm_history],
        system_prompt_filename="system_prompt_past.md",   # baseline + Phase 2 mode=past 공유
    )
    await _stream_response(agent, query)


def main() -> None:
    load_dotenv()
    # ... (Phase 1 run.py 와 동일 — argparse, header print, asyncio.run)
```

### 6-6-2. `local/run.py` (Phase 2 current — Gateway MCP, two-mode)

신규 파일. Phase 2 가 current production demo. **`--mode {past,live}` 분기** 로 P2-A3 (mock 검증) 과 P2-A4/A5 (라이브 검증) 격리.

```python
# agents/monitor/local/run.py
"""Phase 2 current — Gateway MCP demo (Cognito + 4 도구).

mode 분기:
  - past: 과거 mock 도구만 사용 → P2-A3 검증 (Phase 1 baseline 출력 동일)
  - live: 라이브 CloudWatch 도구만 사용 → P2-A4/A5 검증 (Phase 0 알람 분류)

Phase 3 에서 이 파일이 Runtime 호출 form 으로 evolve.
"""
import argparse, asyncio, os
from dotenv import load_dotenv

from agents.monitor.shared.agent import create_agent
from agents.monitor.shared.mcp_client import create_mcp_client

QUERY_PAST = "지난 7일 alarm history를 분석해 3가지 진단 유형으로 제안하고, real alarm은 따로 나열해줘."
QUERY_LIVE = "현재 라이브 알람 2개 (payment-${DEMO_USER}-status-check, payment-${DEMO_USER}-noisy-cpu) 의 상태와 classification 을 분석해, 실제 봐야 할 알람만 알려줘."

# mode → (Gateway 가 노출한 4 도구 중 부분 집합, system prompt 파일명)
MODE_CONFIG = {
    "past": ({"get_past_alarms_metadata", "get_past_alarm_history"}, "system_prompt_past.md"),
    "live": ({"list_live_alarms", "get_live_alarm_history"},          "system_prompt_live.md"),
}


async def _amain(mode: str, query: str) -> None:
    wanted_names, prompt_filename = MODE_CONFIG[mode]
    mcp_client = create_mcp_client()
    # Strands MCPClient 는 sync context manager (검증 완료).
    with mcp_client:
        all_tools = mcp_client.list_tools_sync()   # Gateway 4 도구 (history mock 2 + cw wrapper 2)
        tools = [t for t in all_tools if t.tool_name in wanted_names]
        if len(tools) != 2:
            raise SystemExit(f"[error] mode={mode} 도구 매칭 실패. 받은 도구: {[t.tool_name for t in all_tools]}")
        agent = create_agent(
            tools=tools,
            system_prompt_filename=prompt_filename,
        )
        await _stream_response(agent, query)


def main() -> None:
    load_dotenv()
    if not os.environ.get("GATEWAY_URL"):
        raise SystemExit("[error] GATEWAY_URL 미설정. infra/cognito-gateway/deploy.sh 실행 후 .env 갱신 필요.")

    parser = argparse.ArgumentParser(description="Monitor Agent (Phase 2 current — Gateway MCP)")
    parser.add_argument("--mode", choices=["past", "live"], required=True,
                        help="past = mock 분석 (P2-A3), live = 라이브 분류 (P2-A4/A5)")
    parser.add_argument("--query", default=None,
                        help="기본: mode 별 default query 사용")
    args = parser.parse_args()

    query = args.query or (QUERY_PAST if args.mode == "past" else QUERY_LIVE)
    # ... (header print, asyncio.run(_amain(args.mode, query)))
```

**호출 명령**:
```bash
# P2-A3 검증 — Phase 1 baseline 과 출력 동일해야
uv run python -m agents.monitor.local.run --mode past

# P2-A4/A5 검증 — Phase 0 라이브 알람 2개 분류
uv run python -m agents.monitor.local.run --mode live
```

**도구·prompt 분기 메커니즘**: mode 별로 (a) Gateway 4 도구 중 2개만 LLM 에 주입 + (b) mode 전용 prompt 사용. prompt 와 실제 도구가 1:1 일치 → LLM 혼동 0. P2-A3 검증: Phase 1 baseline (`run_local_import.py`) 과 Phase 2 mode=past 가 **같은 prompt + 같은 도구 명** 사용 → 출력 byte-level 동일 기대 (Lambda 응답 shape 가 data/mock 직접 호출 결과와 일치하는 한).

### 6-6-3. 출력 헬퍼 공유 (결정: 각자 복제)

`_stream_response` / `_print_token_usage` 는 두 demo 가 동일 패턴 사용. **결정 (가) — baseline / current 각자 복제**.

**근거**: Phase 1 baseline 의 "AWS 의존 0 + 영구 동작 + 변경 0" 가치가 ~30 LoC 중복보다 큼. 헬퍼 분리 시:
- baseline 이 `local/_streaming.py` 의존 → 향후 헬퍼 변경이 baseline 출력에 영향 → "frozen" 보장 약화
- current 가 token 추적 패턴을 진화시킬 때 (예: Phase 3 Runtime 의 다른 usage shape) baseline 이 따라가면 의도치 않은 회귀

→ 두 파일 독립 유지. 향후 어느 한쪽이 진화해도 다른쪽 영향 0.

### 6-7. system prompt — mode 별 2 버전 (combined 4-tool prompt 없음)

two-mode 분기 채택 (이슈 4 결정) → prompt 도 mode 별 분리. baseline 과 Phase 2 mode=past 가 **같은 past prompt 공유** — P2-A3 검증 (출력 동일성) 가장 깔끔.

prompts 디렉토리 결과:
```
prompts/
├── system_prompt_past.md       # past 2 tools — Phase 1 baseline + Phase 2 mode=past 공유
└── system_prompt_live.md       # live 2 tools — Phase 2 mode=live 전용
```

> 현재 Phase 1 의 `system_prompt.md` 를 `system_prompt_past.md` 로 **rename** (도구 명만 새 컨벤션으로 갱신). combined 4-tool prompt 는 만들지 않음 — mode 분기 후 어느 호출도 안 씀.

#### 6-7-1. `system_prompt_past.md` (rename + 도구 명 갱신)

Phase 1 검증된 prompt 본문 그대로. 도구 명만 새 컨벤션 (`<verb>_past_<noun>`):
```
사용 가능한 도구 (2개):
- get_past_alarms_metadata   — 과거 mock 알람 5개 metadata
- get_past_alarm_history     — 과거 mock 알람 history 24 events

출력 형식 (Phase 1 정책 그대로): ── 1. 알람 현황 ── ── 2. 개선 권고 ── ── 3. 실제로 봐야 할 알람 ── (3 섹션 + 2 연결 문장)
```

> Phase 1 데이터 + 출력 형식 + LLM 5/5 정확도 = frozen contract → 변경 0. 도구 이름은 contract 외 → rename 후 1회 재검증으로 5/5 유지 확인.

#### 6-7-2. `system_prompt_live.md` (신규 — Phase 2 mode=live 전용)

라이브 CloudWatch 도구 2개 명시. 출력 형식은 past 와 동일 컨벤션 유지 (audience 가 두 mode 출력 비교 가능):
```
사용 가능한 도구 (2개):
- list_live_alarms          — 라이브 CloudWatch 알람 (Phase 0 의 2개) + classification 라벨
- get_live_alarm_history    — 특정 라이브 알람의 최근 상태 전이

규칙: 라이브 알람 분류는 Tags.Classification 라벨 활용. 실제 봐야 할 알람만 골라내라.
출력 형식 (past 와 동일 컨벤션): ── 1. 알람 현황 ── ── 2. 개선 권고 ── ── 3. 실제로 봐야 할 알람 ──
```

> **도구 명 매트릭스**: `<verb>_<past|live>_<noun>` — 페어 단어만 다른 카노니컬 패턴. Phase 3+ RCA 도구 (`investigate_live_alarm`, `fetch_live_metrics_window`) 도 동일 컨벤션 fit.
> **출력 형식 일관**: 두 mode 모두 같은 3-섹션 + 2-연결-문장 — audience 가 past↔live 결과 비교 시 인지 부담 0.

### 6-8. P2-A1 검증 명령 (current path 만 대상)

P2-A1 = "agent 코드에 도구 import 0건". **검증 대상은 current path** (`shared/agent.py` + `local/run.py` + `shared/mcp_client.py`). Phase 1 frozen baseline 인 `local/run_local_import.py` 는 의도적으로 mock import 보존 → grep 대상 외.

```bash
# 도구 본체 import 가 current path 에 0건인지 확인
grep -E "from agents.monitor.shared.tools|from data/mock" \
    agents/monitor/shared/agent.py \
    agents/monitor/shared/mcp_client.py \
    agents/monitor/local/run.py
# 기대: 결과 0줄

# 참고: agents/monitor/local/run_local_import.py 는 Phase 1 frozen baseline 이라 mock import 의도적 보존
# (educational baseline + offline LLM 5/5 재현 용도)
```

→ Phase 2 PR 머지 전 CI/manual check.

### 6-9. Phase 3 transition diff (예고)

Phase 3 PR 의 변경 (예상 분량 ~50줄 삭제):

```diff
# agents/monitor/shared/auth/cognito_token.py (파일 통째 삭제)
- (전체 파일)

# agents/monitor/shared/auth/__init__.py (파일 통째 삭제)
- (전체 파일)

# agents/monitor/shared/mcp_client.py
-from agents.monitor.shared.auth.cognito_token import get_gateway_access_token
 
 def create_mcp_client() -> MCPClient:
     gateway_url = os.environ["GATEWAY_URL"]
     def _transport():
-        token = get_gateway_access_token()
-        return streamablehttp_client(
-            url=gateway_url,
-            headers={"Authorization": f"Bearer {token}"},
-            timeout=timedelta(seconds=120),
-        )
+        return streamablehttp_client(url=gateway_url, timeout=timedelta(seconds=120))
     return MCPClient(_transport)

# agents/monitor/local/run.py
# (Phase 3 에서 Runtime 호출 form 으로 evolve — 별도 design 필요)

# agents/monitor/runtime/entry.py (신규)
+ # BedrockAgentCoreApp.entrypoint — create_agent() 호출

# pyproject.toml
- "requests >= 2",   # Phase 2 transitional
```

**Phase 1 frozen baseline 의 Phase 3 영향**: 0. `local/run_local_import.py` + `shared/tools/alarm_history.py` + `shared/prompts/system_prompt_past.md` 모두 unchanged. offline 이라 의존 끊김. 영구 동작.

→ helper 영역 완전 격리 → Phase 3 PR 이 minimal + reviewable.

### 5-6. ToolSchema InlinePayload

```yaml
GatewayTargetHistoryMock:
  Type: AWS::BedrockAgentCore::GatewayTarget
  Properties:
    GatewayIdentifier: !Ref Gateway
    Name: history-mock
    TargetConfiguration:
      Mcp:
        Lambda:
          LambdaArn: !GetAtt HistoryMockLambda.Arn
          ToolSchema:
            InlinePayload:
              - Name: get_past_alarms_metadata
                Description: |
                  과거 5개 알람 metadata 조회 (mock 데이터). 페어: 라이브는 list_live_alarms.
                  CloudWatch DescribeAlarms 와 동일 PascalCase 필드 + 합성 필드(Tags.Classification, ack, action_taken).
                  ground truth 분류는 노출 안 됨 (의도적 — agent 가 직접 진단).
                InputSchema:
                  Type: object
                  Properties: {}
              - Name: get_past_alarm_history
                Description: |
                  과거 알람 history 이벤트 (시간 윈도우 필터). 24 events. 7일 cutoff 기본. 페어: 라이브는 get_live_alarm_history.
                  HistorySummary 텍스트로 fire/recovery 패턴 + ack/action_taken 으로 noise 신호 추론 가능.
                InputSchema:
                  Type: object
                  Properties:
                    days:
                      Type: integer
                      Default: 7
                      Description: "최근 며칠 분 history 반환. 7 이상이면 전체."
```

### 5-7. Lambda execution role (minimum)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
      "Resource": "arn:aws:logs:*:*:*"
    }
  ]
}
```

→ **AWS API 호출 권한 0** (mock 데이터는 Lambda 안에 vendoring). CloudWatch wrapper Lambda 와 권한 책임 명확히 분리.

### 5-8. Phase 1 호환성 검증 (P2-A3)

Phase 1 → Phase 2 전환 후 동일 정확도 보장:

| 단계 | 검증 |
|---|---|
| (1) Lambda 단독 호출 (Gateway 우회) | `aws lambda invoke --function-name ... --payload '{"tool_name":"get_past_alarms_metadata"}'` → 응답 JSON shape 가 Phase 1 `get_past_alarms_metadata()` 직접 호출 결과와 100% 동일 |
| (2) Gateway 경유 MCP 호출 (Monitor 로컬) | `agents/monitor/local/run.py` 가 MCP 로 호출 → 같은 shape 받음 → 같은 system prompt 로 LLM 호출 → **5/5 진단 정확도 유지** (Phase 1 검증 결과와 일치) |

> (2) 가 깨지면 후보 원인: (a) Gateway 가 Lambda 응답을 변형, (b) MCPClient 가 응답 unwrap 시 데이터 손실, (c) system prompt 의 도구 명 (`get_past_alarms_metadata`/`get_past_alarm_history`) 미반영. 첫 implementation 시 (1) 통과 후 (2) 단계로 진행하면 격리 디버깅 가능.

### 5-9. Phase 1 baseline rename 영향 (이번 Phase 2 PR 의 부수 변경)

`data/mock/phase1/alarm_history.py` 의 Python 함수 + Phase 1 baseline 의 system_prompt + Strands `@tool` wrapper + tests/test_monitor.py 모두 새 이름 (`get_past_alarms_metadata` / `get_past_alarm_history`) 으로 동시 rename. **Phase 1 baseline 의 frozen contract (data + 출력 + LLM 5/5)** 는 영향 없음 — 이름만 변경 → 한 번 재검증 (`uv run python -m agents.monitor.local.run_local_import`) 으로 5/5 유지 확인.

이름 매트릭스 최종:
```
              past (mock baseline)              live (Phase 2 신규)
list/get      get_past_alarms_metadata          list_live_alarms
              get_past_alarm_history            get_live_alarm_history
```

## 7. 폴더 구조 (Phase 2 전체)

### 7-1. `infra/cognito-gateway/` 디렉토리 (신규)

```
infra/cognito-gateway/
├── README.md                                # entry doc — 구성 / 배포 / 검증 / 정리 4섹션 (Phase 0 패턴, implementation 완료 후 작성)
├── deploy.sh                                # 진입점 — DEPLOY_BUCKET 보장 → vendor data/mock → cfn package → cfn deploy(cognito.yaml) → setup_gateway.py → .env 갱신
├── teardown.sh                              # cleanup_gateway.py → cfn stack 삭제 → DEPLOY_BUCKET 비우기 + 삭제 + .env 비움
├── cognito.yaml                             # CFN: UserPool + Domain + ResourceServer + Client + 2 Lambda + Lambda execution roles + Gateway IAM Role
├── setup_gateway.py                         # boto3 step-by-step (Gateway + 2 GatewayTarget) — ec-customer-support 패턴, educational
├── cleanup_gateway.py                       # boto3 (delete_gateway_target × 2 + delete_gateway) — teardown 대칭
└── lambda/
    ├── cloudwatch_wrapper/
    │   └── handler.py                       # list_live_alarms + get_live_alarm_history dispatch (단일 파일, Phase 2 minimum)
    └── history_mock/
        ├── handler.py                       # get_past_alarms_metadata + get_past_alarm_history dispatch (단일 파일)
        └── data/mock/                       # ← deploy.sh 가 cp -r data/mock/phase1/ 로 vendor (gitignore 추가)
```

#### 7-1 결정사항

| 항목 | 결정 | 근거 |
|---|---|---|
| 배포 방식 | **Hybrid (CFN + boto3)** — Cognito/Lambda/IAM = CFN, Gateway/GatewayTarget = boto3 | Educational — AgentCore 학습 핵심 (Gateway/Target) 이 step-by-step 가시화. ec-customer-support-e2e-agentcore lab-03 패턴 차용. 사용자 own codebase 와 mental model 일관 |
| Lambda handler 구조 | **단일 `handler.py`** (도구 분기 if/elif) | Phase 2 minimum (도구 2개씩). Phase 3+ RCA 확장 시 도구별 분리 검토 |
| `README.md` 작성 시점 | **implementation 완료 후** | Phase 0 패턴 — 실 동작 확인 후 정확한 명령 기록 (deploy/검증/정리 4 섹션) |
| Vendor 디렉토리 위치 | **`lambda/history_mock/data/mock/`** | Lambda import path = `data.mock.phase1.alarm_history` 그대로 깔끔 (Phase 1 unit test 와 동일 path) |
| `deploy-bucket-lifecycle.json` | **제거** (simplification) | teardown.sh 자동 cleanup 으로 leak 방지 충분. lifecycle 별도 파일 + put 명령 부담 제거 |

### 7-2. `agents/monitor/` 변경

전체 구조와 결정 근거는 **Section 6-0 참조** (DRY). 아래는 Phase 2 신규/변경 자원 요약:

```
agents/monitor/
├── shared/
│   ├── agent.py                             # refactor — caller tools/prompt 주입 (Section 6-3)
│   ├── prompts/
│   │   ├── system_prompt_past.md            # rename + 도구 명 갱신 (Section 6-7-1)
│   │   └── system_prompt_live.md            # 신규 (Section 6-7-2)
│   ├── tools/alarm_history.py               # @tool 함수 rename → get_past_alarm_history
│   ├── auth/                                # 신규 (Phase 2 transitional, Phase 3에서 통째 삭제)
│   │   ├── __init__.py
│   │   └── cognito_token.py                 # Section 6-5
│   └── mcp_client.py                        # 신규 — MCPClient factory (Section 6-4)
├── local/
│   ├── run_local_import.py                  # 현재 run.py rename (baseline, Section 6-6)
│   └── run.py                               # 신규 — --mode {past,live} 분기 (Section 6-6-2)
└── runtime/
    └── __init__.py                          # Phase 2 placeholder (Phase 3 에서 entry.py 추가, transition 명시)
```

> `runtime/__init__.py` 빈 파일을 Phase 2 에 둠 — Phase 3 transition 시점이 design 단계에서 명시된 상태로 보존. Phase 3 PR 이 `runtime/entry.py` 추가하는 자연스러운 흐름.

### 7-3. `data/mock/phase1/` 변경

```
data/mock/phase1/
└── alarm_history.py                         # 함수 rename only (시그니처·반환 shape·데이터 그대로)
                                              #   get_alarms_metadata → get_past_alarms_metadata
                                              #   get_history          → get_past_alarm_history
                                              #   get_ground_truth     → get_past_ground_truth   (테스트 전용, 컨벤션 일관)
```

**근거**:
- 이슈 3 도구 명 컨벤션 (`<verb>_<past|live>_<noun>`) 적용
- Phase 1 frozen contract = data + 출력 + LLM 5/5 정확도. 함수 이름은 contract 외 → rename 후 1회 재검증 (`uv run python -m agents.monitor.local.run_local_import`)
- `get_past_ground_truth` 도 같이 rename — agent 에 노출 안 되지만 (Section 5-2 참조) 코드 일관성 위해. 단, 도구 명 매트릭스에는 미포함 (테스트 전용 함수)

**Phase 2 PR 영향 범위**:
- `data/mock/phase1/alarm_history.py` 함수 rename 3건
- `agents/monitor/shared/tools/alarm_history.py` import + @tool wrapper 함수명 갱신
- `tests/test_monitor.py` import + assertion 함수 호출 갱신 (`get_past_ground_truth` 사용)
- Lambda `infra/cognito-gateway/lambda/history_mock/handler.py` import (vendored copy 도 같은 함수명 사용)

### 7-4. `tests/` 변경

```
tests/
└── test_monitor.py                          # 단일 파일 유지 (Phase 1 unit + Phase 2 E2E 같은 파일, marker 로 구분)
                                              # import rename: get_past_alarms_metadata / get_past_alarm_history / get_past_ground_truth
                                              # @tool wrapper 함수 reference: get_alarm_history → get_past_alarm_history
                                              # 기존 11/11 unit test pass 유지 (assertion 본문 변경 0)
```

**Phase 2 변경 범위**:
- import 명 갱신 (3 함수 + @tool wrapper 1개)
- assertion 본문 그대로 (반환 shape 변경 0)
- E2E test 추가는 **Phase 2 implementation 시점** — design 단계에선 outline 안 작성

**E2E test 마커 컨벤션** (Phase 2 implementation 시 도입):
```python
@pytest.mark.phase2_gateway   # Gateway 배포 의존 — `pytest -m phase2_gateway` 로 별도 실행
def test_run_mode_past_via_gateway():
    ...   # Phase 2 implementation 시 작성
```

**Phase 1 baseline 회귀 검증**:
- 방식: **manual** — Phase 2 PR 머지 전 `uv run python -m agents.monitor.local.run_local_import` 1회 실행 → 5/5 진단 정확도 출력 확인
- 자동화 안 함 — LLM 출력은 비결정적, byte-level diff 도구 도입 부담 큼. manual 검증으로 충분 (사용자 패턴 일관 — minimum)
- 시점: Phase 1 도구 rename 후 1회 + Phase 2 implementation 완료 후 1회 (총 2회)

### 7-5. 루트 변경

| 파일 | 변경 | 근거 |
|---|---|---|
| `.env.example` | Phase 2 변수 추가 (아래 9개) | Phase 0 패턴 일관 — 빈 값 + 형식 주석. `COGNITO_GATEWAY_SCOPE` 는 deploy.sh 가 ResourceServer Identifier 조회 후 자동 채움 |
| `.gitignore` | `infra/cognito-gateway/lambda/history_mock/data/mock/` 추가 | Vendor copy 는 deploy 시점 생성물 (Section 5-4) — git 추적 안 함 |
| `pyproject.toml` | `[project] dependencies` 에 `requests >= 2` 추가 | `cognito_token.py` 가 production 코드 (Phase 2 current path 가 사용). Phase 3 PR 에서 제거 |
| `bootstrap.sh` | 변경 없음 | Phase 별 자원은 `infra/phaseN/deploy.sh` 가 담당 (Phase 0 패턴 일관) |

#### `.env.example` 추가 변수 (9개)

```bash
# === Phase 2: Cognito ===
COGNITO_USER_POOL_ID=
COGNITO_DOMAIN=                    # 예: aiops-demo-ubuntu (region.amazoncognito.com 앞 prefix)
COGNITO_CLIENT_ID=
COGNITO_CLIENT_SECRET=           # deploy.sh 가 describe-user-pool-client 로 별도 조회
COGNITO_GATEWAY_SCOPE=             # 형식: aiops-demo-${DEMO_USER}-resource-server/invoke (deploy.sh 자동 채움)

# === Phase 2: Gateway ===
GATEWAY_ID=                        # 디버깅용 (aws bedrock-agentcore describe-gateway 등)
GATEWAY_URL=                       # MCP endpoint — Monitor Agent 가 사용

# === Phase 2: Lambda ARNs ===
LAMBDA_HISTORY_MOCK_ARN=           # 디버깅용 (aws lambda invoke 직접 호출 시)
LAMBDA_CLOUDWATCH_WRAPPER_ARN=     # 디버깅용
```

> **`GATEWAY_ID` / Lambda ARN 보존 근거**: Phase 2 current 코드는 `GATEWAY_URL` 만 사용. 단 디버깅 시 `aws lambda invoke` (Section 5-8 P2-A3 검증 단계 (1)) / `aws bedrock-agentcore describe-gateway` 등 명령 편의 위해 보존.

### 7-6. `docs/design/` 변경

| 파일 | 변경 | 시점 |
|---|---|---|
| `docs/design/plan_summary.md` | Phase 2 status `🚧 design` → `✅ done` + 도구 명 컨벤션 (`<verb>_<past\|live>_<noun>`) 명시 | Phase 2 implementation 완료 시점 |
| `docs/design/phase2.md` | (이 문서 자체) — implementation 완료 후에도 **active doc 으로 보존** (design 근거 reference) | 현재 진행 중 (design 단계) |
| `docs/design/phase2_audit.md` | **신규 — Phase 2 implementation 완료 후 작성** (Phase 0 패턴, 실 발견 audit 항목 기록) | Phase 2 implementation 완료 후 |
| `docs/design/resource.md` | Phase 2 베이스 코드 차용 매핑 추가 (Section 9 합의 후 동기화) | Section 9 합의 시점 (Phase 2 design 단계) |

**근거**:
- `plan_summary.md` 는 SoT — phase 별 status·전체 inventory 만 추적. design 상세는 phase2.md
- `phase2.md` 는 implementation 후에도 **archive 안 함** — Phase 0 의 `plan.md` (DEPRECATED archive) 와 다른 위상. phase2.md 는 design 합의 + 결정 근거 (이슈 1~4 + Section 7 결정 사항) 의 trace 가치 영구 보존
- `phase2_audit.md` 는 Phase 0 패턴 — implementation 시 발견된 audit 항목 (예: deploy.sh fail-fast 누락, multi-user 격리 보강 등) 정리. design 단계에서 outline 작성 안 함 (premature)
- `resource.md` 는 phase 별 베이스 코드 차용 매핑 점진 갱신 — Section 9 합의 후 phase2.md ↔ resource.md 양방향 동기화 (audit 시 trace 가능)

### 7-7. Phase 2 전체 산출물 인벤토리 (확정)

> Section 1-4 (design 진입 시점 예상치) 와 함께 보존 — design 합의 후 확정치. Phase 2 implementation 진입 시 이 표 참조.

| 카테고리 | 항목 | 수 |
|---|---|---|
| **AgentCore** | Gateway | 1 |
| AgentCore | GatewayTarget | 2 (cloudwatch_wrapper Lambda + history_mock Lambda) |
| **Lambda** | Lambda 함수 | 2 (cloudwatch_wrapper + history_mock) |
| Lambda | Lambda execution role | 2 (함수별 1개) |
| **Cognito** | UserPool | 1 |
| Cognito | UserPoolDomain | 1 |
| Cognito | ResourceServer | 1 |
| Cognito | UserPoolClient (Client) | 1 |
| **IAM** | Gateway execution role | 1 |
| **S3** | DEPLOY_BUCKET (`aiops-demo-${DEMO_USER}-deploy-${ACCOUNT}-${REGION}`) | 1 (phase-shared) |
| **CloudFormation** | Stack | 1 (cognito.yaml — UserPool + Lambda + IAM Role 통합) |
| **boto3 setup** | `setup_gateway.py` + `cleanup_gateway.py` (Gateway + GatewayTarget × 2) | 2 (educational, ec-customer-support 패턴) |
| **Strands (코드)** | `agent.py` refactor | 1 |
| Strands | `mcp_client.py` 신규 | 1 |
| Strands | `auth/cognito_token.py` 신규 (transitional, Phase 3 삭제) | 1 |
| Strands | system_prompt 파일 (past + live) | 2 |
| Strands | local CLI runner (baseline + current) | 2 |
| **기타 코드** | Python 함수 rename (data/mock 3 + Strands @tool wrapper 1) | 4 |
| **Test** | Phase 1 unit test rename + E2E marker 신규 | 1 |
| **Doc** | phase2.md (이 문서) + resource.md 갱신 + plan_summary.md status | 3 |

→ Phase 2 implementation 완료 후 `phase2_audit.md` 신규 작성 시 이 표 대비 실 산출물 비교.

## 8. 검증 시나리오 (P2-A1 ~ P2-A5 매핑)

### 8-0. acceptance 매트릭스 (Section 1-2 재확인)

| ID | 항목 | 검증 단계 |
|---|---|---|
| P2-A1 | `agents/monitor/shared/agent.py` 도구 본체 import 0건 | 정적 grep |
| P2-A2 | Monitor Agent 가 MCPClient 로 Gateway 호출 | runtime log 흔적 |
| P2-A3 | Gateway → history mock Lambda → 응답 shape Phase 1 mock 동일 | Lambda 단독 + Gateway 경유 2단 검증 |
| P2-A4 | Gateway → CloudWatch wrapper → Phase 0 라이브 알람 2개 반환 | Monitor 출력에 두 알람 + classification 라벨 |
| P2-A5 | Monitor 가 noisy-cpu 를 noise, status-check 를 real 로 분류 | 출력 "실제로 봐야 할 알람" 섹션에 status-check 만 |

> **자동화 정책 (8-0 결정)**: 검증 흐름은 사용자 manual 실행 — `verify.sh` 같은 자동화 스크립트는 만들지 않음. audience 가 각 step 결과를 보면서 학습 (audience-friendly 원칙). 각 검증 단계의 출력이 educational asset.

### 8-1. P2-A1 — 정적 grep (도구 본체 import 0건)

**검증 명령** (Section 6-8 재확인):
```bash
grep -E "from agents.monitor.shared.tools|from data/mock" \
    agents/monitor/shared/agent.py \
    agents/monitor/shared/mcp_client.py \
    agents/monitor/local/run.py
```

**기대 출력**: 0줄

**제외 대상** (의도적):
- `agents/monitor/local/run_local_import.py` — Phase 1 frozen baseline 이라 mock import 보존
- `agents/monitor/shared/tools/alarm_history.py` — Strands @tool wrapper, baseline 이 사용

**시점**: Phase 2 PR 머지 전 manual or CI check.

### 8-2. P2-A2 — MCPClient → Gateway 호출 흔적

**검증 명령**:
```bash
LOG_LEVEL=DEBUG uv run python -m agents.monitor.local.run --mode past 2>&1 | tee /tmp/p2a2.log
grep -E "streamable_http|gateway.bedrock-agentcore|mcp.*request" /tmp/p2a2.log | head
```

**기대 출력**: MCP streamable-http POST 요청 + JWT Bearer header 흔적 (e.g. `POST .../mcp Authorization: Bearer eyJ...`)

**시점**: Phase 2 implementation 첫 라이브 호출 시.

### 8-3. P2-A3 — Lambda 응답 shape Phase 1 동일 (2단계 격리)

#### 단계 (1) Lambda 단독 호출 (Gateway 우회)

```bash
# history_mock Lambda 직접 invoke
aws lambda invoke \
    --function-name "aiops-demo-${DEMO_USER}-history-mock" \
    --payload '{"tool_name":"get_past_alarms_metadata"}' \
    --cli-binary-format raw-in-base64-out \
    /tmp/lambda_metadata.json

# Phase 1 mock 직접 호출
uv run python -c "
import json
from data.mock.phase1.alarm_history import get_past_alarms_metadata
print(json.dumps({'alarms': get_past_alarms_metadata()}, default=str, indent=2))
" > /tmp/phase1_metadata.json

# diff
diff <(jq -S . /tmp/lambda_metadata.json) <(jq -S . /tmp/phase1_metadata.json)
```

**기대**: diff 0줄 (응답 shape byte-level 동일).

#### 단계 (2) Gateway + MCP 경유

```bash
# Phase 1 baseline 출력 (offline)
uv run python -m agents.monitor.local.run_local_import 2>&1 | tee /tmp/baseline.txt

# Phase 2 mode=past 출력 (Gateway 경유)
uv run python -m agents.monitor.local.run --mode past 2>&1 | tee /tmp/phase2_past.txt

# 비교 — 8-3 결정 (가): "실제로 봐야 할 알람" 섹션의 alarm 명 list 만 비교 (LLM 비결정 출력 허용)
grep -A 5 "실제로 봐야 할 알람" /tmp/baseline.txt
grep -A 5 "실제로 봐야 할 알람" /tmp/phase2_past.txt
```

**기대**: 두 출력의 "실제로 봐야 할 알람" 섹션이 같은 alarm 명 (real 2개) 명시. 5/5 분류 정확도 유지.

> **비교 방식 결정 (8-3 (가))**: alarm 명 list 만 비교 — LLM 출력은 비결정적이라 byte-level diff / snapshot 도구는 부담 큼. boolean signal (같은 real 알람 식별) 만으로 충분.

**디버깅** (단계 (2) 가 깨지면):
- (a) Gateway 가 Lambda 응답 변형 — `aws bedrock-agentcore get-gateway-target` 로 토큰 transform 확인
- (b) MCPClient 응답 unwrap 시 데이터 손실 — 단계 (1) 통과면 Gateway/MCP 영역 의심
- (c) system_prompt_past.md 의 도구 명 미반영 — `get_past_alarms_metadata` 명시 확인

### 8-4. P2-A4 — 라이브 CloudWatch 알람 2개 반환

```bash
# cloudwatch_wrapper Lambda 직접 호출
aws lambda invoke \
    --function-name "aiops-demo-${DEMO_USER}-cloudwatch-wrapper" \
    --payload '{"tool_name":"list_live_alarms"}' \
    --cli-binary-format raw-in-base64-out \
    /tmp/live_alarms.json

cat /tmp/live_alarms.json | jq '.alarms[] | {name, classification}'
```

**기대 출력**:
```json
{"name": "payment-${DEMO_USER}-status-check", "classification": "real"}
{"name": "payment-${DEMO_USER}-noisy-cpu",    "classification": "noise"}
```

**선행 조건**: Phase 0 EC2 + 알람 배포 완료 (Section 1-5 의존).

### 8-5. P2-A5 — Monitor 가 noise/real 분류

```bash
uv run python -m agents.monitor.local.run --mode live 2>&1 | tee /tmp/p2a5.txt
sed -n '/── 3. 실제로 봐야 할 알람 ──/,$p' /tmp/p2a5.txt
```

**기대 출력 (boolean signal 만 검증, 8-5 결정 (가))**:
- 섹션 3 에 `payment-${DEMO_USER}-status-check` 포함
- `payment-${DEMO_USER}-noisy-cpu` 는 섹션 3 미포함 (섹션 1 알람 현황엔 noise 라벨로 표시)

> **LLM 비결정 허용도 결정 (8-5 (가))**: 출력 형식/표현 변동은 무시. 핵심 boolean signal = "real 알람만 섹션 3 포함" — 이 boolean 으로 P2-A5 통과 판정. Phase 1 5/5 정확도 검증 패턴과 일관.

### 8-6. 전체 검증 실행 흐름 (Phase 2 implementation 후)

```bash
# 1. Phase 0 라이브 검증 (선행 조건)
bash infra/ec2-simulator/deploy.sh
bash infra/ec2-simulator/chaos/stop_instance.sh && sleep 150
aws cloudwatch describe-alarms --alarm-names "payment-${DEMO_USER}-status-check" --query 'MetricAlarms[0].StateValue'   # ALARM
bash infra/ec2-simulator/chaos/start_instance.sh && sleep 150
# StateValue → OK 확인

# 2. Phase 2 deploy (Hybrid)
bash infra/cognito-gateway/deploy.sh

# 3. Phase 1 baseline 회귀 (이름 rename 후 5/5 유지)
uv run python -m agents.monitor.local.run_local_import   # P2-A3 baseline 비교용

# 4. P2-A1: 정적 grep (Section 8-1)
# 5. P2-A2: MCPClient log (Section 8-2)
# 6. P2-A3: Lambda 직접 + Gateway 경유 (Section 8-3)
# 7. P2-A4: cloudwatch_wrapper 직접 호출 (Section 8-4)
# 8. P2-A5: Monitor mode=live 실행 (Section 8-5)

# 9. teardown
bash infra/cognito-gateway/teardown.sh
bash infra/ec2-simulator/teardown.sh
```

> **수동 실행 결정 (8-6 (가))**: bash script 로 묶지 않음. 각 step 결과를 사용자/audience 가 보면서 AgentCore 학습 (audience-friendly). 자동화는 P2-A1 (정적 grep) 만 CI 후보 — 나머지는 라이브 자원 의존이라 manual 적합.

## 9. 베이스 코드 차용 매핑

### 9-0. 차용 대상 3 codebase 요약 (resource.md 와 동기화)

| Codebase | 경로 | 차용 영역 |
|---|---|---|
| **A2A-multi-agent-incident-response** | `/home/ubuntu/amazon-bedrock-agentcore-samples/02-use-cases/A2A-multi-agent-incident-response/` | Cognito CFN 패턴, MCPClient 호출 패턴 (Phase 3) |
| **ec-customer-support-e2e-agentcore** | `/home/ubuntu/ec-customer-support-e2e-agentcore/` | boto3 Gateway/Target step-by-step (Section 3 hybrid 의 educational core) |
| **developer-briefing-agent** | `/home/ubuntu/developer-briefing-agent/` | `create_agent()` 단일 진실 원천 + Strands streaming + bootstrap |

### 9-1. A2A 샘플 차용 매핑

| 차용 파일 (A2A) | 적용 대상 (phase2) | 변형 |
|---|---|---|
| `cloudformation/cognito.yaml:28-156` (UserPool + Domain + ResourceServer + UserPoolClient M2M) | `infra/cognito-gateway/cognito.yaml` 의 Cognito 자원 (Section 3-2) | Multi-user prefix (`aiops-demo-${DEMO_USER}-*`) 추가. Phase 2 = Client 만 |
| `cognito.yaml` 의 `ResourceServer Identifier = ${StackName}-resource-server` 패턴 | `aiops-demo-${DEMO_USER}-resource-server` (Section 3-2) | 동일 |
| `monitoring_strands_agent/utils.py:27-48` `create_gateway_client(workload_token)` MCPClient 생성 | **Phase 3** Runtime `mcp_client.py` (참고만) | Phase 2 는 transitional helper (Cognito POST). Phase 3 transition 시 이 패턴 재구현 (`agentcore_client.get_resource_oauth2_token(...)`) |
| A2A 의 Lambda Custom Resource (OAuth2CredentialProvider 생성 패턴) | **deprecated** | Phase 3 패턴 결정은 Phase 3 design 시점에 (premature 회피) |

> **A2A 의 Gateway/GatewayTarget CFN 패턴 (`AWS::BedrockAgentCore::Gateway`, `AWS::BedrockAgentCore::GatewayTarget`) = 차용 안 함** — 우리는 Hybrid (boto3 setup_gateway.py) 채택.

### 9-2. ec-customer-support-e2e-agentcore 차용 매핑 (Hybrid 핵심)

| 차용 파일 (ec-customer-support) | 적용 대상 (phase2) | 변형 |
|---|---|---|
| `notebooks/lab-03-agentcore-gateway.ipynb` Step 5 (Gateway 생성) | `infra/cognito-gateway/setup_gateway.py:step1_create_gateway` (Section 3-3-B) | Notebook → Python script 화. SSM parameter store 조회 → CFN outputs export 로 대체. step print 패턴 그대로 |
| Lab 03 Step 6 (Lambda 함수 대상 추가) | `setup_gateway.py:step2_create_target` × 2 호출 (Section 3-3-B) | InlinePayload tool schema 는 Section 4-3 + 5-6 의 Python literal. notebook single target → 우리 2 targets |
| Lab 03 의 idempotency 패턴 (`list_gateways` → 매칭 → 재사용) | `setup_gateway.py` step1/step2 의 idempotent 분기 | 동일 |
| Lab 03 의 `gateway_client = boto3.client("bedrock-agentcore-control")` | `setup_gateway.py` boto3 client 초기화 | 동일 |
| **Lab 09 (cleanup)** 의 `delete_gateway_target` + `delete_gateway` 패턴 | `infra/cognito-gateway/cleanup_gateway.py` | 역순 (target 먼저 삭제) |

> **Educational core**: ec-customer-support 의 step-by-step print 패턴 (`print(f"\n=== Step N: ... ===")`) 는 audience 학습 가치의 핵심. setup_gateway.py 도 동일 패턴 유지.

### 9-3. developer-briefing-agent 차용 매핑

| 차용 파일 (developer-briefing-agent) | 적용 대상 (phase2) | 변형 |
|---|---|---|
| `local-agent/chat.py` `agent.stream_async(prompt)` async iterator + `null_callback_handler` | `agents/monitor/local/run.py` + `run_local_import.py` 의 `_stream_response` (Section 6-6 + 6-6-2) | Phase 1 에서 이미 차용. Phase 2 에선 그대로 유지 (이슈 1 결정) |
| `local-agent/agent.py` + `managed-agentcore/agent.py` 가 같은 `create_agent()` 호출 (단일 진실 원천) | `agents/monitor/shared/agent.py:create_agent(tools, system_prompt_filename)` baseline + current + Phase 3 Runtime 모두에서 호출 | 시그니처 확장 — caller 가 tools + prompt 파일명 주입 (Phase 1→2 변경의 핵심) |
| `prompts/system_prompt.md` 외부화 + load 패턴 | `agents/monitor/shared/prompts/{system_prompt_past, system_prompt_live}.md` (Section 6-7) | mode 별 2 파일로 확장 |
| `setup.sh` 통합 부트스트랩 (uv sync → .env → SSM 토큰) | `bootstrap.sh` (Phase 0 에서 이미 적용) | Phase 2 에선 변경 없음 |

### 9-4. 신규 (차용 없음 — Phase 2 자체 design)

| 자원 | 신규 사유 |
|---|---|
| `infra/cognito-gateway/lambda/cloudwatch_wrapper/handler.py` | Intent shape Lambda — Smithy 폐기 결정 (Section 4) 의 결과. 산업 표준 패턴 참고는 했지만 코드 차용 0 |
| `infra/cognito-gateway/lambda/history_mock/handler.py` | Phase 1 mock 데이터를 Lambda 로 wrap (Section 5) — 신규 |
| `agents/monitor/shared/auth/cognito_token.py` | Phase 2 transitional helper (Section 6-5). Phase 3 PR 에서 통째 삭제 |
| `agents/monitor/shared/mcp_client.py` | Strands MCPClient factory (Section 6-4). transport callable 패턴 — A2A 의 `create_gateway_client()` 와 유사하지만 token 인자 처리 transitional |
| `agents/monitor/local/run.py --mode {past,live}` 분기 | 이슈 4 결정 (P2-A3 와 P2-A4/A5 검증 격리) — 차용 없음 |

### 9-5. Phase 3 OAuth2CredentialProvider 패턴 결정 = 미정

**결정 (9-5 (가))**: Phase 3 design 시점에 결정. Phase 2 단계에선 명시 안 함 (premature 회피).

후보 옵션 (Phase 3 design 진입 시):
- A2A 의 Lambda Custom Resource (deprecated)
- `AWS::BedrockAgentCore::OAuth2CredentialProvider` CFN native (2026-05 GA)
- boto3 hybrid (ec-customer-support 패턴 일관)

### 9-6. resource.md 갱신 (Section 9 합의 시점에 즉시 동기화)

`docs/design/resource.md` 변경:

| 항목 | 갱신 내용 |
|---|---|
| ec-customer-support 섹션 | "학습용 (코드 차용 없음)" → **"베이스 코드 (직접 차용)"** 로 이동. lab-03/lab-09 가 Phase 2 hybrid 의 핵심 |
| A2A 차용 영역 | Phase 2 = Cognito CFN 만 (Gateway CFN 차용 안 함 — hybrid 채택). Phase 3 = MCPClient Runtime 패턴 + OAuth2CredentialProvider 패턴 미정 |
| 신규 섹션 | "Phase 2 자체 design (차용 없음)" — 위 9-4 의 5개 자원 |
