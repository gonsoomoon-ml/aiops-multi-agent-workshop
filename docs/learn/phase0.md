# Phase 0 — EC2 시뮬레이터 + CloudWatch Alarm

> 워크샵 첫 번째 phase. 후속 모든 phase 가 의존하는 **라이브 alarm 발화원** 을 한 대의 EC2 + 2개 CloudWatch alarm 으로 구축.

---

## 무엇을 만드나

CloudWatch alarm 두 종류 (real + noise) 가 fire 할 수 있는 최소 환경:

```
┌─────────────────────┐
│  EC2 t3.micro       │   ← Flask 결제 API 서버 (/health)
│  Amazon Linux 2023  │
│  + EIP + SSH/8080   │
└──────────┬──────────┘
           │ AWS native metric (StatusCheckFailed, CPUUtilization)
           ▼
┌─────────────────────────────────────────┐
│  CloudWatch Alarm × 2                   │
│  ├─ payment-${USER}-status-check (real) │   ← stop_instance.sh 시 fire
│  └─ payment-${USER}-noisy-cpu  (noise)  │   ← 의도적 잘못된 임계값
└─────────────────────────────────────────┘
```

**핵심 제약**: noise vs real 두 종류 alarm 을 단일 EC2 로 시연 — 후속 Monitor Agent 의 분류 학습 대상.

---

## 왜 필요한가

| 후속 Phase | Phase 0 산출물 의존 |
|---|---|
| Phase 1 — 로컬 Monitor Agent (mock data) | mock 만 사용 — 직접 의존 0, 단 분류 패턴 학습 대상 |
| Phase 2 — Gateway + CloudWatch native API | Gateway 가 호출하는 실 alarm 으로 사용 |
| Phase 3 — Monitor Runtime | Phase 2 통해 alarm read |
| Phase 4 — Incident Runtime | Monitor 가 분류 한 alarm 받아 진단 |
| Phase 5 — Supervisor + A2A | Monitor → Incident orchestration |

→ Phase 0 EC2 가 살아있어야 Phase 2 이후 모든 시연 동작.

---

## 어떻게 동작

### 자원 (CloudFormation 2 stack)

| Stack | 자원 |
|---|---|
| `aiops-demo-${DEMO_USER}-ec2-simulator` | EC2 t3.micro + EIP + Security Group (operator IP /32 만) + KeyPair (SSM SecureString 자동 저장) |
| `aiops-demo-${DEMO_USER}-alarms` | Alarm 2개 — `payment-${DEMO_USER}-status-check` (real) + `payment-${DEMO_USER}-noisy-cpu` (noise) |

### Real vs Noise 설계

| | Real alarm | Noise alarm |
|---|---|---|
| 이름 | `payment-${USER}-status-check` | `payment-${USER}-noisy-cpu` |
| Metric | `AWS/EC2 StatusCheckFailed` | `AWS/EC2 CPUUtilization` |
| Threshold | `> 0` for 1× 60s | **`> 0.5%`** (의도적 너무 낮음) |
| `TreatMissingData` | `breaching` (stop = 죽음 → ALARM) | `notBreaching` |
| Tag `Classification` | `real` | `noise` |
| Trigger 방법 | `stop_instance.sh` | (라이브에선 거의 안 fire — Phase 1 mock 으로 학습) |

→ Monitor Agent 가 후속 phase 에서 두 alarm 의 `Classification` 태그 + 통계 패턴으로 noise/real 구분 학습.

---

## 진행 단계

### 1. 사전 확인

- [ ] `bash bootstrap.sh` 1회 통과 — `.env` + uv sync + `DEMO_USER` 결정 (Phase 0 자체는 storage backend 무관, GitHub PAT 도 불필요)
- [ ] AWS 자격증명 (`aws sts get-caller-identity` 통과)

### 2. Deploy

```bash
bash infra/ec2-simulator/deploy.sh
```

흐름 (~3분):
1. AWS 자격증명 사전 검증
2. `.env` 자동 생성 (없으면 .env.example 복사)
3. 운영자 IP 자동 감지 (`checkip.amazonaws.com`)
4. `DEMO_USER` 결정 + 형식 검증
5. CFN stack `ec2-simulator` 배포 → InstanceId, PublicIp 캡처
6. CFN stack `alarms` 배포
7. `.env` 갱신 (`EC2_INSTANCE_ID`, `EC2_PUBLIC_IP`)

성공 시 출력:
```
[deploy] Phase 0 배포 완료
  Payment API : http://<EIP>:8080/health
  alarm 2종   : payment-${USER}-status-check (real) / payment-${USER}-noisy-cpu (noise)
```

### 3. 검증 — 5분 시나리오

#### 3-1. `/health` 응답 확인 (Flask 부팅 ~2-3분 대기)

```bash
source .env
curl http://$EC2_PUBLIC_IP:8080/health
# 기대: {"status":"ok"}
```

부팅 디버깅 (timeout 시):
```bash
aws ec2 get-console-output --instance-id "$EC2_INSTANCE_ID" --region "$AWS_REGION" --output text | tail -40
```

#### 3-2. Chaos — Real alarm 발화

```bash
bash infra/ec2-simulator/chaos/stop_instance.sh
# 출력: alarm 'payment-${USER}-status-check' 발화까지 ~1분 대기 (EvaluationPeriods=1)
sleep 90

aws cloudwatch describe-alarms \
    --alarm-names "payment-${DEMO_USER}-status-check" \
    --region "$AWS_REGION" \
    --query 'MetricAlarms[0].StateValue' --output text
# 기대: ALARM
```

> Production 모범 사례는 `EvaluationPeriods: 2` (flap 방지). 본 데모는 워크샵 iteration 속도 위해 `1` 로 단축.

#### 3-3. 복원

```bash
bash infra/ec2-simulator/chaos/start_instance.sh
sleep 60
curl http://$EC2_PUBLIC_IP:8080/health   # 다시 ok
```

→ Alarm 도 ~1-2분 후 OK 자동 복원.

#### 3-4. 통과 기준

- [ ] EC2 + 2 alarm 배포 성공
- [ ] Flask `/health` 응답 정상
- [ ] `stop_instance.sh` → ~1분 내 `payment-${USER}-status-check` ALARM 진입
- [ ] `start_instance.sh` → OK 복원
- [ ] Phase 0 만 단독 teardown 가능 (`bash infra/ec2-simulator/teardown.sh`)

### 4. 다음 Phase 진입 또는 정리

**Phase 1 진행** (단독 정리 불필요 — Phase 1 도 EC2 alive 가정 OK):
→ `docs/learn/phase1.md`

**완전 정리** (모든 phase 자원 일괄):
→ `bash teardown_all.sh` ([`docs/learn/teardown.md`](teardown.md))

---

## Reference

| 자료 | 용도 |
|---|---|
| [`infra/ec2-simulator/README.md`](../../infra/ec2-simulator/README.md) | 기술 reference — 파일 구성, 비용, SSH 절차 |
| `infra/ec2-simulator/{ec2-simulator,alarms}.yaml` | CFN 템플릿 원본 |
| `infra/ec2-simulator/chaos/` | stop / start 스크립트 |
| [`../design/_archive/phase0_audit.md`](../design/_archive/phase0_audit.md) | 첫 설계 시 14개 review 결정 (역사 보존) |
