# Bedrock Mantle + IAM Role 샘플

Claude Opus 4.7을 **Bedrock Mantle Anthropic 호환 엔드포인트**로 호출하는 IAM 역할 기반 샘플입니다.
EC2 인스턴스 프로파일, ECS task role, EKS IRSA, Lambda 실행 역할, `aws sts assume-role` 등 어떤 IAM 역할 자격 증명에서도 동작합니다.

## 인증 방식

두 가지 패턴을 모두 포함합니다.

1. **SigV4 직접 서명** (`mantle_sigv4.py`)
   - 토큰 발급 없이 IAM 역할의 임시 자격 증명으로 매 요청에 SigV4 서명
   - 별도 라이브러리 불필요 — `boto3` + `requests`만 있으면 동작
   - 장기 실행 워크로드에 적합 (토큰 만료 관리 불필요)

2. **단기 Bedrock API 키** (`mantle_token.py`)
   - `aws-bedrock-token-generator`로 IAM 역할에서 12시간 토큰 발급
   - Anthropic 네이티브 SDK 그대로 사용 가능 (이식성 우수)

## 필요 IAM 권한

역할 정책 예시:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ],
      "Resource": [
        "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-opus-4-7",
        "arn:aws:bedrock:us-east-1:*:inference-profile/us.anthropic.claude-opus-4-7"
      ]
    }
  ]
}
```

## 실행

```bash
pip install -r requirements.txt

# IAM 역할 자격 증명이 있는 환경(EC2/ECS/Lambda) 또는 로컬에서 assume-role 후
export AWS_REGION=us-east-1

python mantle_sigv4.py
python mantle_token.py
```

리전: `us-east-1`, `ap-northeast-1`, `eu-west-1`, `eu-north-1` 중 선택.
