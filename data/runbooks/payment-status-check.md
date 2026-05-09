# Runbook — payment-*-status-check

## Alarm
- 이름 패턴: `payment-${DEMO_USER}-status-check` (e.g., `payment-ubuntu-status-check`)
- 클래스: `payment-status-check`
- Severity: **P1**
- Trigger: EC2 instance status check 실패 (1 evaluation period, 60s)

## 진단 절차

1. `aws ec2 describe-instance-status --instance-ids <instance-id>` 로 instance state + status 상세 조회.
2. **System status check** vs **Instance status check** 구분:
   - System check 실패 → AWS 인프라 이슈 (host hardware, network)
   - Instance check 실패 → OS 이슈 (kernel panic, EBS volume, network interface)
3. CloudWatch Logs `/var/log/messages` (또는 dmesg) 의 최근 5분 fetch — kernel/disk 오류 확인.
4. Auto Scaling Group 소속 여부 확인 — 소속이면 자동 교체 대기 가능.

## 권장 조치 (우선순위 순)

1. **첫 5분**: instance reboot 시도 (`aws ec2 reboot-instances --instance-ids <id>`).
2. **5분 후 미해결**: AMI 로 신규 인스턴스 launch + Auto Scaling Group 으로 교체 (또는 manual replace).
3. **30분 후 미해결**: 동료 oncall 에게 escalate. AWS Support case (severity: 긴급) open.
4. **재발 방지**: detailed monitoring 활성화 (CloudWatch agent), kernel/EBS 모니터링 alarm 추가.

## 일반적 원인 (root cause)

- Kernel panic — `/var/log/kern.log` 확인
- EBS volume I/O error — `aws ec2 describe-volumes --filters Name=attachment.instance-id,Values=<id>`
- Network interface failure — `aws ec2 describe-network-interfaces`
- 메모리 고갈 (OOM killer) — CloudWatch metric `mem_used_percent` 추세
- 호스트 hardware 문제 (드물게) — AWS 가 system status check 로 자동 감지

## 관련 alarm
- `payment-${DEMO_USER}-noisy-cpu` — CPU 고부하만 별도 분류 (대개 noise — runbook 별도)

## reference
- AWS docs: [EC2 instance status checks](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/monitoring-system-instance-status-check.html)
- 우리 시나리오: `infra/ec2-simulator/chaos/stop_instance.sh` 가 이 alarm 의 의도적 trigger
