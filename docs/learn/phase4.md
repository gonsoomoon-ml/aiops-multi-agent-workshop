# Phase 4 — Incident Agent + Storage Backend

> Phase 4 는 Phase 3 의 Monitor Runtime 패턴을 **Incident Agent 에 carry-over**. `@app.entrypoint` + `OAuth2CredentialProvider` 자동 inject + MCPClient → Gateway 호출. 차이점: **storage Lambda** (S3 default / GitHub 선택) 가 **runbook** 을 fetch, Incident 가 alarm 1건 받아 **runbook 조회 + 진단 + 권장 조치 JSON** 반환.

---

## 1. 왜 필요한가   *(~3 min read)*

Phase 4 는 **multi-agent topology 의 첫 단계** — Monitor 옆에 Incident Runtime 을 추가하여 알람 분류 vs runbook 진단을 책임 분리 + Phase 5 sequential CLI / A2A 의 토대. 4가지 동기:


| 동기                       | Phase 3 한계               | Phase 4 해결                                                                    |
| ------------------------ | ------------------------ | ----------------------------------------------------------------------------- |
| **Multi-agent topology** | Monitor 1개만 — 진단/조치 분리 X | Incident 독립 Runtime — 알람 분류 (Monitor) vs runbook driven 진단 (Incident) 책임 분리   |
| **Runbook driven 의사결정**  | hard-coded LLM knowledge | data/runbooks/*.md 외부화 + Lambda fetch → 운영팀이 markdown 으로 직접 관리                |
| **Storage backend 추상화**  | (없음)                     | `STORAGE_BACKEND=s3` 또는 `github` env 분기 — Lambda 응답 shape 동형 (Incident 코드 무관) |
| **Sequential CLI 준비**    | (없음)                     | Monitor → Incident 순차 호출 (Phase 5 A2A 전 단계)                                   |


---

## 2. 진행 (Hands-on)   *(deploy ~10 min / 검증 ~5 min)*

### 2-1. 사전 확인

- **bootstrap 1회 실행** (`bash bootstrap.sh`) — Phase 1 과 동일
- **Phase 2 완료** (Cognito stack + Gateway alive, repo root `.env` 의 `GATEWAY_URL` / `COGNITO_`*)
- **Phase 3 완료** (Monitor Runtime READY — `MONITOR_RUNTIME_ARN` repo root `.env`)
- AWS 자격 증명 + Docker daemon + `uv sync`
- `data/runbooks/*.md` 가 repo 에 존재 (S3 backend seed 대상)

### 2-2. Deploy

**Step C — Storage Lambda + Gateway Target** (backend 별 한 번):

S3 backend (default):

```bash
bash infra/s3-lambda/deploy.sh
```

[주의: 실행 안함] 또는 GitHub backend (PAT + SSM 필요): <-- bootstrap.sh 에서 S3 대신에 Github 선택시

```bash
bash infra/github-lambda/deploy.sh
```

Storage Lambda + bucket/repo seed + Gateway Target (`s3-storage` 또는 `github-storage`) 등록. `.env` 에 `S3_STORAGE_LAMBDA_ARN` / `STORAGE_BUCKET_NAME` (또는 `GITHUB_STORAGE_LAMBDA_ARN`) 자동 작성.

**Step D — Incident Runtime**:

```bash
uv run agents/incident/runtime/deploy_runtime.py
```

5단계 — shared/×2 + _shared_debug copy → toolkit configure → launch → IAM extras + OAuth provider → READY. ~5-10분 첫 배포, ~40초 update. 성공 시 repo root `.env` 에 `INCIDENT_RUNTIME_*` + `INCIDENT_OAUTH_PROVIDER_NAME` 저장.

deploy 후 interactive shell 에 동기:

```bash
source .env
```

### 2-3. 검증

#### 단독 alarm 진단 (Step D 완료 후)

env 변수 export:

```bash
set -a; source .env; set +a
```

invoke:

```bash
uv run agents/incident/runtime/invoke_runtime.py --alarm "payment-${DEMO_USER}-status-check"
```

JSON 출력 schema:

```json
{
  "alarm": "payment-<demo-user>-status-check",
  "runbook_found": true,
  "diagnosis": "한국어 1-2 문장 — runbook content 기반 진단",
  "recommended_actions": ["영어 verb phrase", ...],
  "severity": "P1"
}
```

`runbook_found:false` 케이스 (등록 안 된 alarm) 도 같은 schema, fallback severity `P2`.

마지막 라인:

```
📊 Tokens — Total: 6,945 | Input: 1,569 | Output: 376 | Cache R/W: 2,500/2,500
✅ 완료 — TTFT 14.9초 / total 18.0초
```

**TTFT (client-side)** — invoke 시작 → 첫 `agent_text_stream` chunk 도착. container 내부 FlowHook 의 LLM TTFT 와 분리.

#### Prompt caching 확인 — 같은 alarm 재호출

5분 이내 같은 alarm 으로 다시 invoke (`source .env` 가 위 단계에서 export 된 상태 가정):

```bash
uv run agents/incident/runtime/invoke_runtime.py --alarm "payment-${DEMO_USER}-status-check"
```

#### Debug 모드 (선택) — Container trace 를 CloudWatch logs 로

호스트 `DEBUG=1` 이 invoke_runtime.py 의 client process 에만 영향. 진짜 debug 코드 (FlowHook / dump_stream_event) 는 Runtime container 안 — container env 가 `DEBUG=1` 이어야 활성. container env 는 deploy 시점에 고정 → 재배포 필요.

`DEBUG=1` 으로 재배포:

```bash
DEBUG=1 uv run agents/incident/runtime/deploy_runtime.py
```

deploy script 가 활성 상태 즉시 표시:

```
[3/5] Runtime 배포 중 (Docker 빌드 → ECR 푸시 → 생성)...
   ⏳ 첫 배포 ~5-10분, 업데이트 ~40초
   ℹ DEBUG=1 활성 — container 에 forward (FlowHook + TTFT + trace 출력)
     로그 확인: aws logs tail /aws/bedrock-agentcore/runtimes/<INCIDENT_RUNTIME_ID>-DEFAULT --follow --region us-east-1
...
   DEBUG 모드:        ACTIVE (CloudWatch logs 에 FlowHook trace 출력)
```

invoke (DEBUG prefix 불필요 — container 가 이미 DEBUG=1):

```bash
uv run agents/incident/runtime/invoke_runtime.py --alarm "payment-${DEMO_USER}-status-check"
```

`.env` 변수 shell 에 export (CloudWatch tail 명령용):

```bash
set -a; source .env; set +a
```

CloudWatch logs tail:

```bash
aws logs tail /aws/bedrock-agentcore/runtimes/${INCIDENT_RUNTIME_ID}-DEFAULT --follow --region "${AWS_REGION:-us-east-1}"
```

확인 가능 trace (DEBUG=1 container 기준) — 모든 라벨이 `Incident` prefix 로 일관:

- `[DEBUG Incident → Gateway] MCP client init (...)` — `mcp_client.create_mcp_client(agent_name="Incident")` 호출자가 명시
- `┏━━━ system prompt loaded — system_prompt.md (3,928 chars) ━━━` (한국어 char count, UTF-8 bytes 는 5,314)
- `┏━━━ Incident → Bedrock — LLM call #N ━━━` (FlowHook delta dump)
- `[DEBUG Bedrock → Incident] call #N TTFT / usage / done` (FlowHook BeforeModel/AfterModel)
- `┏━━━ message complete (role=assistant) ━━━ 💬 Bedrock → Incident (decided: call tool) 🔧 toolUse: s3-storage___get_runbook(...)` (event_dump message complete)
- `[DEBUG Incident → Gateway] tool call: ...` (FlowHook BeforeToolCall)
- `┏━━━ message complete (role=user) ━━━ 🔧 Lambda → Incident (tool result) 📋 toolResult: ...` (event_dump)

> 라벨 prefix 의 일관성은 3개 위치에서 `agent_name` 명시 필요:
>
> 1. `agent.py:create_agent()` 가 `FlowHook(agent_name="Incident")` 등록 — pre/post-call + before-tool trace
> 2. `agent.py:create_agent()` 가 agent attribute (`agent._debug_agent_name`) 셋업 → `event_dump.py` 가 message complete + TTFT 라벨에 사용
> 3. `agentcore_runtime.py` 가 `create_mcp_client(agent_name="Incident")` 전달 — helper 의 MCP client init 라벨
>
> 2 는 FlowHook 이 자동 셋업 (`_before_model` 안), 1 + 3 은 호출자가 명시. Phase 5 supervisor / a2a 작성 시 동일 3 곳 모두 매칭 필요.

자세한 trace 의미: `[debug_mode.md](debug_mode.md)`.

### 2-4. 정리 (P4-A5)

**Step D — Incident Runtime + OAuth provider + ECR + IAM**:

```bash
bash agents/incident/runtime/teardown.sh
```

**Step C — Storage Lambda + Gateway Target** (backend 별):

S3 backend:

```bash
bash infra/s3-lambda/teardown.sh
```

또는 GitHub backend:

```bash
bash infra/github-lambda/teardown.sh
```

Incident teardown 후 Phase 3 Monitor + Phase 2 Cognito stack + Phase 2 Gateway 보존 자동 verify (negative check).

---

## 3. 무엇을 만드나   *(~3 min read)*


| 산출물                                                 | 위치                                                | 비고                                                                                                                                                                 |
| --------------------------------------------------- | ------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Storage Lambda** (S3 default)                     | `infra/s3-lambda/`                                | CFN — S3 bucket + Lambda + IAM + cross-stack policy. `data/runbooks/<class>.md` 조회                                                                                 |
| **Storage Lambda** (GitHub 선택)                      | `infra/github-lambda/`                            | sibling backend. PAT 필요. byte-level 동형 응답 shape                                                                                                                    |
| **Gateway Target** `s3-storage` 또는 `github-storage` | boto3 (`setup_*_target.py`)                       | cognito-gateway 의 Gateway 에 추가 (기존 Target 유지)                                                                                                                      |
| **Incident Runtime**                                | `agents/incident/runtime/agentcore_runtime.py`    | `@app.entrypoint` 함수 `incident_agent` — payload `{alarm_name}` → SSE yield (`agent_text_stream` / `token_usage` / `workflow_complete`)                             |
| **Incident agent factory**                          | `agents/incident/shared/agent.py`                 | Strands Agent 생성 — prompt caching Layer 1+2 + FlowHook(`agent_name="Incident"`) 등록                                                                                 |
| **System prompt**                                   | `agents/incident/shared/prompts/system_prompt.md` | JSON-only 출력 schema + Severity 판단 기준 (P1/P2/P3) + 출력 예시 3건                                                                                                         |
| **5-step deploy**                                   | `agents/incident/runtime/deploy_runtime.py`       | (1) monitor/shared + incident/shared + _shared_debug copy → (2) toolkit configure → (3) launch → (4) IAM extras + OAuth provider → (5) READY + repo root `.env` 저장 |
| **호출 테스트**                                          | `agents/incident/runtime/invoke_runtime.py`       | `boto3 invoke_agent_runtime` + SSE + token usage + TTFT + `--session-id` (warm container)                                                                          |
| **자원 정리**                                           | `agents/incident/runtime/teardown.sh`             | 6 step reverse + Phase 3 Monitor + Phase 2 Cognito 보존 verify                                                                                                       |


**핵심**: Storage Lambda 가 backend 추상화 layer — Incident agent 코드는 `STORAGE_BACKEND=s3|github` env 분기만, 응답 shape 동형으로 backend 무관.

**새 AWS 자원** (S3 backend):

- S3 bucket × 1 (versioned, public block)
- Lambda × 1 (Python 3.13, S3 GetObject)
- IAM Role × 1 + cross-stack inline policy × 1
- AgentCore Runtime × 1 + ECR × 1 + IAM execution role × 1 (toolkit)
- `OAuth2CredentialProvider` × 1 (Incident 전용)
- Gateway Target × 1 (`s3-storage`)

**재사용 자원 (Phase 0/2/3)**: Phase 2 Cognito + Gateway, Phase 3 Monitor Runtime (Phase 5 sequential CLI 에서 같이 호출), Phase 0 EC2 alarm `payment-${DEMO_USER}-`* (alarm name 으로 runbook 조회 trigger).

---

## 4. 어떻게 동작   *(~10 min read)*

### Storage backend 추상화 (D3-D4)

Incident Agent 는 backend 무관. tool name prefix 만 분기:

```python
TOOL_TARGET_PREFIX = f"{os.environ.get('STORAGE_BACKEND', 's3')}-storage___"
```

- `STORAGE_BACKEND=s3` → tool `s3-storage___get_runbook` → S3 Lambda
- `STORAGE_BACKEND=github` → tool `github-storage___get_runbook` → GitHub Lambda

Lambda 응답 shape 동일 (`runbook_found`, `path`, `content`) → Agent 코드 무변경.

### 호출 흐름 — Phase 3 와의 차이

Phase 3 와 동일 entity 흐름 (invoke → SIGV4 → container → OAuth → Gateway → Lambda → Bedrock). Phase 4 의 deltas:

- **Payload**: `{alarm_name}` (vs Phase 3 `{mode, query}`)
- **Tool dispatch**: `TOOL_TARGET_PREFIX = "${STORAGE_BACKEND}-storage___"` env-based (vs Phase 3 `MODE_CONFIG` dict)
- **Output**: JSON-only stream (`{alarm, runbook_found, diagnosis, recommended_actions, severity}`) vs Phase 3 text stream
- **Tool**: `get_runbook(alarm_name)` → Lambda S3 GetObject (vs Phase 3 multi-tool list_tools)
- **OAuth provider**: `aiops_demo_${DEMO_USER}_incident_gateway_provider` (Monitor 와 분리, 패턴 동일)

자세한 entity-level diagram: `[phase3.md](phase3.md)` `### 호출 흐름` + `[debug_mode.md](debug_mode.md)` §5-1.

## 5. References


| 자료                                                                                                         | 용도                                                      |
| ---------------------------------------------------------------------------------------------------------- | ------------------------------------------------------- |
| `[agents/incident/runtime/agentcore_runtime.py](../../agents/incident/runtime/agentcore_runtime.py)`       | Runtime entrypoint — payload `{alarm_name}` + SSE yield |
| `[agents/incident/shared/agent.py](../../agents/incident/shared/agent.py)`                                 | Strands Agent 생성 — caching + FlowHook                   |
| `[agents/incident/shared/prompts/system_prompt.md](../../agents/incident/shared/prompts/system_prompt.md)` | JSON schema + Severity 기준 + 예시 3건                       |
| `[agents/incident/runtime/deploy_runtime.py](../../agents/incident/runtime/deploy_runtime.py)`             | 5단계 배포 (build context 3-디렉토리 확장)                        |
| `[agents/incident/runtime/teardown.sh](../../agents/incident/runtime/teardown.sh)`                         | 6 step reverse + negative check                         |
| `[infra/s3-lambda/](../../infra/s3-lambda/)`                                                               | S3 backend (default) — bucket + Lambda + Gateway Target |
| `[infra/github-lambda/](../../infra/github-lambda/)`                                                       | GitHub backend (alternative — PAT 필요)                   |
| `[debug_mode.md](debug_mode.md)`                                                                           | DEBUG=1 시 FlowHook / TTFT / cache 통계                    |
| `[phase3.md](phase3.md)`                                                                                   | Phase 3 Monitor — 같은 OAuth provider + Runtime 패턴        |



