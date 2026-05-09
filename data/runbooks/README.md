# Runbooks — Incident Agent 가 read 하는 진단 문서

Phase 4 의 Incident Agent (`agents/incident/`) 가 GitHub Lambda 를 통해 이 디렉토리의 markdown 을 fetch. CloudWatch alarm 의 class 별로 진단 절차 + 권장 조치를 기록.

## 파일 명명 규약

```
data/runbooks/<alarm-class>.md
```

- `<alarm-class>` = full alarm name 에서 user prefix 를 제거한 것.
- 예: alarm `payment-ubuntu-status-check` → runbook `payment-status-check.md`.
- 변환 로직: Lambda `_alarm_class()` (`infra/github-lambda/lambda_src/github_storage/handler.py`) 가 환경변수 `DEMO_USER` 로 prefix 제거.
- 모든 워크샵 청중 (`${DEMO_USER}=alice`, `${DEMO_USER}=bob`, ...) 이 동일 runbook 사용 — class 단위 user-agnostic 데이터.

## 구조 (markdown convention)

각 runbook 은 다음 5 section 권장:

1. **Alarm** — 이름 패턴, severity, trigger 조건
2. **진단 절차** — 단계별 확인 명령 + 의미
3. **권장 조치** — 우선순위 순 (시간 단위 escalation)
4. **일반적 원인** — root cause 후보들
5. **관련 alarm** + **reference** — cross-link

Incident Agent 의 system_prompt (`agents/incident/shared/prompts/system_prompt.md`) 가 이 구조를 가정하고 `recommended_actions` 배열 + `severity` 필드 추출.

## 현재 등록된 runbook

| 파일 | alarm class | severity |
|---|---|---|
| `payment-status-check.md` | `payment-status-check` | P1 |

## Phase 별 확장

| Phase | 추가 |
|---|---|
| **4 (현재)** | `payment-status-check.md` 1건 |
| 5+ (가능) | `payment-noisy-cpu.md` (noise 분류 시 운영자 안내), `payment-latency.md` |
| 6a+ (Change Agent) | `deployments/` 별 디렉토리 — 24h 배포 회귀 탐지용 |

## 추가/수정 시

1. Markdown 파일 commit + push (이 repo, branch `main`).
2. Lambda 의 `_token_cache` 가 warm container 에서 재사용 — 즉시 반영.
3. GitHub PAT (SSM `/aiops-demo/github-token`) 이 `repo:read` scope 보유 필요.

## 도구 호출 흐름

```
Incident Agent (Strands)
  → MCPClient.list_tools_sync()
  → "github-storage___get_runbook" 호출 (alarm_name 인자)
  → Gateway → Lambda (github-storage)
  → SSM 토큰 조회 (cached) → GitHub Contents API → markdown raw 반환
  → Lambda 응답: {runbook_found: true, path, content}
  → LLM 이 content 해석 → JSON schema 응답 (recommended_actions 포함)
```
