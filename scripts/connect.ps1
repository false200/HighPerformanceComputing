# Worker laptop: prepare + join the master's peer pool.
param(
  [string]$MasterIP = "",
  [string]$Name = "",
  [switch]$AutoConsent
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$env:PYTHONPATH = $Root

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  HPC Grid — CONNECT (worker laptop)" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

if (-not $MasterIP) {
  $MasterIP = Read-Host "Enter the Master laptop IP (shown on the Host screen)"
}
$MasterIP = $MasterIP.Trim()
if (-not $MasterIP) {
  throw "Master IP is required."
}
if ($MasterIP -match "^\d+\.\d+\.\d+\.\d+$") {
  $Master = "${MasterIP}:9100"
} elseif ($MasterIP -match ":\d+$") {
  $Master = $MasterIP
} else {
  $Master = "${MasterIP}:9100"
}

if (-not $Name) {
  $Name = $env:COMPUTERNAME
  if (-not $Name) { $Name = "worker-" + (Get-Random -Maximum 9999) }
}

# Deps + OpenMP binary
if (-not (Test-Path "$Root\bin\omp_kernels.exe") -and -not (Test-Path "$Root\bin\omp_kernels")) {
  Write-Host "[1/3] Building OpenMP kernels..." -ForegroundColor Yellow
  & "$Root\scripts\build_kernels.ps1"
} else {
  Write-Host "[1/3] OpenMP kernels already built." -ForegroundColor Green
}

Write-Host "[2/3] Checking Python packages..." -ForegroundColor Yellow
py -3 -m pip install -r "$Root\requirements.txt" -q

Write-Host "[3/3] Connecting to master at $Master as '$Name'..." -ForegroundColor Yellow
Write-Host ""
Write-Host "Controls after join:  p=pause  r=resume  l=leave  s=status" -ForegroundColor DarkGray
Write-Host "Press Ctrl+C or type l then Enter to leave the pool." -ForegroundColor DarkGray
Write-Host ""

$args = @(
  "-3", "-m", "worker",
  "--master", $Master,
  "--kind", "campus",
  "--name", $Name
)
if ($AutoConsent) {
  $args += "--auto-consent"
}

py @args
