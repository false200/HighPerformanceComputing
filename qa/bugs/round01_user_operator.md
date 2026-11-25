# Round 1 — Grid Operator
## Bugs found
### BUG-001 Critical - AWS bursts point workers at localhost
`master/burst.py` always passes `127.0.0.1` into the AWS launch path, so any real EC2 worker started by `scripts/aws_launch_worker.ps1` or `.sh` will try to register back to itself instead of the master. That makes cloud bursting unusable outside the local simulator.

### BUG-002 Critical - AWS burst cleanup cannot stop real instances
The AWS launch path never captures the EC2 instance ID returned by `aws ec2 run-instances`, but `_stop_vm()` only knows how to terminate AWS workers when `instance_id` is populated. In practice, the controller is tracking the launcher process, not the VM, so real bursts can leak until manual cleanup. The placeholder/no-op launch path also still increments burst counts, which can consume the burst budget even when no instance was created.

### BUG-003 Required - Checkpoint reads can be stale or torn
`master/storage.py` writes JSON directly to the final checkpoint/result path and `get_json()` always prefers the local file if it exists, even in S3 mode. A crash or concurrent write can leave a partial JSON file on disk, and a stale local copy can shadow the authoritative S3 object on restart. That is a bad failure mode for checkpoint recovery.
## Passed scenarios
- `py -3 -m pytest tests/test_protocol.py tests/test_storage_metrics.py -q --tb=short`
- 4 tests passed

## Fix applied BUG-009/010
- AWS burst launches now resolve a reachable master host from `burst.aws_master_host` or `master.advertise_host`; AWS mode no longer injects `127.0.0.1`.
- `aws ec2 run-instances` output is parsed for the EC2 instance ID and stored on the VM record so `_stop_vm()` can terminate the real instance.
- Placeholder or no-op AWS launches return no VM and do not consume a burst slot.
- Verified with `py -3 -m pytest tests -q --tb=short` (`36 passed`).

## Notes for developers
- I did not change code.
- I reviewed `config/default.yaml`, `scripts/run_all.ps1`, `scripts/run_demo.ps1`, `master/server.py`, `master/burst.py`, and the dashboard entrypoint.
