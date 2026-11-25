# Single-run: build → install deps → pytest → local hybrid demo
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "=== 1/5 Build OpenMP kernels ==="
& "$Root\scripts\build_kernels.ps1"

Write-Host "=== 2/5 Install Python deps ==="
py -3 -m pip install -r "$Root\requirements.txt" -q

Write-Host "=== 3/5 Unit + integration tests ==="
$env:PYTHONPATH = $Root
py -3 -m pytest "$Root\tests" -q --tb=short
if ($LASTEXITCODE -ne 0) { throw "tests failed" }

Write-Host "=== 4/5 Local hybrid demo ==="
& "$Root\scripts\run_demo.ps1"
if ($LASTEXITCODE -ne 0) { throw "demo failed" }

Write-Host "=== 5/5 Experiment traces ==="
& "$Root\scripts\run_experiments.ps1"
if ($LASTEXITCODE -ne 0) { throw "experiments failed" }

Write-Host ""
Write-Host "ALL GREEN. Artifacts under data/logs and data/results."
Write-Host "AWS: configure config/default.yaml burst.aws_* then set burst.mode=aws when ready."
