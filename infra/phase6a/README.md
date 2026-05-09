# Phase 6a — deployments-storage Lambda + Gateway Target (Option X)

Phase 2 의 Gateway 에 `deployments-storage` Target 1건 추가. **새 Cognito 자원 0** (Option X — Phase 2 Client C 재사용). Phase 2 Cognito stack / Gateway / 기존 3 Target / Phase 4 미터치.

설계 원본: [`docs/design/phase6a.md`](../../docs/design/phase6a.md) §7 (deployments-storage Lambda).

## Option X 의 의미

본 Phase 6a 의 인증 설계 결정 (2026-05-09):

| 인증 hop | 메커니즘 | 사용 자원 |
|---|---|---|
| Operator → Supervisor | **SigV4 IAM** (Phase 4 패턴) | (Cognito 무관) |
| Supervisor → 3 sub-agents | Cognito Client C M2M Bearer | Phase 2 Client C 재사용 |

**핵심 통찰**: AgentCore `customJWTAuthorizer.allowedClients` 는 토큰의 `aud` (= client_id) 만 검증, scope 미검증. Phase 2 가 만든 Client C 의 토큰 (Gateway scope) 이 sub-agent A2A inbound 에도 통과. 따라서:
- 새 Cognito Client A/B 추가 불필요
- 새 ResourceServer / OperatorUser 불필요
- `cognito_extras.yaml` 불필요 (이전 design 의 ~143줄)

## 사전 조건

1. **Phase 0/2/3/4 deploy 완료** — Cognito UserPool + Client C + Gateway + 3 Target + 2 Runtime alive
2. **GitHub PAT scope `repo` (full write)** — Phase 4 가 `repo:read` 면 충분했지만, Phase 6a 의 `append_incident` 는 write 필요. 동일 SSM path `/aiops-demo/github-token` 재사용 — scope 만 확장:
   ```bash
   read -s -p "GitHub PAT (repo full): " GH_PAT && \
     aws ssm put-parameter --name /aiops-demo/github-token --type SecureString \
       --value "$GH_PAT" --region us-west-2 --overwrite && unset GH_PAT
   ```
3. **AWS 자격 증명** + `uv sync` 완료
4. **사용자 IAM Role 에 `bedrock-agentcore:InvokeAgentRuntime` 권한** — Operator CLI 가 SigV4 invoke

## 배포

```bash
bash infra/phase6a/deploy.sh
```

수행 단계 (3-step):
1. deployments_lambda CFN stack — Lambda + IAM Role + cross-stack policy on Phase 2 GatewayIamRole
2. boto3: Gateway Target `deployments-storage` 추가 (또는 update)
3. `.env` 갱신 — DEPLOYMENTS_STORAGE_LAMBDA_ARN

## 배포 후 .env 변화

```ini
# 새로 추가됨 (1줄만!)
DEPLOYMENTS_STORAGE_LAMBDA_ARN=arn:aws:lambda:...
```

→ Phase 2 의 기존 키 (`COGNITO_CLIENT_C_ID` 등) 그대로 활용. 새 키 1줄만.

## 다음 단계

배포 후 4 Runtime 배포 (Phase 6a Step B 의 산출물):
```bash
uv run agents/change/runtime/deploy_runtime.py
uv run agents/monitor_a2a/runtime/deploy_runtime.py
uv run agents/incident_a2a/runtime/deploy_runtime.py
uv run agents/supervisor/runtime/deploy_runtime.py     # ← sub-agent ARN cross-load 후 마지막
```

End-to-end smoke (Phase 6a Step D):
```bash
python agents/operator/cli.py --query "현재 상황 진단해줘"
```

## teardown

```bash
bash infra/phase6a/teardown.sh
```

순서:
1. Gateway Target 삭제
2. deployments_lambda stack 삭제
3. `.env` cleanup

Phase 0/2/3/4 자원 + Phase 6a Runtime 자원 보존 (Runtime teardown 은 별도). Phase 4 의 inline policy 보존 검증 step 포함.

## 자원 분리 격리

| Phase | Stack | Gateway Role 의 inline policy | Target |
|---|---|---|---|
| Phase 2 | `aiops-demo-${user}-phase2-cognito` | `invoke-wrapper-lambdas` (managed) | history-mock, cloudwatch-wrapper |
| Phase 4 | `aiops-demo-${user}-phase4-github` | `aiops-demo-${user}-phase4-gateway-invoke-github` | github-storage |
| **Phase 6a** | `aiops-demo-${user}-phase6a-deployments` | `aiops-demo-${user}-phase6a-gateway-invoke-deployments` | **deployments-storage** |

→ phase 별 stack delete 시 자기 inline policy 만 detach. Phase 2 Role 자체는 보존.

## reference

- `docs/design/phase6a.md` §7 (Lambda + Target 상세)
- `infra/phase4/deploy.sh` (cfn package + boto3 setup 동일 패턴)
- 02-a2a-agent-sigv4 reference (SigV4 IAM A2A 패턴 — Operator CLI 측)
