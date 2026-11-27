"""Generate the demo exam-pass dataset for sharded logistic regression."""

from __future__ import annotations

import csv
import math
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "exam_pass.csv"


def main() -> None:
    random.seed(42)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    header = [
        "hours_studied",
        "attendance",
        "sleep_hours",
        "prior_gpa",
        "assignments_pct",
        "tutoring",
        "passed",
    ]
    true_w = [0.35, 0.02, 0.08, 0.55, 0.015, 0.4]
    true_b = -6.5
    rows = []
    for _ in range(1200):
        hours = random.uniform(0, 20)
        attend = random.uniform(40, 100)
        sleep = random.uniform(4, 9)
        gpa = random.uniform(1.5, 4.0)
        assign = random.uniform(30, 100)
        tutor = 1.0 if random.random() < 0.35 else 0.0
        x = [hours, attend, sleep, gpa, assign, tutor]
        z = true_b + sum(w * v for w, v in zip(true_w, x)) + random.gauss(0, 1.1)
        p = 1.0 / (1.0 + math.exp(-max(min(z, 30.0), -30.0)))
        y = 1 if p >= 0.5 else 0
        rows.append(x + [y])
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    rate = sum(r[-1] for r in rows) / len(rows)
    print(f"wrote {OUT} rows={len(rows)} features={len(header)-1} pass_rate={rate:.3f}")


if __name__ == "__main__":
    main()
