"""
Bedrock Mantle Anthropic 호환 엔드포인트 호출 - IAM 역할 + 단기 Bedrock API 키 방식.

aws-bedrock-token-generator가 IAM 역할 자격 증명 체인에서 Bearer 토큰을 발급하고,
Anthropic 네이티브 SDK를 그대로 사용해 호출.
"""

import os

import anthropic
from aws_bedrock_token_generator import provide_token

REGION = os.environ.get("AWS_REGION", "us-east-1")
MODEL_ID = "anthropic.claude-opus-4-7"
BASE_URL = f"https://bedrock-mantle.{REGION}.api.aws/anthropic"


def build_client() -> anthropic.Anthropic:
    token = provide_token(region=REGION)
    return anthropic.Anthropic(base_url=BASE_URL, api_key=token)


if __name__ == "__main__":
    client = build_client()
    resp = client.messages.create(
        model=MODEL_ID,
        max_tokens=128,
        messages=[
            {"role": "user", "content": "한 문장으로 자기소개를 해주세요."},
        ],
    )
    for block in resp.content:
        if block.type == "text":
            print(block.text)

    print("---")
    print(f"input_tokens={resp.usage.input_tokens}, output_tokens={resp.usage.output_tokens}")
