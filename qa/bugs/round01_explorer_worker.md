# Round 1 — Worker/Kernels Explorer
Source: [Worker explorer](6a3b202a-eabb-41bd-a6ac-e6a1c2247dc4)

## Bugs found
### WORKER-101 Windows idle detection fails open — Medium
- `worker/qos.py:68-80` — sampling failure → busy_ratio 0.0 → treated as idle

### WORKER-102 Task dropped on pause/leave — High
- Duplicate of BUG-001 (`worker/agent.py:300-310`)

### WORKER-103 Leave is not preemptive — High
- `worker/agent.py:329-366` — kernel keeps running after leave ACK

### WORKER-104 CPU cap bypass when threads preset — Medium
- `worker/agent.py:320-324` — no clamp if params.threads already set

### WORKER-105 Checkpoint too weak for reclaim/resume — Medium
- Synthetic phase-only checkpoints; no progress cursor

## Fix applied BUG-003
- `worker/agent.py` now tracks the active kernel `Popen`, terminates it on leave, and suppresses `TASK_RESULT` after a leave-triggered cancellation.
- Regression coverage: `tests/test_pause_reclaim.py::test_worker_leave_terminates_inflight_kernel`
