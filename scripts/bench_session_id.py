#!/usr/bin/env python3
"""
bench_session_id.py — Phase 3 monitor agent 의 session-id A/B 통계 측정

워크샵 narrative 검증: AWS docs 는 `runtimeSessionId` 가 microVM routing 의 binding
key 라 명시 (https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-sessions.html).
N=1 single-shot 으로는 noise 가 커서 결론 약함 → N 회 반복 + percentile 통계.

시나리오:
  - A (warm path): 동일 session-id N 회 재사용. i=1 cold, i>=2 warm 기대
  - B (cold path): 매 invoke fresh session-id. docs 의도상 매번 microVM cold

집계:
  - ttft / total latency 각각 n / min / p50 / p95 / max / mean / stdev
  - cache_write_nonzero_ratio (Bedrock prompt cache miss 빈도)

실행 순서: B 먼저 → A 다음 (A 의 잔류 microVM 이 B 결과 오염 방지).

사용법:
    uv run scripts/bench_session_id.py --scenarios A,B --n 5 --mode live \\
        --query "현재 라이브 알람 분류해줘" --append-md

사전 조건:
    - Phase 3 monitor Runtime 배포 완료 (repo root .env 에 `MONITOR_RUNTIME_ARN`)
    - AWS 자격증명 + `bedrock-agentcore:InvokeAgentRuntime` 권한

reference:
    - docs/learn/phase5_detail.md §3 (본 스크립트가 자동 갱신하는 결과 섹션)
    - agents/monitor/runtime/invoke_runtime.py (subprocess 호출 대상)
"""
import argparse
import json
import os
import re
import statistics
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PHASE5_DETAIL = PROJECT_ROOT / "docs" / "learn" / "phase5_detail.md"

# agent 별 invoke 진입점 + 출력 format + phase5_detail.md 섹션 위치.
# monitor (Phase 3, 1 agent) — 출력에 TTFT + total 둘 다 inline
# supervisor (Phase 5, 3 agent A2A) — 출력에 total 만 inline (TTFT 는 DEBUG 시 dprint)
AGENT_CONFIG = {
    "monitor": {
        "invoke_path": PROJECT_ROOT / "agents" / "monitor" / "runtime" / "invoke_runtime.py",
        "use_mode_arg": True,
        "section_num": 3,
        "section_title_suffix": "Phase 3 single-agent 통계 측정",
        "phase_label": "Phase 3 monitor (single agent, no A2A hop)",
    },
    "supervisor": {
        "invoke_path": PROJECT_ROOT / "agents" / "supervisor" / "runtime" / "invoke_runtime.py",
        "use_mode_arg": False,
        "section_num": 4,
        "section_title_suffix": "Phase 5 multi-agent 통계 측정",
        "phase_label": "Phase 5 supervisor (3 agent, 2 A2A hops)",
    },
}

ANSI = re.compile(r"\x1b\[[0-9;]*m")
PAT_DONE_MONITOR = re.compile(r"완료\s*—\s*TTFT\s+([\d.]+)초\s*/\s*total\s+([\d.]+)초")
PAT_DONE_SUPERVISOR = re.compile(r"완료\s*\(([\d.]+)초\)")
PAT_TOKENS = re.compile(
    r"Tokens\s*—\s*Total:\s*([\d,]+)\s*\|\s*Input:\s*([\d,]+)\s*\|\s*"
    r"Output:\s*([\d,]+)\s*\|\s*Cache R/W:\s*([\d,]+)/([\d,]+)"
)

GREEN, YELLOW, BLUE, RED, DIM, NC = (
    "\033[0;32m", "\033[1;33m", "\033[0;34m", "\033[0;31m", "\033[2m", "\033[0m"
)


def parse_args() -> argparse.Namespace:
    """CLI 인자 — agent 선택 + 시나리오 + N + output 옵션."""
    p = argparse.ArgumentParser(description="session-id A/B 통계 측정 (monitor or supervisor)")
    p.add_argument("--agent", choices=["monitor", "supervisor"], default="monitor",
                   help="monitor (Phase 3, single) 또는 supervisor (Phase 5, 3-agent A2A)")
    p.add_argument("--scenarios", default="A,B", help="실행할 시나리오 (A,B 또는 A 또는 B)")
    p.add_argument("--n", type=int, default=5, help="시나리오당 invoke 반복 횟수 (default 5)")
    p.add_argument("--mode", choices=["live", "past"], default="live",
                   help="monitor mode (supervisor 에선 무시)")
    p.add_argument("--query", default=None, help="invoke query (agent 별 default 사용)")
    p.add_argument("--output", choices=["table", "json"], default="table", help="stdout 형식")
    p.add_argument("--append-md", action="store_true",
                   help=f"결과를 {PHASE5_DETAIL} 의 agent 별 섹션으로 append/replace")
    return p.parse_args()


def new_session_id() -> str:
    """`workshop-<uuid hex>` — 41자 (AgentCore 제약 ≥ 33자 충족)."""
    return f"workshop-{uuid.uuid4().hex}"


def parse_stdout(text: str, agent: str) -> dict:
    """invoke_runtime.py stdout 에서 timing + token 추출. agent 별 regex 분기.

    monitor: `완료 — TTFT X초 / total Y초` → ttft + total
    supervisor: `완료 (X초)` → total 만 (ttft 는 DEBUG=1 시에만 dprint, parse 대상 X)
    """
    clean = ANSI.sub("", text)
    t = PAT_TOKENS.search(clean)
    to_i = lambda s: int(s.replace(",", ""))
    if agent == "monitor":
        d = PAT_DONE_MONITOR.search(clean)
        if not d:
            raise RuntimeError(f"monitor invoke 실패 — '완료 — TTFT' 라인 미발견. tail:\n{clean[-500:]}")
        ttft, total = float(d.group(1)), float(d.group(2))
    else:  # supervisor
        d = PAT_DONE_SUPERVISOR.search(clean)
        if not d:
            raise RuntimeError(f"supervisor invoke 실패 — '완료 (X초)' 라인 미발견. tail:\n{clean[-500:]}")
        ttft, total = None, float(d.group(1))
    return {
        "ttft": ttft,
        "total": total,
        "total_tokens": to_i(t.group(1)) if t else 0,
        "input_tokens": to_i(t.group(2)) if t else 0,
        "output_tokens": to_i(t.group(3)) if t else 0,
        "cache_read": to_i(t.group(4)) if t else 0,
        "cache_write": to_i(t.group(5)) if t else 0,
    }


def run_iteration(agent: str, mode: str, query: str, session_id: str | None) -> dict:
    """1회 invoke + parse. session_id None 이면 --session-id 인자 생략. agent 별 CLI 차이 처리."""
    cfg = AGENT_CONFIG[agent]
    cmd = ["uv", "run", str(cfg["invoke_path"])]
    if cfg["use_mode_arg"]:
        cmd += ["--mode", mode]
    cmd += ["--query", query]
    if session_id:
        cmd += ["--session-id", session_id]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=PROJECT_ROOT)
    if proc.returncode != 0:
        raise RuntimeError(f"{agent} invoke 실패 (rc={proc.returncode}):\n{proc.stderr[-500:]}")
    record = parse_stdout(proc.stdout, agent)
    record["session_id"] = session_id or "(auto-gen)"
    return record


def run_scenario(name: str, n: int, agent: str, mode: str, query: str, mk_sid) -> list[dict]:
    """N 회 반복 — mk_sid() 가 매 iteration session-id 결정."""
    print(f"{BLUE}=== Scenario {name} — agent={agent} N={n} ==={NC}", file=sys.stderr)
    records = []
    for i in range(1, n + 1):
        sid = mk_sid()
        sid_label = sid[:30] + "..." if sid and len(sid) > 33 else (sid or "(none)")
        print(f"{DIM}  [{i}/{n}] session_id={sid_label} → invoke 중...{NC}",
              file=sys.stderr, end="", flush=True)
        try:
            r = run_iteration(agent, mode, query, sid)
        except Exception as e:
            print(f" {RED}❌ {e}{NC}", file=sys.stderr)
            raise
        r["i"] = i
        r["scenario"] = name
        records.append(r)
        ttft_str = f"ttft={r['ttft']:.1f}s " if r["ttft"] is not None else ""
        print(
            f" {GREEN}{ttft_str}total={r['total']:.1f}s "
            f"cache_R/W={r['cache_read']:,}/{r['cache_write']:,}{NC}",
            file=sys.stderr,
        )
    return records


def _pct(values: list[float], p: float) -> float:
    """p (0~100) percentile — N<2 시 max 반환."""
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    # statistics.quantiles N>=2 필요. 단순 sorted indexing 으로 통일.
    s = sorted(values)
    k = (len(s) - 1) * (p / 100)
    f, c = int(k), min(int(k) + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)


def summarize(records: list[dict]) -> dict:
    """ttft + total 각각 통계 산출 + cache_write 비율. ttft 가 None 인 record (supervisor) 는 ttft stats 생략."""
    if not records:
        return {}
    totals = [r["total"] for r in records]
    ttfts = [r["ttft"] for r in records if r["ttft"] is not None]
    cw_nonzero = sum(1 for r in records if r["cache_write"] > 0)

    def stats(vs: list[float]) -> dict:
        if not vs:
            return None
        return {
            "n": len(vs),
            "min": min(vs),
            "p50": _pct(vs, 50),
            "p95": _pct(vs, 95),
            "max": max(vs),
            "mean": statistics.mean(vs),
            "stdev": statistics.stdev(vs) if len(vs) >= 2 else 0.0,
        }

    return {
        "ttft": stats(ttfts),  # None for supervisor (no inline TTFT)
        "total": stats(totals),
        "cache_write_nonzero_ratio": cw_nonzero / len(records),
        "tokens_total_p50": _pct([r["total_tokens"] for r in records], 50),
        "cache_read_p50": _pct([r["cache_read"] for r in records], 50),
    }


def format_table(meta: dict, summaries: dict, records_by_scen: dict) -> str:
    """ASCII 표 — stdout 용. ttft/total/cache_write_ratio 시나리오별 비교."""
    lines = []
    lines.append(f"\n{BLUE}{'=' * 70}{NC}")
    lines.append(f"  {meta['phase_label']} — session-id A/B bench")
    lines.append(f"  region={meta['region']} demo_user={meta['demo_user']} mode={meta['mode']}")
    lines.append(f"  N={meta['n']}  started={meta['started_at']}")
    lines.append(f"{BLUE}{'=' * 70}{NC}\n")

    # 통계 비교 표
    header = f"{'metric':<28}" + "".join(f"{s:>16}" for s in summaries.keys())
    lines.append(header)
    lines.append("-" * len(header))
    metric_rows = [
        ("total.p50", "total p50 (s)"),
        ("total.p95", "total p95 (s)"),
        ("total.min", "total min (s)"),
        ("total.max", "total max (s)"),
        ("total.mean", "total mean (s)"),
        ("total.stdev", "total stdev (s)"),
        ("ttft.p50", "ttft p50 (s)"),
        ("ttft.p95", "ttft p95 (s)"),
        ("cache_write_nonzero_ratio", "cache W>0 비율"),
    ]
    for metric_key, label in metric_rows:
        row = f"{label:<28}"
        for sname, summ in summaries.items():
            if "." in metric_key:
                top, sub = metric_key.split(".")
                stats_dict = summ.get(top)
                v = stats_dict[sub] if stats_dict else None
            else:
                v = summ.get(metric_key)
            if v is None:
                row += f"{'N/A':>16}"
            elif isinstance(v, float):
                row += f"{v:>16.2f}"
            else:
                row += f"{v:>16}"
        lines.append(row)

    # raw records (시나리오별)
    lines.append("")
    for sname, recs in records_by_scen.items():
        lines.append(f"{YELLOW}[{sname}] raw invokes:{NC}")
        lines.append(f"  {'i':>3} {'ttft':>6} {'total':>7} {'cache_R':>10} {'cache_W':>10}  session_id")
        for r in recs:
            sid = r["session_id"]
            sid_label = sid[:24] + "..." if len(sid) > 27 else sid
            ttft_str = f"{r['ttft']:>6.2f}" if r["ttft"] is not None else f"{'N/A':>6}"
            lines.append(
                f"  {r['i']:>3} {ttft_str} {r['total']:>7.2f} "
                f"{r['cache_read']:>10,} {r['cache_write']:>10,}  {sid_label}"
            )
        lines.append("")

    return "\n".join(lines)


def format_md(meta: dict, summaries: dict, records_by_scen: dict) -> str:
    """phase5_detail.md 의 agent 별 섹션 append 용 markdown. 한국어 prose + 영어 식별자."""
    lines = []
    lines.append(f"## {meta['section_num']}. Session-Id 효과 — {meta['section_title_suffix']}")
    lines.append("")
    isolation_note = (
        "단일 agent (Phase 3 monitor) 에서 session-id 의 latency 효과를 측정 — A2A 다중 hop 변수를 제거하고 cold-start 효과만 isolation."
        if meta["agent"] == "monitor"
        else "3 agent (Supervisor + Monitor A2A + Incident A2A) Phase 5 구성에서 session-id 의 누적 latency 효과를 측정 — 다중 microVM cold-start 효과 관측."
    )
    lines.append(
        f"`scripts/bench_session_id.py --agent {meta['agent']}` 가 자동 갱신하는 섹션. "
        f"N={meta['n']} 회 반복 측정한 결과. {isolation_note}"
    )
    lines.append("")
    lines.append(
        f"**측정 환경**: region `{meta['region']}` · DEMO_USER `{meta['demo_user']}` · "
        f"mode `{meta['mode']}` · started `{meta['started_at']}` · query `{meta['query']}`"
    )
    lines.append("")
    lines.append("### 시나리오 정의")
    lines.append("")
    lines.append("| 시나리오 | session-id 전략 | 기대 |")
    lines.append("|---|---|---|")
    lines.append(
        "| **A — warm path** | 단일 session-id N 회 재사용 | i=1 cold, i>=2 warm "
        "(docs: 동일 session-id → 동일 microVM) |"
    )
    lines.append(
        "| **B — cold path** | 매 invoke `workshop-<uuid>` 새로 생성 | docs 의도상 매번 cold microVM. "
        "실제는 pool 재사용 가능성 (docs `may` hedging) |"
    )
    lines.append("")
    lines.append("### 통계 비교 (latency = total invoke time, 초)")
    lines.append("")
    lines.append("| metric | " + " | ".join(summaries.keys()) + " |")
    lines.append("|---|" + "|".join(["---"] * len(summaries)) + "|")
    for metric_key, label in [
        ("total.p50", "total **p50**"),
        ("total.p95", "total p95"),
        ("total.min", "total min"),
        ("total.max", "total max"),
        ("total.mean", "total mean"),
        ("total.stdev", "total stdev"),
        ("ttft.p50", "ttft p50"),
        ("ttft.p95", "ttft p95"),
        ("cache_write_nonzero_ratio", "cache W>0 비율"),
    ]:
        row = f"| {label} |"
        for summ in summaries.values():
            if "." in metric_key:
                top, sub = metric_key.split(".")
                stats_dict = summ.get(top)
                v = stats_dict[sub] if stats_dict else None
            else:
                v = summ.get(metric_key)
            if v is None:
                row += " N/A |"
            elif isinstance(v, float):
                row += f" {v:.2f} |"
            else:
                row += f" {v} |"
        lines.append(row)
    lines.append("")

    # raw 표
    lines.append("### Raw invokes")
    lines.append("")
    for sname, recs in records_by_scen.items():
        lines.append(f"**{sname}**")
        lines.append("")
        lines.append("| i | ttft (s) | total (s) | cache R | cache W | session-id (앞 12자) |")
        lines.append("|---|---|---|---|---|---|")
        for r in recs:
            sid_short = r["session_id"][:12]
            ttft_str = f"{r['ttft']:.2f}" if r["ttft"] is not None else "N/A"
            lines.append(
                f"| {r['i']} | {ttft_str} | {r['total']:.2f} | "
                f"{r['cache_read']:,} | {r['cache_write']:,} | `{sid_short}…` |"
            )
        lines.append("")

    # 해석
    a_p50 = (summaries.get("A_warm") or {}).get("total", {}).get("p50")
    b_p50 = (summaries.get("B_cold") or {}).get("total", {}).get("p50")
    if a_p50 is not None and b_p50 is not None:
        delta = b_p50 - a_p50
        a_stdev = (summaries.get("A_warm") or {}).get("total", {}).get("stdev", 0)
        b_stdev = (summaries.get("B_cold") or {}).get("total", {}).get("stdev", 0)
        avg_stdev = (a_stdev + b_stdev) / 2 if (a_stdev or b_stdev) else 0.0
        noise_ratio = abs(delta) / avg_stdev if avg_stdev > 0 else float("inf")
        signif = (
            "noise 수준 (Δ < stdev)" if noise_ratio < 1.0
            else "noise 위로 emerge (1× ≤ Δ < 2× stdev)" if noise_ratio < 2.0
            else "noise 보다 명확히 큼 (Δ ≥ 2× stdev)"
        )
        verdict = (
            f"**Δ p50 = {delta:+.2f}s** (B − A), avg stdev ≈ {avg_stdev:.2f}s → Δ/stdev ≈ "
            f"{noise_ratio:.1f}× → {signif}."
        )
        lines.append("### 해석")
        lines.append("")
        lines.append(verdict)
        lines.append("")
        lines.append(
            "AWS docs ([Use isolated sessions](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-sessions.html)) "
            "는 session-id 를 microVM routing 의 binding key 라 명시 (\"uses the session "
            "header to route requests to the **same microVM instance**\"). 단 \"each request "
            "**may be routed** to a new microVM\" 의 \"may\" hedging — pool 재사용 시 cold 효과 "
            "관측 어려움."
        )
        lines.append("")
        lines.append(
            "session-id 의 본질적 가치는 **conversation memory 보존** (Strands `agent.messages` "
            "in-memory) + **idle timeout 15분** 안 같은 microVM 재진입. latency 는 부수 효과 — "
            "본 측정의 Δ 가 그 부수 효과의 크기."
        )
    return "\n".join(lines)


def append_to_phase5_detail(md_text: str, section_num: int) -> None:
    """phase5_detail.md 의 §N 자동 갱신. idempotent — 기존 §N detect → 교체, 없으면 EOF append."""
    if not PHASE5_DETAIL.exists():
        raise RuntimeError(f"{PHASE5_DETAIL} 없음 — append-md 불가")
    body = PHASE5_DETAIL.read_text(encoding="utf-8")
    sect_re = re.compile(rf"\n## {section_num}\. .*?(?=\n## |\Z)", re.DOTALL)
    new_section = "\n" + md_text.rstrip() + "\n"
    if sect_re.search(body):
        new_body = sect_re.sub(new_section, body)
        action = "replaced"
    else:
        sep = "" if body.endswith("\n") else "\n"
        sep += "\n---\n"
        new_body = body + sep + new_section
        action = "appended"
    PHASE5_DETAIL.write_text(new_body, encoding="utf-8")
    print(f"{GREEN}✅ {PHASE5_DETAIL.name} §{section_num} {action}{NC}", file=sys.stderr)


def main() -> None:
    args = parse_args()
    scenarios = [s.strip().upper() for s in args.scenarios.split(",")]
    invalid = [s for s in scenarios if s not in ("A", "B")]
    if invalid:
        sys.exit(f"❌ 잘못된 시나리오: {invalid}. A 또는 B 사용")
    cfg = AGENT_CONFIG[args.agent]
    if not cfg["invoke_path"].exists():
        sys.exit(f"❌ {cfg['invoke_path']} 없음")
    default_queries = {"monitor": "현재 라이브 알람 분류해줘", "supervisor": "현재 상황 진단해줘"}
    query = args.query or default_queries[args.agent]

    meta = {
        "agent": args.agent,
        "phase_label": cfg["phase_label"],
        "section_num": cfg["section_num"],
        "section_title_suffix": cfg["section_title_suffix"],
        "region": os.getenv("AWS_REGION", "us-east-1"),
        "demo_user": os.getenv("DEMO_USER", "bob"),
        "mode": args.mode,
        "query": query,
        "n": args.n,
        "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    # B 먼저 → A 다음 (A 의 잔류 microVM 이 B 결과 오염 방지)
    records_by_scen = {}
    summaries = {}

    if "B" in scenarios:
        recs = run_scenario("B_cold", args.n, args.agent, args.mode, query, mk_sid=new_session_id)
        records_by_scen["B_cold"] = recs
        summaries["B_cold"] = summarize(recs)

    if "A" in scenarios:
        fixed_sid = new_session_id()
        recs = run_scenario("A_warm", args.n, args.agent, args.mode, query, mk_sid=lambda: fixed_sid)
        records_by_scen["A_warm"] = recs
        summaries["A_warm"] = summarize(recs)

    if args.output == "json":
        print(json.dumps({
            "meta": meta,
            "scenarios": {
                name: {"records": records_by_scen[name], "stats": summaries[name]}
                for name in records_by_scen
            },
        }, indent=2, ensure_ascii=False))
    else:
        print(format_table(meta, summaries, records_by_scen))

    if args.append_md:
        md = format_md(meta, summaries, records_by_scen)
        append_to_phase5_detail(md, meta["section_num"])


if __name__ == "__main__":
    main()
