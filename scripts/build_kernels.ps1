$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Bin = Join-Path $Root "bin"
New-Item -ItemType Directory -Force -Path $Bin | Out-Null

$GppCandidates = @(
  "D:\mys64\mingw64\bin\g++.exe",
  "C:\msys64\mingw64\bin\g++.exe",
  "g++"
)
$Gpp = $null
foreach ($c in $GppCandidates) {
  if ($c -eq "g++") {
    $cmd = Get-Command g++ -ErrorAction SilentlyContinue
    if ($cmd) { $Gpp = $cmd.Source; break }
  } elseif (Test-Path $c) {
    $Gpp = $c; break
  }
}
if (-not $Gpp) { throw "g++ with OpenMP not found" }

$Src = Join-Path $Root "backend\kernels\omp_kernels.cpp"
$Out = Join-Path $Bin "omp_kernels.exe"
Write-Host "Compiling OpenMP kernels with $Gpp"
& $Gpp -O2 -std=c++17 -fopenmp -Wall -Wextra $Src -o $Out
if ($LASTEXITCODE -ne 0) { throw "kernel compile failed" }
Write-Host "Running selftest..."
& $Out selftest
if ($LASTEXITCODE -ne 0) { throw "kernel selftest failed" }
Write-Host "OK: $Out"
