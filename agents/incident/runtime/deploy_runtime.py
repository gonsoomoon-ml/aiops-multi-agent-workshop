#!/usr/bin/env python3
"""
deploy_runtime.py — Phase 4 Incident Agent AgentCore Runtime 배포

Phase 3 monitor `deploy_runtime.py` 와 동일 5-step 흐름. 차이점:
  - agent_name = ``aiops_demo_${DEMO_USER}_incident``
  - Build context 에 monitor/shared + incident/shared 모두 copy (phase4.md §3-6 Option A)
  - IAM inline policy 이름: ``IncidentRuntimeExtras``

사용법:
    uv run agents/incident/runtime/deploy_runtime.py

사전 조건:
    - Phase 2 + Phase 3 deploy 완료 (Cognito stack + Gateway + Monitor Runtime alive)
    - AWS 자격 증명 + Docker daemon
    - bedrock-agentcore-starter-toolkit 설치 (pyproject.toml)
    - repo root .env 에 GATEWAY_URL / COGNITO_* 채워진 상태

수행 단계:
    1. monitor/shared + incident/shared + _shared_debug 를 빌드 컨텍스트로 복사
    2. Runtime.configure (Dockerfile / ECR / IAM Role 자동)
    3. Runtime.launch (Docker 빌드 → ECR push → Runtime 생성, AWS_REGION / DEBUG / STORAGE_BACKEND 등 env_vars forward)
    4. IAM ``IncidentRuntimeExtras`` + OAuth2CredentialProvider 부착
    5. READY 대기 + INCIDENT_RUNTIME_{NAME,ARN,ID} / OAUTH_PROVIDER_NAME 을 repo root .env 에 저장

reference:
    - phase3.md §4 (5단계 흐름)
    - phase4.md §3 (Incident Agent 상세)
    - phase4.md §3-6 (Build context Option A)
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
AGENT_NAME = f"aiops_demo_{DEMO_USER}_incident"
OAUTH_PROVIDER_NAME = f"{AGENT_NAME}_gateway_provider"


def copy_shared_into_build_context() -> None:
    """[1/5] monitor/shared + incident/shared + _shared_debug 를 build context 로 복사.

    컨테이너 layout (`/app/`):
      shared/             ← monitor/shared (auth_local, mcp_client, env_utils, modes)
      incident_shared/    ← incident/shared (agent.py + prompts/)
      _shared_debug/      ← repo root _shared_debug (FlowHook + dump_stream_event for DEBUG=1)

    phase4_design_pivots.md (memory) + phase4.md §3-6 (Option A) 참조.
    """
    print(f"{YELLOW}[1/5] shared/ × 2 + _shared_debug/ 를 빌드 컨텍스트로 복사 중...{NC}")

    for src, dst, label in [
        (PROJECT_ROOT / "agents" / "monitor" / "shared", SCRIPT_DIR / "shared", "monitor helper"),
        (PROJECT_ROOT / "agents" / "incident" / "shared", SCRIPT_DIR / "incident_shared", "incident truth"),
        (PROJECT_ROOT / "_shared_debug", SCRIPT_DIR / "_shared_debug", "debug helpers"),
    ]:
        if not src.exists():
            print(f"{RED}❌ {src.name}/ 미발견: {src}{NC}")
            sys.exit(1)
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        print(f"{GREEN}  ✅ {src.relative_to(PROJECT_ROOT)} → "
              f"{dst.relative_to(PROJECT_ROOT)} ({label}){NC}")
    print()


def configure_runtime():
    """[2/5] toolkit Runtime.configure() — Dockerfile / ECR / IAM 자동 생성."""
    print(f"{YELLOW}[2/5] AgentCore Runtime 설정 중...{NC}")
    try:
        from bedrock_agentcore_starter_toolkit import Runtime
    except ImportError:
        print(f"{RED}❌ bedrock-agentcore-starter-toolkit 미설치 — uv sync 필요{NC}")
        sys.exit(1)

    runtime = Runtime()
    response = runtime.configure(
        agent_name=AGENT_NAME,
        entrypoint="agentcore_runtime.py",
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
    """[3/5] Docker 빌드 → ECR push → Runtime 생성 (~5-10분, update ~40초)."""
    print(f"{YELLOW}[3/5] Runtime 배포 중 (Docker 빌드 → ECR 푸시 → 생성)...{NC}")
    print(f"   ⏳ 첫 배포 ~5-10분, 업데이트 ~40초")

    debug_val = os.environ.get("DEBUG", "")
    if debug_val:
        print(f"   {GREEN}ℹ DEBUG={debug_val} 활성 — container 에 forward (FlowHook + TTFT + trace 출력){NC}")
        print(f"     로그 확인: aws logs tail /aws/bedrock-agentcore/runtimes/<INCIDENT_RUNTIME_ID>-DEFAULT --follow --region {REGION}")
    else:
        print(f"   {YELLOW}ℹ DEBUG 비활성 — trace 미출력. 활성화하려면 'DEBUG=1 uv run …' 재배포{NC}")
    print()

    env_vars = {
        "AWS_REGION": REGION,
        "AWS_DEFAULT_REGION": REGION,
        "GATEWAY_URL": os.environ["GATEWAY_URL"],
        "OAUTH_PROVIDER_NAME": OAUTH_PROVIDER_NAME,
        "COGNITO_GATEWAY_SCOPE": os.environ["COGNITO_GATEWAY_SCOPE"],
        "INCIDENT_MODEL_ID": os.environ.get(
            "INCIDENT_MODEL_ID", "global.anthropic.claude-sonnet-4-6"
        ),
        "OTEL_RESOURCE_ATTRIBUTES": f"service.name={AGENT_NAME}",
        "AGENT_OBSERVABILITY_ENABLED": "true",
        "DEMO_USER": DEMO_USER,
        "STORAGE_BACKEND": os.environ.get("STORAGE_BACKEND", "s3"),  # s3 / github
        # 호스트 DEBUG 값 그대로 forward — 미설정/empty 면 container 에서도 off
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
    """[4/5] Phase 4 IAM inline policy + OAuth2CredentialProvider 부착.

    - IAM ``IncidentRuntimeExtras``: GetResourceOauth2Token + Cognito secret read
    - OAuth2CredentialProvider: Phase 3 와 동일 패턴 — Cognito Client M2M.
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
                    f"arn:aws:secretsmanager:{REGION}:{account_id}:secret:bedrock-agentcore-identity!*",
                ],
            },
        ],
    }
    iam.put_role_policy(
        RoleName=role_name,
        PolicyName="IncidentRuntimeExtras",
        PolicyDocument=json.dumps(extras_policy),
    )
    print(f"{GREEN}✅ IAM inline policy 부착: {role_name}/IncidentRuntimeExtras{NC}")

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
    """[5/5 의 일부] Runtime metadata 를 ``repo root .env`` 에 저장 (INCIDENT_ prefix).

    Phase 3 monitor (MONITOR_ prefix) 와 namespace 분리. Phase 5 의 supervisor / a2a
    runtimes 와도 prefix 충돌 없도록. ``.env.example`` 의 Phase 3+ AgentCore Runtimes
    섹션에 schema 미리 노출됨.

    이전 dual-key 패턴 (`RUNTIME_ARN` generic + `INCIDENT_RUNTIME_ARN` cross-agent) 은
    single .env 통합 시 generic key 가 monitor 와 충돌 → `INCIDENT_RUNTIME_ARN` 단일
    사용 (self invoke + cross-agent caller 모두 동일 key read).
    """
    print(f"{YELLOW}[5/5] Runtime 정보를 repo root .env 에 저장 중...{NC}")

    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        with open(env_file, "r") as f:
            lines = [
                line for line in f.readlines()
                if not line.startswith("INCIDENT_RUNTIME_NAME=")
                and not line.startswith("INCIDENT_RUNTIME_ARN=")
                and not line.startswith("INCIDENT_RUNTIME_ID=")
                and not line.startswith("INCIDENT_OAUTH_PROVIDER_NAME=")
                and not line.strip().startswith("# Phase 4 — Incident Runtime")
            ]
    else:
        lines = []

    lines.append(f"\n# Phase 4 — Incident Runtime ({datetime.now().strftime('%Y-%m-%d')})\n")
    lines.append(f"INCIDENT_RUNTIME_NAME={AGENT_NAME}\n")
    lines.append(f"INCIDENT_RUNTIME_ARN={launch_result.agent_arn}\n")
    lines.append(f"INCIDENT_RUNTIME_ID={launch_result.agent_id}\n")
    lines.append(f"INCIDENT_OAUTH_PROVIDER_NAME={OAUTH_PROVIDER_NAME}\n")

    with open(env_file, "w") as f:
        f.writelines(lines)
    print(f"{GREEN}✅ repo root .env 갱신 완료 (INCIDENT_ prefix){NC}\n")


def print_summary(launch_result) -> None:
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
    print(f"   1. Incident 단독 invoke (P4-A2):")
    print(f"      uv run agents/incident/runtime/invoke_runtime.py --alarm payment-{DEMO_USER}-status-check")
    print(f"   2. Sequential CLI (P4-A3 + A4 — Step D 구현 후):")
    print(f"      uv run agents/monitor/runtime/invoke_runtime.py --mode live --sequential")
    print(f"   3. 로그 확인:")
    print(f"      aws logs tail /aws/bedrock-agentcore/runtimes/{AGENT_NAME} --follow")
    print(f"   4. 자원 정리 (P4-A5):")
    print(f"      bash agents/incident/runtime/teardown.sh")
    print()


def main() -> None:
    print(f"\n{BLUE}{'=' * 60}{NC}")
    print(f"{BLUE}  Phase 4 — Incident Agent AgentCore Runtime 배포{NC}")
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
