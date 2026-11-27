$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$env:PYTHONPATH = Join-Path $Root "backend"

if (-not (Test-Path "$Root\bin\omp_kernels.exe")) {
  & "$Root\scripts\build_kernels.ps1"
}

Get-NetTCPConnection -LocalPort 9100 -ErrorAction SilentlyContinue |
  ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }

$master = Start-Process -PassThru -NoNewWindow -FilePath "py" -ArgumentList @(
  "-3", "-m", "master", "--config", "$Root\config\default.yaml"
)
Start-Sleep -Seconds 2

$workers = @()
1..2 | ForEach-Object {
  $workers += Start-Process -PassThru -NoNewWindow -FilePath "py" -ArgumentList @(
    "-3", "-m", "worker",
    "--master", "127.0.0.1:9100",
    "--kind", "campus",
    "--auto-consent",
    "--no-controls",
    "--cpu-cap", "4",
    "--name", "campus-$_"
  )
}

Start-Sleep -Seconds 2
Write-Host "Submitting hybrid heat2d job..."
py -3 -m master.client --master 127.0.0.1:9100 --kernel heat2d --policy hybrid --chunks 8 --deadline 60 --timeout 90
$code = $LASTEXITCODE

foreach ($w in $workers) {
  if (-not $w.HasExited) { Stop-Process -Id $w.Id -Force -ErrorAction SilentlyContinue }
}
if (-not $master.HasExited) { Stop-Process -Id $master.Id -Force -ErrorAction SilentlyContinue }

if ($code -ne 0) { throw "demo job failed with code $code" }
Write-Host "Demo OK"
