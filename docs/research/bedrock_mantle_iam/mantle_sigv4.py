"""
Bedrock Mantle Anthropic 호환 엔드포인트 호출 - IAM 역할 + SigV4 직접 서명 방식.

토큰 발급 없이 boto3 자격 증명 체인(IAM 역할 자동 감지)으로 매 요청 서명.
EC2 인스턴스 프로파일, ECS task role, EKS IRSA, Lambda 실행 역할에서 그대로 동작.
"""

import json
import os

import boto3
import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

REGION = os.environ.get("AWS_REGION", "us-east-1")
MODEL_ID = "anthropic.claude-opus-4-7"
ENDPOINT = f"https://bedrock-mantle.{REGION}.api.aws/anthropic/v1/messages"


def call_mantle(messages: list, max_tokens: int = 512) -> dict:
    session = boto3.Session()
    creds = session.get_credentials()
    if creds is None:
        raise RuntimeError("자격 증명을 찾을 수 없습니다. IAM 역할 또는 AWS 프로파일이 설정되어 있는지 확인하세요.")
    frozen = creds.get_frozen_credentials()

    body = json.dumps(
        {
            "model": MODEL_ID,
            "max_tokens": max_tokens,
            "messages": messages,
        }
    )

    req = AWSRequest(
        method="POST",
        url=ENDPOINT,
        data=body,
        headers={
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    SigV4Auth(frozen, "bedrock-mantle", REGION).add_auth(req)

    resp = requests.post(
        req.url,
        headers=dict(req.headers.items()),
        data=req.body,
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()


if __name__ == "__main__":
    result = call_mantle(
        messages=[
            {"role": "user", "content": "한 문장으로 자기소개를 해주세요."},
        ],
        max_tokens=128,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


# 실행 예시 출력:
# $ uv run mantle_sigv4.py
# {
#   "model": "claude-opus-4-7",
#   "id": "msg_bdrk_o3llxkrau7irkabthsmnu3csln5nko66m72u5kkzvkloitfojcfq",
#   "type": "message",
#   "role": "assistant",
#   "content": [
#     {
#       "type": "text",
#       "text": "안녕하세요, 저는 Anthropic에서 만든 AI 어시스턴트 Claude이며, 여러분의 질문에 답하고 다양한 작업을 돕기 위해 여기 있습니다."
#     }
#   ],
#   "stop_reason": "end_turn",
#   "stop_sequence": null,
#   "stop_details": null,
#   "usage": {
#     "input_tokens": 30,
#     "cache_creation_input_tokens": 0,
#     "cache_read_input_tokens": 0,
#     "cache_creation": {
#       "ephemeral_5m_input_tokens": 0,
#       "ephemeral_1h_input_tokens": 0
#     },
#     "output_tokens": 80,
#     "service_tier": "standard"
#   }
# }
