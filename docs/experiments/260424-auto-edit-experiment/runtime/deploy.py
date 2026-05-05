"""Deploy the Rule Optimization Agent to AgentCore Runtime (Lab 3).

Wraps `bedrock_agentcore_starter_toolkit.Runtime` so the Lab 3 student runs:

    python -m runtime.deploy configure
    python -m runtime.deploy launch
    python -m runtime.deploy invoke "최근 1주 noise alarm 진단해줘"

The toolkit handles ECR push, container build, IAM role provisioning
(when `auto_create_execution_role=True`), and Runtime creation.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from bedrock_agentcore_starter_toolkit import Runtime

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENTRYPOINT = "runtime/agent_runtime.py"
_AGENT_NAME = "noise-alarm-agent"


def _rt() -> Runtime:
    return Runtime()


def cmd_configure(args: argparse.Namespace) -> int:
    rt = _rt()
    result = rt.configure(
        entrypoint=_ENTRYPOINT,
        agent_name=_AGENT_NAME,
        requirements_file="requirements.txt",
        region=args.region,
        protocol="HTTP",
        auto_create_execution_role=args.auto_role,
        auto_create_ecr=True,
        non_interactive=True,
    )
    print(json.dumps(result.to_dict() if hasattr(result, "to_dict") else result.__dict__, default=str, indent=2))
    return 0


def cmd_launch(args: argparse.Namespace) -> int:
    rt = _rt()
    env_vars = {
        "AWS_REGION": args.region,
        "BEDROCK_MODEL_ID": os.environ.get(
            "BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
        ),
        "OFFLINE_MODE": os.environ.get("OFFLINE_MODE", "0"),
        "GITHUB_TOKEN": os.environ.get("GITHUB_TOKEN", ""),
        "GITHUB_REPO": os.environ.get("GITHUB_REPO", ""),
        "GITHUB_BRANCH": os.environ.get("GITHUB_BRANCH", "main"),
    }
    result = rt.launch(env_vars=env_vars, auto_update_on_conflict=True)
    print(json.dumps(result.to_dict() if hasattr(result, "to_dict") else result.__dict__, default=str, indent=2))
    return 0


def cmd_invoke(args: argparse.Namespace) -> int:
    rt = _rt()
    out = rt.invoke({"prompt": args.prompt})
    print(json.dumps(out, default=str, indent=2, ensure_ascii=False))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    rt = _rt()
    out = rt.status()
    print(out if isinstance(out, str) else json.dumps(out, default=str, indent=2))
    return 0


def cmd_destroy(args: argparse.Namespace) -> int:
    rt = _rt()
    rt.destroy()
    print("destroyed")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="AgentCore Runtime deploy helper")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("configure", help="bake a deployment config into .bedrock_agentcore.yaml")
    p.add_argument("--region", default=os.environ.get("AWS_REGION", "us-west-2"))
    p.add_argument("--auto-role", action="store_true", help="auto-create execution role")
    p.set_defaults(func=cmd_configure)

    p = sub.add_parser("launch", help="build image, push to ECR, create the Runtime")
    p.add_argument("--region", default=os.environ.get("AWS_REGION", "us-west-2"))
    p.set_defaults(func=cmd_launch)

    p = sub.add_parser("invoke", help="invoke the deployed Runtime with a prompt")
    p.add_argument("prompt")
    p.set_defaults(func=cmd_invoke)

    p = sub.add_parser("status", help="show current Runtime status")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("destroy", help="tear down the Runtime")
    p.set_defaults(func=cmd_destroy)

    args = parser.parse_args()
    os.chdir(_PROJECT_ROOT)  # toolkit writes config files relative to cwd
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
