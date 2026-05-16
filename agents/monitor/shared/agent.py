"""Monitor Agent factory — model + system prompt 만 담당. 도구는 caller 가 주입.

caller (Phase 2 = ``local/run.py`` / Phase 3+ = ``runtime/agentcore_runtime.py``) 가
tools 와 system_prompt 파일명을 결정. agent.py 는 어느 phase 인지 모름 — 시스템
목표 C1 적합 (로컬 == Runtime 응답 단일 진실 원천).
"""
import os
from pathlib import Path

from strands import Agent
from strands.handlers.callback_handler import null_callback_handler
from strands.models import BedrockModel
from strands.types.content import SystemContentBlock

from _shared_debug import FlowHook, dprint_box, is_debug

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def _load_system_prompt(filename: str) -> str:
    return (_PROMPTS_DIR / filename).read_text(encoding="utf-8")


def create_agent(
    tools: list,
    system_prompt_filename: str,
) -> Agent:
    """Strands Agent 인스턴스 생성.

    Args (둘 다 명시 강제 — phase 별 caller 가 결정):
        tools: caller 가 주입하는 도구 list. baseline = `[get_past_alarms_metadata,
            get_past_alarm_history]` (mock @tool). Phase 2 current = MCPClient
            `list_tools_sync()` 결과의 mode 별 부분 집합.
        system_prompt_filename: ``prompts/`` 안의 파일명. baseline / Phase 2
            mode=past = ``"system_prompt_past.md"``, Phase 2 mode=live =
            ``"system_prompt_live.md"``.
    """
    model_id = os.environ.get("MONITOR_MODEL_ID") or "global.anthropic.claude-sonnet-4-6"
    region = os.environ.get("AWS_REGION") or "us-east-1"

    prompt_text = _load_system_prompt(system_prompt_filename)
    dprint_box(
        f"system prompt loaded — {system_prompt_filename} ({len(prompt_text):,} chars)",
        prompt_text,
        color="magenta",
    )

    # Bedrock prompt caching (dba 패턴 답습 — 3 layer 중 1+2):
    #   Layer 1: cache_tools="default"  → tool schema 캐시
    #   Layer 2: system_prompt 가 [text + cachePoint] 리스트 → system prompt 캐시
    #   Layer 3 (message-level cachePoint) 은 hooks 가 필요 — 우리는 single-turn 이라 미해당
    return Agent(
        model=BedrockModel(model_id=model_id, region_name=region, cache_tools="default"),
        tools=tools,
        system_prompt=[
            SystemContentBlock(text=prompt_text),
            SystemContentBlock(cachePoint={"type": "default"}),
        ],
        callback_handler=null_callback_handler,
        # DEBUG=1 시점에만 FlowHook 등록 — pre-call (LLM / tool) 가시화. off 시 hook 0.
        # agent_name = "Monitor" (Phase 4 Incident / Phase 5 Supervisor 는 각자 명시).
        hooks=[FlowHook(agent_name="Monitor")] if is_debug() else [],
    )
