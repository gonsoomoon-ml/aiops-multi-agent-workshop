# Phase 4 — Incident Agent + Storage Backend

> Phase 3 의 Monitor Runtime 패턴을 Incident Agent 에 carry-over. `@app.entrypoint` + OAuth2CredentialProvider 자동 inject + MCPClient → Gateway 호출. 차이점: **storage Lambda** (S3 default / GitHub 선택) 가 runbook 을 fetch, Incident 가 alarm 1건 받아 runbook 조회 + 진단 + 권장 조치 JSON 반환.

설계 원본: [`docs/design/phase4.md`](../design/phase4.md) (D1~D6 + P4-A1~A5).

---

## 무엇을 만드나

| 산출물 | 위치 | 비고 |
|---|---|---|
| **Storage Lambda** (S3 default) | `infra/s3-lambda/` | CFN — S3 bucket + Lambda + IAM + cross-stack policy. `data/runbooks/<class>.md` 조회 |
| **Storage Lambda** (GitHub 선택) | `infra/github-lambda/` | sibling backend. PAT 필요. byte-level 동형 응답 shape |
| **Gateway Target** `s3-storage` 또는 `github-storage` | boto3 (`setup_*_target.py`) | cognito-gateway 의 Gateway 에 추가 (기존 Target 유지) |
| **Incident Runtime** | `agents/incident/runtime/agentcore_runtime.py` | `@app.entrypoint` 함수 `incident_agent` — payload `{alarm_name}` → SSE yield (`agent_text_stream` / `token_usage` / `workflow_complete`) |
| **Incident agent factory** | `agents/incident/shared/agent.py` | Strands Agent 생성 — prompt caching Layer 1+2 + FlowHook(`agent_name="Incident"`) 등록 |
| **System prompt** | `agents/incident/shared/prompts/system_prompt.md` | JSON-only 출력 schema + Severity 판단 기준 (P1/P2/P3) + 출력 예시 3건 |
| **5-step deploy** | `agents/incident/runtime/deploy_runtime.py` | (1) monitor/shared + incident/shared + _shared_debug copy → (2) toolkit configure → (3) launch → (4) IAM extras + OAuth provider → (5) READY + repo root `.env` 저장 |
| **호출 테스트** | `agents/incident/runtime/invoke_runtime.py` | `boto3 invoke_agent_runtime` + SSE + token usage + TTFT + `--session-id` (warm container) |
| **자원 정리** | `agents/incident/runtime/teardown.sh` | 6 step reverse + Phase 3 Monitor + Phase 2 Cognito 보존 verify |

새 AWS 자원 (S3 backend):
- S3 bucket × 1 (versioned, public block)
- Lambda × 1 (Python 3.13, S3 GetObject)
- IAM Role × 1 + cross-stack inline policy × 1
- AgentCore Runtime × 1 + ECR × 1 + IAM execution role × 1 (toolkit)
- `OAuth2CredentialProvider` × 1 (Incident 전용)
- Gateway Target × 1 (`s3-storage`)

---

## 왜 필요한가

| 동기 | Phase 3 한계 | Phase 4 해결 |
|---|---|---|
| Multi-agent topology | Monitor 1개만 — 진단/조치 분리 X | Incident 독립 Runtime — 알람 분류 (Monitor) vs runbook driven 진단 (Incident) 책임 분리 |
| Runbook driven 의사결정 | hard-coded LLM knowledge | data/runbooks/*.md 외부화 + Lambda fetch → 운영팀이 markdown 으로 직접 관리 |
| Storage backend 추상화 | (없음) | `STORAGE_BACKEND=s3` 또는 `github` env 분기 — Lambda 응답 shape 동형 (Incident 코드 무관) |
| sequential CLI 준비 | (없음) | Monitor → Incident 순차 호출 (Phase 5 A2A 전 단계) |

---

## 어떻게 동작

### Storage backend 추상화 (D3-D4)

Incident Agent 는 backend 무관. tool name prefix 만 분기:

```python
TOOL_TARGET_PREFIX = f"{os.environ.get('STORAGE_BACKEND', 's3')}-storage___"
```

- `STORAGE_BACKEND=s3` → tool `s3-storage___get_runbook` → S3 Lambda
- `STORAGE_BACKEND=github` → tool `github-storage___get_runbook` → GitHub Lambda

Lambda 응답 shape 동일 (`runbook_found`, `path`, `content`) → Agent 코드 무변경.

### Build context (3-디렉토리 확장)

deploy_runtime.py 가 **3개 디렉토리** 를 build context 로 copy:

```
agents/incident/runtime/         ← Docker build context
├── agentcore_runtime.py
├── Dockerfile / requirements.txt
├── shared/                       ← monitor/shared 복사 (auth_local, mcp_client, env_utils, modes)
├── incident_shared/              ← incident/shared 복사 (agent.py + prompts)
└── _shared_debug/                ← repo root _shared_debug 복사 (FlowHook / TTFT)
```

container 안 `/app/` 으로 통째 upload. import:
- container: `from shared.mcp_client import ...` + `from incident_shared.agent import create_agent`
- local dev: `from agents.monitor.shared.mcp_client import ...` + `from agents.incident.shared.agent import create_agent`
- `try/except ModuleNotFoundError` 분기로 통합

### OAuth provider 자동 inject

Phase 3 monitor 와 동일 패턴 — `@requires_access_token` decorator 가 workload identity → Cognito M2M 교환 → access_token 자동 inject. 별도 OAuth provider (`aiops_demo_${DEMO_USER}_incident_gateway_provider`) — Monitor 와 분리.

### 호출 흐름

```
invoke_runtime.py
    │  boto3.invoke_agent_runtime(payload={alarm_name}, runtimeUserId=DEMO_USER)
    ▼
AgentCore Runtime endpoint
    │  SIGV4 인증
    ▼
container: agentcore_runtime.py:incident_agent()
    │  TOOL_TARGET_PREFIX = "${STORAGE_BACKEND}-storage___"
    │
    ├─ _fetch_gateway_token()           ← OAuth2CredentialProvider 자동 inject
    │
    ├─ create_mcp_client(token)         ← monitor/shared 의 helper (C1 — code reuse)
    │
    ├─ list_tools_sync() + filter by prefix
    │
    ├─ create_agent(tools, prompt)      ← incident/shared/agent.py (Incident truth)
    │   (prompt caching + FlowHook if DEBUG=1)
    │
    ▼
agent.stream_async(json_payload)        ← {"alarm_name": "..."}
    │  → tool call: get_runbook(alarm_name="...")
    │  → Lambda: S3 GetObject — data/runbooks/<class>.md
    │  → LLM JSON 생성
    │
    │  → yield agent_text_stream {text} × N
    │  → yield token_usage {usage}
    │  → yield workflow_complete
```

자세한 sequence: [`debug_mode.md`](debug_mode.md) §5-1 + [`phase3.md`](phase3.md) `### 호출 흐름` (Phase 4 도 같은 entity 흐름).

---

## 진행 단계

### 1. 사전 확인

- Phase 2 완료 (Cognito stack + Gateway alive, repo root `.env` 의 `GATEWAY_URL` / `COGNITO_*`).
- Phase 3 완료 (Monitor Runtime READY — `MONITOR_RUNTIME_ARN` repo root .env).
- AWS 자격 증명 + Docker daemon + `uv sync`.
- `data/runbooks/*.md` 가 repo 에 존재 (S3 backend seed 대상).

### 2. Deploy

**Step C — Storage Lambda + Gateway Target** (backend 별 한 번):

```bash
# S3 backend (default)
bash infra/s3-lambda/deploy.sh

# 또는 GitHub backend (PAT + SSM 필요)
bash infra/github-lambda/deploy.sh
```

Storage Lambda + bucket/repo seed + Gateway Target (`s3-storage` 또는 `github-storage`) 등록. `.env` 에 `S3_STORAGE_LAMBDA_ARN` / `STORAGE_BUCKET_NAME` (또는 `GITHUB_STORAGE_LAMBDA_ARN`) 자동 작성.

**Step D — Incident Runtime**:

```bash
uv run agents/incident/runtime/deploy_runtime.py
```

5단계 — shared/×2 + _shared_debug copy → toolkit configure → launch → IAM extras + OAuth provider → READY. ~5-10분 첫 배포, ~40초 update. 성공 시 repo root `.env` 에 `INCIDENT_RUNTIME_*` + `INCIDENT_OAUTH_PROVIDER_NAME` 저장.

### 3. 검증

#### 3-1. P4-A2 — 단독 alarm 진단 (Step D 완료 후)

> Shell 에 `${DEMO_USER}` 가 export 안 되어 있으면 빈 문자열로 expand → `payment--status-check` 같은 이상한 alarm name 으로 호출됨. 미리 `set -a; source .env; set +a` 로 env 변수 export 또는 직접 `payment-bob-status-check` 처럼 명시.

```bash
set -a; source .env; set +a   # DEMO_USER + AWS_REGION 등 shell 에 export
uv run agents/incident/runtime/invoke_runtime.py --alarm "payment-${DEMO_USER}-status-check"
```

JSON 출력 schema:
```json
{
  "alarm": "payment-bob-status-check",
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

#### 3-2. Prompt caching 확인 — 같은 alarm 재호출

5분 이내 같은 alarm 으로 다시 invoke (`source .env` 가 §3-1 에서 export 된 상태 가정):

```bash
uv run agents/incident/runtime/invoke_runtime.py --alarm "payment-${DEMO_USER}-status-check"
```

Cache R/W 가 **5,000/0 (warm)** 로 변동 — system prompt + tool schema cache hit. cold (2,500/2,500) 대비 ~54% 비용 절감 + TTFT ~5초로 단축 (~63% 감소).

> **Workshop 학습 포인트**: Bedrock prompt cache 의 최소 임계값 ~1024 tokens. Incident system prompt 가 처음엔 작아서 cache 무효 → second-pass 시 P1/P2/P3 기준 + 출력 예시 3건 추가로 임계값 초과 → warm cache 활성.

#### 3-3. Debug 모드 (선택) — Container trace 를 CloudWatch logs 로

호스트 `DEBUG=1` 이 invoke_runtime.py 의 client process 에만 영향. 진짜 debug 코드 (FlowHook / dump_stream_event) 는 Runtime container 안 — container env 가 `DEBUG=1` 이어야 활성. container env 는 deploy 시점에 고정 → 재배포 필요.

```bash
# 1. DEBUG=1 으로 재배포 → container env 에 DEBUG=1 forward
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

```bash
# 2. invoke (DEBUG prefix 불필요)
uv run agents/incident/runtime/invoke_runtime.py --alarm payment-${DEMO_USER}-status-check

# 3. CloudWatch logs — .env 변수 shell 에 export 후 tail
set -a; source .env; set +a
aws logs tail /aws/bedrock-agentcore/runtimes/${INCIDENT_RUNTIME_ID}-DEFAULT \
    --follow --region "${AWS_REGION:-us-west-2}"
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
> 1. `agent.py:create_agent()` 가 `FlowHook(agent_name="Incident")` 등록 — pre/post-call + before-tool trace
> 2. `agent.py:create_agent()` 가 agent attribute (`agent._debug_agent_name`) 셋업 → `event_dump.py` 가 message complete + TTFT 라벨에 사용
> 3. `agentcore_runtime.py` 가 `create_mcp_client(agent_name="Incident")` 전달 — helper 의 MCP client init 라벨
>
> 2 는 FlowHook 이 자동 셋업 (`_before_model` 안), 1 + 3 은 호출자가 명시. Phase 5 supervisor / a2a 작성 시 동일 3 곳 모두 매칭 필요.

자세한 trace 의미: [`debug_mode.md`](debug_mode.md).

#### 3-4. Warm container 효과 (선택) — `--session-id`

매 invoke 가 새 microVM 에 할당되면 container cold start. 같은 `runtimeSessionId` 로 반복 호출 시 AgentCore 가 같은 warm container 로 routing → **TTFT 단축** 시연.

```bash
# 0. shell env 미리 export (DEMO_USER 의 빈 expand 회피)
set -a; source .env; set +a

# 1. Fresh microVM (cold container) — session-id 미설정
uv run agents/incident/runtime/invoke_runtime.py --alarm "payment-${DEMO_USER}-status-check"

# 2. 같은 session-id 로 재호출 (warm container hit)
#    AgentCore 제약: runtimeSessionId 최소 33자 — UUID hex (32자) + prefix 권장
SID="incident-$(uuidgen | tr -d -)"   # → incident-<32 hex chars> = 41자
uv run agents/incident/runtime/invoke_runtime.py --alarm "payment-${DEMO_USER}-status-check" --session-id "$SID"
uv run agents/incident/runtime/invoke_runtime.py --alarm "payment-${DEMO_USER}-status-check" --session-id "$SID"
uv run agents/incident/runtime/invoke_runtime.py --alarm "payment-${DEMO_USER}-status-check" --session-id "$SID"
```

마지막 라인 `✅ 완료 — TTFT X.X초 / total Y.Y초` 비교:
- 1차 cold microVM: TTFT 8-15초 범위 (cold start + Bedrock cold)
- 같은 ID 재호출 (warm): TTFT 5-7초 범위 → ~50% 단축

> 실측 폭은 매 시점 다름 (network / AgentCore 운영 변동성). workshop 라이브 시연 시 청중이 직접 확인.

**두 가지 caching layer 비교**:

| Layer | 도구 | 효과 | 어디서 측정 |
|---|---|---|---|
| **Prompt cache** (Bedrock) | `cache_tools="default"` + system prompt cachePoint | input token 단가 ~90% 감 | usage 라인의 `Cache R/W` |
| **Warm container** (AgentCore) | `runtimeSessionId` 반복 | TTFT 단축 (~30-60%) | `✅ 완료 — TTFT X.X초` |

dba `chat.py` 가 multi-turn 대화에 같은 패턴 사용 (첫 응답에서 받은 sessionId 를 후속 invoke 에 재전달). 본 invoke_runtime.py 는 단일 호출이라 사용자가 ID 명시.

### 4. 정리 (P4-A5)

```bash
# Step D — Incident Runtime + OAuth provider + ECR + IAM
bash agents/incident/runtime/teardown.sh

# Step C — Storage Lambda + Gateway Target (backend 별)
bash infra/s3-lambda/teardown.sh
# 또는
bash infra/github-lambda/teardown.sh
```

Incident teardown 후 Phase 3 Monitor + Phase 2 Cognito stack + Phase 2 Gateway 보존 자동 verify (negative check).

---

## Reference

| 자료 | 용도 |
|---|---|
| [`agents/incident/runtime/agentcore_runtime.py`](../../agents/incident/runtime/agentcore_runtime.py) | Runtime entrypoint — payload `{alarm_name}` + SSE yield |
| [`agents/incident/shared/agent.py`](../../agents/incident/shared/agent.py) | Strands Agent 생성 — caching + FlowHook |
| [`agents/incident/shared/prompts/system_prompt.md`](../../agents/incident/shared/prompts/system_prompt.md) | JSON schema + Severity 기준 + 예시 3건 |
| [`agents/incident/runtime/deploy_runtime.py`](../../agents/incident/runtime/deploy_runtime.py) | 5단계 배포 (build context 3-디렉토리 확장) |
| [`agents/incident/runtime/teardown.sh`](../../agents/incident/runtime/teardown.sh) | 6 step reverse + negative check |
| [`infra/s3-lambda/`](../../infra/s3-lambda/) | S3 backend (default) — bucket + Lambda + Gateway Target |
| [`infra/github-lambda/`](../../infra/github-lambda/) | GitHub backend (alternative — PAT 필요) |
| [`debug_mode.md`](debug_mode.md) | DEBUG=1 시 FlowHook / TTFT / cache 통계 |
| [`phase3.md`](phase3.md) | Phase 3 Monitor — 같은 OAuth provider + Runtime 패턴 |
| [`../design/phase4.md`](../design/phase4.md) | 의사결정 로그 (D1~D6) |

---

## 알려진 제약

- **Storage Lambda 의존**: Incident Runtime 호출 전에 `infra/s3-lambda/deploy.sh` (또는 github-lambda) 필수 — Gateway Target 미등록 시 도구 0개로 실패.
- **runbook seed 의존** (S3 backend): `data/runbooks/*.md` 가 repo 에 있어야 deploy.sh 가 S3 sync. 0건이면 모든 invoke 가 `runbook_found:false`.
- **Single-tool dispatch**: `get_runbook` 1개만. 다른 도구 추가 시 system_prompt 의 "도구 사용 규칙" + setup_*_target.py 의 toolSchema 동시 갱신.
- **Prompt caching 임계값**: system prompt + tool schema 합산 1024 tokens 미만이면 cache 비활성. second-pass review 에서 incident system_prompt 를 5,314 chars 로 확장한 이유.
- **dual-key 패턴 폐기**: first-pass 의 `RUNTIME_ARN` (self) + `INCIDENT_RUNTIME_ARN` (cross-agent caller) 이중 key 가 single .env 통합 시 monitor 와 충돌 → `INCIDENT_RUNTIME_ARN` 단일 (Phase 5 sequential CLI / supervisor 도 같은 key 참조).
