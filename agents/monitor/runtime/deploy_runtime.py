#!/usr/bin/env python3
"""
deploy_runtime.py — Phase 3 Monitor Agent AgentCore Runtime 배포

bedrock_agentcore_starter_toolkit 으로 Docker 빌드 + ECR 푸시 + Runtime 생성을 자동화하고,
Phase 3 추가 자원 (IAM inline policy, OAuth2CredentialProvider) 을 boto3 로 부착합니다.
첫 배포 ~5-10분, 이후 업데이트 ~40초.

사용법:
    uv run agents/monitor/runtime/deploy_runtime.py

사전 조건:
    - AWS 자격 증명 (aws configure 또는 AWS_PROFILE)
    - bedrock-agentcore-starter-toolkit 설치 (pyproject.toml dev dep)
    - Docker daemon 실행 중 (Runtime.launch 가 docker buildx 호출)
    - Phase 2 완료 — repo root .env 에 GATEWAY_URL / COGNITO_* 채워진 상태

수행 단계:
    1. agents/monitor/shared/ 를 빌드 컨텍스트(runtime/shared/)로 복사
    2. Runtime 설정 (Dockerfile, ECR 저장소, IAM 실행 역할 자동 생성)
    3. Runtime 배포 (Docker 빌드 → ECR 푸시 → AgentCore Runtime 생성)
    4. 추가 권한 부착 + OAuth2CredentialProvider 생성
    5. READY 상태 대기 (10s × 60 = 최대 10분)
    6. MONITOR_RUNTIME_NAME / _ARN / _ID / OAUTH_PROVIDER_NAME 을 repo root .env 에 저장

reference:
    - phase3.md §4 (5단계 흐름) + §5 (OAuth provider 매커니즘)
    - developer-briefing-agent/managed-agentcore/deploy.py (단일 main + 단계 marker 패턴)
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

# 빌드 컨텍스트 = runtime/ 디렉토리. dba 패턴 따라 chdir 로 cwd 고정.
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[2]
os.chdir(SCRIPT_DIR)

# Phase 2 가 채운 repo root .env 에서 carry-over 값 로드 (Cognito + Gateway)
load_dotenv(PROJECT_ROOT / ".env", override=True)

# 터미널 색상
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
BLUE = "\033[0;34m"
RED = "\033[0;31m"
NC = "\033[0m"

DEMO_USER = os.environ["DEMO_USER"]
REGION = os.environ.get("AWS_REGION", "us-east-1")
AGENT_NAME = f"aiops_{DEMO_USER}_monitor"                               # D3
OAUTH_PROVIDER_NAME = f"{AGENT_NAME}_gateway_provider"                  # D2


def copy_shared_into_build_context() -> None:
    """[1/5] Docker 빌드 컨텍스트(runtime/) 안으로 shared/ + _shared_debug/ 복사.

    빌드 컨텍스트 밖(``../shared``, ``../../../_shared_debug``) 참조 불가 → sibling 배치.
    container 안에선 ``/app/shared/`` + ``/app/_shared_debug/`` 로 import 가능 (cwd sys.path).
    """
    print(f"{YELLOW}[1/5] shared/ + _shared_debug/ 를 빌드 컨텍스트로 복사 중...{NC}")
    for src, dst in [
        (PROJECT_ROOT / "agents" / "monitor" / "shared", SCRIPT_DIR / "shared"),
        (PROJECT_ROOT / "_shared_debug", SCRIPT_DIR / "_shared_debug"),
    ]:
        if not src.exists():
            print(f"{RED}❌ {src.name}/ 를 찾을 수 없습니다: {src}{NC}")
            sys.exit(1)
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        print(f"{GREEN}✅ {src.relative_to(PROJECT_ROOT)} → "
              f"{dst.relative_to(PROJECT_ROOT)}{NC}")
    print()


def configure_runtime():
    """[2/5] toolkit Runtime.configure() 호출.

    Dockerfile / ECR 저장소 / IAM 실행 역할을 toolkit 이 자동 생성. 실제 빌드/푸시는 launch 단계.
    """
    print(f"{YELLOW}[2/5] AgentCore Runtime 설정 중...{NC}")
    try:
        from bedrock_agentcore_starter_toolkit import Runtime
    except ImportError:
        print(f"{RED}❌ bedrock-agentcore-starter-toolkit 가 설치되지 않았습니다{NC}")
        print(f"   uv sync (pyproject.toml 의 deps 확인)")
        sys.exit(1)

    runtime = Runtime()
    response = runtime.configure(
        agent_name=AGENT_NAME,
        entrypoint="agentcore_runtime.py",                              # D4
        auto_create_execution_role=True,
        auto_create_ecr=True,
        requirements_file="requirements.txt",
        region=REGION,
        non_interactive=True,
    )
    print(f"{GREEN}✅ 설정 완료{NC}")
    print(f"   Dockerfile: {response.dockerfile_path}")
    print(f"   Config:     {response.config_path}\n")
    return runtime


def launch_runtime(runtime):
    """[3/5] Docker 빌드 → ECR 푸시 → Runtime 생성 (~5-10분, update ~40초).

    Phase 2 가 채운 repo root .env 의 carry-over 값을 Runtime 환경변수로 전달.
    """
    print(f"{YELLOW}[3/5] Runtime 배포 중 (Docker 빌드 → ECR 푸시 → 생성)...{NC}")
    print(f"   ⏳ 첫 배포 ~5-10분, 업데이트 ~40초")

    debug_val = os.environ.get("DEBUG", "")
    if debug_val:
        print(f"   {GREEN}ℹ DEBUG={debug_val} 활성 — container 에 forward (FlowHook + TTFT + trace 출력){NC}")
        print(f"     로그 확인: aws logs tail /aws/bedrock-agentcore/runtimes/<MONITOR_RUNTIME_ID>-DEFAULT --follow --region {REGION}")
    else:
        print(f"   {YELLOW}ℹ DEBUG 비활성 — trace 미출력. 활성화하려면 'DEBUG=1 uv run …' 재배포{NC}")
    print()

    env_vars = {
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
        # 호스트 DEBUG 값 그대로 forward — 미설정/empty 면 container 에서도 off (is_debug() = False)
        "DEBUG": debug_val,
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
    """[4/5] toolkit 이 처리 안 하는 Phase 3 전용 자원/권한 부착.

    - IAM ``MonitorRuntimeExtras`` inline policy: GetResourceOauth2Token + Cognito secret read
    - ``OAuth2CredentialProvider``: Cognito Client 의 client_credentials 흐름 자동화 (D2)
    """
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
                    # OAuth provider 가 client_secret 을 SecretsManager 에 보관
                    f"arn:aws:secretsmanager:{REGION}:{account_id}:secret:bedrock-agentcore-identity!*",
                ],
            },
        ],
    }
    iam.put_role_policy(
        RoleName=role_name,
        PolicyName="MonitorRuntimeExtras",
        PolicyDocument=json.dumps(extras_policy),
    )
    print(f"{GREEN}✅ IAM inline policy 부착: {role_name}/MonitorRuntimeExtras{NC}")

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
        # 재배포 시나리오 — AWS 가 ConflictException 또는 "already exists" 메시지의
        # ValidationException 으로 회신. 둘 다 idempotent 처리.
        if code == "ConflictException" or (code == "ValidationException" and "already exists" in message):
            print(f"   (OAuth Provider {OAUTH_PROVIDER_NAME} 이미 존재 — 재배포 시나리오 skip)\n")
        else:
            raise


def wait_until_ready(launch_result) -> None:
    """[5/5 의 일부] Runtime 상태가 READY 가 될 때까지 polling (최대 10분).

    terminal state 도달 시 break. READY 외 상태로 종료되면 sys.exit(1).
    """
    print(f"{YELLOW}[5/5] Runtime READY 상태 대기 중 (최대 10분)...{NC}")

    agentcore_control = boto3.client("bedrock-agentcore-control", region_name=REGION)
    terminal_states = {"READY", "CREATE_FAILED", "DELETE_FAILED", "UPDATE_FAILED"}
    status = "CREATING"
    max_attempts = 60                                                   # 10s × 60 = 10분

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
    """[5/5 의 일부] Runtime metadata 를 ``repo root .env`` 에 저장 (MONITOR_ prefix).

    Phase 4/5 multi-agent 와 prefix 충돌 없도록 ``MONITOR_RUNTIME_*`` namespace.
    invoke_runtime.py / teardown.sh 가 같은 파일에서 read. `.env.example` 의
    `Phase 3+ AgentCore Runtimes` 섹션에 schema 미리 노출됨.
    """
    print(f"{YELLOW}[5/5] Runtime 정보를 repo root .env 에 저장 중...{NC}")

    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        with open(env_file, "r") as f:
            lines = [
                line for line in f.readlines()
                if not line.startswith("MONITOR_RUNTIME_NAME=")
                and not line.startswith("MONITOR_RUNTIME_ARN=")
                and not line.startswith("MONITOR_RUNTIME_ID=")
                and not line.startswith("MONITOR_OAUTH_PROVIDER_NAME=")
                and not line.strip().startswith("# Phase 3 — Monitor Runtime")
            ]
    else:
        lines = []

    lines.append(f"\n# Phase 3 — Monitor Runtime ({datetime.now().strftime('%Y-%m-%d')})\n")
    lines.append(f"MONITOR_RUNTIME_NAME={AGENT_NAME}\n")
    lines.append(f"MONITOR_RUNTIME_ARN={launch_result.agent_arn}\n")
    lines.append(f"MONITOR_RUNTIME_ID={launch_result.agent_id}\n")
    lines.append(f"MONITOR_OAUTH_PROVIDER_NAME={OAUTH_PROVIDER_NAME}\n")

    with open(env_file, "w") as f:
        f.writelines(lines)
    print(f"{GREEN}✅ repo root .env 갱신 완료 (MONITOR_ prefix){NC}\n")


def print_summary(launch_result) -> None:
    """배포 성공 시 사용자 다음 단계 안내."""
    print(f"{BLUE}{'=' * 60}{NC}")
    print(f"{GREEN}  배포 완료!{NC}")
    print(f"{BLUE}{'=' * 60}{NC}")
    print(f"   Runtime 이름:      {AGENT_NAME}")
    print(f"   Runtime ARN:       {launch_result.agent_arn}")
    print(f"   ECR URI:           {launch_result.ecr_uri}")
    print(f"   OAuth Provider:    {OAUTH_PROVIDER_NAME}")
    print(f"   리전:              {REGION}")
    debug_val = os.environ.get("DEBUG", "")
    if debug_val:
        print(f"   DEBUG 모드:        {GREEN}ACTIVE{NC} (CloudWatch logs 에 FlowHook trace 출력)")
    else:
        print(f"   DEBUG 모드:        비활성 (trace 보려면 'DEBUG=1 uv run …' 재배포)")
    print()
    print(f"   다음 단계:")
    print(f"   1. live mode 호출:  uv run agents/monitor/runtime/invoke_runtime.py --mode live")
    print(f"   2. past mode 호출:  uv run agents/monitor/runtime/invoke_runtime.py --mode past")
    print(f"   3. 로그 확인:       aws logs tail /aws/bedrock-agentcore/runtimes/{AGENT_NAME} --follow")
    print(f"   4. 자원 정리:       bash agents/monitor/runtime/teardown.sh")
    print()


def main() -> None:
    print(f"\n{BLUE}{'=' * 60}{NC}")
    print(f"{BLUE}  Phase 3 — Monitor Agent AgentCore Runtime 배포{NC}")
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
