#!/usr/bin/env python3
"""
deploy_runtime.py — Phase 5 Monitor A2A AgentCore Runtime 배포

Phase 4 ``agents/monitor/runtime/deploy_runtime.py`` 와 동일 5-step 흐름. 차이점:
  - **agent_name = ``aiops_${DEMO_USER}_monitor_a2a``** (Phase 4 monitor 와 별 Runtime, `_demo` 제거 — 60자 trace destination 한도)
  - **protocol="A2A"** + customJWTAuthorizer (allowedClients=[Cognito Client id] — Option X)
  - Build context: **Phase 4 의 agents/monitor/shared 직접 재사용** (Option G — 2026-05-09).
    monitor_a2a/ 자체에 shared/ 없음, runtime/ 만 보유. 청중에게 "Phase 4 의 monitor 위에
    A2A wrap 만 추가" 메시지 명확.
  - IAM inline policy: ``MonitorA2aRuntimeExtras``

사용법:
    uv run agents/monitor_a2a/runtime/deploy_runtime.py

사전 조건:
    - Phase 0/2/3/4 deploy 완료 (Cognito + Gateway alive)
    - repo `.env` 에 GATEWAY_URL / COGNITO_USER_POOL_ID / COGNITO_DOMAIN /
      COGNITO_CLIENT_ID / COGNITO_CLIENT_SECRET (Phase 2 산출물 — Option X)

수행 단계:
    1. Phase 4 monitor/shared + _shared_debug → 빌드 컨텍스트 복사 (Option G + Phase 3/4 parity)
    2. Runtime.configure(protocol="A2A", authorizer_configuration=...)
    3. Runtime.launch (호스트 DEBUG env forward — '1' / 'true' 시 FlowHook 활성)
    4. IAM ``MonitorA2aRuntimeExtras`` + OAuth provider (Client M2M Gateway 호출용)
    5. READY 대기 + repo root .env 갱신 (MONITOR_A2A_ prefix — Phase 3/4 second-pass parity)
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

load_dotenv(PROJECT_ROOT / ".env", override=True)

GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
BLUE = "\033[0;34m"
RED = "\033[0;31m"
NC = "\033[0m"

DEMO_USER = os.environ["DEMO_USER"]
REGION = os.environ.get("AWS_REGION", "us-east-1")
AGENT_NAME = f"aiops_{DEMO_USER}_monitor_a2a"
OAUTH_PROVIDER_NAME = f"{AGENT_NAME}_gateway_provider"


def copy_shared_into_build_context() -> None:
    """[1/5] Phase 4 monitor/shared + _shared_debug 를 build context 로 복사 (Option G).

    monitor_a2a 자체에 shared/ 없음 — Phase 4 의 monitor/shared 가 single source of truth.
    ``_shared_debug/`` 도 sibling copy — Phase 4 shared/agent.py 가 ``FlowHook`` /
    ``dprint_box`` 차용 (transitive import, Phase 3/4 parity).
    """
    print(f"{YELLOW}[1/5] Phase 4 monitor/shared + _shared_debug 를 빌드 컨텍스트로 복사 중...{NC}")

    for src, dst, label in [
        (PROJECT_ROOT / "agents" / "monitor" / "shared", SCRIPT_DIR / "shared", "Phase 4 truth 직접 재사용"),
        (PROJECT_ROOT / "_shared_debug", SCRIPT_DIR / "_shared_debug", "DEBUG=1 시 FlowHook trace"),
    ]:
        if not src.exists():
            print(f"{RED}❌ {src.name}/ 미발견 — 사전 조건 확인 필요: {src}{NC}")
            sys.exit(1)
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))
        print(f"{GREEN}  ✅ {src.relative_to(PROJECT_ROOT)} → {dst.relative_to(PROJECT_ROOT)} ({label}){NC}")
    print()


def configure_runtime():
    """[2/5] toolkit Runtime.configure(protocol="A2A", authorizer_configuration=...)."""
    print(f"{YELLOW}[2/5] AgentCore Runtime 설정 중 (A2A protocol)...{NC}")
    try:
        from bedrock_agentcore_starter_toolkit import Runtime
    except ImportError:
        print(f"{RED}❌ bedrock-agentcore-starter-toolkit 미설치 — uv sync 필요{NC}")
        sys.exit(1)

    user_pool_id = os.environ["COGNITO_USER_POOL_ID"]
    # Option X — Phase 2 Client 재사용 (새 Cognito 자원 추가 0)
    client_id = os.environ["COGNITO_CLIENT_ID"]
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
                "allowedClients": [client_id],
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
    print(f"   AllowedClients: [{client_id}]  (Phase 2 Client 재사용)")
    print(f"   Dockerfile:  {response.dockerfile_path}\n")
    return runtime


def launch_runtime(runtime):
    """[3/5] Docker 빌드 → ECR push → Runtime 생성."""
    print(f"{YELLOW}[3/5] Runtime 배포 중 (Docker 빌드 → ECR 푸시 → 생성)...{NC}")
    print(f"   ⏳ 첫 배포 ~5-10분, 업데이트 ~40초")

    debug_val = os.environ.get("DEBUG", "")
    if debug_val:
        print(f"   {GREEN}ℹ DEBUG={debug_val} 활성 — container 에 forward (FlowHook trace 출력){NC}")
        print(f"     로그 확인: aws logs tail /aws/bedrock-agentcore/runtimes/<MONITOR_A2A_RUNTIME_ID>-DEFAULT --follow --region {REGION}")
    else:
        print(f"   {YELLOW}ℹ DEBUG 비활성 — trace 미출력. 활성화하려면 'DEBUG=1 uv run …' 재배포{NC}")
    print()

    env_vars = {
        # Dockerfile 에 region 미주입 — 호스트 REGION 을 컨테이너로 forward.
        "AWS_REGION": REGION,
        "AWS_DEFAULT_REGION": REGION,
        "GATEWAY_URL": os.environ["GATEWAY_URL"],
        "OAUTH_PROVIDER_NAME": OAUTH_PROVIDER_NAME,
        "COGNITO_GATEWAY_SCOPE": os.environ["COGNITO_GATEWAY_SCOPE"],
        "MONITOR_MODEL_ID": os.environ.get(
            "MONITOR_MODEL_ID", "global.anthropic.claude-sonnet-4-6"
        ),
        "OTEL_RESOURCE_ATTRIBUTES": f"service.name={AGENT_NAME}",
        "AGENT_OBSERVABILITY_ENABLED": "true",
        "DEMO_USER": DEMO_USER,
        # 호스트 DEBUG 값 그대로 forward — 미설정/empty 면 container 에서도 off
        "DEBUG": debug_val,
    }

    start_time = datetime.now()
    result = runtime.launch(env_vars=env_vars, auto_update_on_conflict=True)
    elapsed = (datetime.now() - start_time).total_seconds()

    print(f"\n{GREEN}✅ 배포 완료 ({elapsed:.0f}초){NC}")
    print(f"   Runtime ARN: {result.agent_arn}")
    print(f"   Runtime ID:  {result.agent_id}\n")
    return result


def attach_extras_and_oauth_provider(launch_result) -> None:
    """[4/5] IAM inline policy + OAuth provider (Gateway 호출용 Client M2M)."""
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
        PolicyName="MonitorA2aRuntimeExtras",
        PolicyDocument=json.dumps(extras_policy),
    )
    print(f"{GREEN}✅ IAM inline policy 부착: {role_name}/MonitorA2aRuntimeExtras{NC}")

    user_pool_id = os.environ["COGNITO_USER_POOL_ID"]
    domain = os.environ["COGNITO_DOMAIN"]
    try:
        agentcore_control.create_oauth2_credential_provider(
            name=OAUTH_PROVIDER_NAME,
            credentialProviderVendor="CustomOauth2",
            oauth2ProviderConfigInput={
                "customOauth2ProviderConfig": {
                    "clientId": os.environ["COGNITO_CLIENT_ID"],
                    "clientSecret": os.environ["COGNITO_CLIENT_SECRET"],
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
            print(f"   (OAuth Provider {OAUTH_PROVIDER_NAME} 이미 존재 — skip)\n")
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
    """[5/5 의 일부] Runtime metadata 를 ``repo root .env`` 에 저장 (MONITOR_A2A_ prefix).

    Phase 3/4 second-pass 와 동일 패턴 (single repo root .env, prefixed keys).
    Supervisor deploy 가 ``MONITOR_A2A_RUNTIME_ARN`` 을 root .env 에서 직접 read.
    """
    print(f"{YELLOW}[5/5] Runtime 정보를 repo root .env 에 저장 중...{NC}")

    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        with open(env_file, "r") as f:
            lines = [
                line for line in f.readlines()
                if not line.startswith(("MONITOR_A2A_RUNTIME_NAME=",
                                        "MONITOR_A2A_RUNTIME_ARN=",
                                        "MONITOR_A2A_RUNTIME_ID=",
                                        "MONITOR_A2A_OAUTH_PROVIDER_NAME="))
                and not line.strip().startswith("# Phase 5 — Monitor A2A Runtime")
            ]
    else:
        lines = []

    lines.append(f"\n# Phase 5 — Monitor A2A Runtime ({datetime.now().strftime('%Y-%m-%d')})\n")
    lines.append(f"MONITOR_A2A_RUNTIME_NAME={AGENT_NAME}\n")
    lines.append(f"MONITOR_A2A_RUNTIME_ARN={launch_result.agent_arn}\n")
    lines.append(f"MONITOR_A2A_RUNTIME_ID={launch_result.agent_id}\n")
    lines.append(f"MONITOR_A2A_OAUTH_PROVIDER_NAME={OAUTH_PROVIDER_NAME}\n")

    with open(env_file, "w") as f:
        f.writelines(lines)
    print(f"{GREEN}✅ repo root .env 갱신 완료 (MONITOR_A2A_ prefix){NC}\n")


def print_summary(launch_result) -> None:
    """배포 완료 metadata + 다음 단계 안내."""
    print(f"{BLUE}{'=' * 60}{NC}")
    print(f"{GREEN}  배포 완료!{NC}")
    print(f"{BLUE}{'=' * 60}{NC}")
    print(f"   Runtime 이름:      {AGENT_NAME}")
    print(f"   Runtime ARN:       {launch_result.agent_arn}")
    print(f"   OAuth Provider:    {OAUTH_PROVIDER_NAME}")
    print(f"   Protocol:          A2A (port 9000 root)")
    print(f"   Mode 지원:         live only (past mode 는 Phase 4 monitor 가 처리)")
    debug_val = os.environ.get("DEBUG", "")
    if debug_val:
        print(f"   DEBUG 모드:        {GREEN}ACTIVE{NC} (CloudWatch logs 에 FlowHook trace 출력)")
    else:
        print(f"   DEBUG 모드:        비활성 (trace 보려면 'DEBUG=1 uv run …' 재배포)")
    print()
    print(f"   다음 단계:")
    print(f"   1. Incident A2A Runtime 배포 (Supervisor 의 다른 sub-agent):")
    print(f"      uv run agents/incident_a2a/runtime/deploy_runtime.py")
    print(f"   2. Supervisor Runtime 배포 (sub-agent ARN cross-load 후 마지막):")
    print(f"      uv run agents/supervisor/runtime/deploy_runtime.py")
    print(f"   3. End-to-end smoke (Operator 호출):")
    print(f"      uv run agents/supervisor/runtime/invoke_runtime.py --query \"현재 상황 진단해줘\"")
    print(f"   4. 로그 확인:")
    print(f"      aws logs tail /aws/bedrock-agentcore/runtimes/{AGENT_NAME} --follow")
    print(f"   5. 자원 정리:")
    print(f"      bash agents/monitor_a2a/runtime/teardown.sh")
    print()


def main() -> None:
    print(f"\n{BLUE}{'=' * 60}{NC}")
    print(f"{BLUE}  Phase 5 — Monitor A2A AgentCore Runtime 배포{NC}")
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
