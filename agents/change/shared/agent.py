"""Change Agent factory — model + system prompt 만 담당. 도구는 caller 가 주입.

Phase 4 incident `agents/incident/shared/agent.py` 와 동일 시그니처. 차이점은 caller 가
주입하는 tools — Change 는 deployments-storage (배포 로그 read) + github-storage
(incidents/ append write) 두 Target 의 tool 들을 모두 받음.

Helper (auth_local, mcp_client, env_utils) 는 monitor_a2a/shared 직접 import — Phase 4
incident 가 monitor/shared 를 import 하는 패턴과 동일하지만 격리된 (preservation rule)
monitor_a2a/shared 를 사용. caller 측 build context Option A 로 deploy 시 함께 복사.
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
    """Strands Agent 인스턴스 생성 (Change).

    Args:
        tools: caller 가 주입하는 도구 list. Phase 6a Change = MCPClient 의
            ``deployments-storage___*`` + ``github-storage___*`` 부분 집합.
        system_prompt_filename: ``prompts/`` 안의 파일명. Phase 6a = ``"system_prompt.md"``.
    """
    # 비용 옵션 — Change 는 단순 lookup + structured write 가 주 — Haiku 로 충분.
    # plan_summary 의 per-agent 모델 분리 정책 (sample-deep-insight 패턴).
    model_id = os.environ.get("CHANGE_MODEL_ID") or "global.anthropic.claude-haiku-4-5-20251001-v1:0"
    region = os.environ.get("AWS_REGION") or "us-west-2"

    return Agent(
        model=BedrockModel(model_id=model_id, region_name=region),
        tools=tools,
        system_prompt=_load_system_prompt(system_prompt_filename),
        callback_handler=null_callback_handler,
    )
