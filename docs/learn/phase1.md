# Phase 1 — 로컬 Monitor Agent (Strands + 3가지 진단 유형)

> 첫 LLM 등장. mock 데이터 (5 alarms × 24 events) 를 Strands Agent + 3가지 진단 유형 prompt 로 분류. **AWS 의존 0** (Bedrock model API 만 호출).

---

## 무엇을 만드나

```
                              [Mock data] data/mock/phase1/alarm_history.py
                              ├─ 5 alarms (real 2 + noise 3)
                              └─ 24 history events
                                       │
                                       ▼
[로컬 CLI]  ─►  Strands Agent  ─►  3가지 진단 유형 매칭  ─►  3 섹션 plain text 출력
                  │                  ├─ rule_retirement (90일+ 방치)
                  │                  ├─ threshold_uplift (auto_resolve > 90%)
                  │                  └─ time_window_exclude (특정 2시간대 80%+)
                  ▼
            BedrockModel (Claude Sonnet 4.6) + system_prompt_past.md
```

**핵심**: AWS 자원 (EC2/Gateway/Cognito) 0건 — Bedrock model API 만 사용. 청중이 LLM agent 의 결정성 + prompt 영향력을 단독으로 학습.

---

## 왜 필요한가

| Educational 가치 | 학습 포인트 |
|---|---|
| **Strands Agent 최소 구성** | `Agent(model, tools, system_prompt, callback_handler)` — 4개 인자만으로 LLM agent 동작 |
| **@tool decorator 패턴** | Python 함수 → LLM 도구 — Strands `@tool` decorator 단 1줄 |
| **Prompt 결정성** | strict output format rule + 정량 진단 조건 → 같은 입력 → 같은 출력 |
| **3가지 진단 유형 도메인 학습** | rule_retirement / threshold_uplift / time_window_exclude — alarm hygiene 의 핵심 패턴 |
| **AWS 의존 격리** | mock 만 → Bedrock 외 0 자원 → 빠른 iteration (~5초) |
| **회귀 baseline** | Phase 2~5 가 변형해도 이 entry 는 동일 출력 — drift 감지 기준점 |

→ **이 phase 는 후속 모든 phase 의 출력 비교 기준점** (P2-A3 = Phase 2 Gateway mode=past 출력이 Phase 1 과 byte-level 동일해야 함).

---

## 어떻게 동작

### 핵심 파일

| 파일 | 역할 | 줄수 |
|---|---|---:|
| `data/mock/phase1/alarm_history.py` | Mock data — 5 alarms + 24 events + ground truth (`_classification`, `_diagnosis_type`) | 271 |
| `agents/monitor/shared/agent.py` | Strands Agent factory — `create_agent(tools, system_prompt_filename)` | 43 |
| `agents/monitor/shared/tools/alarm_history.py` | `@tool` wrappers — mock data 를 LLM 도구로 노출 | 40 |
| `agents/monitor/shared/prompts/system_prompt_past.md` | Phase 1 system prompt (3섹션 형식 + 진단 유형 정의 + 예시 출력) | 227 |
| `agents/monitor/local/run_local_import.py` | Phase 1 entry — `create_agent()` + 도구 주입 + stream | 93 |

### 5개 mock 알람 (ground truth)

| 알람 | 분류 | 진단 유형 | 데이터 패턴 |
|---|---|---|---|
| `web-server-cpu-high` | real | — | ack 2/2, action 2/2 |
| `payment-api-5xx-errors` | real | — | ack 2/2, action 2/2 |
| `legacy-2018-server-cpu` | noise | `rule_retirement` | age 100일, ack 0건, fire 1건 |
| `web-server-memory-routine` | noise | `threshold_uplift` | auto_resolve 4/4 (100%), 시간대 분산 |
| `nightly-batch-cpu` | noise | `time_window_exclude` | fire 3건 모두 02시대 (100% > 80%) |

### 진단 유형 우선순위 (mutual exclusive)

```
rule_retirement (90일+ AND ack 0)
    └─ NO ─► time_window_exclude (특정 2h 윈도우 ≥ 80%)
                └─ NO ─► threshold_uplift (auto_resolve > 90% AND ack < 5%)
                            └─ NO ─► real (진단 없음)
```

> **Mock data baseline date**: `2026-05-03 12:00 UTC` 로 hardcoded — agent 의 `alarm_age_days` 계산이 이 시점 기준. 워크샵 청중이 다른 날짜 (e.g., 2026-06+) 실행해도 이 baseline 을 사용 (legacy-2018 의 100일+ rule_retirement 매칭이 안정적).

---

## 진행 단계

### 1. 사전 확인

- [ ] `bash bootstrap.sh` 1회 통과 (`uv sync` + AWS 자격증명) — Bedrock model 접근 필요
- [ ] Bedrock model access 활성화 — Claude Sonnet 4.6 (`global.anthropic.claude-sonnet-4-6`)
- [ ] Phase 0 deploy 불필요 — Phase 1 은 mock 만 사용 (AWS 자원 무관)

### 2. Run

```bash
uv run python -m agents.monitor.local.run_local_import
```

또는 custom query:
```bash
uv run python -m agents.monitor.local.run_local_import --query "<your query>"
```

### 3. 기대 출력

```
============================================================
Monitor Agent — Phase 1 frozen baseline (mock 직접 import)
Model: global.anthropic.claude-sonnet-4-6
Query: 지난 7일 alarm history를 분석해 3가지 진단 유형으로 제안하고, real alarm은 따로 나열해줘.
============================================================

분석 중... (도구 호출 + LLM 추론, 약 5~15초)

── 1. 알람 현황 ──
🔍 알람 현황 — 지난 7일 / 총 5개
🔴 real(유효) │ 🟡 noise(개선) │ ⚠️ rule_retirement 후보(90일+) │ ★ 동일 시간대 집중

⚠️ legacy-2018-server-cpu    │ noise │ 발화 1 │ ack 0/1 │ 조치 0/1 │ 100일 │ 15시
🟡 nightly-batch-cpu         │ noise │ 발화 3 │ ack 0/3 │ 조치 0/3 │  30일 │ ★ 02시만
🟡 web-server-memory-routine │ noise │ 발화 4 │ ack 0/4 │ 조치 0/4 │  60일 │ 08·11·13·16시 분산
🔴 web-server-cpu-high       │ real  │ 발화 2 │ ack 2/2 │ 조치 2/2 │   7일 │ 09·14시
🔴 payment-api-5xx-errors    │ real  │ 발화 2 │ ack 2/2 │ 조치 2/2 │  14일 │ 11·20시

위 5개 중 noise로 분류된 3개에 대해, 왜 그렇게 판단했고 어떻게 고치면 되는지
아래에 정리합니다. real로 분류된 2개는 그대로 운영하시면 됩니다.

── 2. 개선 권고 ──

[1] legacy-2018-server-cpu — 규칙 폐기
    판단 근거: 알람 나이 100일(>= 90일), 7일간 발화 1건에 ack 0건/조치 0건. 방치된 알람.
    제안 조치: 규칙 삭제

[2] nightly-batch-cpu — 시간대 제외
    판단 근거: 7일간 발화 3건 모두 UTC 02시대(100% > 80%). 야간 배치 작업의 정상 부하 패턴.
    제안 조치: UTC 02~04시 suppression 윈도우 추가

[3] web-server-memory-routine — 임계값 상향
    판단 근거: 7일간 발화 4건 모두 auto-resolve(100% > 90%), ack 0건(0% < 5%). 임계값 70%가 정상 범위 내.
    제안 조치: 임계값 70% → P90(약 88~90%)으로 상향

이 3가지 모두 적용하면 주간 발화량 약 62% 감소 예상.

── 3. 실제로 봐야 할 알람 ──
- web-server-cpu-high
- payment-api-5xx-errors
📊 Tokens — Total: ~17,000 | Input: ~15,500 | Output: ~1,200 | Cache Read: 0 | Cache Write: 0
```

### 4. 통과 기준

- [ ] 출력 첫 글자 `─` (U+2500) 으로 시작 — 사전 narration 0
- [ ] 5개 알람 모두 분류됨 (real 2 + noise 3)
- [ ] 3가지 noise 알람의 진단 유형 정확 매칭 (legacy → 규칙 폐기, nightly-batch → 시간대 제외, memory-routine → 임계값 상향)
- [ ] 정량 근거 인용 (모호한 표현 "거의 전부" 금지)
- [ ] Section 3 에 real 2개만 나열
- [ ] Token usage ~17k total, 5~15초 응답

### 5. 다음 phase 진입

→ `docs/learn/phase2.md` (Gateway + MCP 도구 외부화)

Phase 1 의 entry (`run_local_import.py`) 는 **영구 보존** — 후속 phase 에서 회귀 격리 검증용으로 계속 호출 가능.

---

## Reference

| 자료 | 용도 |
|---|---|
| [`agents/monitor/shared/agent.py`](../../agents/monitor/shared/agent.py) | Strands Agent factory (40+ 줄) — 학습 entry |
| [`agents/monitor/shared/prompts/system_prompt_past.md`](../../agents/monitor/shared/prompts/system_prompt_past.md) | System prompt (227 줄) — WHO/WHAT/DOMAIN/HOW/FORMAT/EXAMPLE/REMINDER 흐름 |
| [`data/mock/phase1/alarm_history.py`](../../data/mock/phase1/alarm_history.py) | Mock data + ground truth + auto_resolve 패턴 docstring (271 줄) |
| [`../design/plan_summary.md`](../design/plan_summary.md) §Monitor Agent 3가지 진단 유형 | 3 type 정량 조건 표 |
