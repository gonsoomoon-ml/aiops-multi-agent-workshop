# Phase 0 — EC2 시뮬레이터 + CloudWatch Alarm

Phase 0은 AIOps 데모의 **라이브 alarm 발화원**을 한 대의 EC2 시뮬레이터로 만든다. 동료의 EC mall이 합류하기 전(Phase 7) 까지 데모는 이 EC2 한 대만으로 incident 시나리오를 재현한다. **노이즈 1종 + 실알람 1종** 의 minimum 구성이다.

목적
- Phase 1의 Monitor Agent가 학습하는 분류 패턴(real vs noise) 의 **라이브 데이터 출처**
- Phase 2 이후 Gateway·Runtime 통합 시 **CloudWatch native API** 로 호출되는 실제 alarm

## 1. 구성

| 자원 | 종류 | 비고 |
| --- | --- | --- |
| EC2 인스턴스 | t3.micro (Amazon Linux 2023) | EIP 부착, KeyPair 자동 생성, user_data로 Flask `/health` 부팅 |
| Security Group | 22 + 8080 ingress | 운영자 IP `/32` 만 허용 (자동 감지) |
| KeyPair | `aiops-demo-${DEMO_USER}-keypair` | CFN이 SSM `/ec2/keypair/<id>` 에 PEM 저장 |
| 알람 1 — `payment-${DEMO_USER}-status-check` | **real** | `AWS/EC2 StatusCheckFailed > 0` for 2× 60s. chaos 트리거 대상 |
| 알람 2 — `payment-${DEMO_USER}-noisy-cpu` | **noise** | `AWS/EC2 CPUUtilization > 0.5%` — 정상 운영 중에도 자주 fire (분류 학습용) |

CloudFormation 스택 2개 (시연자 충돌 방지를 위해 `${DEMO_USER}` 포함):
- `aiops-demo-${DEMO_USER}-phase0-ec2` — `ec2-simulator.yaml`
- `aiops-demo-${DEMO_USER}-phase0-alarms` — `alarms.yaml`

`DEMO_USER` 는 `.env` 또는 `export DEMO_USER=...` 로 지정. 미설정 시 OS user(`$USER`) 자동 사용. 영문/숫자/하이픈 ≤ 16자.

모든 리소스에 `Project=aiops-demo` + `User=${DEMO_USER}` 태그.

**예상 비용**: t3.micro ~$0.0104/h + EIP (인스턴스에 부착되어 있는 동안 무료) + CloudWatch alarm 2개 ($0.10/month/alarm). 24h 띄워둬도 ~$0.25 미만.

## 2. 배포

**사전 조건**
- [ ] `bash bootstrap.sh` 1회 실행 완료 (`.env` 생성 + uv sync + GitHub PAT SSM 저장)
- [ ] AWS 자격증명 (`aws sts get-caller-identity` 통과)

**명령**
```bash
bash infra/ec2-simulator/deploy.sh
```

배포 흐름 (deploy.sh 내부):
1. AWS 자격증명 사전 검증 (fail-fast)
2. `.env` 미존재 시 `.env.example` 자동 복사
3. 운영자 IP 자동 감지 (`https://checkip.amazonaws.com`) — 실패 시 `ALLOWED_SSH_IP` env로 직접 지정 가능
4. `DEMO_USER` 결정 (`.env` 값 → 미설정 시 OS user) + 형식 검증
5. CFN 스택 1: `aiops-demo-${DEMO_USER}-phase0-ec2` 배포
6. `.env` 자동 갱신 (`EC2_INSTANCE_ID`, `EC2_PUBLIC_IP`)
7. CFN 스택 2: `aiops-demo-${DEMO_USER}-phase0-alarms` 배포

배포 직후 Flask 부팅에 **약 2~3분** 소요 (user_data 안에서 `pip install flask` + systemd 등록).

부팅 디버깅:
```bash
aws ec2 get-console-output --instance-id "$EC2_INSTANCE_ID" --region "$AWS_REGION" --output text | tail -40
```

### 2-1. (선택) SSH 접속

데모는 `/health` HTTP만 사용하므로 SSH는 불필요. 다만 EC2 내부 디버깅이 필요하면 KeyPair PEM을 SSM에서 추출:

```bash
KEY_PAIR_ID="$(aws ec2 describe-key-pairs \
    --key-names "aiops-demo-${DEMO_USER}-keypair" \
    --region "$AWS_REGION" \
    --query 'KeyPairs[0].KeyPairId' --output text)"

aws ssm get-parameter \
    --name /ec2/keypair/$KEY_PAIR_ID \
    --with-decryption \
    --query Parameter.Value --output text \
    > aiops-demo.pem
chmod 400 aiops-demo.pem

ssh -i aiops-demo.pem ec2-user@$EC2_PUBLIC_IP
```

PEM 파일은 `.gitignore` 처리 또는 사용 후 삭제 권장.

## 3. 검증

### 3-1. /health 정상 응답

```bash
source .env
curl http://$EC2_PUBLIC_IP:8080/health
# 기대: {"status":"ok"}
```

### 3-2. Chaos — EC2 stop → real alarm 발화

```bash
bash infra/ec2-simulator/chaos/stop_instance.sh
sleep 120                       # EvaluationPeriods=2 × Period=60s

aws cloudwatch describe-alarms \
    --alarm-names "payment-${DEMO_USER}-status-check" \
    --region us-west-2 \
    --query 'MetricAlarms[0].StateValue' \
    --output text
# 기대: ALARM
```

### 3-3. 복원

```bash
bash infra/ec2-simulator/chaos/start_instance.sh
sleep 60
curl http://$EC2_PUBLIC_IP:8080/health   # 다시 ok
```

### 3-4. Noise alarm 라벨 확인 (라이브 fire 비대상)

`payment-${DEMO_USER}-noisy-cpu`는 의도적으로 잘못된 임계값(`CPUUtilization > 0.5%`)을 가진 noise 라벨 알람. 실측 t3.micro Flask idle CPU 가 **평균 0.001% 미만**으로 임계값보다 훨씬 낮아 라이브 환경에선 사실상 fire 하지 않습니다 — Phase 0 라이브 시연의 핵심은 `payment-${DEMO_USER}-status-check` (real) 트리거이며, **noise 분류 학습/검증은 Phase 1 mock 데이터(5 알람 × 24 events)** 가 담당합니다.

이 알람의 라이브 가치는 (a) Phase 2 Monitor Agent 가 *"이 알람의 Tags.Classification=noise 라벨"* 을 함께 가져와 분류 출력에 반영할 수 있는지, (b) 두 알람을 동시에 본 상태에서 real 만 "실제로 봐야 할 알람" 으로 골라내는지 검증하는 것.

라벨 확인:

```bash
aws cloudwatch describe-alarms \
    --alarm-names "payment-${DEMO_USER}-noisy-cpu" \
    --region us-west-2 \
    --query 'MetricAlarms[0].[AlarmName,StateValue]' --output table
# 기대: payment-ubuntu-noisy-cpu | OK
```

### 3-5. 통과 기준

- [ ] EC2 + 2종 alarm 배포 성공
- [ ] Flask `/health` 응답 정상
- [ ] `stop_instance.sh` 실행 후 2분 이내 `payment-${DEMO_USER}-status-check` ALARM 진입
- [ ] `start_instance.sh` 실행 후 OK 복원
- [ ] `teardown.sh` 실행 후 모든 리소스 삭제 (CloudFormation 콘솔 확인)

통과 시 → **Phase 1 (Monitor Agent 로컬, Strands + 3가지 진단 유형, Track B mock 검증)** 이미 완료된 상태이므로 Phase 2 진입 가능.

## 4. 정리

```bash
bash infra/ec2-simulator/teardown.sh
```

수행:
1. `aiops-demo-${DEMO_USER}-phase0-alarms` 스택 삭제 (alarm 2개)
2. `aiops-demo-${DEMO_USER}-phase0-ec2` 스택 삭제 (EC2 + EIP + SG + KeyPair)
3. `.env` 의 `EC2_INSTANCE_ID`, `EC2_PUBLIC_IP` 비움

KeyPair PEM이 보관된 SSM 파라미터 `/ec2/keypair/<id>` 는 CFN이 KeyPair 삭제 시 자동 삭제. 별도 정리 불필요.
