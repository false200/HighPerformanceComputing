# Round 1 — Job Submitter
## Bugs found
### BUG-001 `campus_only` can still spill to cloud workers
`master/scheduler.py` falls back from campus workers to cloud workers inside `assign_next(...)` whenever no campus worker is available. `master/server.py` only disables burst for `campus_only`, but it does not block this fallback path. That means a `campus_only` job can still run on cloud workers if the campus pool is empty or if all campus workers leave mid-job.

### BUG-002 Cloud cost is recorded as zero for finished burst jobs
`master/server.py` finalizes metrics with `self.burst.vm_seconds`, but `BurstController.vm_seconds` is only incremented when a VM is retired or when the master shuts down. If a hybrid/cloud-only job finishes while cloud workers are still alive, `_finalize_job()` records `cloud_vm_seconds = 0` and `cloud_cost_proxy_usd = 0` even though the job used cloud capacity. The experiment outputs show this pattern on hybrid runs with cloud workers.

### BUG-003 Speedup/efficiency are being computed from the wrong baseline
`master/server.py` seeds `serial_proxy_sec` at job submission, then overwrites it during `_finalize_job()` with the sum of per-task `elapsed_ms`. That value is not a serial baseline; it is the observed parallel task runtime. As a result, the reported `speedup` and `efficiency` in `data/logs/metrics.csv` are artificially tiny and do not reflect actual job-level speedup.

## Passed scenarios
- `py -3 -m pytest tests/test_scheduler.py tests/test_burst_policy.py tests/test_integration_local.py tests/test_kernels.py -q --tb=short`
- The focused scheduler, burst-policy, integration, and kernel tests all passed (`15 passed`).
- Campus-only and hybrid experiment rows were generated in `experiments/out/summary.txt` and `data/logs/metrics.csv`.

## Notes for developers
- `scripts/run_experiments.ps1` includes a `cloud_only_batch` scenario, but the current `experiments/out/summary.txt` and `data/logs/metrics.csv` do not include a matching result row.
- The current metrics table shows cloud workers on some hybrid runs but still reports `cloud_cost_proxy_usd = 0`, which matches BUG-002.

## Fix applied BUG-002
- `master/scheduler.py` now supports a `campus_only` assignment mode that never falls back to cloud workers.
- `master/server.py` passes that mode through for `job.policy == "campus_only"`.
