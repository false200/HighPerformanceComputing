# USER path: upload train.py + CSV to the *live* AWS master, then submit.
# Does NOT deploy or restart EC2. Platform must already be running; workers already connected.
param(
  [string]$Master = "127.0.0.1:9100",
  [string]$Token = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$env:PYTHONPATH = $Root

$data = Join-Path $Root "examples\logistic_regression\data\exam_pass.csv"
$train = Join-Path $Root "examples\logistic_regression\train.py"
if (-not (Test-Path $data)) {
  py -3 (Join-Path $Root "examples\logistic_regression\generate_dataset.py")
}
if (-not (Test-Path $train)) { throw "Missing $train" }

if ($Master -eq "127.0.0.1:9100") {
  $gw = Join-Path $Root "config\aws_gateway_local.yaml"
  if (Test-Path $gw) {
    $ipLine = Select-String -Path $gw -Pattern 'gateway_public_ip:\s*"?([^"\r\n]+)"?' | Select-Object -First 1
    if ($ipLine) {
      $gwIp = $ipLine.Matches[0].Groups[1].Value.Trim()
      if ($gwIp) { $Master = "${gwIp}:9100" }
    }
  }
}
if (-not $Token) { $Token = $env:HPC_JOIN_TOKEN }
if (-not $Token -and (Test-Path (Join-Path $Root "key\join_token.txt"))) {
  $Token = (Get-Content (Join-Path $Root "key\join_token.txt") -Raw).Trim()
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  USER → live platform (upload + run)" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "Master  : $Master"
Write-Host "Upload  : train.py + exam_pass.csv  (stored as INPUT on gateway)"
Write-Host "Then    : cluster shards → workers → merged model OUTPUT"
Write-Host "No EC2 redeploy / restart in this path." -ForegroundColor DarkGray
Write-Host ""

$argsList = @(
  "-3", "-m", "master.upload_job",
  "--master", $Master,
  "--train", "examples/logistic_regression/train.py",
  "--dataset", "examples/logistic_regression/data/exam_pass.csv",
  "--dataset-name", "data.csv",
  "--entrypoint", "train.py",
  "--label-col", "passed",
  "--epochs", "40",
  "--lr", "0.08",
  "--chunks", "6",
  "--policy", "campus_only"
)
if ($Token) { $argsList += @("--token", $Token) }
py @argsList
exit $LASTEXITCODE
