"""
Simple end-to-end test for AWS Agent Registry (AgentCore, preview).

Flow:
  1. create a registry
  2. publish an MCP server record
  3. submit it for approval and approve it
  4. search the registry
  5. clean up

Prereqs:
  pip install boto3
  AWS creds with bedrock-agentcore + bedrock-agentcore-control permissions
  Region: one of us-east-1 / us-west-2 / ap-southeast-2 / ap-northeast-1 / eu-west-1
"""

import json
import time
import boto3

REGION = "us-east-1"
REGISTRY_NAME = "demo-registry"
RECORD_NAME = "weather-mcp-server"

control = boto3.client("bedrock-agentcore-control", region_name=REGION)
data = boto3.client("bedrock-agentcore", region_name=REGION)


def _id_from_arn(arn: str) -> str:
    # arn:...:registry/<id>  or  arn:...:registry/<rid>/record/<recordid>
    return arn.rsplit("/", 1)[-1]


def _wait_registry_ready(registry_id: str, timeout: int = 120) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = control.get_registry(registryId=registry_id)
        status = resp.get("status")
        if status == "READY":
            print(f"[wait] registry READY")
            return
        if status in {"FAILED", "DELETING"}:
            raise RuntimeError(f"registry entered terminal status: {status}")
        time.sleep(3)
    raise TimeoutError("registry did not become READY in time")


def _wait_record_status(registry_id: str, record_id: str, target: set[str], timeout: int = 120) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = control.get_registry_record(registryId=registry_id, recordId=record_id)
        status = resp.get("status")
        if status in target:
            print(f"[wait] record status={status}")
            return status
        if status in {"FAILED", "DELETING"}:
            raise RuntimeError(f"record entered terminal status: {status}")
        time.sleep(3)
    raise TimeoutError(f"record did not reach {target} in time")


def create_registry() -> tuple[str, str]:
    resp = control.create_registry(
        name=REGISTRY_NAME,
        description="Demo registry for testing",
    )
    arn = resp["registryArn"]
    print(f"[create_registry] arn={arn}")
    return _id_from_arn(arn), arn


def publish_record(registry_id: str) -> str:
    server_content = json.dumps({
        "name": "io.example/weather-server",
        "description": "A weather MCP server",
        "version": "1.0.0",
    })
    tools_content = json.dumps({
        "tools": [{
            "name": "get_weather",
            "description": "Get the current weather for a location",
            "inputSchema": {
                "type": "object",
                "properties": {"location": {"type": "string"}},
                "required": ["location"],
            },
        }]
    })

    resp = control.create_registry_record(
        registryId=registry_id,
        name=RECORD_NAME,
        descriptorType="MCP",
        descriptors={
            "mcp": {
                "server": {
                    "schemaVersion": "2025-12-11",
                    "inlineContent": server_content,
                },
                "tools": {
                    "protocolVersion": "2024-11-05",
                    "inlineContent": tools_content,
                },
            }
        },
        recordVersion="1.0",
        description="Weather lookup tool exposed via MCP",
    )
    arn = resp["recordArn"]
    print(f"[create_registry_record] arn={arn} status={resp['status']}")
    return _id_from_arn(arn)


def approve(registry_id: str, record_id: str) -> None:
    control.submit_registry_record_for_approval(
        registryId=registry_id, recordId=record_id
    )
    resp = control.update_registry_record_status(
        registryId=registry_id,
        recordId=record_id,
        status="APPROVED",
        statusReason="Approved for demo",
    )
    print(f"[approve] status={resp['status']}")


def search(registry_arn: str, query: str = "weather") -> None:
    resp = data.search_registry_records(
        registryIds=[registry_arn],
        searchQuery=query,
        maxResults=10,
    )
    hits = resp.get("registryRecords", [])
    print(f"[search] query='{query}' hits={len(hits)}")
    for r in hits:
        print(f"  - {r['name']} ({r['descriptorType']}) v{r.get('version')} [{r['status']}]")


def cleanup(registry_id: str, record_id: str) -> None:
    control.delete_registry_record(registryId=registry_id, recordId=record_id)
    control.delete_registry(registryId=registry_id)
    print("[cleanup] done")


if __name__ == "__main__":
    registry_id, registry_arn = create_registry()
    _wait_registry_ready(registry_id)

    record_id = publish_record(registry_id)
    _wait_record_status(registry_id, record_id, {"DRAFT", "PENDING_APPROVAL", "APPROVED"})

    approve(registry_id, record_id)
    _wait_record_status(registry_id, record_id, {"APPROVED"})

    # Indexing for semantic search is async — give it a few seconds.
    time.sleep(10)
    search(registry_arn, "weather forecast tool")

    cleanup(registry_id, record_id)
