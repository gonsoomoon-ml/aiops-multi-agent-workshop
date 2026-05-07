"""agents/monitor/runtime/verify_c1.py — Phase 3 P3-A3 검증.

JSON schema diff 4 assertion × 3 runs = 12 check. local 응답 vs Runtime 응답을
schema-level 비교 — LLM 비결정성에 견고한 set/tolerance 비교 (D8).

reference: phase3.md §8-2 + §7-3 (P3-A3 acceptance 정의).
"""
import json
import re
import subprocess
import sys
from pathlib import Path

GREEN, RED, YELLOW, NC = "\033[0;32m", "\033[0;31m", "\033[1;33m", "\033[0m"

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[2]
PCT_TOLERANCE = 10
N_RUNS = 3


def extract_json(text: str) -> dict:
    """LLM 출력 (markdown / raw) 에서 final JSON 추출. 3단 fallback (§8-3)."""
    fence = re.search(r"```json\s*(\{[\s\S]*?\})\s*```", text)
    if fence:
        return json.loads(fence.group(1))
    fence = re.search(r"```\s*(\{[\s\S]*?\})\s*```", text)
    if fence:
        return json.loads(fence.group(1))
    raw = re.search(r'\{[\s\S]*"real_alarms"[\s\S]*\}', text)
    if raw:
        return json.loads(raw.group(0))
    raise ValueError(f"JSON 블록 추출 실패. 출력 일부: {text[:200]!r}")


def run_command(cmd: list[str]) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=PROJECT_ROOT, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f"명령 실패: {' '.join(cmd)}\nstderr: {result.stderr}")
    return result.stdout


def assert_schema_match(local: dict, runtime: dict, run_idx: int) -> list[bool]:
    results = []

    local_types = {d["type"] for d in local.get("diagnoses", [])}
    runtime_types = {d["type"] for d in runtime.get("diagnoses", [])}
    a31 = local_types == runtime_types
    print(f"  [run {run_idx}] A3.1 (diagnoses.type set):       "
          f"{GREEN if a31 else RED}{a31}{NC}  local={local_types} / runtime={runtime_types}")
    results.append(a31)

    local_alarms = {d["alarm"] for d in local.get("diagnoses", [])}
    runtime_alarms = {d["alarm"] for d in runtime.get("diagnoses", [])}
    a32 = local_alarms == runtime_alarms
    print(f"  [run {run_idx}] A3.2 (diagnoses.alarm set):      "
          f"{GREEN if a32 else RED}{a32}{NC}")
    results.append(a32)

    local_real = set(local.get("real_alarms", []))
    runtime_real = set(runtime.get("real_alarms", []))
    a33 = local_real == runtime_real
    print(f"  [run {run_idx}] A3.3 (real_alarms set):          "
          f"{GREEN if a33 else RED}{a33}{NC}")
    results.append(a33)

    local_pct = local.get("estimated_weekly_fire_reduction_pct", 0)
    runtime_pct = runtime.get("estimated_weekly_fire_reduction_pct", 0)
    a34 = abs(local_pct - runtime_pct) <= PCT_TOLERANCE
    print(f"  [run {run_idx}] A3.4 (pct ±{PCT_TOLERANCE}):                     "
          f"{GREEN if a34 else RED}{a34}{NC}  local={local_pct} / runtime={runtime_pct}")
    results.append(a34)

    return results


def main() -> None:
    print(f"{YELLOW}=== Phase 3 P3-A3 — JSON schema diff 4 × {N_RUNS} runs ==={NC}\n")

    all_results = []
    for i in range(1, N_RUNS + 1):
        print(f"{YELLOW}[run {i}/{N_RUNS}] capture local + runtime mode=past...{NC}")
        local_out = run_command(["uv", "run", "agents/monitor/local/run.py", "--mode", "past"])
        runtime_out = run_command(["uv", "run", "agents/monitor/runtime/invoke_runtime.py", "--mode", "past"])
        local_json = extract_json(local_out)
        runtime_json = extract_json(runtime_out)
        all_results.extend(assert_schema_match(local_json, runtime_json, i))
        print()

    n_pass = sum(all_results)
    n_total = len(all_results)
    if n_pass == n_total:
        print(f"{GREEN}=== ✅ P3-A3 PASS ({n_pass}/{n_total}) ==={NC}")
        sys.exit(0)
    print(f"{RED}=== ❌ P3-A3 FAIL ({n_pass}/{n_total}) ==={NC}")
    sys.exit(1)


if __name__ == "__main__":
    main()
