"""Monitor Agent factory — model + system prompt 만 담당. 도구는 caller 가 주입.

caller (run_local_import.py / run.py / Phase 3 runtime/entry.py) 가 tools 와
system_prompt 파일명을 결정. agent.py 는 어느 phase 인지 모름 — 시스템 목표 C1
적합 (로컬 == Runtime 응답 단일 진실 원천).
"""
import os
from pathlib import Path

from strands import Agent
from strands.handlers.callback_handler import null_callback_handler
from strands.models import BedrockModel

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
    region = os.environ.get("AWS_REGION") or "us-west-2"

    return Agent(
        model=BedrockModel(model_id=model_id, region_name=region),
        tools=tools,
        system_prompt=_load_system_prompt(system_prompt_filename),
        callback_handler=null_callback_handler,
    )
