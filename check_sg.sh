#!/bin/bash
aws ec2 describe-security-groups \
  --filters Name=tag:Project,Values=aiops-demo \
  --region us-west-2 \
  --query "SecurityGroups[].IpPermissions[].[IpProtocol,FromPort,IpRanges[].CidrIp]" \
  --output table
