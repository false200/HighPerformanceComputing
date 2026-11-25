#!/usr/bin/env bash
# Deploy Master (= AWS gateway) on EC2. Requires AWS CLI.
set -euo pipefail
REGION="${HPC_REGION:-us-east-1}"
TYPE="${HPC_INSTANCE_TYPE:-t3.micro}"
KEY_NAME="${HPC_KEY_NAME:-}"
REPO_URL="${HPC_REPO_URL:-https://github.com/false200/HighPerformanceComputing.git}"
ALLOWED_CIDR="${HPC_ALLOWED_CIDR:-0.0.0.0/0}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

AMI=$(aws ssm get-parameters \
  --names /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 \
  --region "$REGION" --query 'Parameters[0].Value' --output text)

SG_NAME="hpc-grid-gateway-sg"
GROUP_ID=$(aws ec2 describe-security-groups --region "$REGION" \
  --filters "Name=group-name,Values=$SG_NAME" \
  --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || true)

if [[ -z "$GROUP_ID" || "$GROUP_ID" == "None" ]]; then
  VPC_ID=$(aws ec2 describe-vpcs --region "$REGION" --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)
  GROUP_ID=$(aws ec2 create-security-group --region "$REGION" --group-name "$SG_NAME" \
    --description "HPC desktop-grid master gateway" --vpc-id "$VPC_ID" --query GroupId --output text)
  aws ec2 authorize-security-group-ingress --region "$REGION" --group-id "$GROUP_ID" --protocol tcp --port 22 --cidr "$ALLOWED_CIDR"
  aws ec2 authorize-security-group-ingress --region "$REGION" --group-id "$GROUP_ID" --protocol tcp --port 9100 --cidr "$ALLOWED_CIDR"
  aws ec2 authorize-security-group-ingress --region "$REGION" --group-id "$GROUP_ID" --protocol tcp --port 8080 --cidr "$ALLOWED_CIDR"
fi

TMP=$(mktemp)
cat >"$TMP" <<EOF
#!/bin/bash
set -euo pipefail
dnf -y update || yum -y update
dnf -y install git gcc-c++ python3 python3-pip libgomp || yum -y install git gcc-c++ python3 python3-pip
cd /opt && rm -rf hpc-grid && git clone "$REPO_URL" hpc-grid && cd hpc-grid
python3 -m pip install -r requirements.txt
mkdir -p bin
g++ -O2 -std=c++17 -fopenmp -Wall kernels/omp_kernels.cpp -o bin/omp_kernels || true
export PYTHONPATH=/opt/hpc-grid
PUBLIC_IP=\$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4 || true)
nohup python3 -m master --config /opt/hpc-grid/config/default.yaml >/var/log/hpc-master.log 2>&1 &
nohup python3 dashboard/app.py --master 127.0.0.1:9100 --port 8080 >/var/log/hpc-dash.log 2>&1 &
EOF

KEY_ARGS=()
[[ -n "$KEY_NAME" ]] && KEY_ARGS=(--key-name "$KEY_NAME")

INSTANCE_ID=$(aws ec2 run-instances --region "$REGION" --image-id "$AMI" --instance-type "$TYPE" \
  --security-group-ids "$GROUP_ID" --user-data "file://$TMP" "${KEY_ARGS[@]}" \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=hpc-grid-gateway}]' \
  --query 'Instances[0].InstanceId' --output text)
rm -f "$TMP"

aws ec2 wait instance-running --region "$REGION" --instance-ids "$INSTANCE_ID"
sleep 5
PUBLIC_IP=$(aws ec2 describe-instances --region "$REGION" --instance-ids "$INSTANCE_ID" \
  --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)

cat <<MSG

============================================
 AWS GATEWAY READY (wait ~2 min for install)
 Public IP : $PUBLIC_IP
 Workers   : Connect.bat → $PUBLIC_IP
 Submit    : ./scripts/submit_job.ps1 -Master ${PUBLIC_IP}:9100
 Dashboard : http://${PUBLIC_IP}:8080
 Terminate : aws ec2 terminate-instances --instance-ids $INSTANCE_ID --region $REGION
============================================
MSG

cat >"$ROOT/config/aws_gateway_local.yaml" <<YAML
gateway_public_ip: "$PUBLIC_IP"
gateway_instance_id: "$INSTANCE_ID"
gateway_region: "$REGION"
YAML
