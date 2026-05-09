#!/usr/bin/env python3
"""
deploy_runtime.py — Phase 6a Change Agent AgentCore Runtime 배포 (A2A protocol)

Phase 4 incident `deploy_runtime.py` 와 다른 점:
  - **protocol="A2A"** — toolkit `Runtime.configure(protocol=...)` 가 A2A protocol 직접 지원
  - **authorizer_configuration** — customJWTAuthorizer.allowedClients=[Cognito Client B id]
    (Cognito M2M Bearer JWT 가 caller — Supervisor 측 OAuth provider 발급)
  - **request_header_configuration** — Custom-Actorid 헤더 allowlist
  - Build context 에 monitor_a2a/shared + change/shared 두 디렉토리 모두 copy
    (Phase 4 incident 의 Option A 패턴, 단 monitor_a2a/shared 사용 — preservation rule)

사용법:
    uv run agents/change/runtime/deploy_runtime.py

사전 조건:
    - Phase 2 + Phase 3 + Phase 4 deploy 완료 (Cognito stack + Gateway + Lambda × 3 alive)
    - Phase 6a Step C 완료 — `infra/phase6a/cognito_extras.yaml` (Cognito Client B 발급) +
      `infra/phase6a/deployments_lambda.yaml` (deployments-storage Lambda + Gateway Target)
    - agents/monitor_a2a/shared/ 신규 디렉토리 존재 (Phase 6a Step B2)
    - AWS 자격 증명 + Docker daemon
    - bedrock-agentcore-starter-toolkit 설치 (pyproject.toml)
    - repo root .env 에 GATEWAY_URL / COGNITO_* / COGNITO_CLIENT_B_ID 채워진 상태

수행 단계:
    1. monitor_a2a/shared + change/shared 를 빌드 컨텍스트로 복사
    2. Runtime.configure(protocol="A2A", authorizer_configuration=...)
    3. Runtime.launch — Docker 빌드 → ECR push → Runtime A2A 생성
    4. IAM `Phase6aChangeRuntimeExtras` + OAuth2CredentialProvider (Gateway 호출용 Client C) 부착
    5. READY 대기 + runtime/.env 저장 (CHANGE_RUNTIME_ARN cross-agent reference)

reference:
    - phase4.md §3 (Incident Agent 패턴 — 5단계 흐름 carry-over)
    - phase6a.md §4 (Change Agent), §5-3 (Inbound Authorizer)
    - 02-a2a-agent-sigv4 (Strands A2AServer + protocol=A2A)
"""
import json
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[2]
os.chdir(SCRIPT_DIR)

load_dotenv(PROJECT_ROOT / ".env")

GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
BLUE = "\033[0;34m"
RED = "\033[0;31m"
NC = "\033[0m"

DEMO_USER = os.environ["DEMO_USER"]
REGION = os.environ.get("AWS_REGION", "us-west-2")
AGENT_NAME = f"aiops_demo_{DEMO_USER}_change"
OAUTH_PROVIDER_NAME = f"{AGENT_NAME}_gateway_provider"


def copy_shared_into_build_context() -> None:
    """[1/5] monitor_a2a/shared (helper) + change/shared (truth) 를 build context 로 복사.

    컨테이너 layout (`/app/`):
      shared/             ← monitor_a2a/shared (auth_local, mcp_client, env_utils, modes)
      change_shared/      ← change/shared (agent.py + prompts/)

    monitor_a2a/shared 는 Phase 4 monitor/shared 의 격리된 복사본 (Phase 6a 의 preservation rule).
    """
    print(f"{YELLOW}[1/5] shared/ × 2 를 빌드 컨텍스트로 복사 중...{NC}")

    monitor_a2a_src = PROJECT_ROOT / "agents" / "monitor_a2a" / "shared"
    change_src = PROJECT_ROOT / "agents" / "change" / "shared"

    if not monitor_a2a_src.exists():
        print(f"{RED}❌ monitor_a2a/shared 미발견: {monitor_a2a_src}{NC}")
        print(f"{RED}   Phase 6a Step B2 (monitor_a2a 신규 작성) 가 선행되어야 함.{NC}")
        sys.exit(1)
    if not change_src.exists():
        print(f"{RED}❌ change/shared 미발견: {change_src}{NC}")
        sys.exit(1)

    shared_dst = SCRIPT_DIR / "shared"
    if shared_dst.exists():
        shutil.rmtree(shared_dst)
    shutil.copytree(monitor_a2a_src, shared_dst)
    print(f"{GREEN}  ✅ monitor_a2a/shared → runtime/shared/ (helper){NC}")

    change_dst = SCRIPT_DIR / "change_shared"
    if change_dst.exists():
        shutil.rmtree(change_dst)
    shutil.copytree(change_src, change_dst)
    print(f"{GREEN}  ✅ change/shared → runtime/change_shared/ (agent.py + prompts){NC}\n")


def configure_runtime():
    """[2/5] toolkit Runtime.configure(protocol="A2A", authorizer_configuration=...).

    customJWTAuthorizer 는 Cognito Client B (M2M, A2A audience) 발급 토큰만 통과.
    """
    print(f"{YELLOW}[2/5] AgentCore Runtime 설정 중 (A2A protocol)...{NC}")
    try:
        from bedrock_agentcore_starter_toolkit import Runtime
    except ImportError:
        print(f"{RED}❌ bedrock-agentcore-starter-toolkit 미설치 — uv sync 필요{NC}")
        sys.exit(1)

    user_pool_id = os.environ["COGNITO_USER_POOL_ID"]
    client_b_id = os.environ["COGNITO_CLIENT_B_ID"]
    discovery_url = (
        f"https://cognito-idp.{REGION}.amazonaws.com/{user_pool_id}/.well-known/openid-configuration"
    )

    runtime = Runtime()
    response = runtime.configure(
        agent_name=AGENT_NAME,
        entrypoint="agentcore_runtime.py",
        auto_create_execution_role=True,
        auto_create_ecr=True,
        requirements_file="requirements.txt",
        region=REGION,
        protocol="A2A",
        authorizer_configuration={
            "customJWTAuthorizer": {
                "discoveryUrl": discovery_url,
                "allowedClients": [client_b_id],
            }
        },
        request_header_configuration={
            "requestHeaderAllowlist": [
                "X-Amzn-Bedrock-AgentCore-Runtime-Custom-Actorid",
            ]
        },
        non_interactive=True,
    )
    print(f"{GREEN}✅ 설정 완료{NC}")
    print(f"   Protocol:    A2A")
    print(f"   AllowedClients: [{client_b_id}]")
    print(f"   Dockerfile:  {response.dockerfile_path}")
    print(f"   Config:      {response.config_path}\n")
    return runtime


def launch_runtime(runtime):
    """[3/5] Docker 빌드 → ECR push → Runtime 생성 (~5-10분, update ~40초)."""
    print(f"{YELLOW}[3/5] Runtime 배포 중 (Docker 빌드 → ECR 푸시 → 생성)...{NC}")
    print(f"   ⏳ 첫 배포 ~5-10분, 업데이트 ~40초\n")

    env_vars = {
        "GATEWAY_URL": os.environ["GATEWAY_URL"],
        "OAUTH_PROVIDER_NAME": OAUTH_PROVIDER_NAME,
        "COGNITO_GATEWAY_SCOPE": os.environ["COGNITO_GATEWAY_SCOPE"],
        "CHANGE_MODEL_ID": os.environ.get(
            "CHANGE_MODEL_ID", "global.anthropic.claude-haiku-4-5-20251001-v1:0"
        ),
        "OTEL_RESOURCE_ATTRIBUTES": f"service.name={AGENT_NAME}",
        "AGENT_OBSERVABILITY_ENABLED": "true",
        "DEMO_USER": DEMO_USER,
    }

    start_time = datetime.now()
    result = runtime.launch(env_vars=env_vars, auto_update_on_conflict=True)
    elapsed = (datetime.now() - start_time).total_seconds()

    print(f"\n{GREEN}✅ 배포 완료 ({elapsed:.0f}초){NC}")
    print(f"   Runtime ARN: {result.agent_arn}")
    print(f"   Runtime ID:  {result.agent_id}")
    print(f"   ECR URI:     {result.ecr_uri}\n")
    return result


def attach_extras_and_oauth_provider(launch_result) -> None:
    """[4/5] IAM inline policy + OAuth2CredentialProvider 부착 (Gateway 호출용 Client C)."""
    print(f"{YELLOW}[4/5] IAM 추가 권한 + OAuth2CredentialProvider 생성 중...{NC}")

    agentcore_control = boto3.client("bedrock-agentcore-control", region_name=REGION)
    runtime_info = agentcore_control.get_agent_runtime(agentRuntimeId=launch_result.agent_id)
    role_arn = runtime_info["roleArn"]
    role_name = role_arn.split("/")[-1]
    account_id = role_arn.split(":")[4]

    iam = boto3.client("iam")
    extras_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "GetResourceOauth2Token",
                "Effect": "Allow",
                "Action": ["bedrock-agentcore:GetResourceOauth2Token"],
                "Resource": "*",
            },
            {
                "Sid": "ReadCognitoClientSecret",
                "Effect": "Allow",
                "Action": ["secretsmanager:GetSecretValue"],
                "Resource": [
                    f"arn:aws:secretsmanager:{REGION}:{account_id}:secret:bedrock-agentcore-identity!*",
                ],
            },
        ],
    }
    iam.put_role_policy(
        RoleName=role_name,
        PolicyName="Phase6aChangeRuntimeExtras",
        PolicyDocument=json.dumps(extras_policy),
    )
    print(f"{GREEN}✅ IAM inline policy 부착: {role_name}/Phase6aChangeRuntimeExtras{NC}")

    user_pool_id = os.environ["COGNITO_USER_POOL_ID"]
    domain = os.environ["COGNITO_DOMAIN"]
    try:
        agentcore_control.create_oauth2_credential_provider(
            name=OAUTH_PROVIDER_NAME,
            credentialProviderVendor="CustomOauth2",
            oauth2ProviderConfigInput={
                "customOauth2ProviderConfig": {
                    "clientId": os.environ["COGNITO_CLIENT_C_ID"],
                    "clientSecret": os.environ["COGNITO_CLIENT_C_SECRET"],
                    "oauthDiscovery": {
                        "authorizationServerMetadata": {
                            "issuer": f"https://cognito-idp.{REGION}.amazonaws.com/{user_pool_id}",
                            "authorizationEndpoint": f"https://{domain}.auth.{REGION}.amazoncognito.com/oauth2/authorize",
                            "tokenEndpoint": f"https://{domain}.auth.{REGION}.amazoncognito.com/oauth2/token",
                            "responseTypes": ["token"],
                        },
                    },
                },
            },
        )
        print(f"{GREEN}✅ OAuth Provider 생성: {OAUTH_PROVIDER_NAME}{NC}\n")
    except ClientError as e:
        code = e.response["Error"]["Code"]
        message = e.response["Error"].get("Message", "")
        if code == "ConflictException" or (code == "ValidationException" and "already exists" in message):
            print(f"   (OAuth Provider {OAUTH_PROVIDER_NAME} 이미 존재 — 재배포 시나리오 skip)\n")
        else:
            raise


def wait_until_ready(launch_result) -> None:
    """[5/5 의 일부] Runtime READY 대기 (max 10분)."""
    print(f"{YELLOW}[5/5] Runtime READY 상태 대기 중 (최대 10분)...{NC}")

    agentcore_control = boto3.client("bedrock-agentcore-control", region_name=REGION)
    terminal_states = {"READY", "CREATE_FAILED", "DELETE_FAILED", "UPDATE_FAILED"}
    status = "CREATING"
    max_attempts = 60

    for attempt in range(1, max_attempts + 1):
        time.sleep(10)
        try:
            resp = agentcore_control.get_agent_runtime(agentRuntimeId=launch_result.agent_id)
            status = resp["status"]
            print(f"   [{attempt}/{max_attempts}] {status}")
        except Exception as e:
            print(f"   {RED}상태 확인 실패: {e}{NC}")
            break
        if status in terminal_states:
            break

    print()
    if status != "READY":
        print(f"{RED}❌ Runtime 실패 (상태: {status}){NC}")
        print(f"   CloudWatch 로그 확인:")
        print(f"   aws logs tail /aws/bedrock-agentcore/runtimes/{AGENT_NAME} --follow --region {REGION}")
        sys.exit(1)


def save_runtime_metadata(launch_result) -> None:
    """[5/5 의 일부] Runtime metadata 를 runtime/.env 에 저장.

    이중 key 패턴 (Phase 4 incident 와 동일) — 자기 invoke 용 generic ``RUNTIME_ARN`` +
    cross-agent caller 용 namespaced ``CHANGE_RUNTIME_ARN`` (Supervisor `@tool
    call_change` 가 read).
    """
    print(f"{YELLOW}[5/5] Runtime 정보를 runtime/.env 에 저장 중...{NC}")

    env_file = SCRIPT_DIR / ".env"
    if env_file.exists():
        with open(env_file, "r") as f:
            lines = [
                line for line in f.readlines()
                if not line.startswith("RUNTIME_ARN=")
                and not line.startswith("RUNTIME_ID=")
                and not line.startswith("RUNTIME_NAME=")
                and not line.startswith("OAUTH_PROVIDER_NAME=")
                and not line.startswith("CHANGE_RUNTIME_ARN=")
                and not line.strip().startswith("# Phase 6a Runtime")
            ]
    else:
        lines = []

    lines.append(f"\n# Phase 6a Runtime ({datetime.now().strftime('%Y-%m-%d')})\n")
    lines.append(f"RUNTIME_NAME={AGENT_NAME}\n")
    lines.append(f"RUNTIME_ARN={launch_result.agent_arn}\n")
    lines.append(f"RUNTIME_ID={launch_result.agent_id}\n")
    lines.append(f"OAUTH_PROVIDER_NAME={OAUTH_PROVIDER_NAME}\n")
    lines.append(f"CHANGE_RUNTIME_ARN={launch_result.agent_arn}\n")

    with open(env_file, "w") as f:
        f.writelines(lines)
    print(f"{GREEN}✅ runtime/.env 저장 완료{NC}\n")


def print_summary(launch_result) -> None:
    print(f"{BLUE}{'=' * 60}{NC}")
    print(f"{GREEN}  배포 완료!{NC}")
    print(f"{BLUE}{'=' * 60}{NC}")
    print(f"   Runtime 이름:      {AGENT_NAME}")
    print(f"   Runtime ARN:       {launch_result.agent_arn}")
    print(f"   ECR URI:           {launch_result.ecr_uri}")
    print(f"   OAuth Provider:    {OAUTH_PROVIDER_NAME}")
    print(f"   Protocol:          A2A (port 9000 root)")
    print(f"   리전:              {REGION}")
    print()
    print(f"   다음 단계:")
    print(f"   1. Change A2A 단독 호출 (Step D 의 Operator CLI 또는 별 A2A 클라이언트):")
    print(f"      # see agents/operator/cli.py 또는 a2a-sdk client 직접 사용")
    print(f"   2. Supervisor 의 call_change 가 본 Runtime 호출 (Step B3 + Step F 후):")
    print(f"      uv run agents/operator/cli.py --query \"...\"")
    print(f"   3. 로그 확인:")
    print(f"      aws logs tail /aws/bedrock-agentcore/runtimes/{AGENT_NAME} --follow")
    print(f"   4. 자원 정리:")
    print(f"      bash agents/change/runtime/teardown.sh")
    print()


def main() -> None:
    print(f"\n{BLUE}{'=' * 60}{NC}")
    print(f"{BLUE}  Phase 6a — Change Agent AgentCore Runtime 배포 (A2A){NC}")
    print(f"{BLUE}{'=' * 60}{NC}\n")

    copy_shared_into_build_context()
    runtime = configure_runtime()
    launch_result = launch_runtime(runtime)
    attach_extras_and_oauth_provider(launch_result)
    wait_until_ready(launch_result)
    save_runtime_metadata(launch_result)
    print_summary(launch_result)


if __name__ == "__main__":
    main()
