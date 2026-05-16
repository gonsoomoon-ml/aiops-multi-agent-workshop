# Teardown 순서

데모 자원 일괄 삭제 절차. 의존성 역순으로 진행 (consumer → provider).

## 의존성 (build 순서)

```
Phase 0  (EC2 + alarms)            ← 독립
Phase 2  (Cognito + Gateway + 2 Lambda)  ← 독립 (CloudWatch 는 native)
Phase 3  (Monitor Runtime)         ← Phase 2 (Cognito JWT, Gateway target) 의존
Phase 4  (Incident Runtime + GitHub Lambda)  ← Phase 2/3 의존
Phase 5  (Supervisor + Monitor a2a + Incident a2a)
         ← Phase 0/2/4 의존 (Phase 4 shared/ 직접 import,
            Phase 2 Client 재사용)
```

→ Teardown 은 Phase 5 → 4 → 3 → 2 → 0 역순. Supervisor 가 sub-agent 호출자이므로 가장 먼저 제거.

## 일괄 실행 (권장)

```
bash teardown_all.sh         # 확인 prompt 후 진행
bash teardown_all.sh --yes   # 확인 skip
```

8 step 을 의존성 역순으로 자동 실행 + 검증 명령 출력. 한 step 이라도 실패 시 즉시 중단 (`set -e`). 개별 실행은 아래 표 참조.

## Teardown 순서 (8 step)

| # | Phase | 명령 | 제거 대상 |
|---|---|---|---|
| 1 | 5 | `bash agents/supervisor/runtime/teardown.sh` | Supervisor Runtime + IAM Role + ECR repo + CW Log Group + OAuth provider |
| 2 | 5 | `bash agents/monitor_a2a/runtime/teardown.sh` | Monitor A2A Runtime + 동일 부속 |
| 3 | 5 | `bash agents/incident_a2a/runtime/teardown.sh` | Incident A2A Runtime + 동일 부속 |
| 4 | 4 | `bash agents/incident/runtime/teardown.sh` | Incident Runtime + 동일 부속 |
| 5 | 4 | `bash infra/{github-lambda,s3-lambda}/teardown.sh` ※ STORAGE_BACKEND 따라 분기 | (github) Lambda + Target `github-storage` / (s3) Lambda + S3 bucket + Target `s3-storage` + cross-stack policy |
| 6 | 3 | `bash agents/monitor/runtime/teardown.sh` | Monitor Runtime + 동일 부속 |
| 7 | 2 | `bash infra/cognito-gateway/teardown.sh` | Gateway + 2 Target + Cognito stack + 2 Lambda + DEPLOY_BUCKET + `.env` Phase 2 변수 |
| 8 | 0 | `bash infra/ec2-simulator/teardown.sh` | EC2 + alarms CFN stack |

## 진행 원칙

- **한 step 씩** 실행 — 결과 확인 후 다음 step.
- 각 teardown.sh 는 **idempotent** — 이미 삭제된 자원은 skip.
- 중간 step 에서 실패 시 stop, 원인 파악 후 재실행.
- Phase 5 (step 1~3) 만 재배포 시 step 1~3 만 teardown 하면 됨 (Phase 0~4 보존).

## 검증 (전체 teardown 후)

```
aws cloudformation list-stacks --region us-east-1 \
  --query "StackSummaries[?starts_with(StackName, 'aiops-demo-')].[StackName,StackStatus]" \
  --output table
```

→ 결과 비어있으면 CFN stack 0 (정상). AgentCore Runtime / Gateway / OAuth provider 는 teardown.sh 가 boto3 로 직접 삭제 (CFN stack 외부).

추가 확인:

```
aws bedrock-agentcore-control list-agent-runtimes --region us-east-1 \
  --query "agentRuntimes[?contains(agentRuntimeName, 'aiops_demo_')].agentRuntimeName" \
  --output table
```

→ `aiops_demo_${USER}_*` 미잔존 확인.

## 재배포 (역순 = build 순서)

teardown 후 다시 띄우려면:

```
bash infra/ec2-simulator/deploy.sh
bash infra/cognito-gateway/deploy.sh
uv run agents/monitor/runtime/deploy_runtime.py
bash infra/github-lambda/deploy.sh
uv run agents/incident/runtime/deploy_runtime.py
uv run agents/monitor_a2a/runtime/deploy_runtime.py
uv run agents/incident_a2a/runtime/deploy_runtime.py
uv run agents/supervisor/runtime/deploy_runtime.py
```
