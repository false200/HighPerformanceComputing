"""Ops helper: wait for RabbitMQ then restart master/dashboard on this host."""
from __future__ import annotations

import os
import subprocess
import time
import urllib.request


def main() -> None:
    token = (os.environ.get("HPC_JOIN_TOKEN") or "").strip()
    if not token:
        raise SystemExit("HPC_JOIN_TOKEN required")

    import pika

    for i in range(60):
        try:
            c = pika.BlockingConnection(
                pika.URLParameters("amqp://guest:guest@localhost:5672/")
            )
            c.close()
            print(f"pika ok after {i}s")
            break
        except Exception as exc:  # noqa: BLE001
            print(f"wait {i}: {type(exc).__name__}")
            time.sleep(1)
    else:
        raise SystemExit("RabbitMQ not ready")

    out = subprocess.check_output(["ps", "-eo", "pid,cmd"], text=True)
    for line in out.splitlines():
        if "python3" in line and ("-m master" in line or "dashboard/app.py" in line):
            pid = int(line.split()[0])
            print("kill", pid)
            subprocess.call(["sudo", "kill", str(pid)])
    time.sleep(2)

    log_m = open("/tmp/hpc-master.log", "a")
    log_d = open("/tmp/hpc-dash.log", "a")
    base = ["sudo", "-E", "env", "PYTHONPATH=/opt/hpc-grid", f"HPC_JOIN_TOKEN={token}"]
    subprocess.Popen(
        base + ["python3", "-m", "master", "--config", "config/enterprise.aws.yaml"],
        stdout=log_m,
        stderr=subprocess.STDOUT,
        cwd="/opt/hpc-grid",
    )
    subprocess.Popen(
        base
        + [
            "python3",
            "dashboard/app.py",
            "--master",
            "127.0.0.1:9100",
            "--port",
            "8080",
            "--token",
            token,
        ],
        stdout=log_d,
        stderr=subprocess.STDOUT,
        cwd="/opt/hpc-grid",
    )
    time.sleep(6)
    print(urllib.request.urlopen("http://127.0.0.1:9101/health", timeout=5).read().decode())
    print(open("/tmp/hpc-master.log", encoding="utf-8", errors="ignore").read()[-600:])


if __name__ == "__main__":
    main()
