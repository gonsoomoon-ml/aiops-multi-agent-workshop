"""Incident Agent factory — model + system prompt 만 담당. 도구는 caller 가 주입.

Monitor `agents/monitor/shared/agent.py` 와 동일 시그니처 — caller (runtime/agentcore_runtime.py
또는 향후 local 진입점) 가 tools + system_prompt 파일명 주입. dba 단일 truth 원칙
multi-agent 확장 (phase4.md D1).

Helper (`auth_local`, `mcp_client`, `env_utils`) 는 monitor/shared 직접 import — 중복 회피.
이 파일은 Incident 만의 truth (`agent.py` + `prompts/`) 를 담당.
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
    """Strands Agent 인스턴스 생성 (Incident).

    Args:
        tools: caller 가 주입하는 도구 list. Phase 4 Incident = MCPClient 의
            ``github-storage___*`` 부분 집합.
        system_prompt_filename: ``prompts/`` 안의 파일명. Phase 4 = ``"system_prompt.md"``
            (single mode — Incident 는 past/live 분기 없음).
    """
    # Default 은 Monitor 와 동일 (Sonnet 4.6) — Incident 도 full agent 라 동급 reasoning 필요.
    # 운영 시 ``INCIDENT_MODEL_ID`` env 로 override 가능 (sample-deep-insight 의 per-agent 모델 분리 패턴).
    model_id = os.environ.get("INCIDENT_MODEL_ID") or "global.anthropic.claude-sonnet-4-6"
    region = os.environ.get("AWS_REGION") or "us-west-2"

    return Agent(
        model=BedrockModel(model_id=model_id, region_name=region),
        tools=tools,
        system_prompt=_load_system_prompt(system_prompt_filename),
        callback_handler=null_callback_handler,
    )
