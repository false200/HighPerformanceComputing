from __future__ import annotations

import asyncio
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin" / "omp_kernels.exe"
if not BIN.exists():
    BIN = ROOT / "bin" / "omp_kernels"


@pytest.fixture(scope="module")
def ensure_binary():
    if not BIN.exists():
        script = ROOT / "scripts" / "build_kernels.ps1"
        if script.exists():
            subprocess.run(["powershell", "-ExecutionPolicy", "Bypass", "-File", str(script)], check=True)
        else:
            pytest.skip("kernel binary missing")
    assert BIN.exists()


def test_end_to_end_campus_job(ensure_binary, tmp_path):
    """Start master + 1 campus worker, submit batch job, wait for completion."""
    env = {**dict(**{k: v for k, v in __import__("os").environ.items()}), "PYTHONPATH": str(ROOT)}
    master = subprocess.Popen(
        [sys.executable, "-m", "master", "--config", str(ROOT / "config" / "default.yaml")],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        time.sleep(2.0)
        worker = subprocess.Popen(
            [
                sys.executable, "-m", "worker",
                "--master", "127.0.0.1:9100",
                "--kind", "campus",
                "--auto-consent",
                "--no-controls",
                "--cpu-cap", "2",
            ],
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        try:
            time.sleep(1.5)
            client = subprocess.run(
                [
                    sys.executable, "-m", "master.client",
                    "--master", "127.0.0.1:9100",
                    "--kernel", "batch",
                    "--policy", "campus_only",
                    "--chunks", "4",
                    "--deadline", "60",
                    "--timeout", "60",
                ],
                cwd=str(ROOT),
                env=env,
                capture_output=True,
                text=True,
            )
            assert client.returncode == 0, client.stdout + client.stderr
            assert "submitted job" in client.stdout
        finally:
            worker.terminate()
            try:
                worker.wait(timeout=3)
            except Exception:
                worker.kill()
    finally:
        master.terminate()
        try:
            master.wait(timeout=3)
        except Exception:
            master.kill()
