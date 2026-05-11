"""Cross-phase debug helpers — env ``DEBUG=1`` 시 활성.

용도:
  - ``dprint`` / ``dprint_box`` — 모듈 단위 trace (auth / MCP setup / system prompt / tool schema 등 Strands 외부)
  - ``dump_stream_event`` — Strands ``stream_async()`` event 에서 tool_use / tool_result / usage / TTFT 추출
  - ``FlowHook`` — Strands hook (pre-call LLM + tool 가시화 + AfterModelCall 의 LLM duration 측정)
  - ``mask`` / ``redact_jwt`` — secret / JWT sanitize

dba (외부 reference: ``developer-briefing-agent/shared/memory_hooks.py``
— https://github.com/gonsoomoon-ml/developer-briefing-agent) 의 ANSI 색 + 박스
보더 + content block iteration + ``HookProvider`` 등록 패턴 + ``dump_prompt``
delta 전략 차용. dba 와 차이: hook 이 Memory 무관 — debug 가시화 전용.

agent_name 으로 라벨 prefix parameterize → Phase 4 (Incident) / Phase 5
(Supervisor) 에서 동일 helper 재사용 가능.
"""
from .event_dump import dump_stream_event
from .formatting import (
    dprint,
    dprint_box,
    is_debug,
    mask,
    redact_jwt,
)
from .strands_hook import FlowHook

__all__ = [
    "is_debug",
    "dprint",
    "dprint_box",
    "mask",
    "redact_jwt",
    "dump_stream_event",
    "FlowHook",
]
