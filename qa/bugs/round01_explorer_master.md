# Round 1 — Master/Protocol Explorer
Source: [Master explorer](b005d3fa-ca8d-4ef4-8ba3-30d6112c8573)

## Bugs found
### MASTER-001 campus_only → cloud fallback — High
- Duplicate of BUG-002

### MASTER-002 Stale TASK_RESULT after reclaim accepted — High
- `complete_task` / `_on_result` do not verify current assignee/attempt

### MASTER-003 Unknown task_id result/checkpoint ACKed — Medium
### MASTER-004 Job metrics session-global not job-scoped — Medium
### MASTER-005 reclaim_timestamps unbounded — Low
### MASTER-006 shutdown_all leaks burst processes — Low
