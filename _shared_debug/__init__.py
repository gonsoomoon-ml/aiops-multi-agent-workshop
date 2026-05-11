"""Cross-phase debug helpers — env ``DEBUG=1`` 시 활성.

용도:
  - ``dprint`` — 모듈 단위 trace (auth / MCP setup 등 Strands 외부 코드)
  - ``dump_stream_event`` — Strands ``stream_async()`` event 에서 tool_use / tool_result / usage 추출
  - ``mask`` / ``redact_jwt`` — secret / JWT sanitize

dba (외부 reference: ``developer-briefing-agent/shared/memory_hooks.py``
— https://github.com/gonsoomoon-ml/developer-briefing-agent) 의 ANSI 색 + 박스
보더 + content block iteration 로직 차용. hook 패턴 미차용 — AgentCore Memory
미사용으로 ``HookProvider`` scaffolding 불필요. Strands stream event 가 동일
데이터 노출.
"""
from .event_dump import dump_stream_event
from .formatting import (
    dprint,
    is_debug,
    mask,
    redact_jwt,
)

__all__ = [
    "is_debug",
    "dprint",
    "mask",
    "redact_jwt",
    "dump_stream_event",
]
