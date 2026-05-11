"""Strands hook — pre-call 시점 가시화 + latency 측정 (DEBUG 모드 전용).

stream event 는 post-call (`usage` / `message complete`) 만 노출 — "호출 직전"
시점은 묵음. 본 hook 이 격차 메움:

  - ``BeforeModelCallEvent`` → ``Monitor → Bedrock`` (LLM 호출 직전 + 새 messages full dump + ``t_start`` 기록)
  - ``AfterModelCallEvent``  → ``Bedrock → Monitor`` (LLM call duration 계산 + 출력)
  - ``BeforeToolCallEvent``  → ``Monitor → Gateway`` (MCP tool 호출 직전)

TTFT (Time To First Token) 는 stream event 에서 첫 ``data``/``current_tool_use``
도착 시점에 ``event_dump.dump_stream_event`` 가 측정 (``agent._debug_t_call_start``
참조). hook 이 timing 시작점을 agent attribute 로 expose 해 stream loop 가 읽음.

dba (https://github.com/gonsoomoon-ml/developer-briefing-agent) 의
``HookProvider + register_hooks`` 등록 패턴 + ``dump_prompt`` delta 전략 차용
(call 마다 누적 새 messages 만 출력 → 중복 최소화). Memory 무관 — debug 가시화
전용 hook.

caller (``agent.create_agent``) 가 ``is_debug()`` 시점에만 인스턴스화 → DEBUG off
시 hook 등록 자체 0.
"""
import time

from strands.hooks import HookProvider, HookRegistry
from strands.hooks.events import (
    AfterModelCallEvent,
    BeforeModelCallEvent,
    BeforeToolCallEvent,
)

from .formatting import dprint, dprint_box

_TRUNC = 500


def _truncate(text: str, limit: int = _TRUNC) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}… (+{len(text) - limit} chars)"


def _format_message(idx: int, msg: dict) -> list[str]:
    """1 message → 박스 안 줄 리스트. role + content blocks 분해."""
    role = msg.get("role", "?")
    out = [f"[{idx}] role={role}:"]
    for block in msg.get("content", []):
        if not isinstance(block, dict):
            continue
        if "text" in block:
            out.append(f"  💬 text: {_truncate(block['text'])}")
        elif "toolUse" in block:
            tu = block["toolUse"]
            out.append(f"  🔧 toolUse: {tu.get('name', '?')}({tu.get('input', {})})")
        elif "toolResult" in block:
            for rc in block["toolResult"].get("content", []):
                if isinstance(rc, dict) and "text" in rc:
                    out.append(f"  📋 toolResult: {_truncate(rc['text'])}")
    return out


class FlowHook(HookProvider):
    """pre-call trace — Bedrock LLM 호출 직전 + MCP tool 호출 직전 마커.

    agent_name 으로 라벨 prefix parameterize. 호출자가 명시:
      - Phase 2/3 Monitor : ``FlowHook(agent_name="Monitor")``
      - Phase 4 Incident  : ``FlowHook(agent_name="Incident")``
      - Phase 5 Supervisor: ``FlowHook(agent_name="Supervisor")``
    """

    def __init__(self, agent_name: str = "Monitor") -> None:
        self.agent_name = agent_name
        self._llm_call_count = 0
        self._last_dumped_count = 0

    def _before_model(self, event: BeforeModelCallEvent) -> None:
        self._llm_call_count += 1
        msgs = getattr(event.agent, "messages", []) or []
        delta_start = self._last_dumped_count
        new_count = len(msgs) - delta_start

        if new_count <= 0:
            # edge case — 새 message 없으면 marker 만
            dprint(
                f"{self.agent_name} → Bedrock",
                f"LLM call #{self._llm_call_count} (msgs={len(msgs)}, no new)",
                color="cyan",
            )
        else:
            body: list[str] = []
            for i in range(delta_start, len(msgs)):
                body.extend(_format_message(i, msgs[i]))
                body.append("")  # message 간 빈 줄
            prev = self._llm_call_count - 1
            header = (
                f"{self.agent_name} → Bedrock — LLM call #{self._llm_call_count} "
                f"(msgs={len(msgs)}, +{new_count} new since #{prev})"
            )
            dprint_box(header, body, color="cyan")
            self._last_dumped_count = len(msgs)

        # timing — TTFT 는 stream loop 의 dump_stream_event 가 첫 chunk 시점에 계산
        # event_dump.py 가 agent_name 도 함께 참조 → message complete 박스에서 사용
        agent = event.agent
        agent._debug_t_call_start = time.monotonic()
        agent._debug_call_count = self._llm_call_count
        agent._debug_first_token_seen = False
        agent._debug_agent_name = self.agent_name

    def _after_model(self, event: AfterModelCallEvent) -> None:
        agent = event.agent
        t_start = getattr(agent, "_debug_t_call_start", None)
        if t_start is None:
            return
        elapsed_ms = (time.monotonic() - t_start) * 1000
        n = getattr(agent, "_debug_call_count", "?")
        dprint(
            f"Bedrock → {self.agent_name}",
            f"call #{n} done — total {elapsed_ms:,.0f}ms",
            color="dim",
        )

    def _before_tool(self, event: BeforeToolCallEvent) -> None:
        tu = event.tool_use
        name = tu.get("name", "?")
        inp = tu.get("input", {})
        dprint(
            f"{self.agent_name} → Gateway",
            f"tool call: {name}({inp})",
            color="cyan",
        )

    def register_hooks(self, registry: HookRegistry) -> None:
        registry.add_callback(BeforeModelCallEvent, self._before_model)
        registry.add_callback(AfterModelCallEvent, self._after_model)
        registry.add_callback(BeforeToolCallEvent, self._before_tool)
