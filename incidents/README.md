# `incidents/` — 사고 사후 기록 (Phase 6a Step E)

Change Agent (`aiops_demo_${DEMO_USER}_change`) 의 `append_incident(date, body)` 도구가 **append/create write** 하는 디렉토리. Phase 6a 시점에선 비어있고, end-to-end 테스트 시 자동으로 `<YYYY-MM-DD>.log` 가 생성됨.

## 형식

`incidents/<YYYY-MM-DD>.log` — 하루치 incident 기록 markdown:

```
## <YYYY-MM-DD HH:MM> [<alarm_name>] severity=<P1|P2|P3>
- diagnosis: <한국어 1-2 문장 — Incident Agent 진단>
- regression_likelihood: <high|medium|low>
- suspected_deployment: <배포 항목 1줄 또는 null>
- recommended_actions: [<영어 동사구>, ...]
- supervisor_session: <session id 또는 null>
```

여러 incident 가 같은 날 발생하면 같은 파일에 append (`\n\n` 구분).

## 자동 생성 흐름

```
Operator CLI → Supervisor LLM
   ↓
Supervisor: call_incident_a2a('{"alarm_name": "..."}') → diagnosis JSON
   ↓
Supervisor: call_change('{"alarm_name": "...", "severity": "...", "diagnosis": "..."}')
   ↓
Change Agent LLM:
   1. get_deployments_log(date) → 회귀 분석
   2. append_incident(date, body) → ← 본 디렉토리 write
   ↓
GitHub Contents API PUT — incidents/<date>.log create or update (sha 기반)
   ↓
새 commit 자동 생성 — git pull 후 본 디렉토리에 결과 가시화
```

## 워크샵 청중 검증 (P6a-A5 acceptance)

1. Operator CLI 호출 후
2. `git pull origin main`
3. `cat incidents/$(date +%Y-%m-%d).log` — 자동 append 된 항목 확인
4. GitHub commit history — Change Agent 가 author 인 commit 확인 (PAT 의 GitHub 사용자 명의)

## 권한

- `append_incident` 는 **write** — `deployments-storage` Lambda 의 `_put_github_file()` 사용. SSM 의 PAT 가 `repo` (full) scope 필요 (Phase 4 가 `repo:read` 면 불충분).
- Phase 6a `infra/phase6a/README.md` 의 사전 조건에 PAT scope 확장 안내 있음.

## 운영 환경 적용 시

본 디렉토리는 GitHub repo 내 — workshop 데모 목적. 운영 적용 시:
- 별 audit/incident 시스템 (Linear, JIRA, Datadog) 으로 wire 변경 (Lambda handler 만 교체, agent 측 무변경)
- 또는 AgentCore Memory 로 cross-agent context 저장 (Phase 7+ 결정 — `phase6a.md` D10)
