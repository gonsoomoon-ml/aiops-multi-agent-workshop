"""Mode → (Gateway target prefix, prompt 파일명) 매핑.

local/run.py 와 runtime/agentcore_runtime.py 양쪽이 import — single source of truth.
Gateway 가 도구 이름을 ``<target>___<tool>`` 로 namespacing 하므로 prefix 로 mode 분리.
(reference: A2A monitoring_strands_agent + ec-customer-support — 둘 다 prompt 에 도구
이름 명시 안 하고 capability 로 LLM 발견 위임. 우리도 동일.)
"""
MODE_CONFIG = {
    "past": ("history-mock___", "system_prompt_past.md"),
    "live": ("cloudwatch-wrapper___", "system_prompt_live.md"),
}
