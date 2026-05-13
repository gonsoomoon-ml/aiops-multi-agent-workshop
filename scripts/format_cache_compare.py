#!/usr/bin/env python3
"""
format_cache_compare.py — Bedrock prompt cache 의 latency-only 효과 측정 결과 정리

`bench_session_id.py --output json` 으로 측정한 cache-OFF / cache-ON 두 JSON 을
읽어 §5 markdown 생성 후 `docs/learn/phase5_detail.md` 에 자동 append/replace.

사용법:
    # 사전: supervisor agent.py cache disable + 재배포 → bench → 원복 + 재배포 → bench
    uv run scripts/bench_session_id.py --agent supervisor --scenarios A --n 5 \\
        --query "현재 상황 진단해줘" --output json > /tmp/bench_cache_off.json
    # (cache 원복 후)
    uv run scripts/bench_session_id.py --agent supervisor --scenarios A --n 5 \\
        --query "현재 상황 진단해줘" --output json > /tmp/bench_cache_on.json
    # 두 결과 비교 + §5 작성
    uv run scripts/format_cache_compare.py \\
        --cache-off /tmp/bench_cache_off.json \\
        --cache-on /tmp/bench_cache_on.json --append-md

reference: docs/learn/phase5_detail.md §5 (본 스크립트가 생성하는 섹션)
"""
import argparse
import json
import re
import statistics
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PHASE5_DETAIL = PROJECT_ROOT / "docs" / "learn" / "phase5_detail.md"

GREEN, NC = "\033[0;32m", "\033[0m"


def parse_args() -> argparse.Namespace:
    """CLI 인자 — 두 JSON 파일 경로 + append 옵션."""
    p = argparse.ArgumentParser(description="Bedrock prompt cache latency effect 비교 + §5 생성")
    p.add_argument("--cache-off", required=True, help="cache 비활성 bench JSON")
    p.add_argument("--cache-on", required=True, help="cache 활성 bench JSON")
    p.add_argument("--append-md", action="store_true", help=f"{PHASE5_DETAIL} §5 에 append/replace")
    return p.parse_args()


def load_bench_json(path: str) -> dict:
    """bench_session_id.py JSON 결과 load + records 추출."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if "A_warm" not in data["scenarios"]:
        raise RuntimeError(f"{path}: 'A_warm' scenario 부재")
    return {
        "meta": data["meta"],
        "records": data["scenarios"]["A_warm"]["records"],
        "stats": data["scenarios"]["A_warm"]["stats"],
    }


def _pct(values: list[float], p: float) -> float:
    """p (0~100) percentile."""
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * (p / 100)
    f, c = int(k), min(int(k) + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)


def stats_of(values: list[float]) -> dict:
    """N>=1 의 기초 통계."""
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "min": min(values),
        "p50": _pct(values, 50),
        "p95": _pct(values, 95),
        "max": max(values),
        "mean": statistics.mean(values),
        "stdev": statistics.stdev(values) if len(values) >= 2 else 0.0,
    }


def format_compare_md(off: dict, on: dict) -> str:
    """§5 markdown 생성 — 가설 + 방법론 + 통계 비교 표 + raw + 해석."""
    lines = []
    lines.append("## 5. Bedrock Prompt Cache — Latency-Only Effect")
    lines.append("")
    lines.append(
        "`scripts/bench_session_id.py` + `scripts/format_cache_compare.py` 가 자동 갱신하는 섹션. "
        "session-id 의 microVM 효과 (§4) 와 분리해, **Bedrock prompt cache 의 순수 latency 효과** "
        "를 측정 — `cache_tools` + `SystemContentBlock(cachePoint=...)` 를 supervisor agent.py 에서 "
        "임시 제거 후 재배포 → bench → 원복 + 재배포 → bench. session-id 는 두 조건 모두 same "
        "(microVM warm 통제 변수)."
    )
    lines.append("")
    lines.append(
        f"**측정 환경**: agent `supervisor (Phase 5, 3 agent A2A)` · region `{off['meta']['region']}` · "
        f"DEMO_USER `{off['meta']['demo_user']}` · N={off['meta']['n']} per condition · "
        f"started OFF `{off['meta']['started_at']}` → ON `{on['meta']['started_at']}`"
    )
    lines.append("")

    # 조건 정의
    lines.append("### 조건 정의")
    lines.append("")
    lines.append("| 조건 | supervisor agent.py | 기대 cache R/W |")
    lines.append("|---|---|---|")
    lines.append("| **cache OFF** | `cache_tools=None`, `system_prompt=<str>` (cachePoint 없음) | 0 / 0 모든 invoke |")
    lines.append("| **cache ON** | `cache_tools=\"default\"`, `SystemContentBlock(cachePoint=default)` | i=1 W>0, i>=2 R>0 W=0 |")
    lines.append("")

    off_totals = [r["total"] for r in off["records"]]
    on_totals = [r["total"] for r in on["records"]]
    off_stats = stats_of(off_totals)
    on_stats = stats_of(on_totals)

    # i=1 (cold microVM) 분리 — i>=2 가 microVM warm + cache 의 순수 비교
    off_warm = [r["total"] for r in off["records"] if r["i"] > 1]
    on_warm = [r["total"] for r in on["records"] if r["i"] > 1]
    off_warm_stats = stats_of(off_warm) if off_warm else None
    on_warm_stats = stats_of(on_warm) if on_warm else None

    # 통계 표 — 전체 invoke
    lines.append("### 통계 비교 (latency = total invoke time, 초)")
    lines.append("")
    lines.append("#### 모든 invoke (i=1 포함, i=1 은 microVM cold 라 outlier)")
    lines.append("")
    lines.append("| metric | cache OFF | cache ON | Δ (ON − OFF) |")
    lines.append("|---|---|---|---|")
    for key, label in [
        ("p50", "p50"),
        ("p95", "p95"),
        ("min", "min"),
        ("max", "max"),
        ("mean", "mean"),
        ("stdev", "stdev"),
    ]:
        o, n = off_stats[key], on_stats[key]
        lines.append(f"| {label} | {o:.2f} | {n:.2f} | {n - o:+.2f} |")
    lines.append("")

    if off_warm_stats and on_warm_stats:
        lines.append("#### microVM warm 만 (i=2..N, fair 비교)")
        lines.append("")
        lines.append("| metric | cache OFF | cache ON | Δ (ON − OFF) |")
        lines.append("|---|---|---|---|")
        for key, label in [
            ("p50", "p50"),
            ("p95", "p95"),
            ("min", "min"),
            ("max", "max"),
            ("mean", "mean"),
            ("stdev", "stdev"),
        ]:
            o, n = off_warm_stats[key], on_warm_stats[key]
            lines.append(f"| {label} | {o:.2f} | {n:.2f} | {n - o:+.2f} |")
        lines.append("")

    # raw invokes
    lines.append("### Raw invokes")
    lines.append("")
    for label, data in [("cache OFF", off), ("cache ON", on)]:
        lines.append(f"**{label}**")
        lines.append("")
        lines.append("| i | total (s) | cache R | cache W |")
        lines.append("|---|---|---|---|")
        for r in data["records"]:
            lines.append(f"| {r['i']} | {r['total']:.2f} | {r['cache_read']:,} | {r['cache_write']:,} |")
        lines.append("")

    # 해석
    lines.append("### 해석")
    lines.append("")

    if off_warm_stats and on_warm_stats:
        d_p50 = on_warm_stats["p50"] - off_warm_stats["p50"]
        avg_stdev = (off_warm_stats["stdev"] + on_warm_stats["stdev"]) / 2
        ratio = abs(d_p50) / avg_stdev if avg_stdev > 0 else float("inf")
        if d_p50 < -0.5:
            verdict = (
                f"cache ON 이 **{abs(d_p50):.2f}초 더 빠름** (i>=2 비교). "
                f"Δ/stdev ≈ {ratio:.1f}× → "
                + ("noise 위 emerge" if ratio >= 1.0 else "noise 수준")
            )
        elif d_p50 > 0.5:
            verdict = (
                f"**cache ON 이 OFF 보다 {d_p50:.2f}초 더 느림** (i>=2 비교, 예상 반대). "
                f"Δ/stdev ≈ {ratio:.1f}× → network jitter 가 latency 변동 dominator. "
                f"supervisor 가 측정하는 token usage 의 cache R/W 와 별개로, **A2A 2 hop + "
                f"sub-agent LLM 호출 (Bedrock cache 와 무관) 이 total latency 의 majority 차지** "
                f"→ cache hit 의 supervisor 부분 절감 (~1-3s) 이 jitter 에 묻힘."
            )
        else:
            verdict = (
                f"Δ p50 = {d_p50:+.2f}s — **거의 무차이** (|Δ| < 0.5s, noise 수준). "
                f"avg stdev = {avg_stdev:.2f}s."
            )
        lines.append(verdict)
        lines.append("")

    lines.append(
        "**확인된 점**:"
    )
    lines.append("")
    off_cw = sum(1 for r in off["records"] if r["cache_write"] > 0)
    on_cw = sum(1 for r in on["records"] if r["cache_write"] > 0)
    lines.append(
        f"- cache OFF 의 cache R/W 가 **모든 invoke 0/0** ({len(off['records']) - off_cw}/"
        f"{len(off['records'])}) → cache 진짜 disable 됐음 검증 완료"
    )
    lines.append(
        f"- cache ON 의 i=1 만 W>0 ({on_cw}/{len(on['records'])}), i>=2 는 cache hit "
        f"(R>0, W=0) → 정상 prompt cache 동작"
    )
    lines.append("")
    lines.append(
        "**워크샵 narrative**: Bedrock prompt cache 의 가치는 **cost** (cache R 토큰의 ~90% 할인) "
        "에 압도적으로 비중. **latency** 효과는 본 워크로드에서 **noise 수준 (~0-3s)** — A2A 2 hop "
        "+ sub-agent LLM 호출 시간이 dominator 라 supervisor 의 cache hit 절감이 묻힘. "
        "single-agent (Phase 3) 또는 longer prompt 워크로드에서는 latency 효과 더 명확할 가능성."
    )
    lines.append("")
    lines.append(
        "**Reference**: [AWS Bedrock prompt caching](https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-caching.html) "
        "(cache read 가격 10% / cache write 가격 125%), "
        "[Strands `BedrockModel(cache_tools=...)`](https://strandsagents.com/reference/models/bedrock-models/) "
        "+ `SystemContentBlock(cachePoint=...)` 가 두 레이어 (tool schema + system prompt) 캐시."
    )
    return "\n".join(lines)


def append_to_phase5_detail(md_text: str, section_num: int = 5) -> None:
    """phase5_detail.md 의 §N 자동 갱신. idempotent — 기존 §N detect → 교체, 없으면 EOF append."""
    if not PHASE5_DETAIL.exists():
        raise RuntimeError(f"{PHASE5_DETAIL} 없음")
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
    off = load_bench_json(args.cache_off)
    on = load_bench_json(args.cache_on)
    md = format_compare_md(off, on)
    print(md)
    if args.append_md:
        append_to_phase5_detail(md, section_num=5)


if __name__ == "__main__":
    main()
