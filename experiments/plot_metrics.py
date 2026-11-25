"""Emit a simple Markdown table from metrics.csv (no heavy plotting deps)."""
from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "data" / "logs" / "metrics.csv"
OUT = ROOT / "experiments" / "out" / "metrics_table.md"


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    if not CSV_PATH.exists():
        OUT.write_text("# No metrics yet\n", encoding="utf-8")
        return
    rows = list(csv.DictReader(CSV_PATH.open(encoding="utf-8")))
    cols = [
        "job_id", "policy", "kernel", "n_tasks", "campus_workers", "cloud_workers",
        "wall_time_sec", "speedup", "efficiency", "reclaim_events", "cloud_cost_proxy_usd",
    ]
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    for r in rows[-20:]:
        lines.append("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |")
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
