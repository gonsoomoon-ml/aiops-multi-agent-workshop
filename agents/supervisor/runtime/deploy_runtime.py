#!/usr/bin/env python3
"""
deploy_runtime.py — Phase 6a Supervisor Agent AgentCore Runtime 배포 (HTTP)

Phase 4 incident `deploy_runtime.py` 와 다른 점 (Option X):
  - **agent_name = ``aiops_demo_${DEMO_USER}_supervisor``**
  - **HTTP protocol** (operator 진입) — Phase 4 와 동일
  - **inbound authorizer 미설정** → SigV4 IAM default (Operator CLI 가 boto3
    invoke_agent_runtime 사용 — Phase 4 invoke 패턴 동일)
  - **OAuth provider = Phase 2 Client C 재사용** (Phase 4 incident 와 동일 Client +
    동일 provider 명명). sub-agent A2A 호출용 Bearer 도 Client C 토큰 — AgentCore
    customJWTAuthorizer 가 aud (= Client C id) 만 검증해서 통과
  - **sub-agent ARN env vars** — MONITOR_A2A_RUNTIME_ARN / INCIDENT_A2A_RUNTIME_ARN
    (2 sub-agent 의 .env 에서 cross-load — Change 는 후속 phase 로 연기)
  - Build context: supervisor/shared 만 (self-contained, helper 의존 없음)

사용법:
    uv run agents/supervisor/runtime/deploy_runtime.py

사전 조건:
    - Phase 0/2/3/4 deploy 완료 (Phase 2 Client C 존재 — repo .env)
    - monitor_a2a + incident_a2a Runtime 모두 deploy 완료
      → 각 .env 에 MONITOR_A2A_RUNTIME_ARN / INCIDENT_A2A_RUNTIME_ARN 작성됨
    - repo `.env` 에 COGNITO_CLIENT_C_ID, COGNITO_CLIENT_C_SECRET (Phase 2 산출물)

수행 단계:
    1. supervisor/shared → 빌드 컨텍스트 복사
    2. sub-agent ARN cross-load (2개의 runtime/.env 에서 — monitor_a2a + incident_a2a)
    3. Runtime.configure(protocol="HTTP")  — authorizer 미설정 = SigV4 default
    4. Runtime.launch
    5. IAM ``Phase6aSupervisorRuntimeExtras`` + OAuth provider (Phase 2 Client C 재사용)
    6. READY 대기 + runtime/.env 저장
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
AGENT_NAME = f"aiops_demo_{DEMO_USER}_supervisor"
# Option X — Phase 2 Client C 재사용. Provider 명명은 Phase 4 incident 와 동일 패턴.
OAUTH_PROVIDER_NAME = f"{AGENT_NAME}_gateway_provider"


def copy_shared_into_build_context() -> None:
    """[1/6] supervisor/shared → build context."""
    print(f"{YELLOW}[1/6] shared/ 를 빌드 컨텍스트로 복사 중...{NC}")
    shared_src = PROJECT_ROOT / "agents" / "supervisor" / "shared"
    shared_dst = SCRIPT_DIR / "shared"
    if shared_dst.exists():
        shutil.rmtree(shared_dst)
    shutil.copytree(shared_src, shared_dst, ignore=shutil.ignore_patterns("__pycache__"))
    print(f"{GREEN}  ✅ supervisor/shared → runtime/shared/{NC}\n")


def load_subagent_arns() -> dict:
    """[2/6] sub-agent ARN cross-load — monitor_a2a + incident_a2a 의 runtime/.env."""
    print(f"{YELLOW}[2/6] sub-agent Runtime ARN cross-load 중...{NC}")
    arns = {}
    sources = [
        ("MONITOR_A2A_RUNTIME_ARN", PROJECT_ROOT / "agents" / "monitor_a2a" / "runtime" / ".env"),
        ("INCIDENT_A2A_RUNTIME_ARN", PROJECT_ROOT / "agents" / "incident_a2a" / "runtime" / ".env"),
    ]
    for key, env_path in sources:
        if not env_path.exists():
            print(f"{RED}❌ {env_path} 미발견 — 해당 sub-agent deploy 선행 필요{NC}")
            sys.exit(1)
        load_dotenv(env_path, override=False)            # cross-agent ARN 만 추가
        arn = os.environ.get(key)
        if not arn:
            print(f"{RED}❌ {key} 미설정 in {env_path}{NC}")
            sys.exit(1)
        arns[key] = arn
        print(f"  ✅ {key} = {arn}")
    print()
    return arns


def configure_runtime():
    """[3/6] toolkit Runtime.configure(protocol="HTTP") — authorizer 미설정 = SigV4."""
    print(f"{YELLOW}[3/6] AgentCore Runtime 설정 중 (HTTP, SigV4 IAM inbound)...{NC}")
    try:
        from bedrock_agentcore_starter_toolkit import Runtime
    except ImportError:
        print(f"{RED}❌ bedrock-agentcore-starter-toolkit 미설치{NC}")
        sys.exit(1)

    runtime = Runtime()
    response = runtime.configure(
        agent_name=AGENT_NAME,
        entrypoint="agentcore_runtime.py",
        auto_create_execution_role=True,
        auto_create_ecr=True,
        requirements_file="requirements.txt",
        region=REGION,
        protocol="HTTP",
        # authorizer_configuration 미설정 — Operator CLI 가 SigV4 (Phase 4 패턴)
        non_interactive=True,
    )
    print(f"{GREEN}✅ 설정 완료 (Protocol: HTTP, Auth: SigV4 IAM){NC}\n")
    return runtime


def launch_runtime(runtime, subagent_arns: dict):
    """[4/6] Docker 빌드 → ECR push → Runtime 생성. sub-agent ARN env 주입."""
    print(f"{YELLOW}[4/6] Runtime 배포 중...{NC}")
    print(f"   ⏳ 첫 배포 ~5-10분, 업데이트 ~40초\n")

    env_vars = {
        # Phase 4 incident 와 동일 키 (단일 OAuth provider 명명).
        "OAUTH_PROVIDER_NAME": OAUTH_PROVIDER_NAME,
        "COGNITO_GATEWAY_SCOPE": os.environ["COGNITO_GATEWAY_SCOPE"],
        "SUPERVISOR_MODEL_ID": os.environ.get(
            "SUPERVISOR_MODEL_ID", "global.anthropic.claude-sonnet-4-6"
        ),
        "MONITOR_A2A_RUNTIME_ARN": subagent_arns["MONITOR_A2A_RUNTIME_ARN"],
        "INCIDENT_A2A_RUNTIME_ARN": subagent_arns["INCIDENT_A2A_RUNTIME_ARN"],
        "OTEL_RESOURCE_ATTRIBUTES": f"service.name={AGENT_NAME}",
        "AGENT_OBSERVABILITY_ENABLED": "true",
        "DEMO_USER": DEMO_USER,
    }

    start_time = datetime.now()
    result = runtime.launch(env_vars=env_vars, auto_update_on_conflict=True)
    elapsed = (datetime.now() - start_time).total_seconds()

    print(f"\n{GREEN}✅ 배포 완료 ({elapsed:.0f}초){NC}")
    print(f"   Runtime ARN: {result.agent_arn}\n")
    return result


def attach_extras_and_oauth_provider(launch_result) -> None:
    """[5/6] IAM + OAuth provider — Phase 2 Client C 재사용 (sub-agent A2A 호출용)."""
    print(f"{YELLOW}[5/6] IAM + OAuth provider (Phase 2 Client C 재사용) 부착...{NC}")

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
        PolicyName="Phase6aSupervisorRuntimeExtras",
        PolicyDocument=json.dumps(extras_policy),
    )
    print(f"{GREEN}✅ IAM inline policy 부착: {role_name}/Phase6aSupervisorRuntimeExtras{NC}")

    user_pool_id = os.environ["COGNITO_USER_POOL_ID"]
    domain = os.environ["COGNITO_DOMAIN"]
    try:
        agentcore_control.create_oauth2_credential_provider(
            name=OAUTH_PROVIDER_NAME,
            credentialProviderVendor="CustomOauth2",
            oauth2ProviderConfigInput={
                "customOauth2ProviderConfig": {
                    # Phase 2 Client C 재사용 (Phase 4 incident provider 와 동일).
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
        print(f"{GREEN}✅ OAuth Provider 생성 (Phase 2 Client C 재사용): {OAUTH_PROVIDER_NAME}{NC}\n")
    except ClientError as e:
        code = e.response["Error"]["Code"]
        message = e.response["Error"].get("Message", "")
        if code == "ConflictException" or (code == "ValidationException" and "already exists" in message):
            print(f"   (OAuth Provider 이미 존재 — skip)\n")
        else:
            raise


def wait_until_ready(launch_result) -> None:
    """[6/6 의 일부] Runtime READY 대기 (max 10분)."""
    print(f"{YELLOW}[6/6] Runtime READY 상태 대기 중 (최대 10분)...{NC}")
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
    """[6/6 의 일부] runtime/.env 저장."""
    print(f"{YELLOW}[6/6] runtime/.env 저장 중...{NC}")
    env_file = SCRIPT_DIR / ".env"
    if env_file.exists():
        with open(env_file, "r") as f:
            lines = [
                line for line in f.readlines()
                if not line.startswith(("RUNTIME_ARN=", "RUNTIME_ID=", "RUNTIME_NAME=",
                                       "OAUTH_PROVIDER_NAME=", "SUPERVISOR_RUNTIME_ARN="))
                and not line.strip().startswith("# Phase 6a Runtime")
            ]
    else:
        lines = []

    lines.append(f"\n# Phase 6a Runtime ({datetime.now().strftime('%Y-%m-%d')})\n")
    lines.append(f"RUNTIME_NAME={AGENT_NAME}\n")
    lines.append(f"RUNTIME_ARN={launch_result.agent_arn}\n")
    lines.append(f"RUNTIME_ID={launch_result.agent_id}\n")
    lines.append(f"OAUTH_PROVIDER_NAME={OAUTH_PROVIDER_NAME}\n")
    lines.append(f"SUPERVISOR_RUNTIME_ARN={launch_result.agent_arn}\n")

    with open(env_file, "w") as f:
        f.writelines(lines)
    print(f"{GREEN}✅ runtime/.env 저장 완료{NC}\n")


def print_summary(launch_result) -> None:
    """배포 완료 metadata + 다음 단계 안내."""
    print(f"{BLUE}{'=' * 60}{NC}")
    print(f"{GREEN}  배포 완료!{NC}")
    print(f"{BLUE}{'=' * 60}{NC}")
    print(f"   Runtime 이름:        {AGENT_NAME}")
    print(f"   Runtime ARN:         {launch_result.agent_arn}")
    print(f"   OAuth Provider:      {OAUTH_PROVIDER_NAME}  (Phase 2 Client C 재사용)")
    print(f"   Inbound:             HTTP, SigV4 IAM (Operator CLI 가 boto3 호출)")
    print(f"   Outbound:            A2A → 2 sub-agents (Client C M2M Bearer)")
    print()
    print(f"   다음 단계:")
    print(f"   1. Supervisor 단독 invoke (admin SIGV4 디버깅):")
    print(f"      uv run agents/supervisor/runtime/invoke_runtime.py --query \"현재 상황 진단해줘\"")
    print(f"   2. End-to-end (Operator 호출):")
    print(f"      uv run agents/supervisor/runtime/invoke_runtime.py --query \"...\"")
    print()


def main() -> None:
    print(f"\n{BLUE}{'=' * 60}{NC}")
    print(f"{BLUE}  Phase 6a — Supervisor Agent AgentCore Runtime 배포{NC}")
    print(f"{BLUE}{'=' * 60}{NC}\n")

    copy_shared_into_build_context()
    subagent_arns = load_subagent_arns()
    runtime = configure_runtime()
    launch_result = launch_runtime(runtime, subagent_arns)
    attach_extras_and_oauth_provider(launch_result)
    wait_until_ready(launch_result)
    save_runtime_metadata(launch_result)
    print_summary(launch_result)


if __name__ == "__main__":
    main()
