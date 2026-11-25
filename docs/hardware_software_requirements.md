# Hardware & Software Requirements

## Campus side
- Lab PCs or student laptops (Windows/Linux), multicore CPU
- LAN or controlled classroom network reaching the master TCP port
- Optional: idle-only / CPU-cap policies for owner QoS

## Master node
- Python 3.10+
- Reachable host for campus + cloud workers
- Disk for logs/checkpoints (`data/`)

## Build toolchain
- g++ with OpenMP (`-fopenmp`)
- CMake optional (Makefile / PowerShell build provided)

## Cloud free tier (operator)
- AWS / GCP / Azure student or free tier account
- Object storage bucket (S3-compatible) optional
- VM/container quota for 1–2 short-lived workers

## Software stack
- OpenMP C++ kernels
- Python master/worker orchestration
- Flask dashboard (optional)
- Docker worker image
- pytest for verification
