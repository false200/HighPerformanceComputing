# Round 1 — Campus Lab Peer
## Bugs found
### BUG-001 Pause can orphan an assigned task
- Severity: High
- Area: Worker controls / reclaim behavior
- Steps / evidence:
  - Start a campus worker with `--auto-consent` and a live master.
  - Let the worker receive a task, then issue `p`/`pause` while it is waiting in the idle-only gate or before `_execute_task()` begins.
  - In `worker/agent.py`, the task message is already dequeued from `_inbox`; when `self.paused` becomes true, `_work_loop()` hits `continue` and drops that assignment instead of requeueing or notifying the master.
- Expected vs actual:
  - Expected: pausing should stop future work, but any task already assigned to that worker should either remain safely queued on the worker or be reclaimed by the master.
  - Actual: the task can disappear from the worker side while staying marked assigned on the master, so it may remain stuck until a disconnect or heartbeat reclaim path happens to recover it.
- Suggested fix:
  - On pause, preserve the in-flight assignment or explicitly reclaim it on the master before returning to the inbox loop.
  - Add a test that pauses a worker after it has dequeued a task and asserts the task is requeued or completed cleanly.
## Passed scenarios
- `tests/test_consent_qos.py` passed.
- `tests/test_idle_qos.py` passed.
- `tests/test_retire_idle.py` passed.
- `tests/test_reclaim_recovery.py` passed.
- Focused pytest run completed successfully: 9 passed.
## Notes for developers
- The user-facing docs and the implementation agree on consent, CPU cap, leave, idle-only, and `--no-controls`.
- The main gap I found is pause semantics during task handoff; that path is not covered by the current focused tests.
