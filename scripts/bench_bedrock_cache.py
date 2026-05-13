#!/usr/bin/env python3
"""
bench_bedrock_cache.py — Direct Bedrock Converse API + prompt cache latency 측정

Strands / AgentCore Runtime / A2A 등 wrapper 모두 우회 — boto3 `bedrock-runtime.converse_stream`
직접 호출로 prompt cache 의 *순수* TTFT/latency 효과 isolation.

가설: 이전 측정 (Strands + AgentCore) 에서 cache latency 효과가 0 으로 나온 이유가
wrapper overhead 혹은 multi-LLM-call loop 때문인지, Bedrock API 자체 특성인지 분리.

시나리오:
  - cache_on: system_prompt 끝에 cachePoint 부착 → i=1 cache write, i>=2 cache hit
  - cache_off: cachePoint 없이 동일 system_prompt 만 전달 → 모든 invoke cache miss

매 invoke:
  - 같은 system_prompt (대용량 padding 포함 — Sonnet 4.6 min cache 2,048 tokens 만족)
  - 같은 user query (deterministic 분기 위해 짧음)
  - converse_stream 으로 TTFT (first chunk 도착 시각) + total latency 측정
  - response 의 usage 에서 cacheReadInputTokens / cacheWriteInputTokens 캡처

사용법:
    uv run scripts/bench_bedrock_cache.py --n 5
    uv run scripts/bench_bedrock_cache.py --n 5 --prompt-tokens 50000  # 큰 prompt
    uv run scripts/bench_bedrock_cache.py --n 5 --output json > /tmp/direct_bedrock.json

reference:
    - https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-caching.html
    - boto3 bedrock-runtime.converse / converse_stream API
"""
import argparse
import json
import os
import statistics
import sys
import time
from datetime import datetime

import boto3
from botocore.config import Config

REGION = os.getenv("AWS_REGION", "us-east-1")
DEFAULT_MODEL = os.getenv("BEDROCK_MODEL_ID", "global.anthropic.claude-sonnet-4-6")

GREEN, YELLOW, BLUE, RED, DIM, NC = (
    "\033[0;32m", "\033[1;33m", "\033[0;34m", "\033[0;31m", "\033[2m", "\033[0m"
)


def parse_args() -> argparse.Namespace:
    """CLI 인자."""
    p = argparse.ArgumentParser(description="Direct Bedrock Converse + prompt cache 효과 측정")
    p.add_argument("--n", type=int, default=5, help="각 mode 별 invoke 반복 (default 5)")
    p.add_argument("--model", default=DEFAULT_MODEL, help="Bedrock model id (default Sonnet 4.6)")
    p.add_argument("--prompt-chars", type=int, default=20_000,
                   help="system_prompt 의 padding 포함 char 수 (default 20K)")
    p.add_argument("--query", default="What is the capital of France? Answer in one short sentence.",
                   help="user query (짧을수록 output variance 적음)")
    p.add_argument("--output", choices=["table", "json"], default="table")
    p.add_argument("--max-tokens", type=int, default=100, help="output token cap (default 100)")
    return p.parse_args()


def build_system_prompt(prompt_chars: int) -> str:
    """대용량 system_prompt 합성 — Sonnet 4.6 min cache 2048 tokens 보장."""
    base = (
        "You are a helpful AI assistant. Follow these guidelines strictly:\n\n"
        "## Style guidelines\n\n"
        "- Be concise.\n"
        "- Use plain text only.\n"
        "- Answer the user's question directly.\n\n"
    )
    # Padding: 의미있는 instruction 형태로 반복 (cache 동작에 자연스러움)
    padding_block = (
        "## Additional reference rule\n\n"
        "Always consider these reference cases when reasoning about user queries:\n"
        "- For geographic questions, prioritize accuracy over brevity.\n"
        "- For mathematical questions, show the final answer clearly.\n"
        "- For scientific questions, cite the relevant principle.\n"
        "- For programming questions, prefer modern idiomatic style.\n"
        "- For factual lookup, defer to widely accepted authoritative sources.\n"
        "- Do not speculate beyond verifiable information.\n"
        "- When uncertain, state the uncertainty explicitly.\n\n"
    )
    content = base
    i = 0
    while len(content) < prompt_chars:
        i += 1
        content += padding_block.replace("Additional reference rule", f"Additional reference rule #{i}")
    return content[:prompt_chars]


def converse_once(client, model_id: str, system_prompt: str, query: str,
                  use_cache: bool, max_tokens: int) -> dict:
    """단일 Bedrock converse_stream 호출 + TTFT/total 측정 + cache usage 캡처."""
    system = [{"text": system_prompt}]
    if use_cache:
        system.append({"cachePoint": {"type": "default"}})

    messages = [{"role": "user", "content": [{"text": query}]}]

    start = time.time()
    response = client.converse_stream(
        modelId=model_id,
        system=system,
        messages=messages,
        inferenceConfig={"maxTokens": max_tokens, "temperature": 0.0},
    )

    first_chunk_ts = None
    output_text_parts = []
    usage = {}
    for event in response["stream"]:
        if first_chunk_ts is None:
            first_chunk_ts = time.time()
        if "contentBlockDelta" in event:
            delta = event["contentBlockDelta"].get("delta", {})
            if "text" in delta:
                output_text_parts.append(delta["text"])
        elif "metadata" in event:
            usage = event["metadata"].get("usage", {})
    end = time.time()

    ttft = (first_chunk_ts - start) if first_chunk_ts else None
    total = end - start
    return {
        "ttft": ttft,
        "total": total,
        "output_chars": len("".join(output_text_parts)),
        "input_tokens": usage.get("inputTokens", 0),
        "output_tokens": usage.get("outputTokens", 0),
        "cache_read": usage.get("cacheReadInputTokens", 0),
        "cache_write": usage.get("cacheWriteInputTokens", 0),
        "total_tokens": usage.get("totalTokens", 0),
    }


def run_scenario(client, model_id: str, system_prompt: str, query: str,
                 use_cache: bool, n: int, max_tokens: int, label: str) -> list[dict]:
    """N 회 반복 + per-invoke 진행 출력."""
    print(f"{BLUE}=== Scenario {label} — use_cache={use_cache} N={n} ==={NC}", file=sys.stderr)
    records = []
    for i in range(1, n + 1):
        print(f"{DIM}  [{i}/{n}] invoke 중...{NC}", file=sys.stderr, end="", flush=True)
        try:
            r = converse_once(client, model_id, system_prompt, query, use_cache, max_tokens)
        except Exception as e:
            print(f" {RED}❌ {e}{NC}", file=sys.stderr)
            raise
        r["i"] = i
        r["scenario"] = label
        records.append(r)
        ttft_str = f"ttft={r['ttft']:.2f}s" if r["ttft"] else "ttft=N/A"
        print(
            f" {GREEN}{ttft_str} total={r['total']:.2f}s "
            f"cache_R/W={r['cache_read']:,}/{r['cache_write']:,} out={r['output_chars']}c{NC}",
            file=sys.stderr,
        )
    return records


def _pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    s = sorted(values)
    k = (len(s) - 1) * (p / 100)
    f, c = int(k), min(int(k) + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)


def stats_of(vs: list[float]) -> dict:
    if not vs:
        return None
    return {
        "n": len(vs), "min": min(vs), "p50": _pct(vs, 50),
        "p95": _pct(vs, 95), "max": max(vs), "mean": statistics.mean(vs),
        "stdev": statistics.stdev(vs) if len(vs) >= 2 else 0.0,
    }


def summarize(records: list[dict], skip_first: bool = False) -> dict:
    """ttft + total 통계. skip_first=True 시 i=1 (cold microVM/cache write) 제외."""
    use = records if not skip_first else [r for r in records if r["i"] > 1]
    if not use:
        return {}
    return {
        "ttft": stats_of([r["ttft"] for r in use if r["ttft"] is not None]),
        "total": stats_of([r["total"] for r in use]),
        "n": len(use),
    }


def format_table(meta: dict, off_recs: list[dict], on_recs: list[dict]) -> str:
    """ASCII 표 — 전체 + warm-only 비교."""
    lines = []
    lines.append(f"\n{BLUE}{'=' * 75}{NC}")
    lines.append(f"  Direct Bedrock Cache Bench — model={meta['model']}")
    lines.append(f"  region={meta['region']} prompt_chars={meta['prompt_chars']:,}")
    lines.append(f"  N={meta['n']} per scenario  started={meta['started_at']}")
    lines.append(f"{BLUE}{'=' * 75}{NC}\n")

    for label, recs in [("cache OFF", off_recs), ("cache ON", on_recs)]:
        lines.append(f"{YELLOW}[{label}] raw invokes:{NC}")
        lines.append(f"  {'i':>3} {'ttft':>6} {'total':>7} {'in_tok':>8} {'out_tok':>8} "
                     f"{'cache_R':>10} {'cache_W':>10}")
        for r in recs:
            ttft_str = f"{r['ttft']:>6.2f}" if r["ttft"] else f"{'N/A':>6}"
            lines.append(
                f"  {r['i']:>3} {ttft_str} {r['total']:>7.2f} "
                f"{r['input_tokens']:>8,} {r['output_tokens']:>8,} "
                f"{r['cache_read']:>10,} {r['cache_write']:>10,}"
            )
        lines.append("")

    # 통계 — 전체 + warm-only
    for skip_first, header in [(False, "All invokes (i=1 포함)"),
                                (True, "Warm only (i>=2)")]:
        off_stats = summarize(off_recs, skip_first=skip_first)
        on_stats = summarize(on_recs, skip_first=skip_first)
        if not off_stats or not on_stats:
            continue
        lines.append(f"{YELLOW}### {header}{NC}")
        lines.append(f"  {'metric':<20} {'cache OFF':>12} {'cache ON':>12} {'Δ (ON-OFF)':>14}")
        lines.append(f"  {'-' * 64}")
        for key, label in [("total.p50", "total p50 (s)"),
                            ("total.mean", "total mean (s)"),
                            ("total.stdev", "total stdev (s)"),
                            ("ttft.p50", "ttft p50 (s)"),
                            ("ttft.mean", "ttft mean (s)"),
                            ("ttft.stdev", "ttft stdev (s)")]:
            top, sub = key.split(".")
            o_stats = off_stats.get(top)
            n_stats = on_stats.get(top)
            if o_stats is None or n_stats is None:
                continue
            o, n = o_stats[sub], n_stats[sub]
            delta = n - o
            lines.append(f"  {label:<20} {o:>12.2f} {n:>12.2f} {delta:>+14.2f}")
        lines.append("")

    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    config = Config(connect_timeout=30, read_timeout=300, retries={"max_attempts": 0})
    client = boto3.client("bedrock-runtime", region_name=REGION, config=config)

    system_prompt = build_system_prompt(args.prompt_chars)
    meta = {
        "model": args.model,
        "region": REGION,
        "prompt_chars": args.prompt_chars,
        "n": args.n,
        "query": args.query,
        "max_tokens": args.max_tokens,
        "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    # B (cache OFF) 먼저 → A (cache ON) 다음 — A 의 잔류 cache 가 B 영향 X
    off_recs = run_scenario(client, args.model, system_prompt, args.query,
                            use_cache=False, n=args.n, max_tokens=args.max_tokens,
                            label="cache_off")
    on_recs = run_scenario(client, args.model, system_prompt, args.query,
                           use_cache=True, n=args.n, max_tokens=args.max_tokens,
                           label="cache_on")

    if args.output == "json":
        print(json.dumps({
            "meta": meta,
            "cache_off": {"records": off_recs, "stats_all": summarize(off_recs),
                          "stats_warm": summarize(off_recs, skip_first=True)},
            "cache_on": {"records": on_recs, "stats_all": summarize(on_recs),
                         "stats_warm": summarize(on_recs, skip_first=True)},
        }, indent=2, ensure_ascii=False))
    else:
        print(format_table(meta, off_recs, on_recs))


if __name__ == "__main__":
    main()
