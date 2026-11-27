# Friend laptop → join AWS Lattice as a WORKER (donate CPU / RAM / GPU inventory).
param(
  [string]$Gateway = "",
  [string]$Name = "",
  [string]$Token = "",
  [int]$CpuCap = -1,
  [int]$RamCapMb = -1,
  [int]$MaxTasks = -1,
  [int]$Gpus = -1,
  [switch]$AutoConsent
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\common_gateway.ps1"
$Root = Get-RepoRoot
Ensure-PythonPath $Root

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Lattice — WORKER (donate compute)" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  You lend CPU/RAM to the AWS cluster." -ForegroundColor DarkGray
Write-Host "  Console: http://GATEWAY:8080" -ForegroundColor DarkGray
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

if (-not $Name) {
  $defaultName = $env:USERNAME
  if (-not $defaultName) { $defaultName = $env:COMPUTERNAME }
  if (-not $defaultName) { $defaultName = "worker-" + (Get-Random -Maximum 9999) }
  $Name = Read-Host "Your display name on the console [$defaultName]"
  if ([string]::IsNullOrWhiteSpace($Name)) { $Name = $defaultName }
}
$Name = $Name.Trim()

$logical = [Environment]::ProcessorCount
if ($logical -lt 1) { $logical = 4 }
$defCpu = [Math]::Max(1, [Math]::Floor($logical / 2))
$defRam = 4096
$defMax = 2
$defGpu = 0

function Read-IntDefault([string]$Prompt, [int]$Default) {
  $raw = Read-Host "$Prompt [$Default]"
  if ([string]::IsNullOrWhiteSpace($raw)) { return $Default }
  return [int]$raw
}

Write-Host ""
Write-Host "Resource donation (keep some free for yourself)" -ForegroundColor Yellow
Write-Host "This PC reports about $logical logical CPU cores." -ForegroundColor DarkGray
if ($CpuCap -lt 0) { $CpuCap = Read-IntDefault "CPU cores/threads to donate" $defCpu }
if ($RamCapMb -lt 0) { $RamCapMb = Read-IntDefault "RAM to donate (MiB)" $defRam }
if ($MaxTasks -lt 0) { $MaxTasks = Read-IntDefault "Max parallel tasks on this PC" $defMax }
if ($Gpus -lt 0) {
  Write-Host "GPUs: inventory only today (kernels are CPU). Enter 0 if none." -ForegroundColor DarkGray
  $Gpus = Read-IntDefault "GPUs to advertise" $defGpu
}

$ProfilePath = Join-Path $Root "config\worker_local.yaml"
@"
# Auto-saved by Worker.bat
cpu_cap: $CpuCap
ram_cap_mb: $RamCapMb
max_tasks: $MaxTasks
gpus: $Gpus
idle_only: false
below_normal_priority: true
"@ | Set-Content -Path $ProfilePath -Encoding UTF8

if (-not (Test-Path "$Root\bin\omp_kernels.exe") -and -not (Test-Path "$Root\bin\omp_kernels")) {
  Write-Host "Building OpenMP kernels..." -ForegroundColor Yellow
  & "$Root\scripts\build_kernels.ps1"
}
Write-Host "Checking Python packages..." -ForegroundColor Yellow
py -3 -m pip install -r "$Root\requirements.txt" -q

Write-Host ""
Write-Host "Connecting as WORKER '$Name' → $Master" -ForegroundColor Green
Write-Host "Donating: CPU=$CpuCap/$logical  RAM=${RamCapMb}MiB  max_tasks=$MaxTasks  gpus=$Gpus" -ForegroundColor Green
Write-Host "Controls: p=pause  r=resume  l=leave  s=status" -ForegroundColor DarkGray
Write-Host ""

$pyArgs = @(
  "-3", "-m", "worker",
  "--master", $Master,
  "--kind", "campus",
  "--name", $Name,
  "--cpu-cap", "$CpuCap",
  "--ram-cap-mb", "$RamCapMb",
  "--max-tasks", "$MaxTasks",
  "--gpus", "$Gpus",
  "--profile", $ProfilePath,
  "--token", $Token
)
# Friend UX: joining via Worker.bat implies consent to donate the caps they set.
$pyArgs += "--auto-consent"

py @pyArgs
