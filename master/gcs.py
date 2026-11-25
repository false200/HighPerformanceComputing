"""Global Control Store — Ray GCS idea, campus-grid scale.

Ray's GCS holds cluster control state (workers, object locations, lineage) so
schedulers and stores stay reconstructable. We keep an in-memory GCS on the
master (single coordinator); durable blobs still go through ObjectStore.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from master.object_ref import ObjectRef, TaskLineage


class GlobalControlStore:
    """Key tables Ray would shard; we keep them local on the master process."""

    def __init__(self) -> None:
        self.workers: Dict[str, Dict[str, Any]] = {}
        self.objects: Dict[str, ObjectRef] = {}
        self.lineage: Dict[str, TaskLineage] = {}
        self.object_locations: Dict[str, List[str]] = {}  # ref_id -> worker_ids / "master"
        self.events: List[Dict[str, Any]] = []

    def put_worker(self, worker_id: str, meta: Dict[str, Any]) -> None:
        self.workers[worker_id] = dict(meta)
        self.workers[worker_id]["updated_at"] = time.time()

    def delete_worker(self, worker_id: str) -> None:
        self.workers.pop(worker_id, None)

    def put_lineage(self, lineage: TaskLineage) -> None:
        self.lineage[lineage.task_id] = lineage

    def get_lineage(self, task_id: str) -> Optional[TaskLineage]:
        return self.lineage.get(task_id)

    def put_object(self, ref: ObjectRef, location: str = "master") -> ObjectRef:
        self.objects[ref.ref_id] = ref
        locs = self.object_locations.setdefault(ref.ref_id, [])
        if location not in locs:
            locs.append(location)
        return ref

    def get_object(self, ref_id: str) -> Optional[ObjectRef]:
        return self.objects.get(ref_id)

    def mark_object_lost(self, ref_id: str) -> Optional[ObjectRef]:
        ref = self.objects.get(ref_id)
        if ref:
            ref.lost = True
            self.object_locations.pop(ref_id, None)
            self._event("object_lost", ref_id=ref_id, task_id=ref.task_id)
        return ref

    def reconstructable(self, ref_id: str) -> bool:
        """True if Ray-style lineage reconstruction can re-run the producer."""
        ref = self.objects.get(ref_id)
        if not ref or not ref.task_id:
            return False
        lin = self.lineage.get(ref.task_id)
        return lin is not None

    def snapshot(self) -> Dict[str, Any]:
        return {
            "workers": len(self.workers),
            "objects": len(self.objects),
            "lineage_entries": len(self.lineage),
            "lost_objects": sum(1 for o in self.objects.values() if o.lost),
        }

    def _event(self, name: str, **kwargs: Any) -> None:
        self.events.append({"event": name, "ts": time.time(), **kwargs})
        if len(self.events) > 5000:
            self.events = self.events[-2500:]
