"""
Smoke test for AgentCore Managed Agent Harness (preview).

Flow:
  1. create a harness (Bedrock model + system prompt, no tools)
  2. wait for READY
  3. invoke it with a user message and stream the response
  4. delete the harness

Prereqs:
  - AWS creds with bedrock-agentcore + bedrock-agentcore-control permissions
  - Bedrock model access for the chosen modelId
  - An IAM execution role the harness can assume — set HARNESS_ROLE_ARN
    (trust policy: bedrock-agentcore.amazonaws.com; permissions: bedrock:InvokeModel*, etc.)
  - Region: one of us-east-1 / us-west-2 / ap-southeast-2 / eu-central-1

Run:
    uv sync
    HARNESS_ROLE_ARN=arn:aws:iam::<acct>:role/AgentCoreHarnessRole uv run main.py
"""

import os
import time
import uuid
import boto3

REGION = os.environ.get("AWS_REGION", "us-east-1")
HARNESS_NAME = "demo_harness"
MODEL_ID = os.environ.get("HARNESS_MODEL_ID", "global.anthropic.claude-sonnet-4-6")
ROLE_ARN = os.environ.get("HARNESS_ROLE_ARN")

if not ROLE_ARN:
    raise SystemExit(
        "HARNESS_ROLE_ARN is required. Create an IAM role with trust principal "
        "'bedrock-agentcore.amazonaws.com' and permission to invoke the model, "
        "then export HARNESS_ROLE_ARN=<arn> before running."
    )

control = boto3.client("bedrock-agentcore-control", region_name=REGION)
data = boto3.client("bedrock-agentcore", region_name=REGION)


def create_harness() -> tuple[str, str]:
    resp = control.create_harness(
        harnessName=HARNESS_NAME,
        executionRoleArn=ROLE_ARN,
        model={
            "bedrockModelConfig": {
                "modelId": MODEL_ID,
                "maxTokens": 1024,
                "temperature": 0.2,
            }
        },
        systemPrompt=[
            {"text": "You are a concise assistant. Reply in one short paragraph."}
        ],
        maxIterations=5,
        timeoutSeconds=120,
    )
    h = resp["harness"]
    print(f"[create_harness] arn={h['arn']} status={h['status']}")
    return h["harnessId"], h["arn"]


def wait_ready(harness_id: str, timeout: int = 300) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = control.get_harness(harnessId=harness_id)
        status = resp["harness"]["status"]
        if status == "READY":
            print("[wait] harness READY")
            return
        if status in {"FAILED", "DELETING"}:
            reason = resp["harness"].get("failureReason", "")
            raise RuntimeError(f"harness terminal status={status} reason={reason}")
        print(f"  ...status={status}")
        time.sleep(5)
    raise TimeoutError("harness did not become READY in time")


def invoke(harness_arn: str, prompt: str) -> None:
    session_id = f"demo-session-{uuid.uuid4().hex}"  # must be >= 33 chars
    print(f"[invoke] session={session_id} prompt={prompt!r}")
    resp = data.invoke_harness(
        harnessArn=harness_arn,
        runtimeSessionId=session_id,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
    )

    print("[stream]")
    for event in resp["stream"]:
        if delta := event.get("contentBlockDelta"):
            text = delta.get("delta", {}).get("text")
            if text:
                print(text, end="", flush=True)
        elif stop := event.get("messageStop"):
            print(f"\n[stop reason={stop.get('stopReason')}]")
        elif meta := event.get("metadata"):
            usage = meta.get("usage", {})
            metrics = meta.get("metrics", {})
            print(
                f"[usage in={usage.get('inputTokens')} "
                f"out={usage.get('outputTokens')} "
                f"latency={metrics.get('latencyMs')}ms]"
            )
        elif err := (event.get("internalServerException")
                     or event.get("validationException")
                     or event.get("runtimeClientError")):
            print(f"\n[error] {err}")


def cleanup(harness_id: str) -> None:
    control.delete_harness(harnessId=harness_id)
    print(f"[cleanup] delete requested for {harness_id}")


if __name__ == "__main__":
    harness_id, harness_arn = create_harness()
    try:
        wait_ready(harness_id)
        invoke(harness_arn, "What is 17 * 23? Show the answer only.")
    finally:
        cleanup(harness_id)
