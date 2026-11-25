# QA Bug Board — Hybrid Consent-Driven Desktop Grid

**Tech lead:** Auto (orchestrator)
**Target:** ≥20 rounds or open C+H = 0 and error_margin < 0.15
**Baseline (R0):** 28 passed → **mid-R1: 36 passed**

## Convergence

`error_margin = (C*4 + H*2 + M) / max(1, filed)`

| Round | Filed | Fixed | Open C/H/M/L | error_margin | Notes |
|-------|-------|-------|--------------|--------------|-------|
| 0 | — | — | — | — | Baseline 28/28 |
| 1 | 16 | 5 | 0/1/8/2 | 0.625 | Crits cleared; only BUG-012 High open |

## Open — Critical / High

### BUG-012 Stale TASK_RESULT after reclaim — **High** — [Dev](06d6044e-5301-4388-a7d5-17f29aacac10)

## Open — Medium / Low (queued)

| ID | Sev | Summary |
|----|-----|---------|
| BUG-004 | M | Cloud cost 0 while VMs still up |
| BUG-005 | M | Speedup/efficiency wrong baseline |
| BUG-006 | M | Windows idle detection fails open |
| BUG-007 | M | CPU cap bypass when threads preset |
| BUG-008 | M | Weak checkpoints |
| BUG-011 | M | Non-atomic JSON + local shadows S3 |
| BUG-013 | M | Unknown task_id ACK |
| BUG-014 | M | Metrics not job-scoped |
| BUG-015 | L | reclaim_timestamps unbounded |
| BUG-016 | L | shutdown_all leaks burst procs |

## Fixed

### BUG-001 Pause orphans assigned task — **High** ✓
- Reclaim-on-pause + `TASK_RECLAIM`; `tests/test_pause_reclaim.py`
### BUG-002 campus_only → cloud spill — **High** ✓
- `assign_next(campus_only=True)`; `tests/test_scheduler.py`
### BUG-003 Leave not preemptive — **High** ✓
- Track active kernel Popen, terminate on leave, skip TASK_RESULT on cancelled tasks; `tests/test_pause_reclaim.py`
### BUG-009 AWS burst master host fix — **Critical** ✓
- AWS launches resolve `burst.aws_master_host` / `master.advertise_host`, never `127.0.0.1`; `tests/test_burst_aws.py`
### BUG-010 AWS burst instance_id capture — **Critical** ✓
- `aws ec2 run-instances` output is parsed and stored on the VM record; placeholder launches do not consume slots and `_stop_vm()` can terminate by instance ID; `tests/test_burst_aws.py`
