"""Job packages stored on the live master (user input) — no redeploy per job."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class JobPackage:
    package_id: str
    name: str
    files: Dict[str, str]  # relative path -> text content
    created_at: float = field(default_factory=time.time)
    meta: Dict[str, Any] = field(default_factory=dict)

    def get(self, path: str) -> Optional[str]:
        return self.files.get(path)

    def csv_rows(self, dataset_path: str) -> List[str]:
        raw = self.files.get(dataset_path)
        if raw is None:
            raise FileNotFoundError(f"{dataset_path} not in package {self.package_id}")
        lines = [ln for ln in raw.splitlines() if ln.strip()]
        return lines


class PackageStore:
    def __init__(self) -> None:
        self._packages: Dict[str, JobPackage] = {}

    def put(
        self,
        files: Dict[str, str],
        name: str = "job",
        meta: Optional[Dict[str, Any]] = None,
    ) -> JobPackage:
        if not files:
            raise ValueError("package has no files")
        # soft size guard (~4 MiB total text)
        total = sum(len(v) for v in files.values())
        if total > 4_000_000:
            raise ValueError("package too large")
        pid = f"pkg-{uuid.uuid4().hex[:12]}"
        pkg = JobPackage(
            package_id=pid,
            name=name or "job",
            files={str(k): str(v) for k, v in files.items()},
            meta=dict(meta or {}),
        )
        self._packages[pid] = pkg
        return pkg

    def get(self, package_id: str) -> Optional[JobPackage]:
        return self._packages.get(package_id)

    def snapshot(self) -> Dict[str, Any]:
        return {
            "count": len(self._packages),
            "packages": [
                {
                    "package_id": p.package_id,
                    "name": p.name,
                    "files": list(p.files.keys()),
                    "created_at": p.created_at,
                }
                for p in list(self._packages.values())[-20:]
            ],
        }
