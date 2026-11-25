# User Guide

## Prerequisites
- Windows 10/11 (or Linux) with `g++` supporting `-fopenmp` (MSYS2 MinGW64 recommended on Windows)
- Python 3.10+
- Optional: Docker, AWS CLI (for real cloud burst)

## One-command local run
```powershell
.\scripts\run_all.ps1
```
This builds OpenMP kernels, installs deps, runs pytest, executes a hybrid demo, and writes experiment traces.

## Manual start
```powershell
.\scripts\build_kernels.ps1
py -3 -m pip install -r requirements.txt
$env:PYTHONPATH = (Get-Location)
py -3 -m master
# other terminals:
py -3 -m worker --master 127.0.0.1:9100 --auto-consent
py -3 -m master.client --kernel heat2d --policy hybrid --chunks 8
```

## Campus consent
Workers print a plain-language consent screen. Work starts only after `YES` (or `--auto-consent` for automation/tests).

## Owner controls
- Interactive keys (TTY): `p` pause, `r` resume, `l` leave, `s` status
- `--cpu-cap N` — OpenMP thread cap
- `--idle-only` — wait for low CPU busy ratio before running (override with `HPC_FORCE_BUSY` / `HPC_FORCE_IDLE`)
- below-normal process priority (default on)
- leave via key `l`, `--demo-leave-after`, or LEAVE message
- Automation: pass `--no-controls` so stdin hotkeys stay off

## Policies
- `campus_only` — no cloud overflow
- `cloud_only` — burst workers only
- `hybrid` — peer-first + policy burst

## AWS (operator-owned)
1. Build/push worker image (`docker/Dockerfile`) or bake AMI with the repo under `/opt/hpc-grid`.
2. Fill `config/default.yaml` → `burst.aws_*` placeholders.
3. Set `burst.mode: aws`.
4. Ensure master TCP port reachable from EC2.
5. Launch via burst controller (calls `scripts/aws_launch_worker.ps1`).

## Dashboard
```powershell
py -3 dashboard\app.py --port 8080
```

## Metrics
CSV: `data/logs/metrics.csv` — speedup, efficiency, reclaim recovery, cloud cost proxy, leave latency.
