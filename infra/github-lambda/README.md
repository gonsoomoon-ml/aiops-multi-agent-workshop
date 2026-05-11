# Phase 4 — GitHub storage Lambda + Gateway Target

Phase 2 의 Gateway 에 `github-storage` Target 1건 추가. Phase 2 Cognito stack / Gateway / 기존 2 Target 미터치, Phase 3 Monitor Runtime 도 미터치.

설계 원본: [`docs/design/phase4.md`](../../docs/design/phase4.md) §4 (GitHub storage 상세).

## 사전 조건

1. **Phase 2 완료** — `infra/cognito-gateway/deploy.sh` 통과 + repo root `.env` 채워진 상태 (`DEMO_USER`, `GATEWAY_ID`, `AWS_REGION` 등).
2. **Phase 3 완료** — Monitor Runtime READY (`aiops_demo_${DEMO_USER}_monitor` alive).
3. **GitHub PAT 등록** — SSM SecureString `/aiops-demo/github-token` 에 GitHub Personal Access Token 저장.
4. AWS 자격 증명 + Docker daemon + `uv sync` 완료.

### GitHub PAT 등록 (one-time)

`data/runbooks/` 디렉토리 read 권한이 필요. https://github.com/settings/tokens 에서 발급:

- **public repo** (워크샵 default `gonsoomoon-ml/aiops-multi-agent-workshop`): scope **불필요** — classic token 또는 fine-grained token, scope 없이 발급 가능.
- **private repo** (fork 후 private 으로 사용 시): scope `repo` (full) 필요.

발급 후 SSM 등록 — `read -s` 로 PAT 가 shell history / 화면에 남지 않게:

```bash
read -s -p "GitHub PAT: " GH_PAT && aws ssm put-parameter --name /aiops-demo/github-token --type SecureString --value "$GH_PAT" --region us-west-2 --overwrite && unset GH_PAT
```

값 검증 (decryption 권한 보유 시):

```bash
aws ssm get-parameter --name /aiops-demo/github-token --with-decryption --region us-west-2 --query 'Parameter.Value' --output text
```

`deploy.sh` 가 첫 단계에서 SSM 존재 여부를 확인 — 미등록 시 fail-fast.

## 배포 순서

```bash
# 1. Phase 4 infra (이 디렉토리) — Lambda + IAM + cross-stack policy + Gateway Target
bash infra/github-lambda/deploy.sh

# 2. Incident Agent Runtime — Phase 4 infra 가 alive 여야 invoke 시 runbook fetch 가능
uv run agents/incident/runtime/deploy_runtime.py
```

`deploy.sh` 가 수행하는 것:
1. Phase 2 stack + `GATEWAY_ID` + SSM PAT 사전 검증.
2. `cfn package` → S3 (Phase 2 의 `aiops-demo-${DEMO_USER}-deploy-*` bucket 재사용).
3. CFN deploy `aiops-demo-${DEMO_USER}-github-lambda` (Lambda + Role + Phase 2 Role 에 inline policy 추가).
4. boto3 로 Gateway Target `github-storage` create-or-update — 재배포 시 lambdaArn + schema 자동 동기화.
5. `.env` 에 `GITHUB_STORAGE_LAMBDA_ARN` 갱신.

## 검증 (P4-A4)

Incident Runtime 배포 후 단독 invoke — runbook content 가 응답에 포함되어야 함:

```bash
uv run agents/incident/runtime/invoke_runtime.py --alarm payment-${DEMO_USER}-status-check
```

기대: SSE stream 의 마지막 JSON 에 `"runbook_found": true` + `recommended_actions` 배열 (`["reboot instance", "replace via Auto Scaling Group", ...]`).

## 정리 순서 (reverse)

```bash
# 1. Incident Runtime 먼저 (Lambda invoke 시 fail 방지)
bash agents/incident/runtime/teardown.sh

# 2. Phase 4 infra (Target → CFN stack)
bash infra/github-lambda/teardown.sh
```

`teardown.sh` 가 수행하는 것:
1. Gateway Target `github-storage` 삭제 (`GATEWAY_ID` 미설정 시 `list-gateways` 자동 복구).
2. CFN stack delete — Lambda + Role + cognito-gateway 의 GatewayIamRole 에서 inline policy 자동 detach.
3. `.env` 에서 `GITHUB_STORAGE_LAMBDA_ARN` 제거.
4. **cognito-gateway stack/Gateway 보존 검증** + **GatewayIamRole 의 invoke-github inline policy 정상 detach 검증**.

## 파일 구성

| 파일 | 역할 |
|---|---|
| `deploy.sh` | orchestrator — CFN package/deploy + boto3 Target setup |
| `teardown.sh` | reverse 삭제 + Phase 2/3 자원 보존 검증 |
| `github_lambda.yaml` | CFN — Lambda + IAM Role + cross-stack inline policy |
| `lambda_src/github_storage/handler.py` | Lambda 코드 — `get_runbook(alarm_name)` 1개 도구 |
| `setup_github_target.py` | boto3 — Gateway Target create-or-update |
