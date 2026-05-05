#!/bin/bash
# 두 알람 상태 한 번에 확인
DEMO_USER="${DEMO_USER:-${USER:-ubuntu}}"
aws cloudwatch describe-alarms \
  --alarm-names "payment-${DEMO_USER}-status-check" "payment-${DEMO_USER}-noisy-cpu" \
  --region us-west-2 \
  --query 'MetricAlarms[].[AlarmName,StateValue,StateReason]' \
  --output table
