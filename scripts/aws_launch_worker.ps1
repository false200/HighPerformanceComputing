# Operator-owned AWS burst launch stub.
# Fill placeholders in config/default.yaml (ami, sg, subnet) then run with AWS CLI configured.
$ErrorActionPreference = "Stop"
$Ami = $env:HPC_AMI
$Type = if ($env:HPC_INSTANCE_TYPE) { $env:HPC_INSTANCE_TYPE } else { "t3.micro" }
$Region = if ($env:HPC_REGION) { $env:HPC_REGION } else { "us-east-1" }
$MasterHost = $env:HPC_MASTER_HOST
$MasterPort = $env:HPC_MASTER_PORT
$WorkerId = $env:HPC_WORKER_ID

if (-not $Ami -or $Ami -like "*PLACEHOLDER*") {
  Write-Host "AWS AMI not configured. Skipping real launch. Configure config/default.yaml burst.aws_* and re-run."
  exit 0
}

$USERDATA = @"
#!/bin/bash
cd /opt/hpc-grid || exit 1
python3 -m worker --master ${MasterHost}:${MasterPort} --kind cloud --worker-id ${WorkerId} --auto-consent
"@
$UserDataB64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($USERDATA))

Write-Host "Launching EC2 worker $WorkerId ($Type) in $Region ..."
aws ec2 run-instances `
  --image-id $Ami `
  --instance-type $Type `
  --region $Region `
  --user-data $UserDataB64 `
  --count 1 `
  --query "Instances[0].InstanceId" `
  --output text
