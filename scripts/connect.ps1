# Worker laptop: prepare + join the master's peer pool (with resource donation prompts).
param(
  [string]$MasterIP = "",
  [string]$Name = "",
  [string]$Token = "",
  [int]$CpuCap = -1,
  [int]$RamCapMb = -1,
  [int]$MaxTasks = -1,
  [int]$Gpus = -1,
  [switch]$IdleOnly,
  [switch]$AutoConsent,
  [switch]$SkipResourcePrompt
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$env:PYTHONPATH = $Root
$ProfilePath = Join-Path $Root "config\worker_local.yaml"

function Read-IntDefault([string]$Prompt, [int]$Default) {
  $raw = Read-Host "$Prompt [$Default]"
  if ([string]::IsNullOrWhiteSpace($raw)) { return $Default }
  return [int]$raw
}

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

if (-not $Token) { $Token = $env:HPC_JOIN_TOKEN }
if (-not $Token) {
  $Token = Read-Host "Join token (from your operator / AWS gateway — leave blank for open lab masters)"
}
if ($Token) { $env:HPC_JOIN_TOKEN = $Token }

$logical = [Environment]::ProcessorCount
if ($logical -lt 1) { $logical = 4 }

# Load previous profile defaults if present
$prevCpu = [Math]::Max(1, [Math]::Floor($logical / 2))
$prevRam = 4096
$prevMax = 1
$prevGpu = 0
if (Test-Path $ProfilePath) {
  try {
    $lines = Get-Content $ProfilePath
    foreach ($ln in $lines) {
      if ($ln -match '^\s*cpu_cap:\s*(\d+)') { $prevCpu = [int]$Matches[1] }
      if ($ln -match '^\s*ram_cap_mb:\s*(\d+)') { $prevRam = [int]$Matches[1] }
      if ($ln -match '^\s*max_tasks:\s*(\d+)') { $prevMax = [int]$Matches[1] }
      if ($ln -match '^\s*gpus:\s*(\d+)') { $prevGpu = [int]$Matches[1] }
    }
  } catch {}
}

if (-not $SkipResourcePrompt -and $CpuCap -lt 0) {
  Write-Host ""
  Write-Host "Resource donation (keep some CPU/RAM free for your own work)" -ForegroundColor Yellow
  Write-Host "This PC reports about $logical logical CPU cores." -ForegroundColor DarkGray
  Write-Host "GPUs: current jobs are CPU/OpenMP only — GPU count is inventory, not used yet." -ForegroundColor DarkGray
  $CpuCap = Read-IntDefault "CPU cores/threads to donate" $prevCpu
  $RamCapMb = Read-IntDefault "RAM to donate (MiB)" $prevRam
  $MaxTasks = Read-IntDefault "Max parallel tasks (1 recommended on a work laptop)" $prevMax
  $Gpus = Read-IntDefault "GPUs to advertise (0 = none / unused)" $prevGpu
  $idleAns = Read-Host "Idle-only mode? only run when PC looks idle (y/N)"
  if ($idleAns -match '^(y|yes)$') { $IdleOnly = $true }
} else {
  if ($CpuCap -lt 0) { $CpuCap = $prevCpu }
  if ($RamCapMb -lt 0) { $RamCapMb = $prevRam }
  if ($MaxTasks -lt 0) { $MaxTasks = $prevMax }
  if ($Gpus -lt 0) { $Gpus = $prevGpu }
}

$idleYaml = if ($IdleOnly) { "true" } else { "false" }
@"
# Auto-saved by Connect.bat — edit freely or delete to reset prompts.
cpu_cap: $CpuCap
ram_cap_mb: $RamCapMb
max_tasks: $MaxTasks
gpus: $Gpus
idle_only: $idleYaml
below_normal_priority: true
"@ | Set-Content -Path $ProfilePath -Encoding UTF8

Write-Host ""
Write-Host "Donating: CPU=$CpuCap/$logical  RAM=${RamCapMb}MiB  max_tasks=$MaxTasks  gpus=$Gpus" -ForegroundColor Green
Write-Host "Saved profile: config\worker_local.yaml" -ForegroundColor DarkGray
Write-Host ""

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
  "--profile", $ProfilePath
)
if ($Token) { $pyArgs += @("--token", $Token) }
if ($IdleOnly) { $pyArgs += "--idle-only" }
if ($AutoConsent) { $pyArgs += "--auto-consent" }

py @pyArgs
