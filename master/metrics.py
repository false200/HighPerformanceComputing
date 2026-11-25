from __future__ import annotations

import csv
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class RunMetrics:
    job_id: str
    policy: str
    kernel: str
    n_tasks: int
    campus_workers: int = 0
    cloud_workers: int = 0
    wall_time_sec: float = 0.0
    serial_proxy_sec: float = 0.0
    speedup: float = 0.0
    efficiency: float = 0.0
    reclaim_events: int = 0
    reclaim_recovery_sec: float = 0.0
    leave_latency_ms: float = 0.0
    cloud_vm_seconds: float = 0.0
    cloud_cost_proxy_usd: float = 0.0
    owner_cpu_cap: int = 0
    checkpoint_uris: List[str] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)

    def finalize(self, hourly_rate_usd: float = 0.0104) -> None:
        """t3.micro-ish free-tier cost proxy (~$0.0104/hr on-demand us-east-1 order)."""
        if self.serial_proxy_sec > 0 and self.wall_time_sec > 0:
            self.speedup = self.serial_proxy_sec / self.wall_time_sec
            cores = max(1, self.campus_workers + self.cloud_workers)
            self.efficiency = self.speedup / cores
        self.cloud_cost_proxy_usd = (self.cloud_vm_seconds / 3600.0) * hourly_rate_usd


class MetricsCollector:
    def __init__(self, log_dir: str, csv_path: str):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.csv_path = Path(csv_path)
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_csv_header()

    def _ensure_csv_header(self) -> None:
        if self.csv_path.exists():
            return
        fields = [
            "ts", "job_id", "policy", "kernel", "n_tasks", "campus_workers",
            "cloud_workers", "wall_time_sec", "serial_proxy_sec", "speedup",
            "efficiency", "reclaim_events", "reclaim_recovery_sec",
            "leave_latency_ms", "cloud_vm_seconds", "cloud_cost_proxy_usd",
        ]
        with self.csv_path.open("w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(fields)

    def record(self, m: RunMetrics) -> Path:
        m.finalize()
        json_path = self.log_dir / f"metrics_{m.job_id}.json"
        json_path.write_text(json.dumps(asdict(m), indent=2), encoding="utf-8")
        with self.csv_path.open("a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([
                time.time(), m.job_id, m.policy, m.kernel, m.n_tasks,
                m.campus_workers, m.cloud_workers, m.wall_time_sec,
                m.serial_proxy_sec, m.speedup, m.efficiency, m.reclaim_events,
                m.reclaim_recovery_sec, m.leave_latency_ms, m.cloud_vm_seconds,
                m.cloud_cost_proxy_usd,
            ])
        return json_path
