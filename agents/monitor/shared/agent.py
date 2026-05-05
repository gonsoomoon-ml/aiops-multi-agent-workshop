"""
Monitor Agent — Strands Agent 정의 (shared core).

create_agent() 단일 진실 원천:
- Phase 1: agents/monitor/local/run.py 가 직접 호출
- Phase 3+: agents/monitor/runtime/entry.py 의 BedrockAgentCoreApp.entrypoint 가 동일 함수 호출

(developer-briefing-agent의 패턴 차용 — 시스템 목표 C1)
"""
import os
from pathlib import Path

from strands import Agent
from strands.handlers.callback_handler import null_callback_handler
from strands.models import BedrockModel

from agents.monitor.shared.tools.alarm_history import get_past_alarm_history

_PROMPT_PATH = Path(__file__).parent / "prompts" / "system_prompt.md"


def _load_system_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def create_agent() -> Agent:
    """Phase 1 / Phase 3+ 공통 — Strands Agent 인스턴스 생성."""
    model_id = os.environ.get("MONITOR_MODEL_ID", "global.anthropic.claude-sonnet-4-6")
    region = os.environ.get("AWS_REGION", "us-west-2")

    return Agent(
        model=BedrockModel(model_id=model_id, region_name=region),
        system_prompt=_load_system_prompt(),
        tools=[get_past_alarm_history],
        callback_handler=null_callback_handler,
    )
