#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$ROOT/bin"
CXX="${CXX:-g++}"
"$CXX" -O2 -std=c++17 -fopenmp -Wall -Wextra "$ROOT/kernels/omp_kernels.cpp" -o "$ROOT/bin/omp_kernels"
"$ROOT/bin/omp_kernels" selftest
echo "OK: $ROOT/bin/omp_kernels"
