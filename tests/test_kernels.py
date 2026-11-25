from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin" / "omp_kernels.exe"
if not BIN.exists():
    BIN = ROOT / "bin" / "omp_kernels"


def _run(*args: str) -> dict:
    assert BIN.exists(), "build kernels first"
    proc = subprocess.run([str(BIN), *args], capture_output=True, text=True, cwd=str(ROOT))
    assert proc.returncode == 0, proc.stderr
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip().startswith("{")]
    assert lines, proc.stdout
    return json.loads(lines[-1])


def test_heat2d_deterministic():
    a = _run("heat2d", "--grid", "32", "--steps", "5", "--tile", "8", "--start-row", "0", "--rows", "32", "--threads", "2")
    b = _run("heat2d", "--grid", "32", "--steps", "5", "--tile", "8", "--start-row", "0", "--rows", "32", "--threads", "4")
    assert a["kernel"] == "heat2d"
    assert abs(a["checksum"] - b["checksum"]) < 1e-9
    assert a["elapsed_ms"] >= 0


def test_batch_checksum_positive():
    r = _run("batch", "--offset", "0", "--count", "4", "--length", "2000", "--threads", "2")
    assert r["kernel"] == "batch"
    assert r["checksum"] > 0


def test_irregular_runs():
    r = _run("irregular", "--seed", "9", "--work", "8000", "--threads", "2")
    assert r["kernel"] == "irregular"
    assert "checksum" in r


def test_selftest_exit_zero():
    proc = subprocess.run([str(BIN), "selftest"], capture_output=True, text=True)
    assert proc.returncode == 0
