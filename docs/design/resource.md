# 리소스 — 역할별 분류

## 베이스 코드 (직접 차용)

### 1. A2A-multi-agent-incident-response — Cognito 인프라 + MCPClient Runtime 패턴
- 경로: `/home/ubuntu/amazon-bedrock-agentcore-samples/02-use-cases/A2A-multi-agent-incident-response/`
- **Phase 2 차용**:
  - `cloudformation/cognito.yaml:28-156` — UserPool + Domain + ResourceServer + UserPoolClient M2M scope 패턴 (multi-user prefix 추가). Phase 2 = Client C 만 (Phase 4 에서 Client A/B 추가)
  - **차용 안 함**: Gateway/GatewayTarget CFN 패턴 — 우리는 Hybrid (boto3 setup_gateway.py) 채택
- **Phase 3 차용 (예정)**:
  - `monitoring_strands_agent/utils.py:27-48` `create_gateway_client(workload_token)` — Runtime 의 MCPClient 호출 패턴 (`agentcore_client.get_resource_oauth2_token(...)`). Phase 2 transitional helper 폐기 후 이 패턴으로 evolve
  - OAuth2CredentialProvider 생성 패턴은 **미정** (Phase 3 design 시점에 결정 — A2A Lambda Custom Resource / CFN native / boto3 hybrid 중)
- **Phase 4+ 차용 (예정)**:
  - `host_adk_agent/agent.py:37-100` (RemoteA2aAgent 패턴) — Phase 6a Supervisor 변환 시 핵심 참조
  - `deploy.py` (1234줄, 병렬 스택 관리), `cleanup.py` (559줄, 역순 삭제) — 다중 stack orchestration 참고

### 2. ec-customer-support-e2e-agentcore — boto3 Gateway/Target step-by-step (Phase 2 Hybrid 의 educational core)
- 경로: `/home/ubuntu/ec-customer-support-e2e-agentcore/`
- URL: https://github.com/gonsoomoon-ml/ec-customer-support-e2e-agentcore
- **2026-05-04 카테고리 변경**: 학습용 → 베이스 코드 (직접 차용). Phase 2 Section 3 hybrid design 의 핵심 패턴 제공
- **Phase 2 차용**:
  - `notebooks/lab-03-agentcore-gateway.ipynb` Step 5 (Gateway 생성) → `infra/phase2/setup_gateway.py:step1_create_gateway`. notebook → Python script 화. SSM parameter store 조회 → CFN outputs export 로 대체
  - Lab 03 Step 6 (Lambda 함수 대상 추가) → `setup_gateway.py:step2_create_target` × 2 호출. notebook single target → 우리 2 targets (cloudwatch_wrapper + history_mock)
  - Lab 03 의 idempotency 패턴 (`list_gateways` → 매칭 → 재사용) → `setup_gateway.py` step1/step2 의 idempotent 분기
  - Lab 03 의 `gateway_client = boto3.client("bedrock-agentcore-control")` → 동일
  - Lab 09 (cleanup) 의 `delete_gateway_target` + `delete_gateway` 패턴 → `infra/phase2/cleanup_gateway.py` (역순 — target 먼저 삭제)
- **Educational core**: step-by-step print 패턴 (`print(f"\n=== Step N: ... ===")`) — audience 한 줄씩 따라가며 AgentCore 학습. setup_gateway.py 도 동일 패턴 유지

### 3. developer-briefing-agent — 폴더 구조 + 로컬↔Runtime + 부트스트랩
- 경로: `/home/ubuntu/developer-briefing-agent/`
- **Phase 1 차용 (완료)**:
  - `local-agent/chat.py` `agent.stream_async(prompt)` async iterator + `null_callback_handler` → `_stream_response` 패턴
  - `prompts/system_prompt.md` 외부화 + load 패턴
  - `setup.sh` 통합 부트스트랩 (uv sync → .env 생성 → SSM 토큰)
  - `setup/store_github_token.sh` SSM Parameter Store SecureString 저장 + 5단계 검증
  - `pyproject.toml` + `uv.lock` 의존성 관리 (uv sync)
- **Phase 2 차용**:
  - `local-agent/agent.py` + `managed-agentcore/agent.py` 가 같은 `create_agent()` 호출 (단일 진실 원천) → `agents/monitor/shared/agent.py:create_agent(tools, system_prompt_filename)` baseline + current + Phase 3 Runtime 모두에서 호출. 시그니처 확장 (caller 가 tools + prompt 파일명 주입)
  - `prompts/system_prompt.md` 외부화 → mode 별 2 파일 (`system_prompt_past.md` + `system_prompt_live.md`)
  - 시스템 목표 C1 ("Strands 로컬 → AgentCore Runtime 동일 코드 승격") 검증 패턴

### 4. sample-deep-insight — `.env.example` 패턴 cherry-pick
- 경로: `/home/ubuntu/sample-deep-insight/managed-agentcore/.env.example`
- 차용 대상:
  - 에이전트별 모델 ID env 분리 (`MONITOR_MODEL_ID`, `CHANGE_MODEL_ID=haiku` 등)
  - 단계별 env 채움 (Phase 1/2/3 deployment에 의해 자동 갱신)
  - OTEL observability 설정 (CloudWatch GenAI Observability 자동 통합 — `OTEL_RESOURCE_ATTRIBUTES=service.name=<agent>`)
- 코드 본체는 우리 규모엔 과함 (VPC + Fargate + ALB + multi-region) — SKIP

---

## Phase 2 자체 design (차용 없음)

| 자원 | 신규 사유 |
|---|---|
| `infra/phase2/lambda/cloudwatch_wrapper/handler.py` | Intent shape Lambda — Smithy 폐기 결정 (phase2.md Section 4). 산업 표준 패턴 (DevOps Guru, Watson AIOps) 참고는 했지만 코드 차용 0 |
| `infra/phase2/lambda/history_mock/handler.py` | Phase 1 mock 데이터를 Lambda 로 wrap (Section 5) — 신규 |
| `agents/monitor/shared/auth/cognito_token.py` | Phase 2 transitional helper (Section 6-5). Cognito client_credentials POST + 1h cache. Phase 3 PR 에서 통째 삭제 |
| `agents/monitor/shared/mcp_client.py` | Strands MCPClient factory (Section 6-4). transport callable 패턴 — A2A 의 `create_gateway_client()` 와 유사하지만 token 인자 처리 transitional |
| `agents/monitor/local/run.py --mode {past,live}` 분기 | 이슈 4 결정 (P2-A3 와 P2-A4/A5 검증 격리) — 차용 없음 |

---

## 학습용 (코드 차용 없음, 옵션)

### AgentCore Deep Dive Workshop (한국어)
- URL: https://catalog.workshops.aws/agentcore-deep-dive/ko-KR
- 역할: AgentCore 7개 컴포넌트 (Runtime / Gateway / Memory / Browser Tool / Code Interpreter / Identity / Observability) 카탈로그 reference
