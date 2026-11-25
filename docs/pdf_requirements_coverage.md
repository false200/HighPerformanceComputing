# PDF Requirements Coverage Matrix

| PDF section | Requirement | Implementation |
|-------------|-------------|----------------|
| §1–2 Title/Abstract | Hybrid consent desktop grid + OpenMP + cloud burst | Entire repo |
| §4.1 Consent | Explicit consent before work | `worker/consent.py`, `consent/consent_form.md` |
| §4.2 Aggregate CPUs | Heterogeneous peer pool | Worker REGISTER cores/memory; scheduler |
| §4.3 Distribute + OpenMP | Task chunks + OpenMP | `kernels/omp_kernels.cpp`, worker runner |
| §4.4 Survive reclaim | Checkpoint / requeue | LEAVE, heartbeat timeout, storage checkpoints |
| §4.5 Owner interference limits | Caps, priority, idle-only, leave | `worker/qos.py`, stdin p/r/l/s, worker flags |
| §4.6 Cloud burst | Policy thresholds | `master/burst.py`, config scheduling |
| §4.7 Object storage | Optional S3/local | `master/storage.py` |
| §4.8 Metrics | Speedup, recovery, cost, owner impact | `master/metrics.py` |
| §5 Primary objs | Master–worker, portable worker, OpenMP, reclaim, burst, evaluate | Implemented |
| §5.2 Secondary | Capability chunks, idle/CPU, S3, experiment package | Implemented |
| §5.3 Out of scope | No MPI-default, no marketplace | Documented |
| §8–10 System parts + workflow | 4 parts + steps 1–8 | Architecture + runtime |
| §11 Burst policy | Conditions + caps + idle retire | BurstController |
| §13 Tools | C++/OpenMP, Python orch, TCP, AWS scripts, CSV/JSON | Yes |
| §14 Workloads | heat + batch (+ irregular) | Three kernels |
| §15 Experiments | Campus / reclaim / hybrid scenarios | `scripts/run_experiments.ps1` |
| §16 Deliverables | Working path, kernels, burst scripts, docs, ethics | Yes |
| §19 Ethics | Consent procedures | `docs/ethics.md` |
| §24 Checklist items | Consent, HW/SW sheet | `consent/`, `docs/hardware_software_requirements.md` |

Operator-owned: live AWS account wiring and institutional signature pages.
