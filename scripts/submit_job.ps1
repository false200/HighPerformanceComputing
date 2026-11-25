# Run on the HOST laptop (while master is already running).
param(
  [string]$Master = "127.0.0.1:9100",
  [ValidateSet("heat2d", "batch", "irregular")]
  [string]$Kernel = "heat2d",
  [ValidateSet("campus_only", "hybrid", "cloud_only")]
  [string]$Policy = "campus_only",
  [int]$Chunks = 12,
  [double]$Deadline = 180,
  [double]$Timeout = 300,
  [string]$Token = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$env:PYTHONPATH = $Root

# If Master left default and an AWS gateway IP was saved, use it
if ($Master -eq "127.0.0.1:9100") {
  $gw = Join-Path $Root "config\aws_gateway_local.yaml"
  if (Test-Path $gw) {
    $ipLine = Select-String -Path $gw -Pattern 'gateway_public_ip:\s*"?([^"\r\n]+)"?' | Select-Object -First 1
    if ($ipLine -and $ipLine.Matches[0].Groups[1].Value) {
      $gwIp = $ipLine.Matches[0].Groups[1].Value.Trim()
      if ($gwIp -and $gwIp -ne "None") {
        $Master = "${gwIp}:9100"
        Write-Host "Using AWS gateway from config\aws_gateway_local.yaml → $Master" -ForegroundColor DarkGray
      }
    }
  }
}

if (-not $Token) { $Token = $env:HPC_JOIN_TOKEN }

Write-Host ""
Write-Host "Submitting $Kernel job ($Policy, $Chunks chunks) to $Master ..." -ForegroundColor Cyan
$clientArgs = @(
  "-3", "-m", "master.client",
  "--master", $Master,
  "--kernel", $Kernel,
  "--policy", $Policy,
  "--chunks", "$Chunks",
  "--deadline", "$Deadline",
  "--timeout", "$Timeout"
)
if ($Token) { $clientArgs += @("--token", $Token) }
py @clientArgs

if ($LASTEXITCODE -ne 0) {
  Write-Host "Job failed or timed out (exit $LASTEXITCODE)." -ForegroundColor Red
  exit $LASTEXITCODE
}
Write-Host "Done. Metrics: data\logs\metrics.csv" -ForegroundColor Green
