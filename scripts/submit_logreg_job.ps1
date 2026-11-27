# USER submit: logistic regression job + dataset → existing AWS/platform.
# Does not deploy EC2. Does not join as a worker.
param(
  [string]$JobFile = "",
  [string]$Master = "127.0.0.1:9100",
  [string]$Token = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$env:PYTHONPATH = $Root

if (-not $JobFile) {
  $JobFile = Join-Path $Root "examples\logistic_regression\job.yaml"
}
if (-not (Test-Path $JobFile)) { throw "Job file not found: $JobFile" }

# Ensure dataset exists
$data = Join-Path $Root "examples\logistic_regression\data\exam_pass.csv"
if (-not (Test-Path $data)) {
  Write-Host "Generating dataset..." -ForegroundColor Yellow
  py -3 (Join-Path $Root "examples\logistic_regression\generate_dataset.py")
}

# Resolve master from saved gateway if needed
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

# Parse job.yaml (minimal YAML subset)
function Get-YamlValue([string]$text, [string]$key) {
  $m = [regex]::Match($text, "(?m)^\s*$([regex]::Escape($key))\s*:\s*(.+)\s*$")
  if (-not $m.Success) { return $null }
  return $m.Groups[1].Value.Trim().Trim('"').Trim("'")
}

$yaml = Get-Content $JobFile -Raw
$kernel = Get-YamlValue $yaml "kernel"; if (-not $kernel) { $kernel = "logreg" }
$policy = Get-YamlValue $yaml "policy"; if (-not $policy) { $policy = "campus_only" }
$chunks = [int](Get-YamlValue $yaml "chunks"); if (-not $chunks) { $chunks = 6 }
$deadline = [double](Get-YamlValue $yaml "deadline_sec"); if (-not $deadline) { $deadline = 240 }
$timeout = [double](Get-YamlValue $yaml "timeout_sec"); if (-not $timeout) { $timeout = 300 }
$dataset = Get-YamlValue $yaml "dataset"
$label = Get-YamlValue $yaml "label_col"
$epochs = Get-YamlValue $yaml "epochs"
$lr = Get-YamlValue $yaml "lr"
$nrows = Get-YamlValue $yaml "n_rows"

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  USER job: logistic regression + dataset" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "Job file : $JobFile"
Write-Host "Dataset  : $dataset"
Write-Host "Master   : $Master"
Write-Host "Platform stays up — submit only." -ForegroundColor DarkGray
Write-Host ""

$clientArgs = @(
  "-3", "-m", "master.client",
  "--master", $Master,
  "--kernel", $kernel,
  "--policy", $policy,
  "--chunks", "$chunks",
  "--deadline", "$deadline",
  "--timeout", "$timeout"
)
if ($Token) { $clientArgs += @("--token", $Token) }
if ($dataset) { $clientArgs += @("--dataset", $dataset) }
if ($label) { $clientArgs += @("--label-col", $label) }
if ($epochs) { $clientArgs += @("--epochs", "$epochs") }
if ($lr) { $clientArgs += @("--lr", "$lr") }
if ($nrows) { $clientArgs += @("--n-rows", "$nrows") }

py @clientArgs
exit $LASTEXITCODE
