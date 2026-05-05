> ⚠️ **DEPRECATED (2026-04-26 작성)** — 본 문서는 single-agent 초기 안으로, 멀티에이전트 v2(이후 `plan.md`)를 거쳐 현재의 [`plan_summary.md`](../plan_summary.md) 로 발전·재작성되었습니다. 단일 진실 원천(SoT)은 `plan_summary.md` 입니다. 본 파일은 초기 진단 유형 정의 등의 역사적 출처로만 보존됩니다. 작업 시 본 파일을 기준으로 삼지 마세요.

# Noise Alarm 탐지 Agent — AgentCore Runtime 데모 구현 계획

> Cloud Operation Group 대상 Bedrock AgentCore Runtime 교육 + AI Ops 유스케이스 데모 코드

---

## 1. 목표

**단일 Agent**(Rule Optimization, Noise Alarm 탐지)를 **로컬 Strands → AgentCore Runtime** 으로 승격 배포하는 전 과정을 터미널에서 재현 가능한 형태로 제공.

- **목적**: Strands Agent + AgentCore Runtime + Gateway(MCP) 네이티브 경험
- **AI Ops 가치**: CloudWatch Alarm 노이즈 탐지 → GitHub `diagnosis/` 리포트 자동 커밋

---

## 2. Rule Optimization Agent

모니터링 시스템에 등록된 alarm rule의 **운영 데이터를 분석해 가성 알람(noise)을 식별하고 rule 개선안을 제안**하는 AI Agent. Alarm 자체를 처리하는 것이 아니라 alarm을 만들어내는 **규칙(rule)을 최적화**하는 메타 레벨 역할이며, 운영자는 Agent의 제안을 검토·반영함으로써 **운영 인력의 반복 대응 업무**를 줄인다.

### 핵심 동작

- 일정 기간 alarm 발생 이력 수집 (CloudWatch Alarm)
- 현행 rule 정의 로드 (GitHub `rules/`)
- Alarm × Rule 매칭 후 alarm별 집계 (빈도, auto-resolve 비율, duration, ack 비율)
- 기준 충족 시 **noise 후보**로 판정
- 원인 추론 + rule 개선안 생성
- Markdown 진단 리포트를 GitHub `diagnosis/` 에 자동 커밋

### Agent가 제안하는 Rule 개선안 유형

- **Threshold 상향** — 정상 트래픽에도 반응하는 과민한 rule. **임계값을 정상 범위의 상단(예: 90-percentile)으로 올려 민감도를 낮춤**
- **조건 결합 (AND)** — 단일 metric만 보면 오탐이 잦은 경우. **다른 metric·이벤트와 동시 위반 시에만 fire 하도록 조건 결합**
- **Time window 제외** — 새벽 배치·배포 등 예측 가능한 시간대에 집중 발생. **해당 시간대에는 alarm을 suppress (무음 처리)**
- **Rule 폐기** — 장기간 ack/action이 0건으로 실무 가치가 없는 rule. **규칙 자체를 삭제하여 노이즈 원천 제거**

### 가치

- Noise 감소로 **운영 인력 피로도** 하락
- 진짜 critical alarm 가시성 회복
- Rule 품질의 **주기적 자동 재검토** 체계 확보

---

## 3. 확정 스코프


| 항목                             | 결정                                                                                                                                                       |
| ------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Agent**                      | Rule Optimization (Noise Alarm 탐지) 1종                                                                                                                    |
| **프레임워크**                      | Strands (로컬 → AgentCore Runtime 동일 코드 승격 배포)                                                                                                             |
| **툴 관리**                       | AgentCore **Gateway**에 2개 tool 등록 (MCP)                                                                                                                  |
| **Tool #1 — CloudWatch Alarm** | **Mock 메인** (Python dict, 1주치 합성 이력). Lab 1: 함수 직접 호출 / Lab 2: Lambda로 감싸 Gateway target / Lab 3: Runtime 승격 / **Bonus**: 실제 `DescribeAlarms` 1건 연동 (선택) |
| **Tool #2 — GitHub**           | 개인 repo + PAT (`repo` scope). `rules/`, `diagnosis/` 디렉터리 운용                                                                                             |
| **최종 Action**                  | 진단 결과를 GitHub `diagnosis/` 에 자동 커밋                                                                                                                       |
| **인터페이스**                      | 터미널 CLI                                                                                                                                                  |


### 아키텍처

```
[터미널 CLI]
    │
    ▼
[Rule Optimization Agent (Strands)]
    │   로컬 실행 → AgentCore Runtime 승격 배포 (동일 코드)
    ▼
[AgentCore Gateway (MCP)]
    ├─► CloudWatch Alarm Mock  (Lambda + Python dict, 합성 alarm 이력 1주치)
    └─► GitHub Tool   (Lambda + PyGithub, 실 repo)
                              │
                              ▼
                        [rules/]  — alarm rule 정의
                        [diagnosis/] — agent 자동 커밋 리포트
```

---

## 4. 사용자 시나리오

모니터링 담당자가 정례 alarm 품질 점검을 수행할 때 Rule Optimization Agent를 터미널에서 호출해, 1주치 진단 리포트를 GitHub에 자동 생성하는 흐름. 기존에 대시보드 수동 확인·엑셀 집계로 반나절 걸리던 작업을 **수 분 내 정량 데이터 기반 의사결정**으로 대체한다.

### 페르소나

- **역할**: Cloud Operation 모니터링 담당자
- **친숙**: CloudWatch Alarm 구조, GitHub PR 리뷰, 터미널 CLI
- **과제**: 주간 "가성 알람 리뷰" 정례 업무

### 트리거

- **정례** — 매주 월요일 아침 주간 점검
- **사안성** — 팀장 지시, 특정 서비스 alarm 급증 보고 접수 시

### 실행 흐름

1. **터미널에서 Agent 호출**
  ```
   $ python invoke_cli.py "최근 1주 noise alarm 진단하고 diagnosis/에 리포트 올려줘"
  ```
2. **진행 상황 스트리밍 (사용자가 실시간으로 보는 것)**
  - `→ cloudwatch.describe_alarm_history(since=7d)` — alarm 상태 변경 이력 수집 (예: 317건)
  - `→ github.list_files("rules/")` — 현행 rule 로드 (예: 18개)
  - `→ [분석]` alarm별 집계 + noise 후보 선별 중
  - `→ github.put_file("diagnosis/2026-04-23-noise.md")` — 리포트 커밋 완료
3. **터미널 요약 출력**
  - Noise 후보 N건 / 진짜 이슈 N건 / 누락 critical rule N건 식별
  - 제안 적용 시 예상 alarm 감소량 (예: "주당 ~42% 감소 예상")
  - GitHub commit URL 반환
4. **GitHub 리포트 리뷰 (브라우저)**
  - 각 noise 후보별 상세 섹션
    - 현재 rule 정의 (YAML/JSON)
    - 발생 패턴 (빈도·시간대·duration 분포)
    - Agent의 **원인 추론** — 왜 noise로 판정했는지
    - **제안 개선안** — 5가지 유형 중 해당 항목 + 구체 수치
    - 근거 데이터 (CloudWatch 콘솔 링크, 최근 상태 변경 샘플)
5. **검토 및 적용**
  - 담당자가 동의하는 제안만 `rules/` 에 PR로 반영
  - 논의 필요 항목은 팀 채널에서 토론 후 결정
  - 적용 이력은 `diagnosis/` 리포트와 연결되어 **개선 사이클 추적 가능**

### 부가 시나리오

- **범위 지정 질의** — "결제 서비스 alarm만 분석해줘" (특정 서비스/태그 한정)
- **비교 질의** — "지난주 대비 noise 증가한 alarm 보여줘" (추세 분석)
- **주기 자동 실행** — EventBridge Scheduler로 매주 자동 리포트 생성 (현 스코프 제외, 향후 확장)

### 사용자가 얻는 것

- 반나절 수작업 → **수 분 자동화**
- 주관적 "감" 기반 판단 → **정량 데이터 기반** 의사결정
- 일회성 점검 → **반복 가능한 주기 자동 진단 체계**
- 개선 제안·적용·추적이 **GitHub 이력으로 일관 관리**

---

## 5. Mock 데이터 예시 (이해관계자용)

실제 데모에서 Agent가 받아볼 **합성 alarm 15건 + 1주치 상태 변경 이력**. 4가지 rule 개선안 유형(Threshold / 조건결합 / Time window / Rule 폐기)이 모두 재현되도록 구성.

### 합성 Alarm 15건


| #   | AlarmName                   | 서비스/Metric                              | 임계     | 1주 Fire          | Auto-resolve | 평균 Duration | Ack 비율     | 예상 판정                         |
| --- | --------------------------- | --------------------------------------- | ------ | ---------------- | ------------ | ----------- | ---------- | ----------------------------- |
| 1   | `payment-api-5xx-rate`      | APIGW `5XXError` > 10                   | 10/min | 3                | 0%           | 22m         | 100%       | ✅ 정상 (진짜 이슈)                  |
| 2   | `ec2-cpu-high-web-fleet`    | EC2 `CPUUtilization` > 70%              | 70     | **142**          | 96%          | 4m          | 2%         | ⚠️ Threshold 상향               |
| 3   | `rds-prod-cpu`              | RDS `CPUUtilization` > 90%              | 90     | 5                | 40%          | 18m         | 100%       | ✅ 정상                          |
| 4   | `lambda-checkout-errors`    | Lambda `Errors` > 1                     | 1      | **87**           | 100%         | 1m          | 0%         | ⚠️ Threshold 상향               |
| 5   | `alb-target-5xx`            | ALB `HTTPCode_Target_5XX` > 5           | 5/5m   | **56**           | 89%          | 3m          | 5%         | ⚠️ 조건 결합                      |
| 6   | `nightly-batch-cpu-spike`   | EC2 `CPUUtilization` > 80%              | 80     | **49** (02-04시)  | 100%         | 12m         | 0%         | ⚠️ Time window 제외             |
| 7   | `deploy-time-5xx`           | ALB `5XXError` > 3                      | 3      | **34** (배포 시간대)  | 100%         | 2m          | 0%         | ⚠️ Time window 제외             |
| 8   | `dynamodb-throttle-orders`  | DDB `ThrottledRequests` > 0             | 0      | 8                | 50%          | 9m          | 87%        | ✅ 정상                          |
| 9   | `sqs-queue-depth-legacy-v1` | SQS `ApproximateNumberOfMessages` > 100 | 100    | **21**           | 100%         | 7m          | 0% (90일+)  | ⚠️ Rule 폐기                    |
| 10  | `old-ec2-status-check`      | EC2 `StatusCheckFailed` > 0             | 0      | **18**           | 100%         | 2m          | 0% (120일+) | ⚠️ Rule 폐기                    |
| 11  | `api-latency-p99`           | APIGW `Latency` p99 > 2000ms            | 2000   | 7                | 57%          | 14m         | 100%       | ✅ 정상                          |
| 12  | `ecs-memory-web`            | ECS `MemoryUtilization` > 60%           | 60     | **98**           | 94%          | 2m          | 3%         | ⚠️ Threshold 상향               |
| 13  | `s3-4xx-public-bucket`      | S3 `4xxErrors` > 20                     | 20     | **41**           | 76%          | 5m          | 12%        | ⚠️ 조건 결합                      |
| 14  | `rds-connections-high`      | RDS `DatabaseConnections` > 80          | 80     | **63** (출퇴근 시간대) | 100%         | 8m          | 0%         | ⚠️ Time window / Threshold    |
| 15  | `waf-blocked-requests`      | WAF `BlockedRequests` > 0               | 0      | **204**          | 100%         | 1m          | 0%         | ⚠️ Rule 폐기 or Threshold 대폭 상향 |


**판정 분포 요약**

- ✅ 정상: **4건** (1, 3, 8, 11) — 진짜 critical, Agent가 flag하면 안 됨
- ⚠️ Threshold 상향: **3건** (2, 4, 12)
- ⚠️ 조건 결합 (AND): **2건** (5, 13)
- ⚠️ Time window 제외: **3건** (6, 7, 14)
- ⚠️ Rule 폐기: **3건** (9, 10, 15)

### Mock 데이터 스키마

`describe_alarms` / `describe_alarm_history` 응답은 **AWS CloudWatch 공식 스키마**를 준수. Mock에서 추가한 보조 필드(`_ack_ratio_7d`, `_tags` 등)는 **Mock 전용**임을 명시 (실제 CW에는 없는 지표이므로 Bonus에서 real API로 전환 시 해당 필드는 사라짐).

```python
# describe_alarms 응답 한 건 예시
{
    "AlarmName": "ec2-cpu-high-web-fleet",
    "MetricName": "CPUUtilization",
    "Namespace": "AWS/EC2",
    "Threshold": 70.0,
    "ComparisonOperator": "GreaterThanThreshold",
    "EvaluationPeriods": 1,
    "Period": 300,
    "StateValue": "OK",
    "StateUpdatedTimestamp": "2026-04-22T14:12:08Z",
    # Mock 전용
    "_tags": {"service": "web", "env": "prod", "team": "platform"},
    "_ack_ratio_7d": 0.02,
}
```

`describe_alarm_history`는 위 15개 alarm에 대해 1주치 `StateUpdate` 이벤트를 합산 **약 900건** 반환 (위 테이블의 Fire 횟수 × 2 — ALARM↔OK 전환).

### Agent가 생성할 리포트 샘플 섹션

이해관계자가 실제로 받아볼 `diagnosis/2026-04-23-noise.md` 일부 예시.

```markdown
### ⚠️ ec2-cpu-high-web-fleet — Threshold 상향 권장

**현재 정의**
- Metric: AWS/EC2 CPUUtilization (Average)
- Threshold: > 70%, Period 5m, EvaluationPeriods 1

**1주 발생 패턴**
- Fire: 142건 / Auto-resolve: 96% / 평균 Duration: 4분 / Ack: 2%
- 주간 트래픽 피크(09:00-11:00, 14:00-16:00) 집중

**원인 추론**
정상 피크 트래픽의 90-percentile CPU가 73%. 현 임계 70%는 정상 부하에도 걸림.
96%가 조치 없이 자동 해소되고 ack도 2%로 실무 무시 상태.

**제안**
- Threshold: 70% → **85%** (90-percentile + 여유)
- EvaluationPeriods: 1 → **2** (단발성 스파이크 흡수)
- 예상 Fire 감소: 142 → ~8건/주 (**-94%**)
```

### 데모에서 기대되는 산출

- **총 900건** 상태 변경 이력 → **15개 alarm 집계**
- **11건 noise 후보** + **4건 정상 유지** 판정
- 제안 전부 적용 시 **예상 주간 Fire ~80% 감소**
- GitHub `diagnosis/2026-04-23-noise.md` 1개 파일로 자동 커밋

