"""Monitor Agent shared helpers (Phase 1~5 carry-over).

본 디렉토리의 4 helper 파일 + agent.py + tools/ 가 Monitor / Incident / *_a2a / Supervisor
모두에서 재사용. 각 파일 단일 책임 (Single Responsibility) 으로 분리 — `from .X import Y`
명시적 의존 추적 + 후속 phase 의 build context copy 단순.

## Helper map (Phase 2~5 사용)

| 파일 | 책임 | 사용처 (외부 import 사이트) |
|---|---|---|
| ``agent.py``      | Strands Agent factory (model + system_prompt + tools) | run.py / run_local_import.py / 모든 *_a2a runtime |
| ``auth_local.py`` | Local 환경의 OAuth provider → Cognito JWT (Runtime 은 자동) | run.py (Phase 2 local) |
| ``env_utils.py``  | ``require_env(key)`` — 친화적 RuntimeError (raw KeyError 대신) | auth_local + mcp_client (내부) |
| ``mcp_client.py`` | MCPClient factory — Gateway URL + Bearer JWT header 주입 | run.py + 4 runtime (monitor / incident / monitor_a2a / incident_a2a) |
| ``modes.py``      | ``MODE_CONFIG`` — past/live mode 별 (target prefix, system prompt) | run.py + monitor / monitor_a2a runtime |
| ``tools/alarm_history.py`` | Phase 1 mock 직접 호출 @tool — Strands wrappers | run_local_import.py only |
| ``prompts/``      | system_prompt_past.md / system_prompt_live.md | agent.py 가 파일명으로 load |

## 설계 흐름 (Phase 2 local — `agents/monitor/local/run.py`)

::

    .env (Phase 2 deploy 가 채움)
        │
        ▼
    auth_local.get_local_gateway_token()    ← env_utils.require_env 검증
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

## 후속 phase 영향

- Phase 3 (Monitor Runtime): 이 디렉토리가 build context 로 그대로 vendor (deploy_runtime.py 의 ``cp -r monitor/shared``). agent.py + mcp_client + modes 만 사용 (auth_local 은 Runtime 자동 메커니즘으로 대체).
- Phase 4 (Incident Runtime): Option A — monitor/shared + incident/shared 둘 다 vendor. mcp_client + agent.py 재사용.
- Phase 5 (*_a2a Runtime): Option G — 본 디렉토리 직접 import (vendor 안 함, source-of-truth 단일).
"""
