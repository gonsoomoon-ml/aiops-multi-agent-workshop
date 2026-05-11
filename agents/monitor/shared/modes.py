"""Mode → (Gateway target prefix, prompt 파일명) 매핑.

본 디렉토리 helper 흐름 (`shared/__init__.py` map 참조):
  ``mcp_client.list_tools_sync()`` 로 받은 전체 tool list →
  **본 파일의 ``MODE_CONFIG[mode][0]`` (target prefix) 로 filter** →
  ``agent.create_agent(tools=filtered, system_prompt_filename=MODE_CONFIG[mode][1])``.

local/run.py 와 runtime/agentcore_runtime.py 양쪽이 import — single source of truth.
Gateway 가 도구 이름을 ``<target>___<tool>`` 로 namespacing 하므로 prefix 로 mode 분리.
(reference: A2A monitoring_strands_agent
[https://github.com/awslabs/amazon-bedrock-agentcore-samples — 02-use-cases/A2A-multi-agent-incident-response/]
+ ec-customer-support
[https://github.com/gonsoomoon-ml/ec-customer-support-e2e-agentcore]
— 둘 다 prompt 에 도구 이름 명시 안 하고 capability 로 LLM 발견 위임. 우리도 동일.)
"""
MODE_CONFIG = {
    "past": ("history-mock___", "system_prompt_past.md"),
    "live": ("cloudwatch-wrapper___", "system_prompt_live.md"),
}
