$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$env:PYTHONPATH = $Root
New-Item -ItemType Directory -Force -Path "$Root\experiments\out" | Out-Null

function Invoke-Scenario($Name, $Policy, $Workers, $Chunks, $Kernel, $ForceBurst, $LeaveAfter) {
  Write-Host "--- experiment: $Name ---"
  Get-NetTCPConnection -LocalPort 9100 -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
  Start-Sleep -Milliseconds 500

  $master = Start-Process -PassThru -NoNewWindow -FilePath "py" -ArgumentList @(
    "-3", "-m", "master", "--config", "$Root\config\default.yaml"
  )
  Start-Sleep -Seconds 2
  $procs = @()
  # campus_only / hybrid start campus workers; cloud_only relies on burst VMs only
  if ($Policy -ne "cloud_only") {
    for ($i = 1; $i -le $Workers; $i++) {
      $args = @(
        "-3", "-m", "worker",
        "--master", "127.0.0.1:9100",
        "--kind", "campus",
        "--auto-consent",
        "--no-controls",
        "--cpu-cap", "2",
        "--name", "$Name-w$i"
      )
      if ($LeaveAfter -gt 0 -and $i -eq 1) {
        $args += @("--demo-leave-after", "$LeaveAfter")
      }
      $procs += Start-Process -PassThru -NoNewWindow -FilePath "py" -ArgumentList $args
    }
    Start-Sleep -Seconds 2
  }
  $clientArgs = @(
    "-3", "-m", "master.client",
    "--master", "127.0.0.1:9100",
    "--kernel", $Kernel,
    "--policy", $Policy,
    "--chunks", "$Chunks",
    "--deadline", "90",
    "--timeout", "120"
  )
  if ($ForceBurst -or $Policy -eq "cloud_only") { $clientArgs += "--force-burst" }
  py @clientArgs
  $code = $LASTEXITCODE
  foreach ($p in $procs) { if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue } }
  if (-not $master.HasExited) { Stop-Process -Id $master.Id -Force -ErrorAction SilentlyContinue }
  if ($code -ne 0) { throw "experiment $Name failed" }
  "$(Get-Date -Format o) $Name OK" | Add-Content "$Root\experiments\out\summary.txt"
}

Invoke-Scenario -Name "campus_only_heat" -Policy "campus_only" -Workers 2 -Chunks 8 -Kernel "heat2d" -ForceBurst $false -LeaveAfter 0
Invoke-Scenario -Name "batch_campus" -Policy "campus_only" -Workers 2 -Chunks 8 -Kernel "batch" -ForceBurst $false -LeaveAfter 0
Invoke-Scenario -Name "irregular_campus" -Policy "campus_only" -Workers 2 -Chunks 8 -Kernel "irregular" -ForceBurst $false -LeaveAfter 0
Invoke-Scenario -Name "reclaim_midjob" -Policy "hybrid" -Workers 2 -Chunks 8 -Kernel "batch" -ForceBurst $false -LeaveAfter 3
Invoke-Scenario -Name "hybrid_force_burst" -Policy "hybrid" -Workers 1 -Chunks 8 -Kernel "heat2d" -ForceBurst $true -LeaveAfter 0
Invoke-Scenario -Name "cloud_only_batch" -Policy "cloud_only" -Workers 0 -Chunks 4 -Kernel "batch" -ForceBurst $true -LeaveAfter 0

Write-Host "Writing metrics table..."
py -3 "$Root\experiments\plot_metrics.py"
Write-Host "Experiments complete. See experiments/out and data/logs/metrics.csv"
