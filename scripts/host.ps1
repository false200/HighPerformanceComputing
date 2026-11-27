# Host laptop: prepare + start the master. Other laptops run Connect.bat.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$env:PYTHONPATH = Join-Path $Root "backend"

function Get-LanIPv4 {
  Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object {
      $_.IPAddress -notlike "127.*" -and
      $_.PrefixOrigin -ne "WellKnown" -and
      $_.IPAddress -notlike "169.254.*"
    } |
    Sort-Object -Property InterfaceMetric |
    Select-Object -ExpandProperty IPAddress -First 3
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  HPC Grid — HOST (master laptop)" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# Deps + OpenMP binary
if (-not (Test-Path "$Root\bin\omp_kernels.exe") -and -not (Test-Path "$Root\bin\omp_kernels")) {
  Write-Host "[1/4] Building OpenMP kernels..." -ForegroundColor Yellow
  & "$Root\scripts\build_kernels.ps1"
} else {
  Write-Host "[1/4] OpenMP kernels already built." -ForegroundColor Green
}

Write-Host "[2/5] Checking Python packages..." -ForegroundColor Yellow
py -3 -m pip install -r "$Root\requirements.txt" -q

Write-Host "[3/5] Ensuring RabbitMQ (required job intake)..." -ForegroundColor Yellow
$rabbitOk = $false
try {
  py -3 -c "import pika; pika.BlockingConnection(pika.URLParameters('amqp://guest:guest@localhost:5672/')).close(); print('ok')" | Out-Null
  if ($LASTEXITCODE -eq 0) { $rabbitOk = $true }
} catch {}
if (-not $rabbitOk) {
  $docker = Get-Command docker -ErrorAction SilentlyContinue
  if ($docker) {
    $existing = docker ps -a --filter "name=lattice-rabbit" --format "{{.Names}}" 2>$null
    if ($existing -eq "lattice-rabbit") {
      docker start lattice-rabbit | Out-Null
    } else {
      Write-Host "      Starting rabbitmq:3 via Docker (lattice-rabbit)..." -ForegroundColor DarkGray
      docker run -d --name lattice-rabbit -p 5672:5672 -p 15672:15672 rabbitmq:3-management | Out-Null
    }
    Start-Sleep -Seconds 4
    try {
      py -3 -c "import pika; pika.BlockingConnection(pika.URLParameters('amqp://guest:guest@localhost:5672/')).close()" | Out-Null
      if ($LASTEXITCODE -eq 0) { $rabbitOk = $true }
    } catch {}
  }
}
if (-not $rabbitOk) {
  throw "RabbitMQ is required. Install RabbitMQ or Docker, then re-run Host.bat (expects amqp://guest:guest@localhost:5672/)."
}
Write-Host "      RabbitMQ reachable on localhost:5672" -ForegroundColor Green

Write-Host "[4/5] Opening firewall port 9100 (may need Admin once)..." -ForegroundColor Yellow
try {
  $existing = Get-NetFirewallRule -DisplayName "HPC Grid Master 9100" -ErrorAction SilentlyContinue
  if (-not $existing) {
    New-NetFirewallRule -DisplayName "HPC Grid Master 9100" -Direction Inbound -Protocol TCP -LocalPort 9100 -Action Allow | Out-Null
    Write-Host "      Firewall rule added." -ForegroundColor Green
  } else {
    Write-Host "      Firewall rule already present." -ForegroundColor Green
  }
} catch {
  Write-Host "      Could not add firewall rule (run Host.bat as Administrator once)." -ForegroundColor DarkYellow
}

$ips = @(Get-LanIPv4)
if (-not $ips -or $ips.Count -eq 0) {
  Write-Host "WARNING: No LAN IPv4 found. Workers need your Wi-Fi IP from ipconfig." -ForegroundColor Red
  $ips = @("<your-wifi-ip>")
}

Write-Host ""
Write-Host "[5/5] Starting master..." -ForegroundColor Yellow
Write-Host ""
Write-Host "--------------------------------------------" -ForegroundColor Green
Write-Host "  Tell workers to run Connect.bat" -ForegroundColor Green
Write-Host "  and enter this Master IP:" -ForegroundColor Green
foreach ($ip in $ips) {
  Write-Host "      $ip" -ForegroundColor White
}
Write-Host "  Port: 9100" -ForegroundColor Green
Write-Host "--------------------------------------------" -ForegroundColor Green
Write-Host ""
Write-Host "After workers show 'registered', submit a job in another window:" -ForegroundColor Cyan
Write-Host "  .\scripts\submit_job.ps1" -ForegroundColor White
Write-Host "  or double-click SubmitJob.bat" -ForegroundColor White
Write-Host ""
Write-Host "Press Ctrl+C to stop the master." -ForegroundColor DarkGray
Write-Host ""

py -3 -m master --config "$Root\config\default.yaml"
