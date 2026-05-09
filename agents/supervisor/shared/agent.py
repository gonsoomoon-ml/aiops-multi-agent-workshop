"""Supervisor Agent factory — Phase 4 incident `shared/agent.py` 와 동일 시그니처.

Strands `Agent` 에 `sub_agents` 파라미터 자체 없음 — sub-agent 호출은 *도구로 노출* 하는
패턴 (research 확인). 따라서 Supervisor 도 `tools=` 시그니처. caller (runtime/
agentcore_runtime.py) 가 `@tool` 함수 2개 (call_monitor_a2a, call_incident_a2a) 를 주입.
Change Agent 는 후속 phase 로 연기 — Phase 6a 의 핵심 메시지 (A2A activation) 에 집중.

reference: phase6a.md §3-1, docs/research/a2a_intro.md §6.
"""
import os
from pathlib import Path

from strands import Agent
from strands.handlers.callback_handler import null_callback_handler
from strands.models import BedrockModel

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def _load_system_prompt(filename: str) -> str:
    return (_PROMPTS_DIR / filename).read_text(encoding="utf-8")


def create_supervisor_agent(
    tools: list,
    system_prompt_filename: str,
) -> Agent:
    """Strands Agent 인스턴스 생성 (Supervisor).

    Args:
        tools: caller 가 주입하는 @tool 함수 list.
            Phase 6a = [call_monitor_a2a, call_incident_a2a] —
            각 tool 이 a2a.client.A2AClient.send_message() 호출을 wrap.
        system_prompt_filename: ``prompts/`` 안의 파일명 — routing 정책 정의.
    """
    # Sonnet 4.6 — Supervisor 는 routing decision + 응답 통합 — Sonnet 급 필요.
    model_id = os.environ.get("SUPERVISOR_MODEL_ID") or "global.anthropic.claude-sonnet-4-6"
    region = os.environ.get("AWS_REGION") or "us-west-2"

    return Agent(
        model=BedrockModel(model_id=model_id, region_name=region),
        tools=tools,
        system_prompt=_load_system_prompt(system_prompt_filename),
        callback_handler=null_callback_handler,
    )
