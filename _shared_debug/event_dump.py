"""Strands ``stream_async()`` event dumper — DEBUG 모드에서 흥미로운 type 만 출력.

dba ``memory_hooks.py:dump_prompt`` (lines 333-371) 의 content block iteration
(``toolUse`` / ``toolResult`` / ``text`` 키 감지) 을 stream event 에 적응
(https://github.com/gonsoomoon-ml/developer-briefing-agent).

dba 와 다른 점:
  - dba 는 hook 의 ``event.agent.messages`` (assembled list) 순회
  - 우리는 ``stream_async()`` 가 흘리는 dict event 를 type 별 분기

text delta (``event['data']``) 는 caller (run.py) 가 이미 출력하므로 skip — 중복 방지.

Strands stream event shape (관찰):
  - ``event['data']``                        : text delta (skip)
  - ``event['message']``                     : message 완성 — assistant 의 toolUse + user 의 toolResult
  - ``event['event']['metadata']['usage']``  : 호출 단위 token usage
"""
import time

from .formatting import BLUE, DIM, MAGENTA, NC, WHITE, YELLOW, is_debug

_TRUNC_LIMIT = 500


def _truncate(text: str, limit: int = _TRUNC_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}… (+{len(text) - limit} chars)"


def _interesting_blocks(blocks: list, role: str) -> list:
    """출력 대상 block 만 필터 — assistant text 는 stream 이 이미 출력하므로 skip."""
    out = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if "toolUse" in block or "toolResult" in block:
            out.append(block)
        elif "text" in block and role != "assistant":
            out.append(block)
    return out


def _dump_content_blocks(blocks: list, agent_name: str = "Monitor", prefix: str = "  ") -> None:
    """dba ``dump_prompt`` 의 toolUse / toolResult / text 분기 (lines 333-374) 차용
    + directional label "ENTITY → <agent_name> (desc)" prefix.

    agent_name 으로 박스 안 라벨 parameterize (Phase 4 Incident / Phase 5 Supervisor
    재사용 대응). 호출자가 ``dump_stream_event`` 의 ``agent._debug_agent_name`` 으로 전달.
    """
    inner = prefix + "  "
    for block in blocks:
        if "toolUse" in block:
            tu = block["toolUse"]
            print(f"{prefix}{WHITE}💬 Bedrock → {agent_name} (decided: call tool){NC}")
            print(f"{inner}{WHITE}🔧 toolUse: {tu.get('name', '?')}({tu.get('input', {})}){NC}")
        elif "toolResult" in block:
            print(f"{prefix}{YELLOW}🔧 Lambda → {agent_name} (tool result){NC}")
            for rc in block["toolResult"].get("content", []):
                if isinstance(rc, dict) and "text" in rc:
                    print(f"{inner}{YELLOW}📋 toolResult: {_truncate(rc['text'])}{NC}")
        elif "text" in block:
            # assistant text 는 _interesting_blocks 에서 이미 skip → 여기 도달 시 user role
            print(f"{prefix}{BLUE}👤 User → {agent_name} (input){NC}")
            print(f"{inner}{BLUE}💬 text: {_truncate(block['text'])}{NC}")


def dump_stream_event(event: dict, agent=None) -> None:
    """Strands stream event 받아 흥미로운 type 만 출력 (DEBUG 모드 전용).

    DEBUG 꺼져있으면 no-op. text delta (``data``) 는 caller 가 이미 출력 → skip.

    agent 가 주어지면 TTFT (Time To First Token) 도 측정 — ``FlowHook._before_model``
    이 ``agent._debug_t_call_start`` 와 ``_debug_first_token_seen`` 를 셋업했음을
    가정. 첫 ``data``/``current_tool_use`` 도착 시 elapsed 계산 후 1회 출력.
    """
    if not is_debug():
        return

    # FlowHook 이 attribute 로 expose 한 agent_name (없으면 default "Monitor")
    agent_name = getattr(agent, "_debug_agent_name", "Monitor") if agent is not None else "Monitor"

    # 0) TTFT — 첫 chunk 도착 시 1회 (FlowHook 이 timing 시작점 셋업한 경우만)
    if agent is not None and not getattr(agent, "_debug_first_token_seen", True):
        if event.get("data") or event.get("current_tool_use"):
            t_start = getattr(agent, "_debug_t_call_start", None)
            if t_start is not None:
                elapsed_ms = (time.monotonic() - t_start) * 1000
                n = getattr(agent, "_debug_call_count", "?")
                print(f"\n{DIM}[DEBUG Bedrock → {agent_name}] call #{n} TTFT {elapsed_ms:,.0f}ms{NC}")
                agent._debug_first_token_seen = True

    # 1) message 완성 — content blocks 순회 (dba dump_prompt 패턴)
    # assistant text 는 stream delta 로 이미 출력 → 출력 대상 block 0 면 박스 자체 skip
    message = event.get("message")
    if isinstance(message, dict):
        content = message.get("content", [])
        if isinstance(content, list):
            role = message.get("role", "?")
            blocks = _interesting_blocks(content, role)
            if blocks:
                bar = "━" * 30
                print(f"\n{MAGENTA}┏━━━ message complete (role={role}) {bar}{NC}")
                _dump_content_blocks(blocks, agent_name=agent_name)
                print(f"{MAGENTA}┗{'━' * 60}{NC}")

    # 2) Bedrock raw event 의 token usage
    raw = event.get("event", {})
    if isinstance(raw, dict):
        meta = raw.get("metadata", {})
        if isinstance(meta, dict) and "usage" in meta:
            u = meta["usage"]
            print(
                f"\n{DIM}[DEBUG Bedrock → {agent_name}] usage total={u.get('totalTokens', 0):,} "
                f"in={u.get('inputTokens', 0):,} "
                f"out={u.get('outputTokens', 0):,} "
                f"cacheR={u.get('cacheReadInputTokens', 0):,} "
                f"cacheW={u.get('cacheWriteInputTokens', 0):,}{NC}"
            )
