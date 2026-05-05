#!/bin/bash
aws ec2 describe-instances \
  --filters Name=tag:Project,Values=aiops-demo \
  --region us-west-2 \
  --query "Reservations[].Instances[].[InstanceId,State.Name,Tags[?Key=='User']|[0].Value,Tags[?Key=='Name']|[0].Value]" \
  --output table
