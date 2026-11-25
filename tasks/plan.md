# Plan: Hybrid Consent-Driven Desktop Grid

## Goal
Working prototype of a campus-first desktop grid with OpenMP workers, reclaim-aware scheduling, policy-driven cloud-burst overflow, metrics, consent/ethics docs, and a single-command local demo. AWS live launch is operator-owned; scripts and interfaces are provided.

## Architecture (dependency order)
1. Protocol (JSON/TCP) → 2. OpenMP kernels → 3. Worker agent → 4. Master (queue, reclaim, burst, metrics) → 5. Dashboard → 6. Burst/AWS scripts → 7. Experiments + tests → 8. Docs

## Vertical slices
| ID | Slice | Acceptance |
|----|-------|------------|
| S1 | OpenMP heat + batch kernels | Compile with `-fopenmp`; unit tests match serial reference |
| S2 | Master task queue + job submit | Job partitions; results merge; JSON logs |
| S3 | Campus worker consent + QoS | Consent gate; pause/leave; CPU cap / idle-only flags |
| S4 | Heartbeat reclaim path | Missed heartbeat / leave requeues unfinished tasks |
| S5 | Cloud-burst policy | Triggers on peer shortage, reclaim rate, deadline, force |
| S6 | Object storage path | Local + S3-compatible checkpoint/result store |
| S7 | Dashboard + metrics | Speedup, recovery, cost proxy, leave latency |
| S8 | Single-run demo + AWS stubs | `scripts/run_all` builds, tests, demo; AWS scripts ready |
| S9 | Experiments package | Campus-only / hybrid / reclaim scripts + CSV traces |
| S10 | Docs deliverables | Consent, ethics, user guide, architecture, checklist |

## Out of scope (per PDF)
Always-on hyperscale hosting; untrusted binary marketplace; default MPI-over-WiFi; multi-region GPU SLA.

## Single-run target
`.\scripts\run_all.ps1` → build kernels → pytest → local master+N workers demo → write experiment CSVs.
