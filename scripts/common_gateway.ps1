# Shared helpers for Worker.bat / User.bat (friend-facing join scripts).

function Get-RepoRoot {
  return (Split-Path -Parent $PSScriptRoot)
}

function Get-GatewayIp {
  param([string]$Root)
  $gwFile = Join-Path $Root "config\aws_gateway_local.yaml"
  if (Test-Path $gwFile) {
    $line = Select-String -Path $gwFile -Pattern 'gateway_public_ip:\s*"?([^"\r\n]+)"?' | Select-Object -First 1
    if ($line -and $line.Matches[0].Groups[1].Value) {
      $ip = $line.Matches[0].Groups[1].Value.Trim()
      if ($ip -and $ip -ne "None") { return $ip }
    }
  }
  return ""
}

function Get-JoinToken {
  param([string]$Root)
  if ($env:HPC_JOIN_TOKEN) { return $env:HPC_JOIN_TOKEN.Trim() }
  $tokFile = Join-Path $Root "key\join_token.txt"
  if (Test-Path $tokFile) {
    return (Get-Content $tokFile -Raw).Trim()
  }
  return ""
}

function Resolve-MasterEndpoint {
  param([string]$Raw)
  $Raw = ($Raw -or "").Trim()
  if (-not $Raw) { throw "Gateway IP / host is required." }
  if ($Raw -match ":\d+$") { return $Raw }
  return "${Raw}:9100"
}

function Ensure-PythonPath {
  param([string]$Root)
  $env:PYTHONPATH = Join-Path $Root "backend"
  Set-Location $Root
}
