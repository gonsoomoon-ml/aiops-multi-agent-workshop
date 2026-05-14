# `.env` — 환경 변수 lifecycle

> repo root `.env` 가 모든 phase 의 자원 식별자 (ARN / ID / URL / Cognito secret) 를 누적 저장. `bootstrap.sh` 가 최초 생성 (`.env.example` template 복사) → 각 phase deploy 가 자기 prefix entry 추가 → 각 phase teardown 이 자기 entry 만 제거.

---

## 1. 파일 2종

| 파일 | 역할 | git 추적 |
|---|---|---|
| `.env.example` | template — 모든 키 + 인라인 주석 + default 값 (`AWS_REGION=us-west-2`, `STORAGE_BACKEND=s3` 등) | ✅ (commit) |
| `.env` | 실제 값 — `DEMO_USER` 등 사용자 입력 + phase deploy 산출물 | ❌ (`.gitignore`) |

**최초 생성**: Phase 0 진입 전 `bash bootstrap.sh` 실행 → (1) `cp .env.example .env` (없을 때만), (2) `AWS_REGION` / `DEMO_USER` / `STORAGE_BACKEND` 대화형 결정 + 검증, (3) (`STORAGE_BACKEND=github` 선택 시) GitHub PAT → SSM SecureString.

---

## 2. Phase 별 추가 entry

| Phase | 채우는 entry | 채우는 script |
|---|---|---|
| **0** (사용자 입력) | `AWS_REGION`, `DEMO_USER`, `STORAGE_BACKEND` | `bootstrap.sh` |
| **0** (EC2 simulator) | `EC2_INSTANCE_ID`, `EC2_PUBLIC_IP` | `infra/ec2-simulator/deploy.sh` |
| **2** (Cognito + Gateway) | `COGNITO_USER_POOL_ID`, `COGNITO_CLIENT_ID`, `COGNITO_CLIENT_SECRET`, `COGNITO_DOMAIN`, `COGNITO_GATEWAY_SCOPE`, `GATEWAY_URL`, `GATEWAY_ID`, `LAMBDA_HISTORY_MOCK_ARN`, `LAMBDA_CLOUDWATCH_WRAPPER_ARN` | `infra/cognito-gateway/deploy.sh` |
| **3** (Monitor Runtime) | `MONITOR_RUNTIME_NAME`, `MONITOR_RUNTIME_ARN`, `MONITOR_RUNTIME_ID`, `MONITOR_OAUTH_PROVIDER_NAME` | `agents/monitor/runtime/deploy_runtime.py` |
| **4** (S3 storage Lambda) | `STORAGE_BUCKET_NAME`, `S3_STORAGE_LAMBDA_ARN` | `infra/s3-lambda/deploy.sh` |
| **4** (Incident Runtime) | `INCIDENT_RUNTIME_NAME`, `INCIDENT_RUNTIME_ARN`, `INCIDENT_RUNTIME_ID`, `INCIDENT_OAUTH_PROVIDER_NAME` | `agents/incident/runtime/deploy_runtime.py` |
| **5** (Monitor A2A) | `MONITOR_A2A_RUNTIME_NAME`, `MONITOR_A2A_RUNTIME_ARN`, `MONITOR_A2A_RUNTIME_ID`, `MONITOR_A2A_OAUTH_PROVIDER_NAME` | `agents/monitor_a2a/runtime/deploy_runtime.py` |
| **5** (Incident A2A) | `INCIDENT_A2A_*` (NAME/ARN/ID + OAUTH_PROVIDER_NAME) | `agents/incident_a2a/runtime/deploy_runtime.py` |
| **5** (Supervisor) | `SUPERVISOR_*` (NAME/ARN/ID + OAUTH_PROVIDER_NAME) | `agents/supervisor/runtime/deploy_runtime.py` |

추가로 모든 phase 가 OTEL config + 3종 model ID (`MONITOR_MODEL_ID` / `INCIDENT_MODEL_ID` / `SUPERVISOR_MODEL_ID`) 는 `.env.example` default 그대로 사용 (변경 거의 없음).

---

## 3. Phase 5 cross-load 흐름

Supervisor deploy 는 자기 entry 만 만드는 게 아니라 **sub-agent 의 ARN 을 자기 container env_vars 로 cross-load** — Supervisor LLM 이 `call_monitor_a2a` / `call_incident_a2a` 도구 안에서 sub-agent A2A 호출 시 ARN 필요.

```
[1] agents/monitor_a2a/runtime/deploy_runtime.py
       → root .env 에 MONITOR_A2A_RUNTIME_ARN 저장

[2] agents/incident_a2a/runtime/deploy_runtime.py
       → root .env 에 INCIDENT_A2A_RUNTIME_ARN 저장
                                                │
[3] agents/supervisor/runtime/deploy_runtime.py ┘
       step [2/6] sub-agent ARN cross-load
       ↓ os.environ.get("MONITOR_A2A_RUNTIME_ARN") + os.environ.get("INCIDENT_A2A_RUNTIME_ARN")
       ↓ Supervisor container env_vars 로 주입
       ↓ Runtime.launch()
```

따라서 Phase 5 deploy 순서는 의존 순서 **monitor_a2a → incident_a2a → supervisor**. 역순 실행 시 supervisor step [2/6] 가 `.env` 에서 ARN 못 찾고 fail.

→ 코드: `agents/supervisor/runtime/deploy_runtime.py:91-99` (cross-load 함수).

---

## 4. Teardown 시 `.env` cleanup

각 phase 의 `teardown.sh` 는 **자기가 채운 prefix entry 만** 제거 (다른 phase 자원 보존). 예:

- `bash agents/supervisor/runtime/teardown.sh` → `SUPERVISOR_*` 만 비움
- `bash agents/monitor_a2a/runtime/teardown.sh` → `MONITOR_A2A_*` 만 비움
- `bash infra/cognito-gateway/teardown.sh` → `COGNITO_*` + `GATEWAY_*` + `LAMBDA_HISTORY_MOCK_ARN` + `LAMBDA_CLOUDWATCH_WRAPPER_ARN` 비움

자세한 전체 teardown 순서: [`teardown.md`](teardown.md).

---

## 5. Security 주의

- **`.gitignore` 포함**: `.env` 는 절대 commit 금지 — `COGNITO_CLIENT_SECRET` 등 포함
- **진짜 secret 은 SSM**: GitHub PAT 같은 high-sensitivity secret 은 `.env` 가 아니라 **SSM SecureString** 에 저장 (`.env` 에는 path 만 — `GITHUB_TOKEN_SSM_PATH=/aiops-demo/github-token`)
- **Runtime container 안에선 `.env` 미사용**: `deploy_runtime.py` 가 launch 시 env_vars 로 명시 주입한 값만 사용 — container 에 `.env` 파일 자체가 없음 (build context 에서 제외). 즉 `.env` 는 *deploy time host* 의 state, runtime 동작과 별개.

---

## reference

| 자료 | 용도 |
|---|---|
| [`.env.example`](../../.env.example) | template + 인라인 주석 (각 key 의 의미·default·언제 채워지는지) |
| [`bootstrap.sh`](../../bootstrap.sh) | `.env` 최초 생성 + 사용자 입력 5단계 |
| [`teardown.md`](teardown.md) | 의존 역순 8 step (각 step 의 `.env` cleanup 포함) |
