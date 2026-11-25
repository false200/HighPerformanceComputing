@echo off
title HPC Grid — Deploy AWS Gateway
cd /d "%~dp0"
echo Requires AWS CLI configured (aws configure).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\aws_deploy_gateway.ps1" %*
echo.
pause
