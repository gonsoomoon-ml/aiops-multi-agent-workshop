# Debug Mode

> env `DEBUG=1` 으로 활성화되는 cross-phase trace helper. dba (`[developer-briefing-agent/shared/memory_hooks.py](https://github.com/gonsoomoon-ml/developer-briefing-agent)`) 의 ANSI 색·박스 보더·content block iteration 패턴 차용.

---

## 1. 무엇 (what it is)

Phase 2+ 의 monitor agent 코드 (`agents/monitor/local/run.py`, `agents/monitor/shared/*`) 에 분산된 debug 출력을 단일 toggle (env `DEBUG=1`) 로 켜고 끔. 켜지면 다음 trace 가 4 stage (**auth** → **MCP setup** → **agent init** → **LLM call cycle**) 흐름 순으로 한 화면에 출력:

모든 trace 가 `[DEBUG <FROM> → <TO>] <body>` 형식 — entity 흐름 (dba 패턴 답습) 단일 라인에 명시. `┏━━━ ... ━━━` 박스는 multi-line dump (system prompt / 새 messages / message complete / tool schemas). LLM call cycle 의 박스/라인은 각 LLM call (도구 호출 시 N+1 회) 마다 반복.


| 카테고리                                        | 출력 예                                                                                                                                              | 어디서                                                                                                                                                 |
| ------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| **token request (direct)**                  | `[DEBUG Monitor → Cognito] direct token request (url=…, client_id=…, scope=…)`                                                                    | `shared/auth_local.py:85` direct 분기                                                                                                                 |
| **token request (provider)**                | `[DEBUG Monitor → AgentCore Identity] via provider (provider=…)`                                                                                  | `shared/auth_local.py:60` provider 분기 (Phase 3+)                                                                                                    |
| **JWT received (direct)**                   | `[DEBUG Cognito → Monitor] JWT {'alg': 'RS256', 'sub': '…', 'scope': '…/invoke', …}`                                                              | `shared/auth_local.py:101` (sanitized)                                                                                                              |
| **JWT received (provider)**                 | `[DEBUG AgentCore Identity → Monitor] JWT {'alg': 'RS256', 'sub': '…', …}`                                                                        | `shared/auth_local.py:68` (sanitized, Phase 3+)                                                                                                     |
| **MCP client init**                         | `[DEBUG Monitor → Gateway] MCP client init (gateway_url=…, bearer=…ABCD)`                                                                         | `shared/mcp_client.py:25`                                                                                                                           |
| **MCP tools listed**                        | `[DEBUG Gateway → Monitor] MCP tools matched 2/4 (prefix='cloudwatch-wrapper___'): […]`                                                           | `local/run.py:81` tool prefix 필터 직후                                                                                                                 |
| **MCP tool schemas**                        | `┏━━━ MCP tool schemas (2 filtered) ━━━` `[<name>]` `description: …` `inputSchema: …` `┗━━━`                                                      | `local/run.py:97` (dprint_box)                                                                                                                      |
| **system prompt loaded**                    | `┏━━━ system prompt loaded — system_prompt_live.md (7,181 chars) ━━━` `<prompt 본문>` `┗━━━`                                                        | `shared/agent.py:42` (dprint_box)                                                                                                                   |
| **LLM call #N pre-dump**                    | `┏━━━ Monitor → Bedrock — LLM call #N (msgs=M, +K new since #N-1) ━━━` `[i] role=user/assistant: …` `💬 text / 🔧 toolUse / 📋 toolResult` `┗━━━` | FlowHook `_before_model` (BeforeModelCallEvent) — 새 messages 만 delta dump                                                                           |
| **MCP tool call (pre)**                     | `[DEBUG Monitor → Gateway] tool call: list_live_alarms({})`                                                                                       | FlowHook `_before_tool` (BeforeToolCallEvent)                                                                                                       |
| **TTFT**                                    | `[DEBUG Bedrock → Monitor] call #N TTFT 412ms`                                                                                                    | `_shared_debug/event_dump.py:90` 첫 chunk 도착 시 (FlowHook timing context 의존)                                                                          |
| **stream live label**                       | `[DEBUG Bedrock → User] 🧠 LIVE — streaming response →`                                                                                           | `local/run.py:61` (text delta 출력 직전 1회)                                                                                                             |
| **message complete (toolUse / toolResult)** | `┏━━━ message complete (role=assistant) ━━━` `💬 Bedrock → Monitor (decided: call tool)` `🔧 toolUse: list_alarms({})` `┗━━━`                     | Strands stream event message 완성 시. 박스 내부도 외부 trace 와 동일 entity 명명 (Bedrock / Monitor / Lambda / User) 으로 통일 — dba 의 `LLM/AGENT/TOOL` 추상 미차용 (혼란 회피) |
| **token usage**                             | `[DEBUG Bedrock → Monitor] usage total=5,377 in=2,862 out=29 cacheR=0 cacheW=2,486`                                                               | `_shared_debug/event_dump.py:113` Bedrock streaming metadata 도착 시 (call #1 cache write 예시; call #2 면 `cacheR≈2,486`)                                |
| **LLM call #N done**                        | `[DEBUG Bedrock → Monitor] call #N done — total 5,234ms`                                                                                          | FlowHook `_after_model` (AfterModelCallEvent)                                                                                                       |


`DEBUG` 미설정 시 모든 helper 가 no-op — 기존 출력과 100% 동일.

---

## 2. 어떻게 동작 (how it works)

### 2-1. 위치 — repo root sibling 에 `_shared_debug/`

```
aiops-multi-agent-workshop/
├── _shared_debug/                              ← cross-phase debug helper
│   ├── __init__.py                             ← public exports (7)
│   ├── formatting.py                           ← ANSI 상수 + is_debug + dprint + dprint_box + mask + redact_jwt
│   ├── event_dump.py                           ← Strands stream event dumper (+ TTFT)
│   └── strands_hook.py                         ← FlowHook (HookProvider) — pre-call LLM/tool 가시화 + duration
│
├── agents/
│   └── monitor/
│       ├── shared/
│       │   ├── agent.py          ── from _shared_debug import FlowHook, dprint_box, is_debug
│       │   ├── auth_local.py     ── from _shared_debug import dprint, redact_jwt
│       │   └── mcp_client.py     ── from _shared_debug import dprint, mask
│       └── local/
│           └── run.py            ── from _shared_debug import dprint, dprint_box, dump_stream_event, is_debug
└── docs/learn/debug_mode.md      ← 본 문서
```

**왜 repo root** ?

- `agentcore.launch()` 의 build context root = `agents/<phase>/runtime/` 이라 그 *내부* 만 container 에 올라감
- `agents/` namespace 는 container 에 부재 → `from agents._shared_debug import …` 는 **container 에서 ImportError**
- repo root 에 두면 deploy script 가 한 줄 (`shutil.copytree`) 로 build context 안에 sibling 으로 vendor → local + container 동일 import (`from _shared_debug import …`)

### 2-2. local 동작 (Phase 2 standalone)

```
$ DEBUG=1 uv run python -m agents.monitor.local.run --mode live
        │
        │  uv run -m 가 repo root 를 sys.path[0] 로 잡음
        │  → from _shared_debug import …  resolve OK
        ▼
   auth_local.py → mcp_client.py → run.py 의 stream loop
        │
        │  각 모듈이 dprint() / dump_stream_event() 호출
        │  → is_debug() 검사 → DEBUG=1 이면 출력, 아니면 no-op
        ▼
   ANSI 색 trace 가 표준 출력에 흐름 순서대로 인쇄
```

### 2-3. container 동작 (Phase 3+ Runtime)

`agentcore.launch()` 가 build context (`agents/monitor/runtime/`) 를 통째로 `/app/` 에 upload — build context 밖의 파일은 container 에 부재. 따라서 deploy script 가 사전에 외부 의존 모듈 두 개 (`agents/monitor/shared/` + repo root `_shared_debug/`) 를 build context 안으로 복사해 둠 (dba 패턴):

```
agents/monitor/runtime/deploy_runtime.py
   │
   │  os.chdir(SCRIPT_DIR)                                          # build root = runtime/
   │
   │  ┌─ shared/ — monitor agent 모듈 (agent + auth + mcp) ────┐
   │  │ shutil.copytree(PROJECT_ROOT/'agents'/'monitor'/'shared',   │
   │  │                 SCRIPT_DIR/'shared')                        │
   │  └────────────────────────────────────────────────────────┘
   │
   │  ┌─ _shared_debug/ — cross-phase debug helper ────────────┐
   │  │ shutil.copytree(PROJECT_ROOT/'_shared_debug',               │
   │  │                 SCRIPT_DIR/'_shared_debug')                 │
   │  └────────────────────────────────────────────────────────┘
   │
   ▼
agentcore_runtime.launch()             # → /app/ 에 build root 통째 upload
```

Container 안:

```
/app/                                            ← Dockerfile WORKDIR, sys.path[0]
├── agentcore_runtime.py                         (entrypoint, python -m agentcore_runtime)
├── shared/
│   ├── agent.py             ── from _shared_debug import FlowHook, dprint_box, is_debug  ✓
│   ├── auth_local.py        ── from _shared_debug import dprint, redact_jwt              ✓
│   └── mcp_client.py        ── from _shared_debug import dprint, mask                    ✓
└── _shared_debug/                               ← deploy 가 copy
    ├── __init__.py
    ├── formatting.py
    ├── event_dump.py
    └── strands_hook.py
```

**Container 에서 DEBUG 켜기**: `deploy_runtime.py:122-147` 가 호스트 `DEBUG` 를 `runtime.launch(env_vars={"DEBUG": debug_val, ...})` 로 forward. `DEBUG=1 uv run agents/monitor/runtime/deploy_runtime.py` 재배포 → CloudWatch logs 에서 trace 확인. 자세한 사용법은 §6.

### 2-4. FlowHook — pre-call 가시화 hook

Strands `stream_async()` 이벤트는 post-call (`message complete` / `usage`) 만 노출 → "호출 직전" 시점은 묵음. `FlowHook` (`_shared_debug/strands_hook.py`) 이 `HookProvider` 를 상속해 3 콜백 등록 → 격차 메움 (TTFT 시작점 셋업 포함).

```python
class FlowHook(HookProvider):
    def __init__(self, agent_name: str = "Monitor") -> None:
        self.agent_name = agent_name           # 라벨 prefix (Phase 4=Incident, Phase 5=Supervisor)
        self._llm_call_count = 0
        self._last_dumped_count = 0            # delta dump — 새 messages 만 출력

    def _before_model(self, event: BeforeModelCallEvent) -> None:
        # 1) dprint_box → ┏━━━ Monitor → Bedrock — LLM call #N (msgs=M, +K new) ━━━ (cyan)
        # 2) agent._debug_t_call_start = time.monotonic()
        #    → stream loop 의 dump_stream_event 가 첫 chunk 도착 시 TTFT 계산
        ...

    def _after_model(self, event: AfterModelCallEvent) -> None:
        # dprint dim → [DEBUG Bedrock → Monitor] call #N done — total Yms
        ...

    def _before_tool(self, event: BeforeToolCallEvent) -> None:
        # dprint cyan → [DEBUG Monitor → Gateway] tool call: <name>(<input>)
        ...

    def register_hooks(self, registry: HookRegistry) -> None:
        registry.add_callback(BeforeModelCallEvent, self._before_model)
        registry.add_callback(AfterModelCallEvent, self._after_model)
        registry.add_callback(BeforeToolCallEvent, self._before_tool)
```

**한 cycle (LLM call 1회 + tool 호출 1회) trace 출력 순서**:

```
agent.stream_async(prompt)
   │
   ├─ FlowHook._before_model       ← BeforeModelCallEvent
   │     • ┏━━━ Monitor → Bedrock — LLM call #1 (msgs=1, +1 new since #0) ━━━  (cyan box)
   │     • agent._debug_t_call_start = monotonic()                              (TTFT 시작점)
   │
   ├─ Bedrock streaming chunks (stream_async event loop — dump_stream_event)
   │     • 첫 chunk    → [DEBUG Bedrock → Monitor] call #1 TTFT 412ms          (dim)
   │     • message    → ┏━━━ message complete (role=assistant) ━━━ toolUse… ━━━ (magenta box)
   │     • usage      → [DEBUG Bedrock → Monitor] usage total=… cacheW=2,486   (dim)
   │
   ├─ FlowHook._after_model        ← AfterModelCallEvent
   │     • [DEBUG Bedrock → Monitor] call #1 done — total 5,234ms              (dim)
   │
   ├─ FlowHook._before_tool        ← BeforeToolCallEvent
   │     • [DEBUG Monitor → Gateway] tool call: list_live_alarms({})           (cyan)
   │
   ├─ MCP tool 실행 (Gateway → Lambda → result, AWS-internal)
   │
   └─ FlowHook._before_model       ← BeforeModelCallEvent (call #2 — 결과 분석)
         • ┏━━━ Monitor → Bedrock — LLM call #2 (msgs=3, +2 new since #1) ━━━  (cyan box)
         • ... (cycle 반복; agent 가 도구 호출 더 이상 안 하면 종료)
```

**활성화**: caller 가 `is_debug()` 시점에만 instantiate → DEBUG off 시 hook 등록 자체 0 (overhead 0).

```python
# agents/monitor/shared/agent.py:62
agent = Agent(
    ...,
    hooks=[FlowHook(agent_name="Monitor")] if is_debug() else [],
)
```

`agent_name` 으로 Phase 별 trace 라벨 prefix 결정 — `"Monitor"` (Phase 2/3) / `"Incident"` (Phase 4) / `"Supervisor"` (Phase 5).

---

## 3. 사용법

### 3-1. 켜고 / 끄기

> Phase 2 인프라 사전 조건 (`infra/cognito-gateway/deploy.sh` 완료 + repo root `.env` 갱신 — monitor agent 자체는 standalone, deploy 없음). past/live 두 mode 모두 Gateway/MCP 경유.

```bash
# 켜기 — past mode (mock alarm history 분석)
DEBUG=1 uv run python -m agents.monitor.local.run --mode past

# 켜기 — live mode (실 CloudWatch alarm 분류)
DEBUG=1 uv run python -m agents.monitor.local.run --mode live

# 끄기 (기본)
uv run python -m agents.monitor.local.run --mode live
```

`DEBUG` 의 truthy 값: `1`, `true`, `yes`, `on` (대소문자 무관).

### 3-2. 새 모듈에서 사용

`_shared_debug` 의 7 export 를 import 후 호출 (DEBUG off 면 모두 no-op):

```python
from _shared_debug import (
    is_debug, dprint, dprint_box, mask, redact_jwt, dump_stream_event, FlowHook,
)

# 1. 단일 trace 라인
dprint("MY label", "body content here", color="cyan")

# 2. 박스 보더 multi-line dump (system prompt / tool schemas 등)
dprint_box("MY top label", "line1\nline2\nline3", color="magenta")

# 3. JWT / secret sanitize
print(mask(some_secret))                    # …ABCD (len=883)
print(redact_jwt(some_jwt))                 # {'alg': 'RS256', 'sub': '…', …}

# 4. Agent 생성 시 pre-call 가시화 hook 등록 (DEBUG off 시 hook 0)
agent = Agent(
    ...,
    hooks=[FlowHook(agent_name="MyAgent")] if is_debug() else [],
)

# 5. Strands stream event 자동 분기 (loop 안에서 1줄)
async for event in agent.stream_async(prompt):
    print(event.get("data", ""), end="")
    dump_stream_event(event, agent=agent)   # agent= 로 TTFT 측정 활성
```

`dprint` 의 color: `cyan` / `green` / `yellow` / `magenta` / `blue` / `red` / `white` / `dim`.

### 3-3. 색 의미 


| 색           | 의미                                                                                                                                                                  |
| ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **CYAN**    | setup / config + pre-call trace — auth path, MCP setup, tool list 매칭, FlowHook `Monitor → Bedrock LLM call #N` (full messages 박스), `Monitor → Gateway tool call: …` |
| **GREEN**   | acquired / saved (JWT 획득 완료)                                                                                                                                        |
| **YELLOW**  | tool result (Lambda 응답) — `🔧 Lambda → Monitor (tool result)`                                                                                                       |
| **BLUE**    | user 입력 (text) — `👤 User → Monitor (input)`                                                                                                                        |
| **MAGENTA** | message 박스 보더 + system prompt dump                                                                                                                                  |
| **WHITE**   | Bedrock 의 도구 호출 결정 — `💬 Bedrock → Monitor (decided: call tool)` + stream live label                                                                                |
| **DIM**     | metadata + 타이밍 — token usage 누적, `call #N TTFT Xms`, `call #N done — total Yms`                                                                                     |
| **RED**     | error trace (현재 미사용, 향후 retry/exception 트레이스용)                                                                                                                      |


---

## 4. Phase 별 적용 상태


| Phase       | 적용 위치                                                                                                                                                                                                  | 상태  |
| ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --- |
| **Phase 1** | mock 기반 standalone (auth/MCP 미사용) → debug helper 적용 무관                                                                                                                                                 | n/a |
| **Phase 2** | `shared/agent.py` (1 dprint_box + FlowHook 등록) + `shared/auth_local.py` (4 dprint) + `shared/mcp_client.py` (1 dprint) + `local/run.py` (2 dprint + 1 dprint_box + 1 dump_stream_event)                | ✅   |
| **Phase 3** | `runtime/agentcore_runtime.py` (1 dump_stream_event) + `runtime/deploy_runtime.py` (★ `_shared_debug/` build context 복사 + 호스트 `DEBUG` 를 `env_vars["DEBUG"]` 로 forward) + runtime 의 `shared/` 동일 import | ✅   |
| **Phase 4** | `agents/incident/` (`FlowHook(agent_name="Incident")`) + `agents/incident_a2a/` 동일 패턴                                                                                                                  | ✅   |
| **Phase 5** | `agents/supervisor/` (`FlowHook(agent_name="Supervisor")`) + sub-agent (`agents/monitor_a2a/`, `agents/incident_a2a/`) trace prefix parameterize                                                       | ✅   |


---

## 5. 검증 (P-D1)

Phase 2 standalone, `DEBUG=1` on/off 비교:

```bash
# off — 기존 stream 출력만, debug 라인 0
uv run python -m agents.monitor.local.run --mode live

# on — 4 stage trace (auth → MCP → init → LLM cycle) + message 박스 + TTFT/duration + token usage
DEBUG=1 uv run python -m agents.monitor.local.run --mode live
```

**기대**: off 결과와 on 결과의 LLM 답변 텍스트 + 최종 token 합 동일 (debug 가 동작 변경 X).

### 5-1. DEBUG=1 trace 가 보여주는 호출 시퀀스

`DEBUG=1` 으로 한 번 돌려보면 Phase 2 의 모든 컴포넌트가 어떻게 협력하는지가 한 화면에 드러남. 위 명령의 trace 를 시퀀스 다이어그램으로 정리:

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

**범례**: `├──▶│` = call (sender → receiver) / `│◀──┤` = response / `┼` = arrow 가 통과만 하는 lifeline (해당 entity 미관여) / `┄` (점선) = AWS-internal flow (Gateway → Lambda forwarding, client trace 불가 — CloudWatch logs 만 가능) / `Monitor` 컬럼 = Strands `Agent` 가 토큰 획득·Gateway 호출·Bedrock 통신을 모두 조율하는 hub.

**핵심 인사이트 4가지**:

1. **Agent loop = LLM call 2번** — "도구 호출 결정" (call #1, output 29 tok) + "결과 분석" (call #2, output 282 tok). 도구가 N개 더 호출되면 call 도 N+1 회로 증가.
2. **Tool result 의 `role=user`** — Bedrock 규약. assistant 가 toolUse → 시스템이 그 결과를 user message 로 다시 주입 → assistant 가 다음 응답 생성. "user 가 말한 적 없는데 user role" 헷갈림 포인트.
3. **Prompt caching 효과 — single invocation 내 즉시** — `cache_tools="default"` + system prompt cachePoint (Layer 1+2) 적용 후, call #1 이 system+tools 를 cache write (`cacheW≈2,486`), call #2 가 즉시 hit (`cacheR≈2,486`). agent loop 안의 2-step LLM 만으로도 ~27% 비용 절감. 5분 이내 재호출 시 warm cache → cacheW=0, ~74% 절감.
4. **TTFT vs total duration** — `[DEBUG Bedrock → Monitor] call #N TTFT Xms` (첫 token 도착) + `call #N done — total Yms` (응답 완료) 분리 출력. Y − X = output token 생성 시간 (~145 tok/s @ Sonnet 4.6). cache hit 시 TTFT 도 단축됨.

---

## 6. 알려진 제약

- **container DEBUG = 재배포 필요** — `agents/monitor/runtime/deploy_runtime.py:122-147` 가 호스트 `DEBUG` 를 `runtime.launch(env_vars={"DEBUG": debug_val, ...})` 로 forward. container trace 켜려면 `DEBUG=1 uv run agents/monitor/runtime/deploy_runtime.py` 재배포 → CloudWatch logs (`aws logs tail /aws/bedrock-agentcore/runtimes/<MONITOR_RUNTIME_ID>-DEFAULT --follow`) 로 확인. 런타임 도중 hot-toggle 불가.
- **AWS-internal 묵음** — Gateway → Lambda forwarding (다이어그램 점선 `┄`) 은 client trace 불가. CloudWatch logs 로만 가시화.
- **assistant text block 박스 skip** — stream delta 가 이미 출력하므로 중복 회피 (의도적; `event_dump.py:_interesting_blocks`).
- **agent business state 무수정** — `dprint` / `dprint_box` / `dump_stream_event` 는 동기 print only. `FlowHook` 만 agent 에 `_debug_`* prefix attribute 4 종 (`_debug_t_call_start`, `_debug_first_token_seen`, `_debug_call_count`, `_debug_agent_name`) 부착 — timing context 전용, business state 무관.

---

## reference

- dba 패턴: `[developer-briefing-agent/shared/memory_hooks.py](https://github.com/gonsoomoon-ml/developer-briefing-agent)`
- dba 의 hook 등록: lines 392-396 (`register_hooks` + `add_callback`)
- 차용 핵심: ANSI 상수 (lines 24-31), 박스 보더 모티프 (lines 289-390), content block iteration (lines 323-371), `dump_prompt` delta 전략 (call 마다 새 messages 만 dump)
- FlowHook 사용 이유: Strands `stream_async()` 는 post-call (`message complete` / `usage`) 만 노출 → pre-call (TTFT 시작점, 새 messages delta dump, MCP 호출 직전) 가시화 위해 `HookProvider` 필요. dba 와 차이: Memory 무관 — debug 가시화 전용

