# A2A 가 뭔가 — 처음부터 직관적으로

> 본 문서는 A2A (Agent-to-Agent) 프로토콜에 처음 노출되는 워크샵 청중 / 본 프로젝트 contributor 를 대상으로, **개념 → 동기 → 어휘 → wire format → 우리 코드** 순서로 설명한다. 별도의 A2A 사양 문서를 읽지 않아도 이 한 페이지로 본 프로젝트의 A2A 사용을 이해할 수 있게 한다.

## 목차

- [0. 한 줄 정의](#0-한-줄-정의)
- [1. 왜 만들어졌나 — 동기](#1-왜-만들어졌나--동기)
- [2. 직관적 비유 — 명함과 회의](#2-직관적-비유--명함과-회의)
- [3. 핵심 어휘 5개](#3-핵심-어휘-5개)
- [4. Wire format — 한 번 보면 끝](#4-wire-format--한-번-보면-끝)
- [5. Function call vs A2A — 가장 중요한 직관 비교](#5-function-call-vs-a2a--가장-중요한-직관-비교)
- [6. 우리 프로젝트에 적용 — 구체 시나리오](#6-우리-프로젝트에-적용--구체-시나리오)
- [7. 왜 그냥 REST API 안 쓰고 A2A?](#7-왜-그냥-rest-api-안-쓰고-a2a)
- [8. 우리 코드에서 A2A 가 보이는 곳](#8-우리-코드에서-a2a-가-보이는-곳)
- [9. 핵심을 한 그림으로](#9-핵심을-한-그림으로)
- [10. AWS canonical 패턴 — `serve_a2a` + `LazyExecutor`](#10-aws-canonical-패턴--serve_a2a--lazyexecutor-bedrock-agentcore-best-practice)
- [참고 자료](#참고-자료)

---

## 0. 한 줄 정의

> **A2A = "AI agent 가 다른 AI agent 를 호출하는 표준 프로토콜"**
>
> HTTP 위에서 JSON-RPC 메시지를 주고받는데, 메시지 형식과 능력 광고 방식 (AgentCard) 이 표준화되어 있음. **vendor 가 달라도 (Strands, Google ADK, OpenAI Agents SDK) 서로 호출 가능.**

---

## 1. 왜 만들어졌나 — 동기

### 익숙한 풍경: function call

```
LLM → tools=[search_web, query_db, send_email] → LLM 이 함수 선택 → 실행 → 결과 LLM 으로 복귀
```

여기서 도구는 **stateless 함수**. "검색해" 같은 행위 1개. 빨리 끝나고 메모리 없음.

### A2A 가 풀려는 새 풍경: agent-to-agent delegation

```
LLM-A (Supervisor)  →  "이 사고 진단해줘"  →  LLM-B (Incident Agent)
                                              └ B 도 자기 LLM 있음
                                              └ B 도 자기 도구 (Gateway, runbook DB) 있음
                                              └ B 도 자기 system_prompt, context 있음
                                              └ B 가 분석 후 진단 JSON 응답
   LLM-A ← {alarm, diagnosis, severity, recommended_actions} ← B
```

**"함수 호출" 이 아니라 "동료에게 작업 위임"**. B 는 자기 판단으로 도구 여러 개 호출하고, 시간 걸리고, 중간에 진행 상황 보고하기도 함.

기존 도구 (`@tool`) 로도 흉내는 가능: "Incident agent 호출" 이라는 함수를 만들면 됨. 근데 표준이 없으면:

| 문제 | A2A 가 해결 |
|---|---|
| B 가 무슨 능력이 있는지 A 가 어떻게 아나? | **AgentCard** — B 의 "명함" 을 표준 URL 에서 GET |
| 진행 상황 (스트리밍, 중간 업데이트) 어떻게? | **Task lifecycle** — submitted → working → completed, SSE 로 push |
| 멀티턴 대화 (A 가 B 에게 후속 질문) 어떻게? | **contextId** + **messages** 배열 |
| B 가 (str 이 아니라) 파일/이미지 응답하려면? | **Artifact** + Part (text/file/data) |
| Strands B 를 Google ADK A 가 호출하려면? | **JSON-RPC 표준 wire format** — 양쪽 SDK 가 같은 스펙 따름 |

→ 본질은 **"agent 들이 서로를 호출할 때 매번 ad-hoc REST API 짜지 말고 한 번 표준 정해서 모두 따르자"**.

---

## 2. 직관적 비유 — 명함과 회의

```
  ┌─────────────┐                        ┌─────────────┐
  │  Supervisor │                        │   Incident  │
  │   (Alice)   │                        │    (Bob)    │
  └──────┬──────┘                        └──────┬──────┘
         │                                      │
         │  ① "Bob, 너 뭐 할 줄 알아?"         │
         │  GET /.well-known/agent-card.json    │
         │  ────────────────────────────────►   │
         │                                      │
         │     "이름: Incident Agent.           │
         │      스킬: diagnose(alarm).           │
         │      입력: {alarm_name: str}.         │
         │      출력: JSON {diagnosis, ...}"     │
         │  ◄────────────────────────────────   │
         │                                      │
         │  ② "이 alarm 진단해줘"               │
         │  POST / (JSON-RPC: message/send)     │
         │  ────────────────────────────────►   │
         │                                      │
         │     [Bob 이 Gateway 호출, runbook   │
         │      읽고, LLM 으로 진단 작성...]    │
         │                                      │
         │  ③ "작업 시작 (status: working)"    │
         │  ◄────────────────────────────────   │
         │  ④ "진행 중... 지금 runbook 읽고    │
         │      있어 (status: working)"         │
         │  ◄────────────────────────────────   │
         │  ⑤ "완료 (status: completed)         │
         │      Artifact: { diagnosis: '...' }" │
         │  ◄────────────────────────────────   │
         │                                      │
```

세 단계 모두 **표준화** 되어 있는 게 A2A 의 본질.

---

## 3. 핵심 어휘 5개

```
┌─────────────┬────────────────────────────────────────────────────┐
│ AgentCard   │ Agent 의 명함. JSON 파일.                          │
│             │ {name, description, url, skills:[…], capabilities} │
│             │ URL: <base>/.well-known/agent-card.json            │
│             │ 누가 호출 전에 "당신 뭐 할 줄 알아" 물어볼 때 응답 │
├─────────────┼────────────────────────────────────────────────────┤
│ Skill       │ Agent 가 할 수 있는 작업 1개의 명세.               │
│             │ {name, description, inputSchema, outputModes}      │
│             │ 함수 시그니처에 가까움                              │
├─────────────┼────────────────────────────────────────────────────┤
│ Message     │ A → B 또는 B → A 로 흐르는 발화 1건                │
│             │ {role: "user"|"agent", parts: [TextPart|FilePart]} │
│             │ 사람의 채팅 메시지와 비슷                           │
├─────────────┼────────────────────────────────────────────────────┤
│ Task        │ "Alice 가 Bob 에게 시킨 작업 1건" 의 단위.          │
│             │ {id, contextId, status: submitted|working|completed│
│             │            |failed|canceled, history:[…]}          │
│             │ 시간 걸리는 작업을 추적하는 "작업 명령서"           │
├─────────────┼────────────────────────────────────────────────────┤
│ Artifact    │ Task 가 만들어낸 결과물.                           │
│             │ {name, parts: [TextPart|FilePart|DataPart]}        │
│             │ "최종 산출물" 이라고 보면 됨                       │
└─────────────┴────────────────────────────────────────────────────┘
```

→ Sub-agent 호출 1번 = **1 Task**. Task 내부에 message 가 여러 개 흐를 수 있고 (멀티턴), 끝에 artifact 1~N 개 반환.

---

## 4. Wire format — 한 번 보면 끝

A2A 는 **JSON-RPC 2.0 over HTTP**. POST 1개로 시작:

```http
POST https://bedrock-agentcore.us-east-1.amazonaws.com/runtimes/{arn}/invocations/
Authorization: Bearer eyJraWQiOiJ...      ← Cognito JWT (또는 SigV4)
Content-Type: application/json
X-Amzn-Bedrock-AgentCore-Runtime-Session-Id: 550e8400-...
X-Amzn-Bedrock-AgentCore-Runtime-Custom-Actorid: supervisor-001

{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "message/send",
  "params": {
    "message": {
      "role": "user",
      "parts": [
        {"kind": "text", "text": "alarm payment-ubuntu-status-check 진단해줘"}
      ],
      "messageId": "abc123"
    }
  }
}
```

응답 (스트리밍 SSE):

```
event: status-update
data: {"taskId":"t1","status":{"state":"working"}}

event: status-update
data: {"taskId":"t1","status":{"state":"working","message":{"parts":[{"kind":"text","text":"runbook 조회 중..."}]}}}

event: artifact-update
data: {"taskId":"t1","artifact":{"name":"agent_response","parts":[{"kind":"text","text":"{\"diagnosis\":\"...\",\"severity\":\"P1\"}"}]}}

event: status-update
data: {"taskId":"t1","status":{"state":"completed"}}
```

다른 메소드들:

| method | 의미 |
|---|---|
| `message/send` | A 가 B 에게 메시지 1건 보내고 응답 stream 받음 (가장 흔한) |
| `message/stream` | 동일하지만 명시적 SSE 모드 |
| `tasks/get` | Task ID 로 현재 상태 조회 (long-running) |
| `tasks/cancel` | Task 취소 요청 |

→ 결국 **REST API 인데, 메시지 schema 와 메소드 이름이 표준화**된 것.

---

## 5. Function call vs A2A — 가장 중요한 직관 비교

```
┌─────────────────────────┬──────────────────────────────────────┐
│  Function tool (@tool)  │  A2A sub-agent                        │
├─────────────────────────┼──────────────────────────────────────┤
│ 네 프로세스 안에서 실행 │ 다른 서버 (다른 컨테이너) 에서 실행  │
│ stateless 함수         │ 자기 LLM + 메모리 + 도구를 가진 agent │
│ 1번 호출 = 1번 실행    │ 1번 호출 = N개 도구 호출 + LLM 추론   │
│ ms 단위                 │ 초~분 단위                            │
│ 입출력은 함수 시그니처  │ 입출력은 message / artifact (구조화) │
│ 도구 schema 는 너가 작성│ AgentCard 가 자동 광고                │
│ 인증 무관 (in-process)  │ Bearer/SigV4 (네트워크 hop)           │
│ 같은 LLM provider 가정  │ 다른 LLM, 다른 SDK 가능               │
└─────────────────────────┴──────────────────────────────────────┘
```

**결정적 차이**: A2A sub-agent 는 *자기도 LLM 을 가진 동료*. function tool 은 *조작 가능한 객체*.

> 비유: function tool = "계산기 키 누르기", A2A sub-agent = "회계사한테 의뢰" — 회계사도 자기 계산기 (도구) 와 자기 판단 (LLM) 을 갖고 있고, 너는 결과만 받음.

---

## 6. 우리 프로젝트에 적용 — 구체 시나리오

```
운영자: "지금 결제 시스템 상황 진단해줘"
   │
   ▼
┌──────────────────────────────────────────────────────────┐
│ Supervisor Runtime  (LLM-A, Strands Agent)               │
│                                                          │
│  Strands LLM 이 system_prompt 보고 결정:                │
│    "monitor sub-agent 부터 호출하자"                     │
│                                                          │
│  call_monitor(query="현재 alarm 상황")                  │
│   │                                                      │
│   └─→ a2a.client.A2AClient.send_message(                 │
│         BASE=https://...{monitor_arn}.../invocations/,   │
│         auth=Bearer(client-B-jwt),                       │
│         msg=Message(parts=[TextPart("현재 alarm...")]))  │
└─────────────────────────┬────────────────────────────────┘
                          │ A2A protocol
                          ▼
┌──────────────────────────────────────────────────────────┐
│ Monitor Runtime  (LLM-B, Strands Agent)                 │
│   AgentCore 가 JWT 검증 → 통과                          │
│   FastAPI 가 POST / 받음 → A2AStarletteApp 처리         │
│   StrandsA2AExecutor 가 Strands Agent 깨움              │
│                                                          │
│   LLM-B 가 자기 도구로 Gateway 호출:                    │
│     monitoragenta2aTarget___DescribeAlarms()            │
│   결과 분석 → 응답 생성                                  │
│                                                          │
│   Artifact: {real_alarms: [{alarm: "payment-...", ...}]} │
└─────────────────────────┬────────────────────────────────┘
                          │ A2A response (SSE)
                          ▼
┌──────────────────────────────────────────────────────────┐
│ Supervisor 다시 LLM-A 차례                              │
│  monitor 결과 보고 결정:                                 │
│    "real_alarms 있으니 incident 호출"                   │
│                                                          │
│  call_incident(query="payment-ubuntu-status-check ...")  │
│   ↓ (위와 같은 A2A hop)                                 │
│   Incident Runtime 의 LLM-C 가 진단 → artifact 반환     │
│                                                          │
│  최종 Supervisor 응답:                                   │
│   {summary, monitor: {...}, incidents: [{...}], ...}     │
└──────────────────────────────────────────────────────────┘
```

→ Supervisor 의 LLM 이 **사람이 회사에서 동료한테 일 시키듯** 다른 agent 에게 위임. A2A 는 그 위임을 가능하게 하는 *언어*.

---

## 7. 왜 그냥 REST API 안 쓰고 A2A?

쓸 수는 있음. A2A 가 주는 추가 가치:

| 측면 | ad-hoc REST | A2A |
|---|---|---|
| 매 agent 마다 endpoint schema 다름 | ✓ (네가 매번 짬) | ✗ (표준) |
| 능력 자동 발견 | ✗ (네가 doc 읽음) | ✓ (AgentCard) |
| Long-running task 진행 보고 | ✗ (네가 design) | ✓ (Task lifecycle 표준) |
| 멀티턴 대화 | ✗ (네가 design) | ✓ (contextId + history) |
| 다른 SDK / vendor 와 호환 | ✗ | ✓ |
| 도구 (Strands SDK 등) 가 제공 | ✗ | ✓ (`A2AServer` 한 줄) |

→ **agent 1~2개면 ad-hoc 으로 충분하지만, agent 가 늘고 vendor 가 섞이면 표준이 비용 절감**.

---

## 8. 우리 코드에서 A2A 가 보이는 곳

```
Supervisor (caller)
  │
  ├── @tool def call_monitor(query): ...       ← 우리가 짤 것
  │     └── a2a.client.A2AClient.send_message  ← a2a-sdk 가 줌
  │           └── HTTPS POST + Bearer JWT       ← AgentCore 가 검증
  │
  └── @tool def call_incident(query): ...
        └── (동일)

Monitor / Incident (server, A2A protocol)
  │
  ├── Strands Agent + tools + system_prompt    ← Phase 3/4 logic 직접 재사용
  │
  └── serve_a2a(LazyExecutor())                ← AgentCore SDK 가 Bedrock-specific glue 자동 처리
        ├── /                                  ← message/send
        ├── /.well-known/agent-card.json       ← AgentCard 자동 도출
        └── /ping                              ← health endpoint
        + BedrockCallContextBuilder            ← workload-token 헤더 → ContextVar
```

**우리가 짜는 것은 `@tool` wrapper 2개 (Supervisor 측) + LazyExecutor 서브클래스 (sub-agent 측)**. AgentCore SDK 가 Bedrock-specific glue 자동 처리 (header propagation, AgentCard, /ping, port 9000).

---

## 9. 핵심을 한 그림으로

```
        ┌────── A2A 가 표준화한 4가지 ──────┐
        │                                    │
        │  ① 능력 광고      AgentCard       │
        │  ② 메시지 형식    Message/Part    │
        │  ③ 작업 추적      Task lifecycle  │
        │  ④ wire format    JSON-RPC + SSE  │
        │                                    │
        └────────────────────────────────────┘
                        ▲
                        │
        agent A  ──HTTP──►  agent B
        (caller)              (server)
                                │
                                └─ 자기 LLM + 도구 + 메모리 보유
```

A2A 는 결국 **"agent 들이 서로를 호출할 때 위 4가지를 약속한 것"**. 그 이상도 이하도 아님. 우리는 SDK (`strands.multiagent.a2a` + `a2a-sdk`) 가 제공하는 helper 로 직접 wire format 을 짤 일 거의 없음.

---

## 10. AWS canonical 패턴 — `serve_a2a` + `LazyExecutor` (Bedrock AgentCore best practice)

OAuth-dependent A2A sub-agent 의 정답. `agentcore create --protocol A2A` CLI 가 scaffolding 하는 정확한 패턴.

### 왜 `Strands A2AServer.to_fastapi_app()` 단독으로는 부족한가

```python
# ❌ 처음 우리가 시도 (잘못된 패턴)
from strands.multiagent.a2a import A2AServer

# 1. module init: workload-token 없음 → ValueError
agent = _build_agent_with_oauth_tools()  # ← @requires_access_token 호출 → 실패

a2a_server = A2AServer(agent=agent, http_url=..., serve_at_root=True)
app.mount("/", a2a_server.to_fastapi_app())
```

**문제 1**: Strands `A2AServer` 가 `BedrockCallContextBuilder` 미부착 → A2A 요청의 `x-amzn-bedrock-agentcore-runtime-workload-accesstoken` 헤더 → `BedrockAgentCoreContext` ContextVar 전달 안 됨. `requires_access_token` decorator 가 ContextVar 에서 token 못 찾음.

**문제 2**: agent 가 module init 시 빌드됨 → workload-token 자체가 inbound request 후에야 set 되므로 timing mismatch.

### ✅ AWS 공식 답: `serve_a2a` + `LazyExecutor`

```python
from bedrock_agentcore.runtime import serve_a2a
from bedrock_agentcore.identity.auth import requires_access_token
from strands import Agent
from strands.multiagent.a2a.executor import StrandsA2AExecutor


@requires_access_token(provider_name=..., scopes=[...], auth_flow="M2M", into="access_token")
async def _fetch_token(*, access_token: str = "") -> str:
    return access_token


async def _build_real_agent() -> Agent:
    token = await _fetch_token()        # ← request 시점 (ContextVar 채워진 후)
    # MCPClient + tools + Strands Agent ...
    return agent


class LazyExecutor(StrandsA2AExecutor):
    """첫 request 시 real agent build — module init 시 workload-token 없음 회피."""

    def __init__(self):
        # placeholder: AgentCard 는 init 시 도출되지만 caller 는 url 만 필요
        placeholder = Agent(name=..., description=..., tools=[])
        super().__init__(agent=placeholder)
        self._built = False

    async def execute(self, context, event_queue):
        if not self._built:
            self.agent = await _build_real_agent()  # ← 첫 request 시 real swap
            self._built = True
        await super().execute(context, event_queue)


if __name__ == "__main__":
    serve_a2a(LazyExecutor(), port=9000)    # AWS-blessed wrapper
```

### `serve_a2a` 가 자동 제공

| 책임 | 처리 |
|---|---|
| `/ping` health endpoint | 자동 |
| AgentCard at `/.well-known/agent-card.json` | 자동 (executor.agent.tool_registry 에서 도출) |
| `AGENTCORE_RUNTIME_URL` env → AgentCard `url` | 자동 |
| `BedrockCallContextBuilder` (header → ContextVar) | **자동** ← `requires_access_token` decorator 작동의 핵심 |
| port 9000 + Docker host detection | 자동 |

### LazyExecutor 의 의도

- **module init 시점**: workload-token 미존재 (incoming request 후에야 set)
- **`StrandsA2AExecutor` 가 정적 agent 받음** → init 시 placeholder
- **첫 request 시 ContextVar 채워짐** → `requires_access_token` decorator 작동 → real agent build → `self.agent` swap
- 이후 request: cached real agent 재사용

### Trade-off — 다른 패턴들

| 패턴 | 적합한 상황 | LoC |
|---|---|---|
| `Strands A2AServer.to_fastapi_app()` 단독 | OAuth 미사용 sub-agent (mock @tool 만) | 가장 짧음 |
| **`serve_a2a + LazyExecutor` (Recommended)** | OAuth-dependent sub-agent (Cognito M2M Gateway) | ~60 LoC |
| `A2AStarletteApplication` + custom `AgentExecutor` | per-session agent 격리 (actor_id 별 다른 agent) 필요 시 | ~150 LoC |

→ **AWS docs 가 명시 권장**: `serve_a2a(StrandsA2AExecutor(agent))` (1-line scaffold) — agent 가 OAuth 미사용 시. OAuth 사용 시 `LazyExecutor` 서브클래스 추가.

### 본 프로젝트 적용

- `agents/monitor_a2a/runtime/agentcore_runtime.py` + `agents/incident_a2a/runtime/agentcore_runtime.py` 둘 다 본 패턴.
- 검증 (2026-05-09): end-to-end smoke test 통과 (42.1초, 7,008 tokens) — Operator → Supervisor → Monitor → Incident 의 4-hop chain 정상 작동.

---

## 참고 자료

### 외부 문서
- A2A 프로토콜 사양: https://a2a-protocol.org/
- Bedrock AgentCore Runtime A2A: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-a2a.html
- Strands Agents 공식 문서: https://strandsagents.com/latest/

### 본 저장소 내 reference 코드 (학습용)
- `/home/ubuntu/amazon-bedrock-agentcore-samples/01-tutorials/01-AgentCore-runtime/05-hosting-a2a/02-a2a-agent-sigv4/` — Strands `A2AServer` 최소 예제 (SigV4 인증)
- `/home/ubuntu/amazon-bedrock-agentcore-samples/02-use-cases/A2A-multi-agent-incident-response/` — Google ADK + Strands + OpenAI 의 3-agent 토폴로지 (Cognito M2M)
- `/home/ubuntu/amazon-bedrock-agentcore-samples/02-use-cases/A2A-realestate-agentcore-multiagents/` — Strands supervisor + Cognito 변형 — Phase 5 와 가장 유사

