# Phase 0 — EC2 시뮬레이터 + CloudWatch Alarm

> Phase 0 는 **라이브 alarm 발화원** 을 한 대의 **EC2 t3.micro** (Flask payment API) + **2개 CloudWatch alarm** 으로 구축. Phase 2 이후 모든 시연이 이 alarm 을 read·classify·diagnose 하므로 워크샵 첫 번째 phase.

---

## 1. 왜 필요한가   *(~2 min read)*

Phase 0 가 없으면 Phase 2 이후의 Gateway/Monitor/Incident 가 read·classify·diagnose 할 *실 alarm* 이 없음. 후속 phase 의존도:


| 후속 Phase                                  | Phase 0 산출물 의존                                |
| ----------------------------------------- | --------------------------------------------- |
| Phase 1 — 로컬 Monitor Agent (mock data)    | mock 만 사용 — 직접 의존 없음, 단 분류 패턴 학습 대상           |
| Phase 2 — Gateway + CloudWatch native API | Gateway 가 호출하는 실 alarm 으로 사용                  |
| Phase 3 — Monitor Runtime                 | Phase 2 통해 alarm read                         |
| Phase 4 — Incident Runtime                | Monitor 가 분류한 alarm 받아 진단                     |
| Phase 5 — Supervisor + A2A                | Supervisor 가 Monitor → Incident orchestration |


---

## 2. 진행 (Hands-on)   *(deploy ~3 min / 검증 ~10 min)*

### 2-1. 사전 확인

bootstrap 1회 실행 — `.env` + `uv sync` + `DEMO_USER` 결정 (Phase 0 자체는 storage backend 무관, GitHub PAT 도 불필요):

```bash
bash bootstrap.sh
```

AWS 자격증명 (`aws sts get-caller-identity` 통과).

`.env` lifecycle 자세히: `[env_config.md](env_config.md)`

### 2-2. Deploy

```bash
bash infra/ec2-simulator/deploy.sh
```

흐름 (~3분):

1. AWS 자격증명 사전 검증
2. `.env` 자동 생성 (없으면 `.env.example` 복사)
3. `DEMO_USER` 결정 + 형식 검증
4. 운영자 IP 자동 감지 (`checkip.amazonaws.com`)
5. CFN stack `ec2-simulator` (full: `aiops-demo-${DEMO_USER}-ec2-simulator`) 배포 → InstanceId, PublicIp 캡처
6. CFN stack `alarms` (full: `aiops-demo-${DEMO_USER}-alarms`) 배포
7. `.env` 갱신 (`DEMO_USER`, `EC2_INSTANCE_ID`, `EC2_PUBLIC_IP`)
8. Flask 부팅 시작 (실제 응답까지 추가 ~2-3분 — §2-3 에서 대기)

성공 시 출력 (실 화면은 `${DEMO_USER}` 가 expand 된 값. 첫 3 줄):

```
[deploy] Phase 0 배포 완료
  Payment API : http://<EIP>:8080/health
  alarm 2종   : payment-${DEMO_USER}-status-check (real) / payment-${DEMO_USER}-noisy-cpu (noise)
```

추가 5 줄: 검증 시나리오 안내 / Flask 부팅 ~2-3분 안내 / `/health` curl 예시 / 부팅 디버깅 명령 (`aws ec2 get-console-output`) / SSH 옵션 (`aws ssm get-parameter`).

deploy 후 interactive shell 에 동기 — `.env` 의 `DEMO_USER`/`EC2_INSTANCE_ID`/`EC2_PUBLIC_IP` 를 현 shell 로 export:

```bash
source .env
```

> **기존 `.env` 가 DEMO_USER 빈 상태로 deploy 이미 끝났다면** — 한 번 더 `bash infra/ec2-simulator/deploy.sh` 실행 (idempotent) 또는 수동으로 `.env` 의 `DEMO_USER=` 라인을 deploy 출력의 `demo_user=X` 값으로 채운 뒤 `source .env`.

### 2-3. 검증 — 5분 시나리오

#### Alarm 2개 존재 확인

deploy 가 만든 alarm 2개를 CloudWatch 에서 직접 조회:

```bash
aws cloudwatch describe-alarms --alarm-name-prefix "payment-${DEMO_USER}-" --region "$AWS_REGION" --query 'MetricAlarms[].[AlarmName,StateValue,MetricName]' --output table
```

기대 출력 (deploy 직후, EC2 alive — 두 alarm 모두 `OK`):

```
-----------------------------------------------------------------------------
|                              DescribeAlarms                               |
+--------------------------------------+--------+---------------------------+
| payment-${DEMO_USER}-noisy-cpu       | OK     | CPUUtilization            |
| payment-${DEMO_USER}-status-check    | OK     | StatusCheckFailed         |
+--------------------------------------+--------+---------------------------+
```

(이름은 `${DEMO_USER}` 가 expand 된 실제 값으로 나옴.)

#### `/health` 응답 확인 (Flask 부팅 ~2-3분 대기)

shell 에 `.env` 변수 export:

```bash
source .env
```

`/health` endpoint 확인:

```bash
curl http://$EC2_PUBLIC_IP:8080/health
```

기대: `{"status":"ok"}`. 부팅 timeout 시 디버깅:

```bash
aws ec2 get-console-output --instance-id "$EC2_INSTANCE_ID" --region "$AWS_REGION" --output text | tail -40
```

#### Chaos — Real alarm 발화

EC2 정지 → `payment-${DEMO_USER}-status-check` alarm fire (EvaluationPeriods=1 → ~1분 후):

```bash
bash infra/ec2-simulator/chaos/stop_instance.sh
```

alarm 발화 대기 (~1분):

```bash
sleep 90
```

alarm 상태 확인:

```bash
aws cloudwatch describe-alarms --alarm-names "payment-${DEMO_USER}-status-check" --region "$AWS_REGION" --query 'MetricAlarms[0].StateValue' --output text
```

기대: `ALARM`.

> Production 모범 사례는 `EvaluationPeriods: 2` (flap 방지). 본 데모는 워크샵 iteration 속도 위해 `1` 로 단축.

#### 복원 (선택 — workshop 종료 시 정리용)

EC2 stop / ALARM 상태가 Phase 2-5 시연의 입력 — Monitor 가 ALARM 상태의 alarm 을 읽고 Incident 가 진단하는 것이 본 데모의 본질. **workshop 종료 시까지 stop 유지**, 재시작은 정리 단계용.

```bash
bash infra/ec2-simulator/chaos/start_instance.sh
```

부팅 ~1분 후 `/health` 정상화 + alarm ~1-2분 후 `OK` 자동 복원:

```bash
curl http://$EC2_PUBLIC_IP:8080/health
```

기대: `{"status":"ok"}`.

#### 통과 기준

- EC2 + 2 alarm 배포 성공
- Flask `/health` 응답 정상
- `stop_instance.sh` → ~1분 내 `payment-${DEMO_USER}-status-check` ALARM 진입
- Phase 0 만 단독 teardown 가능 (`bash infra/ec2-simulator/teardown.sh`)

### 2-4. 다음 Phase 진입 또는 정리

**Phase 1 진행** (단독 정리 불필요 — Phase 1 은 mock 이므로 EC2 상태 무관):
→ [`phase1.md`](phase1.md)

**완전 정리** (모든 phase 자원 일괄):

```bash
bash teardown_all.sh
```

자세한 단계: [`teardown.md`](teardown.md).

---

## 3. 무엇을 만드나   *(~3 min read)*

CloudWatch alarm 두 종류 (real + noise) 가 fire 할 수 있는 최소 환경:

```
┌─────────────────────┐
│  EC2 t3.micro       │   ← Flask 결제 API 서버 (/health)
│  Amazon Linux 2023  │
│  + EIP + SSH/8080   │
└──────────┬──────────┘
           │ AWS native metric (StatusCheckFailed, CPUUtilization)
           ▼
┌──────────────────────────────────────────────┐
│  CloudWatch Alarm × 2                        │
│  ├─ payment-${DEMO_USER}-status-check (real) │   ← stop_instance.sh 시 fire
│  └─ payment-${DEMO_USER}-noisy-cpu  (noise)  │   ← 의도적 잘못된 임계값
└──────────────────────────────────────────────┘
```

**핵심 제약**: noise vs real 두 종류 alarm 을 단일 EC2 로 시연 — 후속 Monitor Agent 의 분류 학습 대상.

---

## 4. 어떻게 동작   *(~5 min read)*

### 자원 (CloudFormation 2 stack)


| Stack                                   | 자원                                                                                               |
| --------------------------------------- | ------------------------------------------------------------------------------------------------ |
| `aiops-demo-${DEMO_USER}-ec2-simulator` | EC2 t3.micro + EIP + Security Group (operator IP /32 만) + KeyPair (SSM SecureString 자동 저장)       |
| `aiops-demo-${DEMO_USER}-alarms`        | Alarm 2개 — `payment-${DEMO_USER}-status-check` (real) + `payment-${DEMO_USER}-noisy-cpu` (noise) |


### Real vs Noise 설계


|                      | Real alarm                      | Noise alarm                            |
| -------------------- | ------------------------------- | -------------------------------------- |
| 이름                   | `payment-${DEMO_USER}-status-check` | `payment-${DEMO_USER}-noisy-cpu`       |
| Metric               | `AWS/EC2 StatusCheckFailed`     | `AWS/EC2 CPUUtilization`               |
| Threshold            | `> 0` for 1× 60s                | **`> 0.5%`** (의도적 너무 낮음)               |
| `TreatMissingData`   | `breaching` (stop = 죽음 → ALARM) | `notBreaching`                         |
| Tag `Classification` | `real`                          | `noise`                                |
| Trigger 방법           | `stop_instance.sh`              | (라이브에선 거의 안 fire — Phase 1 mock 으로 학습) |


→ Monitor Agent 가 후속 phase 에서 두 alarm 의 `Classification` 태그 + 통계 패턴으로 noise/real 구분 학습.

---

## 5. References


| 자료                                                                         | 용도                                                                                                                                           |
| -------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| [`infra/ec2-simulator/README.md`](../../infra/ec2-simulator/README.md)     | 기술 reference — 파일 구성, 비용, SSH 절차                                                                                                             |
| `infra/ec2-simulator/{ec2-simulator,alarms}.yaml`                          | CFN 템플릿 원본                                                                                                                                   |
| `infra/ec2-simulator/chaos/`                                               | stop / start 스크립트                                                                                                                            |
| [`env_config.md`](env_config.md)                                           | `.env` lifecycle — Phase 0 가 채우는 entry (`DEMO_USER` / `EC2_INSTANCE_ID` / `EC2_PUBLIC_IP`) + bootstrap.sh 의 `AWS_REGION` / `STORAGE_BACKEND` |


