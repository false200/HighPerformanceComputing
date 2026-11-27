"""Ray-inspired ObjectRef + lineage metadata.

In Ray, tasks return immutable remote objects addressed by ObjectRef; lost values
can be reconstructed by re-executing the producing task (lineage). Here we keep
the same *idea* on top of our filesystem/S3 ObjectStore — refs, not Plasma.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ObjectRef:
    """Handle to an immutable value in the object store."""

    ref_id: str
    kind: str  # result | checkpoint | put
    task_id: Optional[str] = None  # producer (lineage root for this value)
    uri: Optional[str] = None
    size_bytes: int = 0
    created_at: float = field(default_factory=time.time)
    lost: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ref_id": self.ref_id,
            "kind": self.kind,
            "task_id": self.task_id,
            "uri": self.uri,
            "size_bytes": self.size_bytes,
            "created_at": self.created_at,
            "lost": self.lost,
        }

    @classmethod
    def new(
        cls,
        kind: str,
        task_id: Optional[str] = None,
        uri: Optional[str] = None,
        size_bytes: int = 0,
    ) -> "ObjectRef":
        return cls(
            ref_id=f"obj-{uuid.uuid4().hex[:12]}",
            kind=kind,
            task_id=task_id,
            uri=uri,
            size_bytes=size_bytes,
        )


@dataclass
class TaskLineage:
    """Enough to re-execute a task if its result object is lost (Ray lineage)."""

    task_id: str
    job_id: str
    kernel: str
    params: Dict[str, Any]
    resources: Dict[str, Any]
    dependency_refs: List[str] = field(default_factory=list)  # input ObjectRefs
    max_retries: int = 3

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "job_id": self.job_id,
            "kernel": self.kernel,
            "params": dict(self.params),
            "resources": dict(self.resources),
            "dependency_refs": list(self.dependency_refs),
            "max_retries": self.max_retries,
        }
