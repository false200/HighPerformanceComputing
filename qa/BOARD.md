# QA Bug Board — Hybrid Consent-Driven Desktop Grid

**Tech lead:** Auto (orchestrator)
**Target:** ≥20 test→fix rounds or open Critical/High = 0 and Medium ≤ 2
**Baseline (R0):** `28 passed` pytest (`qa/baseline_pytest.txt`)

## Roles

| Role | Agent type | Duty |
|------|------------|------|
| Tech lead | Orchestrator (this session) | Triage, prioritize, assign, verify convergence |
| Arch explorer (master) | explore | Scheduler / burst / protocol defects |
| Arch explorer (worker) | explore | Consent / QoS / leave / kernels |
| User: Campus peer | generalPurpose | Act as workstation owner |
| User: Job submitter | generalPurpose | Act as researcher submitting jobs |
| User: Grid operator | generalPurpose | Act as admin / ops |
| Dev juniors | generalPurpose | Fix assigned bugs (TDD: prove → fix → guard) |
| Reviewer | code-review / findbugs lens | Gate merges after fixes |

## Convergence metric

```
error_margin = (open_critical * 4 + open_high * 2 + open_medium) / max(1, total_filed)
stop when: rounds >= 20 OR (open_critical + open_high == 0 AND error_margin < 0.15)
```

## Round log

| Round | Filed | Fixed | Open C/H/M/L | error_margin | Notes |
|-------|-------|-------|--------------|--------------|-------|
| 0 | — | — | — | — | Baseline green: 28/28 |
| 1 | _pending_ | — | — | — | User + explorer swarm in flight |

## Open bugs

_(populated after Round 1 triage)_

## Fixed bugs

_(none yet)_
