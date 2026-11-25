# Run on the HOST laptop (while master is already running).
param(
  [string]$Master = "127.0.0.1:9100",
  [ValidateSet("heat2d", "batch", "irregular")]
  [string]$Kernel = "heat2d",
  [ValidateSet("campus_only", "hybrid", "cloud_only")]
  [string]$Policy = "campus_only",
  [int]$Chunks = 12,
  [double]$Deadline = 180,
  [double]$Timeout = 300
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$env:PYTHONPATH = $Root

Write-Host ""
Write-Host "Submitting $Kernel job ($Policy, $Chunks chunks) to $Master ..." -ForegroundColor Cyan
py -3 -m master.client `
  --master $Master `
  --kernel $Kernel `
  --policy $Policy `
  --chunks $Chunks `
  --deadline $Deadline `
  --timeout $Timeout

if ($LASTEXITCODE -ne 0) {
  Write-Host "Job failed or timed out (exit $LASTEXITCODE)." -ForegroundColor Red
  exit $LASTEXITCODE
}
Write-Host "Done. Metrics: data\logs\metrics.csv" -ForegroundColor Green
