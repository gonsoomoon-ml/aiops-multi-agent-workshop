"""Register Lambda functions as AgentCore Gateway tool targets (Lab 2).

This script is a thin wrapper around boto3 `bedrock-agentcore-control` that:
  1. Creates (or reuses) a Gateway
  2. Creates tool targets pointing at the two Lambdas
  3. Prints the Gateway invocation endpoint so the Agent can consume it

Prerequisite:
  - The two Lambda functions `noise-alarm-cw-mock` and `noise-alarm-github`
    already deployed (see `scripts/deploy_lambdas.sh` — not included here; this
    is an exercise for the class). Each Lambda must bundle the `tools/` and
    `mock_data/` modules and have the right IAM role for logging.
  - AgentCore Gateway APIs enabled in the target region.

Usage:
  python -m gateway.register \
      --gateway-name noise-alarm-gateway \
      --cw-lambda-arn arn:aws:lambda:us-west-2:XXX:function:noise-alarm-cw-mock \
      --gh-lambda-arn arn:aws:lambda:us-west-2:XXX:function:noise-alarm-github

The exact control-plane API shape may evolve; refer to the bedrock-agentcore
starter toolkit docs if method names change. This module intentionally
fails fast with a clear error if the control client is unavailable.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_SCHEMA = Path(__file__).resolve().parent / "openapi_schema.json"


def _ctrl_client(region: str):
    import boto3

    try:
        return boto3.client("bedrock-agentcore-control", region_name=region)
    except Exception as exc:  # noqa: BLE001
        print(
            "error: bedrock-agentcore-control client unavailable. "
            "Ensure boto3 version supports AgentCore and the service is enabled "
            f"in region {region}. ({exc})",
            file=sys.stderr,
        )
        raise


def register(gateway_name: str, cw_lambda_arn: str, gh_lambda_arn: str, region: str) -> None:
    client = _ctrl_client(region)

    # Create gateway (idempotent via name lookup)
    print(f"→ ensuring gateway '{gateway_name}' exists in {region} ...")
    try:
        created = client.create_gateway(
            name=gateway_name,
            protocolType="MCP",
            description="Noise Alarm Agent tool gateway",
        )
        gateway_id = created["gatewayId"]
        print(f"   created gatewayId={gateway_id}")
    except client.exceptions.ConflictException:  # type: ignore[attr-defined]
        gateways = client.list_gateways()
        gateway_id = next(
            g["gatewayId"] for g in gateways.get("gateways", []) if g["name"] == gateway_name
        )
        print(f"   reusing gatewayId={gateway_id}")

    schema = json.loads(_SCHEMA.read_text(encoding="utf-8"))

    # CloudWatch target
    cw_target = {
        "mcp": {
            "lambda": {
                "lambdaArn": cw_lambda_arn,
                "toolSchema": {"inlinePayload": [_op for _op in _ops_for(schema, {"describe_alarms", "describe_alarm_history", "get_alarm_statistics"})]},
            }
        }
    }
    # GitHub target
    gh_target = {
        "mcp": {
            "lambda": {
                "lambdaArn": gh_lambda_arn,
                "toolSchema": {"inlinePayload": [_op for _op in _ops_for(schema, {"list_files", "get_file", "put_file"})]},
            }
        }
    }

    print("→ creating CloudWatch Lambda target ...")
    client.create_gateway_target(
        gatewayIdentifier=gateway_id,
        name="noise-alarm-cw-mock",
        credentialProviderConfigurations=[{"credentialProviderType": "GATEWAY_IAM_ROLE"}],
        targetConfiguration=cw_target,
    )
    print("→ creating GitHub Lambda target ...")
    client.create_gateway_target(
        gatewayIdentifier=gateway_id,
        name="noise-alarm-github",
        credentialProviderConfigurations=[{"credentialProviderType": "GATEWAY_IAM_ROLE"}],
        targetConfiguration=gh_target,
    )

    info = client.get_gateway(gatewayIdentifier=gateway_id)
    mcp_url = info.get("gatewayUrl") or info.get("mcpEndpoint")
    print()
    print("✓ Gateway ready")
    print(f"  gatewayId : {gateway_id}")
    print(f"  mcp url   : {mcp_url}")
    print()
    print("Export the URL for the Agent:")
    print(f"  export AGENTCORE_GATEWAY_URL='{mcp_url}'")


def _ops_for(schema: dict, op_ids: set[str]) -> list[dict]:
    ops: list[dict] = []
    for path, methods in schema.get("paths", {}).items():
        for _m, spec in methods.items():
            if spec.get("operationId") in op_ids:
                ops.append(
                    {
                        "name": spec["operationId"],
                        "description": spec.get("summary", ""),
                        "inputSchema": _extract_request_schema(spec),
                    }
                )
    return ops


def _extract_request_schema(spec: dict) -> dict:
    try:
        return spec["requestBody"]["content"]["application/json"]["schema"]
    except KeyError:
        return {"type": "object"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gateway-name", default="noise-alarm-gateway")
    parser.add_argument("--cw-lambda-arn", required=True)
    parser.add_argument("--gh-lambda-arn", required=True)
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "us-west-2"))
    args = parser.parse_args()
    register(args.gateway_name, args.cw_lambda_arn, args.gh_lambda_arn, args.region)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
