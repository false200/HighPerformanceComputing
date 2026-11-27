# Deploy the Master (= AWS gateway) on EC2.
# Prerequisites: AWS CLI logged in; permissions for EC2 + SG.
# Usage:
#   .\scripts\aws_deploy_gateway.ps1
#   .\scripts\aws_deploy_gateway.ps1 -KeyName mykey -InstanceType t3.micro -Region us-east-1

param(
  [string]$Region = $(if ($env:HPC_REGION) { $env:HPC_REGION } else { "us-east-1" }),
  [string]$InstanceType = $(if ($env:HPC_INSTANCE_TYPE) { $env:HPC_INSTANCE_TYPE } else { "t3.micro" }),
  [string]$KeyName = $(if ($env:HPC_KEY_NAME) { $env:HPC_KEY_NAME } else { "" }),
  [string]$RepoUrl = $(if ($env:HPC_REPO_URL) { $env:HPC_REPO_URL } else { "https://github.com/false200/HighPerformanceComputing.git" }),
  [string]$AllowedCidr = $(if ($env:HPC_ALLOWED_CIDR) { $env:HPC_ALLOWED_CIDR } else { "0.0.0.0/0" })
)

$ErrorActionPreference = "Stop"

Write-Host "=== HPC Grid · Deploy AWS Gateway (Master) ===" -ForegroundColor Cyan
Write-Host "Region=$Region  Type=$InstanceType  CIDR=$AllowedCidr"
Write-Host "Repo=$RepoUrl"
Write-Host ""

# Amazon Linux 2023 AMI (SSM public param)
$Ami = (aws ssm get-parameters `
  --names /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 `
  --region $Region `
  --query "Parameters[0].Value" `
  --output text).Trim()
if (-not $Ami -or $Ami -eq "None") { throw "Could not resolve Amazon Linux 2023 AMI" }
Write-Host "AMI: $Ami"

$SgName = "hpc-grid-gateway-sg"
$GroupId = aws ec2 describe-security-groups `
  --region $Region `
  --filters "Name=group-name,Values=$SgName" `
  --query "SecurityGroups[0].GroupId" `
  --output text 2>$null

if (-not $GroupId -or $GroupId -eq "None") {
  Write-Host "Creating security group $SgName ..."
  $VpcId = aws ec2 describe-vpcs --region $Region --filters "Name=isDefault,Values=true" --query "Vpcs[0].VpcId" --output text
  $GroupId = aws ec2 create-security-group `
    --region $Region `
    --group-name $SgName `
    --description "HPC desktop-grid master gateway" `
    --vpc-id $VpcId `
    --query "GroupId" --output text
  aws ec2 authorize-security-group-ingress --region $Region --group-id $GroupId --protocol tcp --port 22 --cidr $AllowedCidr | Out-Null
  aws ec2 authorize-security-group-ingress --region $Region --group-id $GroupId --protocol tcp --port 9100 --cidr $AllowedCidr | Out-Null
  aws ec2 authorize-security-group-ingress --region $Region --group-id $GroupId --protocol tcp --port 8080 --cidr $AllowedCidr | Out-Null
  aws ec2 authorize-security-group-ingress --region $Region --group-id $GroupId --protocol tcp --port 9101 --cidr $AllowedCidr | Out-Null
}
Write-Host "Security group: $GroupId"

$JoinToken = if ($env:HPC_JOIN_TOKEN) { $env:HPC_JOIN_TOKEN } else { "" }
if (-not $JoinToken) {
  Write-Host "TIP: set `$env:HPC_JOIN_TOKEN before deploy for enterprise auth." -ForegroundColor Yellow
}

$TokenForBash = $JoinToken -replace "'", "'\\''"
$HasToken = if ($JoinToken) { "yes" } else { "no" }
$USERDATA = @"
#!/bin/bash
set -euo pipefail
dnf -y update || yum -y update
dnf -y install git gcc-c++ python3 python3-pip libgomp rabbitmq-server || yum -y install git gcc-c++ python3 python3-pip rabbitmq-server
systemctl enable --now rabbitmq-server || service rabbitmq-server start || true
# wait for AMQP
for i in `$(seq 1 30); do rabbitmq-diagnostics -q ping && break; sleep 1; done
cd /opt
rm -rf hpc-grid
git clone "$RepoUrl" hpc-grid
cd hpc-grid
python3 -m pip install -r requirements.txt
mkdir -p bin data/logs
g++ -O2 -std=c++17 -fopenmp -Wall kernels/omp_kernels.cpp -o bin/omp_kernels || true
export PYTHONPATH=/opt/hpc-grid
export HPC_JOIN_TOKEN='$TokenForBash'
if [ "$HasToken" = "yes" ]; then CFG=config/enterprise.aws.yaml; else CFG=config/default.yaml; fi
PUBLIC_IP=`$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4 || true)
export CFG_PATH="`$CFG"
export PUBLIC_IP
python3 <<'PY'
import os, pathlib, re
p = pathlib.Path(os.environ.get("CFG_PATH", "config/default.yaml"))
t = p.read_text()
ip = os.environ.get("PUBLIC_IP", "")
if ip:
    t = re.sub(r"advertise_host:.*", f'advertise_host: "{ip}"', t)
    t = re.sub(r"aws_master_host:.*", f'aws_master_host: "{ip}"', t)
p.write_text(t)
PY
nohup env HPC_JOIN_TOKEN='$TokenForBash' PYTHONPATH=/opt/hpc-grid python3 -m master --config "`$CFG" >/var/log/hpc-master.log 2>&1 &
nohup env HPC_JOIN_TOKEN='$TokenForBash' PYTHONPATH=/opt/hpc-grid python3 dashboard/app.py --master 127.0.0.1:9100 --port 8080 >/var/log/hpc-dash.log 2>&1 &
echo "HPC gateway started cfg=`$CFG rabbitmq=on" >> /var/log/hpc-master.log
"@

$Tmp = [System.IO.Path]::GetTempFileName() + ".sh"
# AWS expects user-data; write UTF8 no BOM
[System.IO.File]::WriteAllText($Tmp, $USERDATA)

$KeyArgs = @()
if ($KeyName) { $KeyArgs = @("--key-name", $KeyName) }

Write-Host "Launching instance..."
$InstanceId = aws ec2 run-instances `
  --region $Region `
  --image-id $Ami `
  --instance-type $InstanceType `
  --security-group-ids $GroupId `
  --user-data "file://$Tmp" `
  @KeyArgs `
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=hpc-grid-gateway}]" `
  --query "Instances[0].InstanceId" `
  --output text

Remove-Item -Force $Tmp -ErrorAction SilentlyContinue
Write-Host "Instance: $InstanceId — waiting for public IP..."
aws ec2 wait instance-running --region $Region --instance-ids $InstanceId
Start-Sleep -Seconds 5
$PublicIp = aws ec2 describe-instances `
  --region $Region `
  --instance-ids $InstanceId `
  --query "Reservations[0].Instances[0].PublicIpAddress" `
  --output text

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "  AWS GATEWAY READY (give ~2 min for install)" -ForegroundColor Green
Write-Host "  Public IP : $PublicIp" -ForegroundColor Green
Write-Host "  Workers   : Connect.bat → enter $PublicIp (+ join token if set)" -ForegroundColor Green
Write-Host "  Submit    : .\scripts\submit_job.ps1 -Master ${PublicIp}:9100" -ForegroundColor Green
Write-Host "  Health    : http://${PublicIp}:9101/health" -ForegroundColor Green
Write-Host "  Dashboard : http://${PublicIp}:8080" -ForegroundColor Green
if ($JoinToken) {
  Write-Host "  Auth      : HPC_JOIN_TOKEN is configured on the instance" -ForegroundColor Green
}
Write-Host "  Stop later: aws ec2 terminate-instances --instance-ids $InstanceId --region $Region" -ForegroundColor Yellow
Write-Host "============================================" -ForegroundColor Green

# Save for local convenience
$OutDir = Join-Path (Split-Path -Parent $PSScriptRoot) "config"
@"
# Auto-written by aws_deploy_gateway.ps1
gateway_public_ip: "$PublicIp"
gateway_instance_id: "$InstanceId"
gateway_region: "$Region"
"@ | Set-Content (Join-Path $OutDir "aws_gateway_local.yaml") -Encoding UTF8
