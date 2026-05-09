"""
다른 계정/역할로 AssumeRole 후 Bedrock Mantle 호출 - IAM 역할 체이닝 예제.

크로스 계정 시나리오나 명시적으로 특정 역할을 사용해야 할 때 적용.
"""

import json
import os

import boto3
import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials

REGION = os.environ.get("AWS_REGION", "us-east-1")
ROLE_ARN = os.environ["BEDROCK_ROLE_ARN"]  # 예: arn:aws:iam::123456789012:role/BedrockMantleCaller
SESSION_NAME = os.environ.get("BEDROCK_SESSION_NAME", "mantle-call")
MODEL_ID = "anthropic.claude-opus-4-7"
ENDPOINT = f"https://bedrock-mantle.{REGION}.api.aws/anthropic/v1/messages"


def assume_role() -> Credentials:
    sts = boto3.client("sts")
    out = sts.assume_role(RoleArn=ROLE_ARN, RoleSessionName=SESSION_NAME, DurationSeconds=3600)
    c = out["Credentials"]
    return Credentials(
        access_key=c["AccessKeyId"],
        secret_key=c["SecretAccessKey"],
        token=c["SessionToken"],
    )


def call_mantle(creds: Credentials, prompt: str) -> dict:
    body = json.dumps(
        {
            "model": MODEL_ID,
            "max_tokens": 256,
            "messages": [{"role": "user", "content": prompt}],
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
    SigV4Auth(creds, "bedrock-mantle", REGION).add_auth(req)

    resp = requests.post(req.url, headers=dict(req.headers.items()), data=req.body, timeout=60)
    resp.raise_for_status()
    return resp.json()


if __name__ == "__main__":
    creds = assume_role()
    result = call_mantle(creds, "AssumeRole 경로로 Mantle을 호출했습니다. 한 문장으로 인사해주세요.")
    print(json.dumps(result, ensure_ascii=False, indent=2))
