# Architecture — Hybrid Consent-Driven Desktop Grid

End-to-end design of the campus-first desktop grid with OpenMP workers and policy-driven cloud-burst overflow. This document is the source of truth for how the system is modeled and built. The [README](../README.md) only shows diagrams and entry points.

---

## 1. Problem model

Campus lab/student machines hold spare CPU, but owners may reclaim at any moment. Continuous public-cloud execution is expensive. The system therefore:

1. Runs work only after **explicit consent** on campus peers.
2. Uses **OpenMP** for shared-memory speedup *inside* each worker.
3. Distributes independent **task chunks** across nodes (queue, not MPI).
4. Treats **reclaim as normal** (checkpoint + requeue).
5. **Bursts** to short-lived cloud workers only under policy pressure.

Out of scope: tightly coupled MPI over student Wi-Fi, untrusted binary marketplaces, always-on hyperscale hosting.

---

## 2. Logical system (four parts)

| Part | Role |
|------|------|
| **Master / Coordinator** | Accept jobs, partition tasks, peer-first schedule, reclaim, burst policy, merge metrics/results |
| **Campus worker** | Consent UI, owner QoS, heartbeat, OpenMP kernel execution, pause/leave |
| **Cloud-burst worker** | Same worker image (`--kind cloud`), system-launched, auto-retired when idle |
| **Cloud support** | Object storage (local or S3) for checkpoints/results; optional dashboard |

```text
                    ┌─────────────────────────────┐
                    │     Operator / Client       │
                    │  submit job · force-burst   │
                    └──────────────┬──────────────┘
                                   │ JOB_SUBMIT
                                   ▼
┌──────────────────────────────────────────────────────────────────┐
│                         MASTER NODE                              │
│  Scheduler (peer-first) · Reclaim manager · Burst controller     │
│  Metrics collector · Object store writer · TCP :9100              │
└───────────────┬────────────────────────────┬─────────────────────┘
                │ TASK_ASSIGN / HEARTBEAT    │ launch / retire
     ┌──────────┴──────────┐      ┌──────────┴──────────┐
     ▼                     ▼      ▼                     ▼
┌─────────────┐      ┌─────────────┐   ┌─────────────┐   ┌──────────┐
│ Campus W1   │ …    │ Campus Wn   │   │ Cloud VM 1  │…  │ Cloud Vk │
│ consent+QoS │      │ OpenMP      │   │ same image  │   │          │
└─────────────┘      └─────────────┘   └─────────────┘   └──────────┘
                                   │
                                   ▼
                         Checkpoints / Results
                         (local data/ or S3)
```

---

## 3. Layered software architecture

| Layer | Contents | Key paths |
|-------|----------|-----------|
| **Presentation / ops** | Consent text, stdin controls, Flask dashboard, CLI client | `worker/consent.py`, `worker/agent.py`, `dashboard/app.py`, `master/client.py` |
| **Orchestration** | Job partition, peer-first assign, reclaim, burst evaluate/launch/retire | `master/server.py`, `master/scheduler.py`, `master/burst.py` |
| **Ray-inspired core** | Logical resources, ObjectRef + lineage, GCS metadata, max_retries, pack/spread | `master/resources.py`, `object_ref.py`, `gcs.py` — see [`ray_inspired_core.md`](ray_inspired_core.md) |
| **Execution** | OpenMP scientific kernels invoked as a native binary | `kernels/omp_kernels.cpp` → `bin/omp_kernels` |
| **Platform** | JSON/TCP protocol, local/S3 object store, Docker/AWS launch stubs, config | `protocol/`, `master/storage.py`, `docker/`, `scripts/aws_*`, `config/default.yaml` |

Data plane (task payloads, checkpoints, results) and control plane (heartbeats, pause/leave, burst) share the same TCP JSON line protocol for simplicity on a classroom LAN.

---

## 4. Parallelism model

```text
Job
 └─ Task queue (across machines)     ← churn-tolerant; reclaim requeues
      └─ Worker process
           └─ OpenMP region            ← local multicore; thread-capped by owner QoS
```

- **Across nodes:** independent chunks (heat strip / batch slice / irregular seed).
- **Inside node:** `#pragma omp` in C++ kernels.
- **Not default:** MPI between student laptops.

Capability-aware sizing: scheduler sets `params.threads` from `min(cores, cpu_cap)`.

---

## 5. End-to-end runtime flow

1. **Consent** — Campus worker shows disclosure; work only after `YES` (or `--auto-consent` for automation).
2. **Register** — Worker advertises cores, memory, OS, CPU cap, idle-only, kind (`campus`|`cloud`).
3. **Submit** — Operator/client sends `JOB_SUBMIT` (`kernel`, `policy`, `chunks`, `deadline`).
4. **Partition** — Master builds task specs (`partition_job` in `master/server.py`).
5. **Peer-first schedule** — Prefer consented idle campus workers; fall back to cloud under hybrid/cloud_only.
6. **Execute** — Worker runs `omp_kernels` with OpenMP; optional mid-task checkpoint.
7. **Heartbeat / reclaim** — Missed heartbeats or owner `LEAVE` requeue unfinished tasks; recovery time measured until re-complete.
8. **Burst** — If peers low, reclaim rate high, deadline at risk, or force-burst: launch cloud workers (`local_sim` or AWS script).
9. **Aggregate** — Results + checksum; metrics CSV/JSON; idle cloud VMs retired after timeout.

### Owner controls (campus)

| Input | Effect |
|-------|--------|
| `p` / `r` | Pause / resume accepting tasks (also told to master) |
| `l` | One-click leave → checkpoint + LEAVE + requeue |
| `s` | Local status |
| `--cpu-cap N` | Caps OpenMP threads |
| `--idle-only` | Wait until CPU busy ratio is low |
| Below-normal priority | Default on Windows/Linux |

---

## 6. Protocol

**Transport:** TCP, newline-delimited JSON, master port **9100**.

| Type | Direction | Purpose |
|------|-----------|---------|
| `REGISTER` / `REGISTER_ACK` | W→M / M→W | Join pool with capabilities + consent |
| `HEARTBEAT` | W→M | Liveness (no ACK; avoids RPC races) |
| `TASK_ASSIGN` | M→W | Kernel + params |
| `TASK_CHECKPOINT` | W→M | Partial state → object store |
| `TASK_RESULT` | W→M | Checksum + timing |
| `PAUSE` / `RESUME` / `LEAVE` | W→M | Owner QoS / reclaim |
| `JOB_SUBMIT` / `JOB_STATUS` | Client→M | Job lifecycle |
| `FORCE_BURST` / `METRICS` | Client→M | Experiments / dashboard |
| `SHUTDOWN` | Either | Tear down |

Worker I/O design: **single reader loop** demuxes push messages (`TASK_ASSIGN`) vs RPC replies so heartbeats never steal task traffic.

---

## 7. Burst policy

Burst when **any** configured condition holds (and under `max_cloud_vms`):

- Campus peers below `min_campus_peers`
- Sustained reclaim rate ≥ `reclaim_rate_threshold`
- Projected finish > deadline
- Operator `FORCE_BURST`

Prefer campus when healthy. Retire cloud workers after `cloud_idle_timeout_sec` with no assigned work.

| Mode | Behavior |
|------|----------|
| `local_sim` (default) | Master spawns `python -m worker --kind cloud` locally |
| `aws` | Invokes `scripts/aws_launch_worker.(ps1\|sh)` with AMI/region env (operator-filled) |

Policies: `campus_only` · `hybrid` · `cloud_only`.

---

## 8. Storage & metrics

**Object store** (`master/storage.py`): always writes under `data/`; optionally mirrors to S3 when `storage.backend: s3`.

**Metrics** (`master/metrics.py` → `data/logs/metrics.csv`):

- Wall time, serial proxy (sum of kernel `elapsed_ms`), speedup, efficiency
- Reclaim events; **reclaim_recovery_sec** = reclaim → successful re-complete
- Leave latency (owner LEAVE handler)
- Cloud VM-seconds and USD cost proxy

---

## 9. Workloads

| Kernel | Pattern | OpenMP usage |
|--------|---------|--------------|
| `heat2d` | Tiled 2D heat on row strips + local hotspot | `parallel for` / collapse |
| `batch` | Embarrassingly parallel array reductions | `parallel for` static |
| `irregular` | Variable work / stragglers | `parallel for` dynamic |

Build: `scripts/build_kernels.ps1` (MSYS2 `g++ -fopenmp`) or `scripts/build_kernels.sh`.

---

## 10. Repository build map (top → bottom)

```text
config/default.yaml          thresholds, ports, workloads, burst mode
        │
protocol/messages.py         wire format
        │
kernels/omp_kernels.cpp      native OpenMP binary
        │
master/scheduler.py          tasks, workers, reclaim, projection
master/burst.py              policy + VM lifecycle
master/storage.py · metrics.py
master/server.py             asyncio TCP master (python -m master)
master/client.py             submit + wait
        │
worker/consent.py · qos.py · agent.py
                             python -m worker
        │
dashboard/app.py             optional status UI
docker/Dockerfile            cloud worker image
scripts/*                    build, demo, experiments, AWS stubs
tests/*                      unit + integration
```

### Process topology (local demo)

```text
run_demo.ps1 / run_all.ps1
  ├─ master process          :9100
  ├─ campus worker × N       consent + OpenMP
  ├─ (optional) cloud worker from BurstController
  └─ master.client           JOB_SUBMIT → wait finished
```

---

## 11. Deployment views

### Classroom / LAN
- Master on lab server or instructor laptop (reachable TCP).
- Students run `Connect.bat` / `python -m worker --master host:9100`.
- Burst stays `local_sim` or unused (`campus_only`).

### AWS Gateway (curriculum default for “deploy on AWS”)
- **Master on EC2 = gateway.** Clients and campus workers connect outbound to the public IP `:9100`.
- No separate API Gateway required for TCP task fabric; optional NLB later for stable DNS.
- Deploy: `DeployGateway.bat` / `scripts/aws_deploy_gateway.ps1` — details in `docs/aws_deployment.md`.

### Hybrid + AWS burst (operator-owned)
1. Gateway already on AWS (above).
2. Fill `burst.aws_*`; set `burst.mode: aws`; set `advertise_host` / `aws_master_host`.
3. Burst controller launches short-lived worker VMs into the same queue.
4. Checkpoints may use S3 (`storage.backend: s3`).

---

## 12. Trust, ethics, and safety boundaries

- No personal file access; only task/heartbeat/result/checkpoint traffic.
- Cloud credentials stay with operators, not campus workers.
- Anonymous node IDs preferred in logs.
- Consent form draft: `consent/consent_form.md`; ethics: `docs/ethics.md`.

---

## 13. Verification map

| Concern | Coverage |
|---------|----------|
| Kernels | `tests/test_kernels.py` |
| Protocol / scheduler / burst | `tests/test_protocol.py`, `test_scheduler.py`, `test_burst_policy.py` |
| Reclaim recovery / idle retire | `tests/test_reclaim_recovery.py`, `test_retire_idle.py` |
| Consent / idle QoS | `tests/test_consent_qos.py`, `test_idle_qos.py` |
| End-to-end | `tests/test_integration_local.py` |
| Scenarios | `scripts/run_experiments.ps1` (campus_only, reclaim, hybrid, cloud_only, irregular) |

Single entry: `.\scripts\run_all.ps1`.
