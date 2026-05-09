# Phase 6a — Cognito extras + deployments-storage Lambda + Gateway Target

Phase 2 의 Gateway / Cognito UserPool 에 **추가**:
- **Cognito Client A + B + OperatorUser** (cognito_extras stack — Phase 2 stack 미터치)
- **deployments-storage Lambda** (deployments_lambda stack — Phase 4 의 github_lambda 패턴 정확 차용)
- **Gateway Target `deployments-storage`** (boto3 — Phase 2 Gateway 에 1건 추가)

설계 원본: [`docs/design/phase6a.md`](../../docs/design/phase6a.md) §6 + §7.

## 사전 조건

1. **Phase 0/2/3/4 deploy 완료** — Cognito UserPool + Gateway + 3 Target + 2 Runtime alive
2. **GitHub PAT scope `repo` (full write)** — Phase 4 가 `repo:read` 면 충분했지만, Phase 6a 의 `append_incident` 는 write 필요. 동일 SSM path `/aiops-demo/github-token` 재사용 — scope 만 확장:
   ```bash
   read -s -p "GitHub PAT (repo full): " GH_PAT && \
     aws ssm put-parameter --name /aiops-demo/github-token --type SecureString \
       --value "$GH_PAT" --region us-west-2 --overwrite && unset GH_PAT
   ```
3. **AWS 자격 증명** + `uv sync` 완료
4. **(옵션) `OPERATOR_USER_EMAIL` env 또는 `git config user.email`** — Operator user 의 email 속성. 미설정 시 placeholder `${DEMO_USER}@aiops-demo.local` (alert 발송 안 함)

## 배포

```bash
bash infra/phase6a/deploy.sh
```

수행 단계:
1. Phase 2 stack 의 UserPoolId / Domain query
2. cognito_extras CFN stack — Client A + B + 새 ResourceServer + OperatorUser
3. Client B secret 캡처 + Operator 비밀번호 설정 (boto3 admin_set_user_password)
4. deployments_lambda CFN stack — Lambda + IAM Role + cross-stack policy
5. boto3: Gateway Target `deployments-storage` 추가 (또는 update)
6. `.env` 갱신 — COGNITO_CLIENT_A/B_*, AGENT_INVOKE_SCOPE, OPERATOR_USERNAME, DEPLOYMENTS_STORAGE_LAMBDA_ARN
7. `.env.operator` 작성 (gitignored, OPERATOR_PASSWORD 포함)

## 배포 후 .env 변화

```ini
# 새로 추가됨
COGNITO_USER_POOL_ID=us-west-2_xxxxxxxxx
COGNITO_DOMAIN=aiops-demo-ubuntu
COGNITO_CLIENT_A_ID=xxxxxxxxxxxxxxxxxxxxxxxxxx
COGNITO_CLIENT_B_ID=xxxxxxxxxxxxxxxxxxxxxxxxxx
COGNITO_CLIENT_B_SECRET=xxxxx...
COGNITO_AGENT_INVOKE_SCOPE=aiops-demo-ubuntu-agent-invoke/invoke
OPERATOR_USERNAME=operator-ubuntu
DEPLOYMENTS_STORAGE_LAMBDA_ARN=arn:aws:lambda:...
```

`.env.operator` (별 파일, gitignored):
```ini
OPERATOR_USERNAME=operator-ubuntu
OPERATOR_PASSWORD=<boto3-generated random password>
```

## 다음 단계

배포 후 4 Runtime 배포 (Phase 6a Step B 의 산출물):
```bash
uv run agents/change/runtime/deploy_runtime.py
uv run agents/monitor_a2a/runtime/deploy_runtime.py
uv run agents/incident_a2a/runtime/deploy_runtime.py
uv run agents/supervisor/runtime/deploy_runtime.py     # ← sub-agent ARN cross-load 후 마지막
```

그 후:
- Phase 6a Step E (`deployments/<date>.log` seed content)
- Phase 6a Step D (Operator CLI — end-to-end smoke)

## teardown

```bash
bash infra/phase6a/teardown.sh
```

순서:
1. Gateway Target 삭제
2. deployments_lambda stack 삭제
3. cognito_extras stack 삭제
4. `.env` / `.env.operator` cleanup

Phase 0/2/3/4 자원 + Phase 6a Runtime 자원 보존 (Runtime teardown 은 별도).

## 자원 분리 격리

| Phase | Stack | Gateway Role 의 inline policy | Target |
|---|---|---|---|
| Phase 2 | `aiops-demo-${user}-phase2-cognito` | `invoke-wrapper-lambdas` (managed) | history-mock, cloudwatch-wrapper |
| Phase 4 | `aiops-demo-${user}-phase4-github` | `aiops-demo-${user}-phase4-gateway-invoke-github` | github-storage |
| **Phase 6a** | `aiops-demo-${user}-phase6a-cognito-extras` + `aiops-demo-${user}-phase6a-deployments` | `aiops-demo-${user}-phase6a-gateway-invoke-deployments` | **deployments-storage** |

→ phase 별 stack delete 시 자기 inline policy 만 detach. Phase 2 Role 자체는 보존.

## reference

- `docs/design/phase6a.md` §6 (Cognito 상세), §7 (Lambda + Target 상세)
- `infra/phase4/deploy.sh` (cfn package + boto3 setup 동일 패턴)
- `02-use-cases/A2A-multi-agent-incident-response/cloudformation/cognito.yaml` (Cognito multi-Client + ResourceServer 패턴)
