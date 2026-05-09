# `deployments/` — 24시간 배포 변경 로그 (Phase 6a Step E)

Change Agent (`aiops_demo_${DEMO_USER}_change`) 의 `get_deployments_log(date)` 도구가 read 하는 디렉토리. 운영 사고 발생 시 회귀 가능성 평가에 사용.

## 형식

`deployments/<YYYY-MM-DD>.log` — 하루치 배포 로그 markdown:

```
## <YYYY-MM-DD HH:MM> [<service>] <action>
- commit: <git sha>
- author: <name>
- status: success|failed|rolled-back
- summary: <한 줄 설명>
```

각 항목은 `##` 헤더로 시작 — Change Agent LLM 이 시간 + service 정보를 파싱.

## 워크샵 시드 데이터

본 디렉토리의 `*.log` 는 **mock** 데이터 — 실제 배포 시스템 (CodeDeploy, Argo, etc.) 과 연동되지 않음. 워크샵에서 Change Agent 의 회귀 검출 데모를 위한 최소 시나리오:

- **`2026-05-09.log`** (오늘) — 결제 시스템에 의심스러운 배포 1건 + 정상 배포 2건. Change Agent 가 `payment-ubuntu-status-check` alarm 과 14:25 결제 배포를 매칭 → `regression_likelihood: high` 반환.
- **`2026-05-08.log`** (어제) — 전부 정상 — Change Agent 가 `regression_likelihood: low` 반환하는 비교 케이스.

## Change Agent 가 호출하는 흐름

```
Supervisor (LLM) → call_change tool 호출
   ↓
Change Agent (LLM) → get_deployments_log(date="2026-05-09") 호출
   ↓
Gateway → deployments-storage Lambda → GitHub Contents API
   ↓
this directory 의 2026-05-09.log → content 반환
   ↓
Change Agent (LLM) → 분석 → append_incident(date, body) → incidents/2026-05-09.log
```

## 운영 환경에서의 변환

워크샵 외 운영 적용 시:
1. CodeDeploy / Argo / Spinnaker 등의 CD 시스템에서 webhook → `deployments-storage` Lambda 가 본 디렉토리에 자동 append
2. 또는 본 Lambda 의 `get_deployments_log` 가 GitHub 대신 다른 source (RDS, OpenSearch) 호출하도록 교체 — Phase 6a 의 도구 schema (`{date}` 입력 → log content 출력) 만 유지하면 agent 측 변경 0
