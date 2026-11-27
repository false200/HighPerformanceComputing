# Friend laptop → join AWS Lattice as a USER and upload code + data to run.
param(
  [string]$Gateway = "",
  [string]$Token = "",
  [string]$UserName = "",
  [string]$Train = "",
  [string]$Dataset = "",
  [string]$DatasetName = "data.csv",
  [string]$Entrypoint = "train.py",
  [string]$LabelCol = "",
  [int]$Epochs = 40,
  [double]$Lr = 0.08,
  [int]$Chunks = 6,
  [string]$Policy = "campus_only",
  [double]$Timeout = 600
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\common_gateway.ps1"
$Root = Get-RepoRoot
Ensure-PythonPath $Root

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Lattice — USER (submit a job)" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Upload your Python + CSV to the live AWS cluster." -ForegroundColor DarkGray
Write-Host "  Your train.py must define: train_shard(header, rows, params)" -ForegroundColor DarkGray
Write-Host "  Console: http://GATEWAY:8080  (you appear as a user node)" -ForegroundColor DarkGray
Write-Host ""

if (-not $Gateway) { $Gateway = Get-GatewayIp $Root }
if (-not $Gateway) {
  $Gateway = Read-Host "AWS gateway public IP (from your friend / operator)"
}
$Master = Resolve-MasterEndpoint $Gateway

if (-not $Token) { $Token = Get-JoinToken $Root }
if (-not $Token) {
  $Token = Read-Host "Join token (same secret as workers + users)"
}
if (-not $Token) { throw "Join token is required." }
$env:HPC_JOIN_TOKEN = $Token

if (-not $UserName) {
  $defaultName = $env:USERNAME
  if (-not $defaultName) { $defaultName = "user" }
  $UserName = Read-Host "Your display name on the console [$defaultName]"
  if ([string]::IsNullOrWhiteSpace($UserName)) { $UserName = $defaultName }
}
$UserName = $UserName.Trim()

if (-not $Train) {
  Write-Host "Examples: examples\matmul_eliza\train.py   or   test\train.py" -ForegroundColor DarkGray
  $Train = Read-Host "Path to your train.py (code file)"
}
if (-not $Dataset) {
  Write-Host "Examples: examples\matmul_eliza\A.csv   or   test\data.csv" -ForegroundColor DarkGray
  $Dataset = Read-Host "Path to your dataset CSV"
}
if (-not $LabelCol) {
  $LabelCol = Read-Host "Label column name (last column if unsure) [tag]"
  if ([string]::IsNullOrWhiteSpace($LabelCol)) { $LabelCol = "tag" }
}

$trainPath = if ([System.IO.Path]::IsPathRooted($Train)) { $Train } else { Join-Path $Root $Train }
$dataPath = if ([System.IO.Path]::IsPathRooted($Dataset)) { $Dataset } else { Join-Path $Root $Dataset }
if (-not (Test-Path $trainPath)) { throw "train.py not found: $trainPath" }
if (-not (Test-Path $dataPath)) { throw "dataset not found: $dataPath" }

$chunksRaw = Read-Host "How many shards/chunks [$Chunks]"
if ($chunksRaw) { $Chunks = [int]$chunksRaw }

Write-Host "Checking Python packages..." -ForegroundColor Yellow
py -3 -m pip install -r "$Root\requirements.txt" -q

Write-Host ""
Write-Host "Submitting as USER '$UserName' → $Master" -ForegroundColor Green
Write-Host "  code : $trainPath" -ForegroundColor White
Write-Host "  data : $dataPath" -ForegroundColor White
Write-Host "  chunks=$Chunks  label=$LabelCol  policy=$Policy" -ForegroundColor DarkGray
Write-Host ""

py -3 -m master.upload_job `
  --master $Master `
  --token $Token `
  --user-name $UserName `
  --name $UserName `
  --train $trainPath `
  --dataset $dataPath `
  --dataset-name $DatasetName `
  --entrypoint $Entrypoint `
  --label-col $LabelCol `
  --epochs $Epochs `
  --lr $Lr `
  --chunks $Chunks `
  --policy $Policy `
  --timeout $Timeout

$code = $LASTEXITCODE
Write-Host ""
if ($code -eq 0) {
  Write-Host "Done. Watch the console: http://$($Gateway.Split(':')[0]):8080" -ForegroundColor Green
} elseif ($code -eq 3) {
  Write-Host "NO WORKERS CONNECTED — job was NOT queued." -ForegroundColor Red
  Write-Host "Have someone run Worker.bat first, then retry User.bat." -ForegroundColor Yellow
} else {
  Write-Host "Submit failed (exit $code)." -ForegroundColor Red
}
exit $code
