#!/usr/bin/env bash
set -euo pipefail
AMI="${HPC_AMI:-}"
TYPE="${HPC_INSTANCE_TYPE:-t3.micro}"
REGION="${HPC_REGION:-us-east-1}"
MASTER_HOST="${HPC_MASTER_HOST:?}"
MASTER_PORT="${HPC_MASTER_PORT:?}"
WORKER_ID="${HPC_WORKER_ID:?}"

if [[ -z "$AMI" || "$AMI" == *PLACEHOLDER* ]]; then
  echo "AWS AMI not configured; skipping real launch."
  exit 0
fi

USERDATA=$(cat <<EOF
#!/bin/bash
cd /opt/hpc-grid || exit 1
python3 -m worker --master ${MASTER_HOST}:${MASTER_PORT} --kind cloud --worker-id ${WORKER_ID} --auto-consent
EOF
)

aws ec2 run-instances \
  --image-id "$AMI" \
  --instance-type "$TYPE" \
  --region "$REGION" \
  --user-data "$USERDATA" \
  --count 1
