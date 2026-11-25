# User Guide

## Prerequisites
- Windows 10/11 (or Linux) with `g++` supporting `-fopenmp` (MSYS2 MinGW64 recommended on Windows)
- Python 3.10+
- Optional: Docker, AWS CLI (for real cloud burst)

## Multi-laptop (recommended for users)

1. Same repo on every laptop; same Wi‑Fi.
2. **Host laptop:** double-click `Host.bat` (run as Administrator once if firewall blocks). Note the printed IP.
3. **Other laptops:** double-click `Connect.bat`, type that IP, accept consent (`YES`).
4. **Host:** double-click `SubmitJob.bat` in a second window.

Scripts: `scripts/host.ps1`, `scripts/connect.ps1`, `scripts/submit_job.ps1`.

## One-command local run (single PC)
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

## Owner controls & resource caps
- Interactive keys (TTY): `p` pause, `r` resume, `l` leave, `s` status
- `Connect.bat` prompts (or CLI flags):
  - `--cpu-cap N` — max OpenMP threads to donate
  - `--ram-cap-mb N` — RAM budget (advertised; Windows Job Object when possible)
  - `--max-tasks N` — max concurrent tasks (use `1` on a work laptop)
  - `--gpus N` — inventory only (kernels are CPU/OpenMP today)
  - `--idle-only` — wait for low CPU busy ratio (`HPC_FORCE_BUSY` / `HPC_FORCE_IDLE` for tests)
- Profile example: `config/worker_profile.example.yaml` → saved as `config/worker_local.yaml`
- Below-normal process priority (default on)
- Automation: `--no-controls` / Connect `-SkipResourcePrompt`

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
