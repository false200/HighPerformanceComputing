# Round Protocol (loop engineering)

Each round (1…N):

1. **User swarm** — 3 personas exercise the system (peer / submitter / operator), write `qa/bugs/roundNN_*.md`.
2. **Explorer swarm** — master + worker deep review (no code changes).
3. **Tech lead triage** — dedupe, severity, assign IDs `BUG-NNN`, update `BOARD.md` + `STATE.json`.
4. **Developer swarm** — juniors fix High/Critical first with TDD (failing test → fix → full pytest).
5. **Verify** — `py -3 -m pytest tests -q --tb=line`; record pass/fail delta.
6. **Convergence check** — recompute `error_margin`; stop or continue.
7. **Arm next wake** — only if not stopped.

Do not invent bugs. Prefer reproducible defects with file:line evidence.
