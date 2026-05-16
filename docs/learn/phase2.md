# Phase 2 — Gateway + MCP 도구 외부화 (CloudWatch native + history mock Lambda)

Phase 2:

- Phase 1 의 in-process @tool 을 **AgentCore Gateway 뒤로 외부화**
- **Cognito JWT 인증** + **2개 Lambda Target** (live CW + mock history)
- 도구는 Lambda behind Gateway 로 이동했지만 **Strands Agent 코드는 무변경**
- 청중이 이 격리를 검증

---

## 1. 왜 필요한가   *(~3 min read)*

Phase 2 는 Phase 3+ 가 모두 의존할 **Gateway+Lambda 인프라의 foundation** — in-process @tool 외부화로 enterprise 도구 분리 학습. 4가지 educational 가치:


| Educational 가치                     | 학습 포인트                                                                                                                                                           |
| ---------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **도구 외부화 검증**                      | Phase 1 의 `@tool` 함수 → Phase 2 의 Gateway+Lambda 로 옮겨도 Agent 코드 무변경 (`run_local_import.py` ≡ `run.py --mode past` 출력)                                             |
| **AgentCore Gateway = MCP server** | MCP 표준 호환 → Strands `MCPClient` 가 list_tools/call_tool 표준 동작                                                                                                     |
| **JWT 인증 첫 등장** (Cognito M2M)      | Phase 1 의 in-process @tool 은 auth 0. Phase 2 가 첫 service-to-service auth 도입 — client_credentials → Bearer → CUSTOM_JWT authorizer (서명/audience/scope 3-layer 검증) |
| **Hybrid 패턴 (CFN + boto3)**        | 표준 자원 (Cognito/Lambda/IAM) = CFN, AgentCore 자원 (Gateway/Target) = boto3 — 청중이 두 영역 차이 인지                                                                         |


→ **이 phase 가 Phase 3+ 의 모든 후속 phase 가 활용하는 Gateway/Lambda 인프라 + 4 helper 의 foundation**.

---

## 2. 진행 (Hands-on)   *(deploy ~5 min / 검증 ~5 min)*

### 2-1. 사전 확인

- **bootstrap 1회 실행** (`bash bootstrap.sh`) — Phase 1 과 동일
- **Phase 0 deploy 완료** (`bash infra/ec2-simulator/deploy.sh`) — `live` mode 의 `cloudwatch-wrapper` 가 read 할 alarm 필요
- AWS 자격증명 + Bedrock model access (Phase 1 동일)

> Phase 1 (mock-only) 와 다르게 Phase 2 는 **Cognito + Gateway + Lambda 실제 자원** 생성. 비용 발생 (CloudFormation + Lambda invoke).

### 2-2. Deploy

```bash
bash infra/cognito-gateway/deploy.sh
```

흐름 (~3-5분):

1. AWS 자격증명 + .env + DEMO_USER 사전 검증
2. DEPLOY_BUCKET 보장 (idempotent — 없으면 생성 + Public Access Block)
3. `data/mock/phase1` → Lambda 디렉토리로 vendor + `__init__.py` 생성
4. `cfn package` — **artifact preprocessing** (자원 생성 X):
  - `cognito.yaml` 의 로컬 Lambda 경로 (`./lambda/history_mock/`, `./lambda/cloudwatch_wrapper/`) 를 zip
  - `DEPLOY_BUCKET` S3 에 업로드 (random hash key)
  - `Code:` property 가 S3 reference (`S3Bucket` / `S3Key`) 로 rewrite → `packaged.yaml` 생성
  - **왜 필요**: CFN Lambda resource 는 로컬 디렉토리 못 받음 — S3 reference 필수
5. `cfn deploy` — **실제 자원 생성/갱신**:
  - `packaged.yaml` 기반 stack `aiops-demo-${DEMO_USER}-cognito-gateway` 생성
  - change set 생성 → 실행 → 자원 provisioning → completion 대기
  - 자원: Cognito × 4 (UserPool / Domain / ResourceServer / UserPoolClient) + Lambda × 2 + IAM Role × 3
6. CFN outputs 캡처 (7 var) + Cognito Client Secret 별도 조회
7. `setup_gateway.py` invoke — Gateway + 2 Target 생성/갱신 (idempotent)
8. `.env` 갱신 (`COGNITO`_*, `GATEWAY_`*, `LAMBDA_*` — 자세히는 `[env_config.md](env_config.md)`)

성공 시 출력 (실 화면은 `${DEMO_USER}` 가 expand 된 값):

```
[deploy] Phase 2 deploy 완료
  Gateway URL: https://aiops-demo-${DEMO_USER}-gateway-xxxx.gateway.bedrock-agentcore.us-east-1.amazonaws.com
  Lambda (history_mock):  arn:aws:lambda:us-east-1:...:function:aiops-demo-${DEMO_USER}-history-mock
  Lambda (cloudwatch):    arn:aws:lambda:us-east-1:...:function:aiops-demo-${DEMO_USER}-cloudwatch-wrapper
  검증: acceptance criteria
```

deploy 후 interactive shell 에 동기 — `.env` 에 갱신된 `GATEWAY_URL`/`COGNITO_*`/`LAMBDA_*` 를 현 shell 로 export:

```bash
source .env
```

### 2-3. 검증

> `local/run.py` 는 Phase 2 단독 + Phase 3+ 통합 모두 작동. `auth_local.py` 가 `OAUTH_PROVIDER_NAME` env 유무로 dispatch 

**Phase 2 standalone 시나리오** (Phase 3 deploy 전 검증 가능):

- `--mode past`: Phase 2 자원만으로 즉시 실행 (mock Lambda 호출)
- `--mode live`:`cloudwatch-wrapper` 가 read 할 alarm 가져옴

**Workshop pedagogy** — phase 점진 학습 의도:

- Phase 2: "Cognito 직접 호출이 작동" 학습 
- Phase 3: "OAuth provider 경유 시 *같은 결과*" 검증 (AgentCore Identity 사용)
- → enterprise 패턴 (provider 경유) 도 같은 token 임을 격리하여 학습

#### Phase 1 baseline 출력 동일성 (mock 경로)

```bash
uv run python -m agents.monitor.local.run --mode past
```

Phase 1 (`run_local_import.py`) 출력과 byte-level 동일해야 함. 차이가 있으면 Gateway/Lambda 외부화 회귀 신호.

#### 라이브 alarm 분류

```bash
uv run python -m agents.monitor.local.run --mode live
```

Phase 0 의 2 alarm (real `payment-${DEMO_USER}-status-check` + noise `payment-${DEMO_USER}-noisy-cpu`) 분류 — `Tags.Classification` 라벨 그대로. `system_prompt_live.md` 의 예시 출력과 유사한 형식.

#### Debug 모드 (선택) — JWT 흐름 가시화

Phase 2 의 `local/run.py` 는 host process 로 실행되므로 `DEBUG=1` env prefix 만으로 즉시 trace 활성 (재배포 불요 — Phase 3 Runtime 과 다른 점):

```bash
DEBUG=1 uv run python -m agents.monitor.local.run --mode past
```

확인 가능 trace:

- `Monitor → Cognito` (Path A) 또는 `Monitor → AgentCore Identity` (Path B) — auth dispatch
- `Cognito → Monitor` (JWT 발급) + Bearer header 주입
- `Monitor → Gateway` (MCP list_tools / call_tool)
- `Lambda → Monitor` (tool result)
- `Bedrock → Monitor` (usage + cache R/W)

자세한 trace 의미 / 색·박스 의미: `[debug_mode.md](debug_mode.md)`.

#### 통과 기준

- Gateway alive: `aws bedrock-agentcore-control list-gateways --region us-east-1`
- Tools listed (4개): mode=past 호출 시 `history-mock___*` 2개 + mode=live 호출 시 `cloudwatch-wrapper___*` 2개 매칭
- mode=past 출력이 Phase 1 baseline 과 동일 (3섹션 + 진단 매칭 정확)
- mode=live 출력이 라이브 alarm 분류 (real/noise 라벨 신뢰)
- Lambda CloudWatch Logs 에 invocation 흔적

### 2-4. 다음 phase 진입 또는 정리

**Phase 3 진행** (Phase 2 자원은 보존 — Phase 3+ 가 모두 의존):
→ `[phase3.md](phase3.md)` (Monitor Runtime 승격)

Phase 3 deploy 가 `OAuth2CredentialProvider` AWS 자원 생성 → `.env` 에 `OAUTH_PROVIDER_NAME` write-back → 다음 `source .env` + `local/run.py` 실행 시 auth dispatch 가 자동 Path A → B 로 전환.

**완전 정리** (모든 phase 자원 일괄):

```bash
bash teardown_all.sh
```

자세한 단계: `[teardown.md](teardown.md)`.

**Phase 2 만 단독 정리**:

```bash
bash infra/cognito-gateway/teardown.sh
```

→ Gateway/Target → CFN stack → DEPLOY_BUCKET → vendor cleanup → `.env` 비우기

---

## 3. 무엇을 만드나   *(~3 min read)*

```
┌────────────────────────────┐         ┌──────────────────────────────────┐
│ Strands Agent (local)       │         │ AgentCore Gateway (MCP server)   │
│                             │  HTTPS  │  ├─ customJWTAuthorizer          │
│  agents/monitor/local/      │ ──────▶ │  │   ├─ ① 서명 (Cognito discov)  │
│    run.py                   │  Bearer │  │   ├─ ② audience (ClientId)   │
│      ↑                      │   JWT   │  │   └─ ③ scope (rs/invoke)     │
│  agents/monitor/shared/     │         │  ├─ Target: history-mock         │
│    (4 helper files)         │         │  └─ Target: cloudwatch-wrapper   │
└────────────────────────────┘         └────────────┬─────────────────────┘
                                                    │  Lambda invoke (IAM)
                                  ┌─────────────────┴─────────────────────┐
                                  ▼                                       ▼
                       ┌──────────────────┐                    ┌──────────────────────┐
                       │ history-mock     │                    │ cloudwatch-wrapper    │
                       │ Lambda           │                    │ Lambda                │
                       │  ↓               │                    │  ↓                    │
                       │ data/mock/phase1 │                    │ boto3 cloudwatch      │
                       │ (vendor 된 mock) │                    │ describe_alarms +     │
                       │                  │                    │ list_tags_for_resource│
                       └──────────────────┘                    └──────────────────────┘
                          (Phase 1 baseline                       (Phase 0 라이브 alarm)
                           동일성 검증)                            `payment-${DEMO_USER}-*`
```

**핵심**: Strands Agent 와 도구 (2 Lambda) 사이에 **AgentCore Gateway (MCP server)** + **Cognito JWT** 의 인증된 호출 경로. Agent 코드는 4 helper 로 추상화 — 도구 위치 (in-process @tool vs Gateway behind Lambda) 변경에도 무변경.

---

## 4. 어떻게 동작   *(~10 min read)*

### 자원 (CFN 통합 stack — `aiops-demo-${DEMO_USER}-cognito-gateway`)


| 그룹           | 자원                                                  | 개수  | 설명                                             |
| ------------ | --------------------------------------------------- | --- | ---------------------------------------------- |
| **Cognito**  | UserPool / Domain / ResourceServer / UserPoolClient | 4   | M2M client_credentials flow + Bearer JWT 발급    |
| **Lambda**   | history_mock + cloudwatch_wrapper                   | 2   | 위 architecture 의 두 Target backend              |
| **IAM Role** | history_mock + cloudwatch_wrapper + Gateway         | 3   | Lambda execution × 2 + Gateway → Lambda invoke |


### 자원 (boto3 — `setup_gateway.py`)


| 자원                 | 이름                                         | 설명                                             |
| ------------------ | ------------------------------------------ | ---------------------------------------------- |
| AgentCore Gateway  | `aiops-demo-${DEMO_USER}-gateway-<random>` | MCP server + CUSTOM_JWT authorizer (3-layer)   |
| Gateway Target × 2 | `history-mock` + `cloudwatch-wrapper`      | tool schema (4 도구) inline + Lambda ARN backend |


### 4 helper (`agents/monitor/shared/`)

Phase 2 부터 Strands Agent 가 Gateway 호출에 필요한 helper:


| 파일              | 책임                                                                                                                               | 사용처                                            |
| --------------- | -------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------- |
| `env_utils.py`  | `require_env(key)` — 친화적 RuntimeError                                                                                            | 내부 (auth_local + mcp_client)                   |
| `auth_local.py` | Local 환경의 Cognito JWT 획득 — 2-path dispatch (아래 [Auth dispatch](#auth-dispatch-auth_localpy--phase-2-standalone-과-phase-3-통합) 참조) | `local/run.py`                                 |
| `mcp_client.py` | MCPClient factory — Bearer JWT 헤더 주입                                                                                             | `local/run.py` + 4개 후속 Runtime                 |
| `modes.py`      | `MODE_CONFIG[mode]` → (target prefix, prompt 파일명)                                                                                | `local/run.py` + monitor / monitor_a2a Runtime |


### Auth dispatch (`auth_local.py`) — Phase 2 standalone 과 Phase 3+ 통합

**AgentCore Identity service**: Cognito Client 자격증명을 Runtime 이 직접 보관하지 않고 *AWS-managed credential vault* 에 위임. `OAuth2CredentialProvider` 자원 (Phase 3 deploy 시 생성) 이 이 vault 의 entry — `OAUTH_PROVIDER_NAME` env 로 식별.

dispatch 2-path 비교:


| 경로                    | trigger                       | call flow                                 | 자원 의존                                          |
| --------------------- | ----------------------------- | ----------------------------------------- | ---------------------------------------------- |
| **A. Cognito 직접**     | `OAUTH_PROVIDER_NAME` env 미설정 | boto3 → `cognito-idp` `/oauth2/token`     | Phase 2 만                                      |
| **B. OAuth provider** | `OAUTH_PROVIDER_NAME` env 설정  | boto3 → AgentCore Identity → (내부) Cognito | Phase 2 + Phase 3 의 `OAuth2CredentialProvider` |


핵심 dispatch 코드 (`auth_local.py`):

```python
provider_name = os.environ.get("OAUTH_PROVIDER_NAME")
if provider_name:
    # Path B — AgentCore Identity 경유
    token = get_token_via_agentcore_identity(provider_name)
else:
    # Path A — Cognito 직접
    token = get_token_via_cognito_direct()
```

→ 같은 `local/run.py` 코드가 Phase 2 standalone (Path A) 와 Phase 3+ 통합 (Path B) 시나리오 모두 작동. workshop 청중이 phase 점진 학습 가능.

### 호출 흐름 (`local/run.py` 가 위 helper 결합)

```
.env (Phase 2 deploy 가 채움)
    │
    ▼
auth_local.get_local_gateway_token()   ← env_utils.require_env 검증
    │  Cognito M2M JWT
    ▼
mcp_client.create_mcp_client(gateway_token=...)
    │  MCPClient with Authorization: Bearer <JWT>
    ▼
mcp_client.list_tools_sync()  →  Gateway → Lambda → tool 응답
    │
    ▼  filter by modes.MODE_CONFIG[mode].target_prefix
agent.create_agent(tools=filtered, system_prompt_filename=...)
    │
    ▼
agent.stream_async(query)  →  LLM + tool calls
```

자세한 module map: `[agents/monitor/shared/__init__.py](../../agents/monitor/shared/__init__.py)`.

`create_agent()` 가 추가로 구성하는 것:

- **Prompt caching (Layer 1+2)** — `BedrockModel(cache_tools="default")` + `system_prompt=[SystemContentBlock(text=...), SystemContentBlock(cachePoint={"type":"default"})]`. agent loop 의 2-step LLM 만으로도 cache hit, 5분 warm TTL.
- **FlowHook** (DEBUG=1 시) — `BeforeModelCall`/`AfterModelCall`/`BeforeToolCall` hook 으로 pre-call 시점 + LLM duration + TTFT 가시화. 자세한 동작: `[debug_mode.md](debug_mode.md)`.

### 시퀀스 (entity 간 시점 순서)

위 호출 흐름을 entity timeline 으로 펼침. `DEBUG=1` 으로 직접 검증 가능 — 자세한 trace 해석은 `[debug_mode.md](debug_mode.md)` §5-1 참고.

```
User      Monitor    Cognito    Gateway    Lambda     Bedrock
  │          │          │          │          │          │
  │  cmd     │          │          │          │          │
  ├─────────▶│          │          │          │          │
  │          │          │          │          │          │
  │          │  POST    │          │          │          │
  │          ├─────────▶│          │          │          │
  │          │  JWT     │          │          │          │
  │          │◀─────────┤          │          │          │
  │          │          │          │          │          │
  │          │  MCP list_tools     │          │          │
  │          ├──────────┼─────────▶│          │          │
  │          │  4 tools            │          │          │
  │          │◀─────────┼──────────┤          │          │
  │          │          │          │          │          │
  │          │  LLM call #1 (sys+tools+query)            │
  │          ├──────────┼──────────┼──────────┼─────────▶│
  │          │  toolUse(list_live_alarms) {in=2862,out=29}
  │          │◀─────────┼──────────┼──────────┼──────────┤
  │          │          │          │          │          │
  │          │  MCP tool call      │          │          │
  │          ├──────────┼─────────▶│          │          │
  │          │          │          │  invoke (AWS-internal)
  │          │          │          ┝┄┄┄┄┄┄┄┄▶│          │
  │          │          │          │  alarms (AWS-internal)
  │          │          │          │◀┄┄┄┄┄┄┄┄┥          │
  │          │  toolResult         │          │          │
  │          │◀─────────┼──────────┤          │          │
  │          │          │          │          │          │
  │          │  LLM call #2 (+ toolResult)               │
  │          ├──────────┼──────────┼──────────┼─────────▶│
  │          │  text {in=3161,out=282}                   │
  │ ◀stream ─┤◀─────────┼──────────┼──────────┼──────────┤
  │          │          │          │          │          │
  │          │  📊 Total: 6,334 tokens                   │
```

**범례**: `├──▶│` = call / `│◀──┤` = response / `┼` = arrow 가 통과만 하는 lifeline (해당 entity 미관여) / `┄` (점선) = AWS-internal flow (Gateway → Lambda forwarding, client trace 불가 — CloudWatch logs 만 가능) / `Monitor` 컬럼 = Strands `Agent` 가 토큰 획득·Gateway 호출·Bedrock 통신을 모두 조율하는 hub.

### 알려진 제약

- **Token TTL**: Cognito M2M token default 1시간. `mcp_client.py` 의 closure 에 보관 — 60분 이상 idle 시 다음 tool call 401 가능. 해결: 새 MCPClient 인스턴스화. Workshop 1-2 시간 세션에선 거의 hit 안 함. Token Refresh 기능을 생성하면 됨. (추후 개발 예정)

---

## 5. References


| 자료                                                                                                                 | 용도                                                                                                  |
| ------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------- |
| `[infra/cognito-gateway/cognito.yaml](../../infra/cognito-gateway/cognito.yaml)`                                   | CFN — Cognito × 4 + Lambda × 2 + IAM × 3                                                            |
| `[infra/cognito-gateway/setup_gateway.py](../../infra/cognito-gateway/setup_gateway.py)`                           | boto3 — Gateway + 2 Target (idempotent + update branch)                                             |
| `[infra/cognito-gateway/cleanup_gateway.py](../../infra/cognito-gateway/cleanup_gateway.py)`                       | boto3 reverse — Target → wait → Gateway                                                             |
| `[infra/cognito-gateway/lambda/{history_mock,cloudwatch_wrapper}/handler.py](../../infra/cognito-gateway/lambda/)` | Lambda 2개 — AgentCore Gateway invoke 패턴 (`bedrockAgentCoreToolName`)                                |
| `[agents/monitor/shared/__init__.py](../../agents/monitor/shared/__init__.py)`                                     | 4-helper module map + 호출 흐름                                                                         |
| `[agents/monitor/local/run.py](../../agents/monitor/local/run.py)`                                                 | Phase 2 entry — `--mode past` 또는 `--mode live`                                                      |
| `[agents/monitor/shared/prompts/system_prompt_live.md](../../agents/monitor/shared/prompts/system_prompt_live.md)` | live mode prompt — `Tags.Classification` 신뢰                                                         |
| `[debug_mode.md](debug_mode.md)`                                                                                   | `DEBUG=1` 활성 시 cross-phase trace (auth / MCP / tool / TTFT / LLM call duration) — Phase 2 검증에 직접 활용 |


