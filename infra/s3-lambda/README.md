# S3 storage Lambda (Phase 4 alternative backend)

GitHub backend (`infra/github-lambda/`) 의 형제. **본 S3 backend 가 default** — corp 환경 호환 + GitHub PAT 불필요. GitHub backend 는 청중이 fork-and-edit 학습 패턴을 원할 때 선택.

`STORAGE_BACKEND=s3` (default) 시 본 디렉토리 사용. `STORAGE_BACKEND=github` 시 `infra/github-lambda/` 사용.

## 디자인

GitHub backend 와 **byte-level 동형** 응답 shape — Incident Agent 코드는 backend 무관 (`TOOL_TARGET_PREFIX` 만 다름).

```
                         ┌─ STORAGE_BACKEND=github → tool 'github-storage___get_runbook' → infra/github-lambda
Incident Agent (Strands) ┤
                         └─ STORAGE_BACKEND=s3     → tool 's3-storage___get_runbook'     → infra/s3-lambda (본 디렉토리)
```

| 측면 | github-lambda | s3-lambda (본 디렉토리) |
|---|---|---|
| 데이터 저장소 | GitHub repo (이 repo, `data/runbooks/` directory) | S3 bucket `aiops-demo-${USER}-storage-${ACCOUNT}-${REGION}` |
| Lambda 데이터 fetch | GitHub Contents API (Bearer + raw) | boto3 S3 GetObject |
| 인증 (Lambda → 데이터) | SSM SecureString PAT | Lambda IAM Role (직접 GetObject 권한) |
| 사전 요구사항 | GitHub PAT 발급 + SSM 저장 (`bash setup/store_github_token.sh`) | (없음) |
| corp 환경 호환 | 사내 GitHub 차단 시 X | OK (S3 는 일반적으로 허용) |
| 데이터 변경 흐름 | git commit + push → 자동 반영 | `aws s3 sync data/runbooks/ s3://...` 또는 deploy.sh 재실행 |

## 자원

CFN stack `aiops-demo-${DEMO_USER}-s3-lambda` 가 만드는 자원:

1. **S3 bucket** `aiops-demo-${DEMO_USER}-storage-${ACCOUNT}-${REGION}` — versioning enabled, public block 활성, DeletionPolicy=Delete (워크샵)
2. **IAM Role** `aiops-demo-${DEMO_USER}-s3-storage-role` — Lambda execution + S3 GetObject/ListBucket
3. **Lambda Function** `aiops-demo-${DEMO_USER}-s3-storage` — Python 3.13, boto3 S3 client
4. **Inline Policy** `aiops-demo-${DEMO_USER}-gateway-invoke-s3` — cognito-gateway 의 GatewayIamRole 에 cross-stack 부착

추가로 boto3 가 만드는 것:
5. **Gateway Target** `s3-storage` — cognito-gateway 의 Gateway 에 추가

## 사전 요구사항

1. **cognito-gateway 완료** — `infra/cognito-gateway/deploy.sh` 통과 + repo root `.env` 채워진 상태 (`DEMO_USER`, `GATEWAY_ID`, `AWS_REGION`).
2. **`data/runbooks/*.md`** — repo 에 seed 대상 markdown 존재.

## 사용

### Deploy

```
bash infra/s3-lambda/deploy.sh
```

흐름:
1. cognito-gateway prerequisite 검증
2. `cfn package` (Lambda zip → cognito-gateway 의 deploy bucket 재사용)
3. `cfn deploy` — S3 bucket + Lambda + IAM + cross-stack policy
4. `aws s3 sync data/runbooks/ s3://<bucket>/data/runbooks/` — seed 데이터 업로드
5. `setup_s3_target.py` — Gateway Target `s3-storage` 등록
6. `.env` 갱신: `S3_STORAGE_LAMBDA_ARN`, `STORAGE_BUCKET_NAME`

### Teardown

```
bash infra/s3-lambda/teardown.sh
```

흐름:
1. Gateway Target `s3-storage` 삭제
2. S3 bucket 비우기 (versioning enabled — current + noncurrent + delete-markers 모두 제거)
3. CFN stack delete — Lambda + Role + cross-stack Policy 자동 detach
4. `.env` 정리 + verify

## 파일 구성

| 파일 | 역할 |
|---|---|
| `s3_lambda.yaml` | CFN — S3 bucket + Lambda + IAM Role + cross-stack policy |
| `lambda_src/s3_storage/handler.py` | Lambda handler — S3 GetObject (github handler 와 byte-level 동형) |
| `setup_s3_target.py` | Gateway Target `s3-storage` 등록 (boto3, idempotent) |
| `deploy.sh` | 전체 orchestration |
| `teardown.sh` | reverse 삭제 (versioning bucket 비우기 포함) |

## Agent 통합 메모

현재 `agents/incident{,_a2a}/runtime/agentcore_runtime.py` 의 `TOOL_TARGET_PREFIX = "github-storage___"` 가 hard-code. S3 backend 로 향하게 하려면:

```python
TOOL_TARGET_PREFIX = f"{os.environ.get('STORAGE_BACKEND', 's3')}-storage___"
```

이는 Phase 4 review 단계의 별도 변경 (preservation rule 영향). 그때 `STORAGE_BACKEND` env 를 `.env` → Runtime container 로 전달하는 부분도 같이 점검.
