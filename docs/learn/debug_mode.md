# Debug Mode

> env `DEBUG=1` 으로 활성화되는 cross-phase trace helper. dba ([`developer-briefing-agent/shared/memory_hooks.py`](https://github.com/gonsoomoon-ml/developer-briefing-agent)) 의 ANSI 색·박스 보더·content block iteration 패턴 차용.

---

## 1. 무엇 (what it is)

Phase 2+ 의 monitor agent 코드 (`agents/monitor/local/run.py`, `agents/monitor/shared/*`) 에 분산된 debug 출력을 단일 toggle (env `DEBUG=1`) 로 켜고 끔. 켜지면 다음 4 카테고리 trace 가 한 화면에 흐름 순으로 출력:

| 카테고리 | 출력 예 | 어디서 |
|---|---|---|
| **AUTH path** | `[DEBUG AUTH path] direct (url=…, client_id=…, scope=…)` | `auth_local.py` provider/direct 분기점 |
| **AUTH JWT** | `[DEBUG AUTH JWT] {'alg': 'RS256', 'sub': '…', 'aud': '…', 'scope': '…/invoke', …}` | JWT 획득 직후 (sanitized) |
| **MCP setup** | `[DEBUG MCP setup] gateway_url=…, bearer=…ABCD (len=883)` | `mcp_client.py` Gateway 클라이언트 생성 시 |
| **MCP tools** | `[DEBUG MCP tools] prefix='cloudwatch-wrapper___' matched 2/4: […]` | `local/run.py` tool prefix 필터 직후 |
| **toolUse / toolResult** | `┏━━━ message complete (role=assistant) ━━━ 🔧 toolUse: list_alarms({}) ━━━┗` | Strands stream event message 완성 시 |
| **token usage** | `[DEBUG ← usage] total=2,891 in=2,862 out=29 cacheR=0 cacheW=0` | Bedrock streaming metadata 도착 시 |

`DEBUG` 미설정 시 모든 helper 가 no-op — 기존 출력과 100% 동일.

---

## 2. 어떻게 동작 (how it works)

### 2-1. 위치 — repo root sibling 에 `_shared_debug/`

```
aiops-multi-agent-demo/
├── _shared_debug/                              ← cross-phase debug helper
│   ├── __init__.py                             ← public exports
│   ├── formatting.py                           ← ANSI 상수 + dprint + mask + redact_jwt
│   └── event_dump.py                           ← Strands stream event dumper
│
├── agents/
│   └── monitor/
│       ├── shared/
│       │   ├── auth_local.py     ── from _shared_debug import dprint, redact_jwt
│       │   └── mcp_client.py     ── from _shared_debug import dprint, mask
│       └── local/
│           └── run.py            ── from _shared_debug import dump_stream_event, …
└── docs/learn/debug_mode.md      ← 본 문서
```

**왜 repo root** (이전 case 였던 `agents/_shared_debug/` 가 아니라):
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

`agentcore.launch()` 가 build context (`agents/monitor/runtime/`) 를 통째로 `/app/` 에 upload. deploy script 가 사전에 sibling 자원을 build context 에 복사 (dba 패턴):

```
agents/monitor/runtime/deploy_runtime.py
   │
   │  os.chdir(SCRIPT_DIR)                                          # build root = runtime/
   │
   │  ┌─ 기존 (Phase 3 first-pass) ────────────────────────────┐
   │  │ shutil.copytree(PROJECT_ROOT/'agents'/'monitor'/'shared',   │
   │  │                 SCRIPT_DIR/'shared')                        │
   │  └────────────────────────────────────────────────────────┘
   │
   │  ┌─ ★ debug helper 추가 (Phase 3 review 시 한 줄 추가) ─┐
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
│   ├── auth_local.py        ── from _shared_debug import dprint, …  ✓
│   └── mcp_client.py        ── from _shared_debug import …          ✓
└── _shared_debug/                               ← deploy 가 copy
    ├── __init__.py
    ├── formatting.py
    └── event_dump.py
```

**Container 에서 DEBUG 켜기**: `agentcore.launch(env_vars={"DEBUG": "1"})` 또는 `Runtime.configure` 의 env 인자 — Phase 3 deploy 시 옵션 노출 필요.

### 2-4. dba 와의 관계

| 항목 | dba `shared/memory_hooks.py` | 우리 `_shared_debug/` |
|---|---|---|
| 목적 | AgentCore Memory hook (retrieve/save) + debug 부수 기능 | debug 만 |
| 활성화 | `--debug` CLI flag → `StandupMemoryHooks(debug=True)` 인스턴스 | env `DEBUG=1` (CLI flag 없음) |
| Strands hook 사용 | `HookProvider` 상속, `BeforeInvocationEvent`/`BeforeModelCallEvent`/`AfterInvocationEvent` 콜백 | **미사용** — Memory 미사용으로 hook scaffolding 불필요. Strands `stream_async()` 가 동일 데이터 노출 |
| 차용 자산 | — | ANSI 색 상수, 박스 보더, content block iteration (`toolUse`/`toolResult`/`text` 분기) |
| Runtime 동작 | dba 도 동일 deploy copy 패턴 | 동일 패턴 답습 |

---

## 3. 사용법

### 3-1. 켜고 / 끄기

> Phase 2 deploy 전제 (`infra/cognito-gateway/deploy.sh` 완료 + `.env` 갱신). past/live 두 mode 모두 Gateway/MCP 경유.

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

`_shared_debug` 의 4 export 를 import 후 호출:

```python
from _shared_debug import dprint, mask, redact_jwt, dump_stream_event

# 1. 단일 trace 라인
dprint("MY label", "body content here", color="cyan")

# 2. JWT / secret sanitize
print(mask(some_secret))                    # …ABCD (len=883)
print(redact_jwt(some_jwt))                 # {'alg': 'RS256', 'sub': '…', …}

# 3. Strands stream event 자동 분기 (loop 안에서 1줄)
async for event in agent.stream_async(prompt):
    print(event.get("data", ""), end="")
    dump_stream_event(event)                # DEBUG=1 일 때만 박스 출력
```

`dprint` 의 color: `cyan` / `green` / `yellow` / `magenta` / `blue` / `red` / `white` / `dim`.

### 3-3. 색 의미 (dba 답습)

| 색 | 의미 |
|---|---|
| **CYAN** | setup / config trace (auth path, MCP setup, tool list 매칭) |
| **GREEN** | acquired / saved (JWT 획득 완료) |
| **YELLOW** | tool result (Lambda 응답) |
| **MAGENTA** | message 박스 보더 |
| **WHITE** | tool 호출 (`🔧 toolUse: …`) |
| **DIM** | metadata (token usage 누적) |
| **RED** | error trace (현재 미사용, 향후 retry/exception 트레이스용) |

---

## 4. Phase 별 적용 상태

| Phase | 적용 위치 | 상태 |
|---|---|---|
| **Phase 1** | mock 기반 standalone (auth/MCP 미사용) → debug helper 적용 무관 | n/a |
| **Phase 2** | `auth_local.py` (4 dprint) + `mcp_client.py` (1 dprint) + `local/run.py` (1 dprint + 1 dump_stream_event) | ✅ |
| **Phase 3** | `agents/monitor/runtime/agentcore_runtime.py` + `deploy_runtime.py` (★ `shutil.copytree` 한 줄 추가) | 🚧 review 시 적용 |
| **Phase 4/5** | Incident / Supervisor / A2A — 신규 코드 작성 시 동일 import + deploy script 한 줄 | 🚧 |

---

## 5. 검증 (P-D1)

Phase 2 standalone, `DEBUG=1` on/off 비교:

```bash
# off — 기존 stream 출력만, debug 라인 0
uv run python -m agents.monitor.local.run --mode live

# on — 4 카테고리 trace + message 박스 + token usage
DEBUG=1 uv run python -m agents.monitor.local.run --mode live
```

**기대**: off 결과와 on 결과의 LLM 답변 텍스트 + 최종 token 합 동일 (debug 가 동작 변경 X).

**확인됨 (2026-05-11)**: live mode, 6,333 token, real/noise 분류 정확. on/off 결과 동일.

---

## 6. 알려진 제약

- **container 에서 DEBUG 켜기는 별도 작업** — Phase 3 deploy 시 `agentcore.launch(env_vars={"DEBUG": "1"})` 옵션 노출 필요
- **assistant text block 박스 skip** — stream delta 가 이미 출력하므로 중복 회피 (의도적; `event_dump.py:_interesting_blocks`)
- **메모리 캐시 영향 없음** — `dprint`/`dump_stream_event` 는 동기 print only, agent state 무수정

---

## reference

- dba 패턴: [`developer-briefing-agent/shared/memory_hooks.py`](https://github.com/gonsoomoon-ml/developer-briefing-agent)
- dba 의 hook 등록: lines 392-396 (`register_hooks` + `add_callback`)
- 차용 핵심: ANSI 상수 (lines 24-31), 박스 보더 모티프 (lines 289-390), content block iteration (lines 323-371)
- AgentCore Runtime build context 동작: `docs/design/phase3.md` (작성 시)
