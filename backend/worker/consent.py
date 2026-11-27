from __future__ import annotations

from textwrap import dedent


CONSENT_TEXT = dedent("""
    ============================================================
    CAMPUS WORKER — INFORMED CONSENT
    ============================================================
    Purpose: Contribute spare CPU time to a scientific classroom
             desktop-grid job managed by your course operators.

    Resources used:
      - CPU cores (subject to your CPU-cap / idle-only settings)
      - Network: task data, heartbeats, and results only

    Exclusions:
      - No access to personal files or browsing history
      - No installation of unrelated software by the job

    Your controls:
      - Pause: temporarily stop accepting new tasks
      - Leave: one-click exit; unfinished work is requeued
      - You may withdraw at any time without penalty

    Operator: course / lab project operators (master node)
    ============================================================
""").strip()


def prompt_consent(auto: bool = False) -> bool:
    print(CONSENT_TEXT)
    if auto:
        print("[consent] auto-accepted (--auto-consent)")
        return True
    try:
        ans = input("Type YES to consent and join the pool (or NO to exit): ").strip().upper()
    except EOFError:
        return False
    return ans in {"Y", "YES"}
