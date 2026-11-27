from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict


class AuditLog:
    """Append-only JSONL security/ops audit trail."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, event: str, **fields: Any) -> None:
        row: Dict[str, Any] = {"ts": time.time(), "event": event, **fields}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, separators=(",", ":")) + "\n")
