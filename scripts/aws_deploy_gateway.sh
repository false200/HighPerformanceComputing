#!/usr/bin/env bash
# Canonical deploy is scripts/aws_deploy_gateway.ps1 (DeployGateway.bat).
# This stub avoids a second, drift-prone userdata copy on Windows-first workflows.
echo "Use: powershell -File scripts/aws_deploy_gateway.ps1" >&2
echo "Or on Windows: DeployGateway.bat" >&2
exit 1
