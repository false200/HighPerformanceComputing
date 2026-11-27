@echo off
title USER — submit test/ linear regression (100 epochs)
cd /d "%~dp0\.."
echo.
echo  USER: upload test\train.py + test\data.csv to LIVE AWS cluster
echo  100 epochs linear regression — no EC2 redeploy
echo.
set /p TOKEN="Join token (or set HPC_JOIN_TOKEN): "
if not "%TOKEN%"=="" set HPC_JOIN_TOKEN=%TOKEN%
if exist "key\join_token.txt" if "%HPC_JOIN_TOKEN%"=="" set /p HPC_JOIN_TOKEN=<key\join_token.txt
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ip='127.0.0.1:9100'; if (Test-Path config\aws_gateway_local.yaml) { $m=Select-String -Path config\aws_gateway_local.yaml -Pattern 'gateway_public_ip:\s*\"?([^\r\n\"]+)' | Select-Object -First 1; if ($m) { $ip=$m.Matches[0].Groups[1].Value.Trim()+':9100' } }; ^
   $env:PYTHONPATH=(Get-Location).Path; ^
   py -3 -m master.upload_job --master $ip --token $env:HPC_JOIN_TOKEN --name test-linreg --train test/train.py --dataset test/data.csv --dataset-name data.csv --entrypoint train.py --label-col price_k --epochs 100 --lr 0.0005 --chunks 6 --policy campus_only --deadline 300 --timeout 360"
echo.
pause
