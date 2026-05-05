# Noise Alarm 탐지 Agent — AgentCore Runtime 데모

Cloud Operation Group 대상 Bedrock **AgentCore Runtime** 교육용 데모.
Strands Agent 한 개(Rule Optimization)를 **로컬 → Gateway → Runtime**으로 동일 코드 승격 배포하며, AI Ops 유스케이스(**CloudWatch Alarm 노이즈 탐지 → GitHub `diagnosis/` 자동 커밋**)를 터미널에서 재현합니다.

> 상세 설계는 [`plan.md`](./plan.md) 참조.

---

## 30초 개요

- **Agent**: 운영자가 등록한 15개 CloudWatch Alarm 중 **noise**를 식별하고 rule 개선안을 markdown으로 커밋
- **Tool #1**: CloudWatch Alarm Mock (`tools/cloudwatch_mock.py`) — 1주치 합성 이력
- **Tool #2**: GitHub (`tools/github_tool.py`) — PyGithub + 오프라인 fs fallback
- **기대 산출**: 15개 중 **11건 noise 후보 + 4건 정상**, 주간 fire ~89% 감소

---

## 빠른 시작 (Lab 1, 오프라인)

AWS · GitHub 자격증명 없이도 가능:

```bash
# 1) 의존성
pip install -r requirements.txt

# 2) 스크립트 기반 레퍼런스(LLM 미사용) 실행 — 항상 성공해야 함
python invoke_cli.py --dry-run

# 3) 리포트 확인
cat diagnosis/2026-04-23-noise.md
```

예상 출력:

```
  Alarms analyzed     : 15
  Noise candidates    : 11  (TH=3 / AND=2 / TW=3 / RET=3)
  Genuine incidents   : 4
  Fires before / after: 836 / 90  (-89.2%)
  Report              : file:///.../diagnosis/2026-04-23-noise.md
```

---

## Lab 진행 가이드

모든 랩은 **툴 입출력 스키마·Agent 코드가 동일**합니다. 바뀌는 것은 툴이 실행되는 위치뿐:

```
Lab 1: 로컬 함수 직접 호출
Lab 2: 로컬 Agent → AgentCore Gateway → Lambda(Mock)
Lab 3: AgentCore Runtime 상의 Agent → Gateway → Lambda
Bonus: Lab 2/3 Lambda를 boto3 실제 DescribeAlarms 경로로 교체
```

### Lab 1 — 로컬 Strands Agent + Mock 툴 직접 호출

Strands Agent가 파이썬 함수 툴을 직접 호출. Bedrock이 필요.

```bash
cp .env.example .env  # 편집: AWS_REGION, BEDROCK_MODEL_ID, (선택) GITHUB_TOKEN/REPO
export AWS_PROFILE=...   # Bedrock invoke 권한 가진 프로필

python invoke_cli.py "최근 1주 noise alarm 진단하고 diagnosis/에 리포트 올려줘"
```

- `OFFLINE_MODE=1` 이면 GitHub 토큰 없이 로컬 `diagnosis/`에 파일 생성
- 모델 디폴트: `us.anthropic.claude-sonnet-4-5-20250929-v1:0` (cross-region inference profile)

### Lab 2 — AgentCore Gateway에 Lambda 툴 등록 (MCP)

Mock 함수를 Lambda로 감싸 Gateway target으로 등록. Agent가 MCP를 통해 Gateway 경유로 호출.

1. Lambda 패키지 만들기 (class 진행 시 CloudFormation/CDK 스니펫 제공):
   ```bash
   # 두 Lambda 모두 tools/ + mock_data/ 를 번들링해야 함
   # handler: gateway.lambda_cloudwatch.lambda_handler
   #          gateway.lambda_github.lambda_handler
   ```
2. Gateway + target 등록:
   ```bash
   python -m gateway.register \
       --gateway-name noise-alarm-gateway \
       --cw-lambda-arn arn:aws:lambda:us-west-2:123456789012:function:noise-alarm-cw-mock \
       --gh-lambda-arn arn:aws:lambda:us-west-2:123456789012:function:noise-alarm-github
   ```
3. Agent를 Gateway URL로 연결 (환경변수 `AGENTCORE_GATEWAY_URL` 설정 후 Lab 1과 동일 명령).

**불변 계약**: Lambda 핸들러는 `tools/cloudwatch_mock.py`의 함수를 그대로 호출합니다. Agent 프롬프트도 바꾸지 않습니다.

### Lab 3 — AgentCore Runtime 승격 배포

Agent를 Runtime에 배포. 엔트리포인트는 `runtime/agent_runtime.py`.

```bash
# 1) deployment config 생성 (.bedrock_agentcore.yaml)
python -m runtime.deploy configure --auto-role

# 2) ECR 푸시 + Runtime 생성 (시간 소요)
python -m runtime.deploy launch

# 3) 원격 호출
python -m runtime.deploy invoke "최근 1주 noise alarm 진단해줘"

# 상태/정리
python -m runtime.deploy status
python -m runtime.deploy destroy
```

Runtime 환경에는 Bedrock 모델 invoke 권한 + Gateway 호출 권한(HTTP)이 필요.

### Bonus — 실제 `DescribeAlarms` 1건 연동 (선택)

Mock 함수 대신 boto3로 실 AWS alarm 하나 조회. 스키마가 동일하므로 Agent 코드 변경 없음.

```bash
export BONUS_ALARM_NAME=demo-cpu-high
python -m bonus.describe_alarms_real "$BONUS_ALARM_NAME" --region us-west-2
python -m bonus.describe_alarms_real --compare "$BONUS_ALARM_NAME"   # 스키마 비교
```

- **포함**: `DescribeAlarms` 1건
- **제외**: `DescribeAlarmHistory` (이력을 API로 소급 생성할 수 없어 Mock 유지)
- `_ack_ratio_7d`, `_tags` 등 Mock 전용 필드는 real 응답에서 사라집니다

---

## 레이아웃

```
.
├── plan.md                 # 설계 문서 (단일 진실 원천)
├── README.md
├── requirements.txt
├── .env.example
├── invoke_cli.py            # Lab 1 entrypoint
│
├── mock_data/
│   ├── alarms.py            # 15 alarms + 1672 StateUpdate events (seeded)
│   └── seed_rules.py        # rules/ YAML 생성기
│
├── tools/
│   ├── cloudwatch_mock.py   # describe_alarms / describe_alarm_history / get_alarm_statistics
│   └── github_tool.py       # list_files / get_file / put_file (offline + remote)
│
├── agent/
│   └── rule_optimizer.py    # Strands Agent + scripted reference pipeline
│
├── gateway/                 # Lab 2
│   ├── lambda_cloudwatch.py
│   ├── lambda_github.py
│   ├── openapi_schema.json
│   └── register.py
│
├── runtime/                 # Lab 3
│   ├── agent_runtime.py     # BedrockAgentCoreApp entrypoint
│   └── deploy.py            # Runtime configure/launch/invoke
│
├── bonus/                   # 선택
│   └── describe_alarms_real.py
│
├── rules/                   # GitOps용 rule YAML (자동 생성)
├── diagnosis/               # Agent 자동 커밋 리포트 누적
└── tests/                   # pytest (오프라인, 네트워크/자격증명 불필요)
```

---

## 테스트

```bash
pytest tests/ -v
```

17개 테스트가 0.7초 내에 통과해야 합니다. 네트워크·AWS·Bedrock 접근 필요 없음.

---

## 환경변수

| 변수 | 용도 | 필요 Lab |
|---|---|---|
| `AWS_REGION` | Bedrock + boto3 region | 1 (Bedrock), 3, Bonus |
| `BEDROCK_MODEL_ID` | Strands BedrockModel id | 1, 3 |
| `OFFLINE_MODE` | `1` = 로컬 fs / `0` = 실제 GitHub | 전 랩 |
| `GITHUB_TOKEN` | PAT (repo scope) | OFFLINE_MODE=0일 때 |
| `GITHUB_REPO` | `owner/repo` | OFFLINE_MODE=0일 때 |
| `GITHUB_BRANCH` | 기본 `main` | OFFLINE_MODE=0일 때 |
| `BONUS_ALARM_NAME` | Bonus에서 조회할 실제 alarm | Bonus |
| `AGENTCORE_GATEWAY_URL` | Lab 2에서 Agent가 바라볼 Gateway MCP URL | 2, 3 |

---

## 트러블슈팅

- **`No module named pytest`** — `pip install pytest`
- **Bedrock AccessDeniedException** — 프로필에 `bedrock:InvokeModel` 권한 + 모델이 해당 리전에서 enable 상태인지 확인. 혹은 `--dry-run`으로 우회.
- **`GITHUB_TOKEN not set`** — `OFFLINE_MODE=1`로 Lab 1 진행하거나, PAT을 `.env`에 설정
- **`bedrock-agentcore-control client unavailable`** — 해당 리전이 AgentCore 활성 리전인지 확인 (`us-west-2`, `us-east-1` 등)
- **Runtime `launch` 실패** — 로컬 Docker가 작동 중인지, ECR 푸시 권한이 있는지 확인

---

## 기대되는 분석 결과 (plan.md §5 참조)

| 분류 | 건수 | 해당 Alarm |
|---|---|---|
| ✅ 정상 (NORMAL) | 4 | `payment-api-5xx-rate`, `rds-prod-cpu`, `dynamodb-throttle-orders`, `api-latency-p99` |
| ⚠️ Threshold 상향 | 3 | `ec2-cpu-high-web-fleet`, `lambda-checkout-errors`, `ecs-memory-web` |
| ⚠️ 조건 결합 (AND) | 2 | `alb-target-5xx`, `s3-4xx-public-bucket` |
| ⚠️ Time window 제외 | 3 | `nightly-batch-cpu-spike`, `deploy-time-5xx`, `rds-connections-high` |
| ⚠️ Rule 폐기 | 3 | `sqs-queue-depth-legacy-v1`, `old-ec2-status-check`, `waf-blocked-requests` |

결정적 결과를 원한다면 `--dry-run`이 레퍼런스. Bedrock Agent는 동일한 분류에 도달하되 표현·뉘앙스는 매 실행마다 다를 수 있습니다.
