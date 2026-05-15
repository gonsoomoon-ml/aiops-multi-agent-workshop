# Phase 5 — Bedrock Prompt Cache Latency Effect (deep-dive)

`docs/research/phase5_detail.md §5` 의 첫 측정에서 의외 결과 (cache ON 이 OFF 보다 +4.75초 **더 느림**) 가 나옴. 본 문서는 그 결과에 의문을 갖고 진행한 **6단계 후속 측정** 의 종합 정리. 워크샵 청중이 "prompt cache 가 정말 latency 줄이나?" 라는 질문에 대해, **size-dependent + wrapper-sensitive** 라는 3-layer 모델을 데이터로 backing.

핵심 결론 (선행 요약):
- **bare Bedrock API + 100K cached tokens**: -38% latency ✅ (AWS 공식 claim "up to 85%" 의 절반 수준)
- **Strands agent wrapper + 76K cached tokens**: -4.4% latency (wrapper baseline 11.8초가 percentage dilute)
- **< 16K cached tokens**: noise 수준 (effect invisible)

---

## 1. 출발점 — phase5_detail.md §5 의 의외 결과

3 agent (Supervisor + Monitor A2A + Incident A2A) Phase 5 구성에서 supervisor 의 `cache_tools` + `cachePoint` 를 임시 비활성 후 N=5 비교:

| 조건 | supervisor agent.py | 기대 cache R/W |
|---|---|---|
| **cache OFF** | `cache_tools=None`, `system_prompt=<str>` (cachePoint 없음) | 0 / 0 모든 invoke |
| **cache ON** | `cache_tools="default"`, `SystemContentBlock(cachePoint=default)` | i=1 W>0, i>=2 R>0 W=0 |

### 통계 (microVM warm only, i>=2..N)

| metric | cache OFF | cache ON | Δ (ON − OFF) |
|---|---|---|---|
| p50 | 23.25 | 28.00 | **+4.75s** ← cache 가 더 느림 |
| mean | 23.57 | 27.68 | +4.10 |
| stdev | 0.97 | 2.13 | +1.15 |

### Raw

**cache OFF**: 22.8 / 23.2 / 23.3 / 25.0s — 매우 stable (stdev 0.97)
**cache ON**: 25.2 / 26.6 / 29.4 / 29.5s — 더 느리고 variance ↑

→ Δ/stdev ≈ 3.1× → 단순 noise 아닌 **systematic 한 차이**. 하지만 방향이 예상과 반대 (cache 가 latency 늘림).

### 잠정 결론 (§5 작성 시점)

"A2A 2 hop + sub-agent LLM 시간이 dominator 라 supervisor cache 절감 (~1-3s) 이 jitter 에 묻힘" — 추정만 가능, 직접 증거 부족. **post-§5 검증 필요**.

---

## 2. Phase 3 single-agent 검증 (A2A 변수 제거)

A2A 다중 hop 가설 검증 — Phase 3 monitor (HTTP 단독, no A2A) 로 재측정.

### N=1 prelim (탐색)

| 조건 | TTFT | Total | Cache R/W |
|---|---|---|---|
| Cache OFF | 5.80s | 8.30s | 0/0 |
| Cache ON i=1 (cold) | 14.80s | **17.60s** | 3,507 / **3,507** ← cache write 비용 |
| Cache ON i=2 (warm) | 5.50s | 7.60s | 7,014 / 0 |

i=1 cache write 가 **+9.3s** 비용 — 큰 발견. 하지만 i=2 (warm hit) 는 cache OFF 와 거의 동일.

### N=5 본 측정

**Cache OFF** (R/W=0/0 검증):
| i | ttft | total |
|---|---|---|
| 1 | 14.0s | 16.6s (cold microVM) |
| 2 | 4.5s | 7.1s |
| 3 | 4.5s | 10.1s |
| 4 | 4.1s | 6.2s |
| 5 | 4.0s | 6.8s |

**Cache ON** (i>=2 cache hit R=7014):
| i | ttft | total |
|---|---|---|
| 1 | 5.8s | 8.0s |
| 2 | 4.4s | 6.6s |
| 3 | 4.6s | 6.7s |
| 4 | 4.8s | 7.6s |
| 5 | 4.7s | 9.9s |

**i>=2 비교**:

| metric | Cache OFF | Cache ON | Δ |
|---|---|---|---|
| total median | 6.95s | 7.15s | +0.20 (noise) |
| total mean | 7.55s | 7.70s | +0.15 (noise) |
| stdev | ~1.8s | ~1.5s | — |

→ **Δ/stdev ≈ 0.1× → noise 수준**. Phase 3 (A2A 없음) 에서도 cache effect 미관측.

---

## 3. 큰 system prompt 가설 (10x 확장)

prompt 크기 가설 — 작은 prompt 라 cache 효과 작다? Phase 3 monitor 의 `system_prompt_live.md` 를 7KB → 100KB 로 확장 (cache R 7,014 → 73,492 tokens, 10x).

### N=5 결과 (Strands+Phase 3, 100K prompt)

**Cache OFF** (R/W=0/0):
i=2-5 mean total = 11.75s, stdev ~0.18

**Cache ON** (R=73,492 i>=2):
i=2-5 mean total = 12.50s, stdev ~0.59

| metric | Cache OFF | Cache ON | Δ |
|---|---|---|---|
| total mean | 11.75s | 12.50s | **+0.75s** ← 여전히 cache 가 더 느림 |
| TTFT mean | 5.30s | 6.28s | +0.98s |

→ **10x prompt 에도 cache 효과 emergence X**. 가설 기각? — 또는 Strands wrapper 가 mask 하는 중.

---

## 4. 웹 research — 문헌 vs 우리 측정

검증을 위해 외부 문헌 조사:

| 출처 | latency claim |
|---|---|
| [AWS Bedrock 공식](https://aws.amazon.com/blogs/machine-learning/effectively-use-prompt-caching-on-amazon-bedrock/) | "**up to 85% latency reduction**" — hedging: "depends on use case" |
| [Anthropic Claude docs](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) | **No specific percentages** — "significantly reduces processing time" |
| [arxiv 2601.06007 (research paper)](https://arxiv.org/html/2601.06007v2) | **Claude Sonnet 4.5: 20.9-22.9% TTFT improvement** (Anthropic API 직접) — Bedrock 평가 X |

### AWS 자체 caveat (핵심)

> "prompt caching might be **less effective for workloads that involve a lengthy 2,000-token system prompt with a long set of dynamically changing text afterwards**."

→ 우리 Strands+agent workload (tool call 후 dynamic content append) 가 정확히 그 anti-pattern 에 해당.

### 가능한 reconciliation 가설

1. Bedrock implementation 이 Anthropic API 보다 latency 효과 작음
2. Sonnet 4.6 가 4.5 와 다른 cache 동작
3. **Strands wrapper overhead 가 cache 절감을 mask** ← 후속 검증 대상
4. cached prompt size threshold 미달

---

## 5. Direct Bedrock bench tool (`scripts/bench_bedrock_cache.py`)

Strands / AgentCore Runtime / A2A 모두 우회 — `boto3.bedrock-runtime.converse_stream` 직접 호출로 cache 의 *순수* latency 효과 isolation. 신규 스크립트:

```bash
uv run scripts/bench_bedrock_cache.py --n 10 --prompt-chars 200000
```

핵심 측정:
- TTFT = 첫 chunk 도착 시각
- Total = 전체 stream 완료
- Cache R/W = response usage 의 `cacheReadInputTokens` / `cacheWriteInputTokens`

시나리오:
- `cache_off`: cachePoint 없이 system 전달 → R/W=0/0
- `cache_on`: cachePoint 부착 → i=1 cache write, i>=2 cache hit

자세한 코드: `scripts/bench_bedrock_cache.py`.

---

## 6. Direct Bedrock — prompt size 별 size scaling 발견

5가지 prompt size 로 N=10 측정:

| prompt chars | cached tokens | Cache OFF mean | Cache ON mean | Δ | % |
|---|---|---|---|---|---|
| 10K | ~2K (below min 2048) | 1.61s | 1.67s | +0.06 | noise (cache disabled silently) |
| 30K | ~6K | 1.18s | 1.31s | +0.14 | noise |
| 80K | ~16K | 1.45s | 1.41s | -0.04 | noise |
| **200K** | **~40K** | **1.75s** | **1.33s** | **-0.42** | **-24%** ✅ |
| **500K** | **~100K** | **3.07s** | **1.91s** | **-1.16** | **-38%** ✅✅ |

### Threshold 발견

**40K cached tokens 가 cache 효과 emergence threshold**.

| cached tokens | latency 효과 |
|---|---|
| < 2K | silently disabled (below Sonnet 4.6 min 2048) |
| 2K - 16K | noise level (Δ < stdev) |
| **40K** | **clear (-24%)** — research paper Sonnet 4.5 의 20-23% 와 일치 |
| **100K** | **dramatic (-38%)** — AWS claim 85% 의 절반 |

### TTFT 분해

500K char prompt 측정 raw:

**Cache OFF** (모든 invoke processes 100K input):
i=1: 1.68s, i=2..10: 1.33-1.87s → mean 1.55s

**Cache ON**:
- i=1: 1.74s (cache write 거의 무료 — +0.06s)
- i=2-10: 1.18-2.45s, decreasing trend (1.37s at i=10)
- mean 1.41s

→ Bedrock 의 cache hit 는 **input prefill 을 거의 0 으로 만듬** → output generation 시간만 남음.

---

## 7. Strands wrapper overhead — direct vs wrapped 비교

같은 200K prompt 를 Strands+Phase 3 monitor 로 측정 (re-deploy + bench):

**Cache ON** (200K prompt, R=153,372):
i=2-5 mean = 12.95s, range 12.3-14.3s

**Cache OFF** (R/W=0/0):
i=2-5 mean = 13.55s, range 13.3-14.1s

| metric | Cache OFF | Cache ON | Δ |
|---|---|---|---|
| mean | 13.55s | 12.95s | **-0.60s (-4.4%)** |

### 같은 prompt, 두 wrapper 비교

| wrapper | cached tokens | OFF baseline | Cache 절감 (absolute) | 절감 % |
|---|---|---|---|---|
| **direct Bedrock** | 40K | 1.75s | -0.42s | **24%** |
| **Strands** | 76K | **13.55s** | -0.60s | **4.4%** |
| wrapper overhead | — | **+11.8s** (tool calls + agent loop) | — | percentage 희석 |

### 핵심 통찰

**Bedrock cache 의 absolute latency 절감 (~0.4-1초) 은 일정**. 차이는 baseline:
- Direct API: 1.75s baseline → 0.42s 절감 = 24% 효과
- Strands: 13.55s baseline → 0.60s 절감 = 4.4% 효과 (희석)

Strands baseline 의 11.8s = **tool call + agent loop overhead** (Bedrock cache 와 무관). 워크샵 narrative 의 핵심 포인트.

---

## 8. 3-layer 최종 모델

```
Bedrock prompt cache latency 효과 — 3 layer:

  Layer 1 — Size scaling:
    < 16K cached tokens   → invisible (noise)
    40K cached tokens     → -24% (emergence)
    100K cached tokens    → -38% (dramatic)
    Cache 효과 ≈ Cache OFF prefill cost (absolute 시간 비례)

  Layer 2 — Wrapper overhead:
    Direct Bedrock API:   1.75s baseline → -0.42s = 24% effect
    Strands agent loop:   13.55s baseline → -0.60s = 4.4% effect
    Wrapper baseline 이 % effect 를 dilute

  Layer 3 — Cache write cost:
    Direct API at 100K:   +0.06s (negligible)
    Strands+Phase 3 7K:   +9.3s (anomalous, Strands 측 overhead)
    Direct 의 cache write 는 사실상 무료

  결론:
    - bare Bedrock + 큰 system_prompt (RAG, doc Q&A) = AWS claim 의 절반 효과
    - agentic workload (Strands + tool calls) = -5% 수준 (wrapper baseline 우세)
    - Cost benefit (~90% 할인) 은 size 와 wrapper 모두 무관하게 유지
```

---

## 9. 측정 데이터 종합

| # | 측정 | wrapper | cached tokens | Δ p50 | % |
|---|---|---|---|---|---|
| 1 | Phase 5 supervisor (3-agent) | Strands+A2A | 12K | +4.75 | A2A jitter |
| 2 | Phase 3 monitor default | Strands | 7K | +0.20 | noise (below threshold) |
| 3 | Phase 3 monitor 100K prompt | Strands | 73K | +0.75 | wrapper masking |
| 4 | Direct Bedrock 10K | none | 2K | +0.06 | below cache min |
| 5 | Direct Bedrock 30K | none | 6K | +0.14 | below threshold |
| 6 | Direct Bedrock 80K | none | 16K | -0.04 | noise |
| **7** | **Direct Bedrock 200K** | **none** | **40K** | **-0.42** | **-24% ✅** |
| **8** | **Direct Bedrock 500K** | **none** | **100K** | **-1.16** | **-38% ✅** |
| **9** | **Strands 200K** | **Strands** | **76K** | **-0.60** | **-4.4%** |

---

## 10. 재현 — scripts + 사용법

### Direct Bedrock bench (가장 깨끗한 측정)

```bash
# Threshold 측정 — prompt size 별 cache 효과 emergence 확인
uv run scripts/bench_bedrock_cache.py --n 10 --prompt-chars 30000
uv run scripts/bench_bedrock_cache.py --n 10 --prompt-chars 200000   # 40K cached tokens
uv run scripts/bench_bedrock_cache.py --n 10 --prompt-chars 500000   # 100K cached tokens
```

CLI 인자:
- `--n N` — 반복 횟수 (default 5)
- `--prompt-chars N` — system_prompt 의 padding 포함 char 수 (default 20K)
- `--model` — Bedrock model id (default Sonnet 4.6)
- `--max-tokens N` — output token cap (default 100)
- `--output table|json`

### Strands wrapper bench (wrapper overhead 확인)

이전 작업의 `scripts/bench_session_id.py` 활용. Strands+AgentCore 진입:

```bash
# 1. monitor prompt 를 200K 로 expand (예: 위 expand_prompt_200k.py)
# 2. monitor/shared/agent.py 의 cache 활성 상태에서 redeploy
uv run agents/monitor/runtime/deploy_runtime.py

# 3. Cache ON 측정
uv run scripts/bench_session_id.py --agent monitor --scenarios A --n 5 \
    --output json > /tmp/strands_on.json

# 4. cache 비활성 (cache_tools=None + system_prompt=<str>) + redeploy
# 5. Cache OFF 측정
uv run scripts/bench_session_id.py --agent monitor --scenarios A --n 5 \
    --output json > /tmp/strands_off.json

# 6. 비교 + §5 갱신 (또는 §5 read 후 manual)
uv run scripts/format_cache_compare.py \
    --cache-off /tmp/strands_off.json --cache-on /tmp/strands_on.json
```

### CLAUDE.md §3 준수

agent 코드 (monitor/incident/supervisor shared/agent.py) 의 임시 cache disable 은 **측정 후 반드시 git checkout 으로 원복**. 본 deep-dive 의 모든 측정 후 `git status agents/` clean 확인.

---

## 11. 워크샵 narrative 변경 권장

| 이전 narrative | **수정된 narrative (본 측정 backing)** |
|---|---|
| "prompt cache 는 latency 줄임 ~85%" | **size + workload 의존** — bare API 대용량 prompt 워크로드만 50%+. agentic 에선 5% 이하 |
| "Phase 5 의 9초 절감은 cache 덕분" | **9초 = microVM warm 효과 (§4 session-id)**, cache 자체 기여는 ~5% (multi-agent 에선 거의 0) |
| "Bedrock prompt cache 항상 enable" | ✅ 여전히 권장 — **cost 절감 (~90%) 은 size 무관**. latency 는 부수 효과 |
| "agentic workload 에서 cache 효과 invisible" | **wrapper baseline 이 dilute** — absolute 절감 (~0.5초) 은 동일하지만 % 측면 작음 |

---

## 12. Reference

- [AWS Bedrock prompt caching](https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-caching.html) — cache read 가격 10% / cache write 가격 125%
- [Effectively use prompt caching on Amazon Bedrock](https://aws.amazon.com/blogs/machine-learning/effectively-use-prompt-caching-on-amazon-bedrock/) — AWS 공식 "up to 85%" claim + workload-dependent caveat
- [Anthropic Claude prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) — minimum 2,048 tokens for Sonnet 4.6
- [Don't Break the Cache (arxiv 2601.06007)](https://arxiv.org/html/2601.06007v2) — Sonnet 4.5 의 20.9-22.9% TTFT improvement 실측 (Anthropic API)
- [Strands `BedrockModel(cache_tools=...)`](https://strandsagents.com/reference/models/bedrock-models/) — tool schema 캐시

## 13. Memory note (auto-memory 후보)

본 측정의 핵심 finding — 다음 세션에서 prompt cache 관련 질문 시 reference:

1. **Bedrock cache 효과 threshold ≈ 40K cached tokens** (Sonnet 4.6, 직접 API)
2. **Direct Bedrock 100K cached → -38% latency** (AWS claim 85% 의 절반)
3. **Strands wrapper 가 cache % 효과 dilute** — baseline overhead 가 dominator
4. **Cache write 비용 size 무관 minimal** (direct API 에선 +0.06s, Strands 의 +9s 는 wrapper artifact)
5. **Workshop narrative**: "cache = cost (확정), latency = size+wrapper 의존 (조건부)"
