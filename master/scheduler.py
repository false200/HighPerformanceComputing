from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from master.gcs import GlobalControlStore
from master.object_ref import ObjectRef, TaskLineage
from master.resources import NodeResources, ResourceSpec


class TaskState(str, Enum):
    PENDING = "PENDING"
    ASSIGNED = "ASSIGNED"
    DONE = "DONE"
    RECLAIMED = "RECLAIMED"
    FAILED = "FAILED"  # exhausted max_retries (Ray-style)


@dataclass
class Task:
    task_id: str
    job_id: str
    kernel: str
    params: Dict[str, Any]
    weight: float = 1.0
    state: TaskState = TaskState.PENDING
    worker_id: Optional[str] = None
    attempts: int = 0
    max_retries: int = 3  # Ray default for non-actor tasks
    resources: ResourceSpec = field(default_factory=ResourceSpec)
    result: Optional[Dict[str, Any]] = None
    checkpoint: Optional[Dict[str, Any]] = None
    result_ref: Optional[str] = None
    checkpoint_ref: Optional[str] = None
    assigned_at: float = 0.0
    reclaimed_at: Optional[float] = None  # set on reclaim; cleared on completion


@dataclass
class WorkerInfo:
    worker_id: str
    kind: str  # campus | cloud
    cores: int
    memory_mb: int
    os_name: str
    cpu_cap_threads: int = 0
    memory_cap_mb: int = 0  # 0 = use memory_mb as-is
    gpu_count: int = 0  # inventory only; kernels are CPU/OpenMP today
    max_tasks: int = 0  # 0 = derive from effective cores
    idle_only: bool = False
    paused: bool = False
    consented: bool = False
    instance_type: Optional[str] = None
    region: Optional[str] = None
    last_heartbeat: float = field(default_factory=time.time)
    connected_at: float = field(default_factory=time.time)
    tasks_done: int = 0
    writer: Any = None  # asyncio StreamWriter
    # Ray-style logical capacity (filled on register / refresh)
    node_resources: Optional[NodeResources] = None


@dataclass
class Job:
    job_id: str
    kernel: str
    policy: str
    deadline_ts: float
    tasks: List[Task] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    checksum: float = 0.0
    placement: str = "spread"  # spread | pack (Ray placement-group spirit)


class Scheduler:
    """Peer-first, resource-aware scheduler with reclaim + lineage hooks.

    Ideas absorbed from Ray (not a clone):
    - logical CPU/memory admission before assign
    - max_retries / FAILED after exhaustion
    - ObjectRef + lineage registered in GCS
    - placement spread vs pack
    Campus consent / reclaim remain first-class (Ray has no owner QoS).
    """

    def __init__(self, gcs: Optional[GlobalControlStore] = None):
        self.gcs = gcs or GlobalControlStore()
        self.workers: Dict[str, WorkerInfo] = {}
        self.jobs: Dict[str, Job] = {}
        self.pending: List[str] = []  # task ids
        self.assigned: Dict[str, str] = {}  # task_id -> worker_id
        self.task_index: Dict[str, Task] = {}
        self.reclaim_events = 0
        self.reclaim_timestamps: List[float] = []
        self.retry_events = 0
        self.failed_tasks = 0
        self.lineage_reconstructions = 0

    def _refresh_node_resources(self, w: WorkerInfo) -> NodeResources:
        cpus = float(self._effective_cores(w))
        mem = float(self.effective_memory_mb(w))
        custom: Dict[str, float] = {}
        if w.gpu_count:
            custom["GPU"] = float(w.gpu_count)
        custom["kind_campus" if w.kind == "campus" else "kind_cloud"] = 1.0
        nr = NodeResources(total_cpus=cpus, total_memory_mb=mem, custom=custom)
        # restore reservations from currently assigned tasks
        for tid, wid in self.assigned.items():
            if wid != w.worker_id:
                continue
            task = self.task_index.get(tid)
            if task:
                nr.reserve(task.resources)
        w.node_resources = nr
        return nr

    def register_worker(self, info: WorkerInfo) -> None:
        self._refresh_node_resources(info)
        self.workers[info.worker_id] = info
        self.gcs.put_worker(
            info.worker_id,
            {
                "kind": info.kind,
                "cores": info.cores,
                "memory_mb": info.memory_mb,
                "cpu_cap_threads": info.cpu_cap_threads,
                "consented": info.consented,
                "paused": info.paused,
            },
        )

    def unregister_worker(self, worker_id: str) -> List[Task]:
        info = self.workers.pop(worker_id, None)
        self.gcs.delete_worker(worker_id)
        return self.reclaim_worker(worker_id, reason="disconnect", info=info)

    def heartbeat(self, worker_id: str) -> None:
        w = self.workers.get(worker_id)
        if w:
            w.last_heartbeat = time.time()

    def set_paused(self, worker_id: str, paused: bool) -> None:
        w = self.workers.get(worker_id)
        if w:
            if paused and not w.paused:
                self.reclaim_worker(worker_id, reason="pause", info=w)
            w.paused = paused
            self.gcs.put_worker(
                worker_id,
                {
                    "kind": w.kind,
                    "cores": w.cores,
                    "memory_mb": w.memory_mb,
                    "cpu_cap_threads": w.cpu_cap_threads,
                    "consented": w.consented,
                    "paused": w.paused,
                },
            )

    def create_job(
        self,
        kernel: str,
        task_specs: List[Dict[str, Any]],
        policy: str = "hybrid",
        deadline_sec: float = 120.0,
        max_retries: int = 3,
        placement: str = "spread",
        default_resources: Optional[ResourceSpec] = None,
    ) -> Job:
        job_id = uuid.uuid4().hex[:12]
        job = Job(
            job_id=job_id,
            kernel=kernel,
            policy=policy,
            deadline_ts=time.time() + deadline_sec,
            placement=placement if placement in ("spread", "pack") else "spread",
        )
        base = default_resources or ResourceSpec(num_cpus=1.0)
        for spec in task_specs:
            tid = f"{job_id}-{uuid.uuid4().hex[:8]}"
            res = ResourceSpec.from_dict(spec.get("resources")) if spec.get("resources") else ResourceSpec(
                num_cpus=base.num_cpus,
                memory_mb=base.memory_mb,
                custom=dict(base.custom),
            )
            task = Task(
                task_id=tid,
                job_id=job_id,
                kernel=kernel,
                params=spec.get("params", {}),
                weight=float(spec.get("weight", 1.0)),
                max_retries=int(spec.get("max_retries", max_retries)),
                resources=res,
            )
            job.tasks.append(task)
            self.task_index[tid] = task
            self.pending.append(tid)
            self.gcs.put_lineage(
                TaskLineage(
                    task_id=tid,
                    job_id=job_id,
                    kernel=kernel,
                    params=dict(task.params),
                    resources=res.to_dict(),
                    max_retries=task.max_retries,
                )
            )
        self.jobs[job_id] = job
        return job

    def eligible_workers(self, prefer: Optional[str] = None) -> List[WorkerInfo]:
        out: List[WorkerInfo] = []
        for w in self.workers.values():
            if not w.consented and w.kind == "campus":
                continue
            if w.paused:
                continue
            if prefer == "campus" and w.kind != "campus":
                continue
            if prefer == "cloud" and w.kind != "cloud":
                continue
            out.append(w)
        return out

    def _load(self, w: WorkerInfo) -> int:
        return sum(1 for tid, wid in self.assigned.items() if wid == w.worker_id)

    def _effective_cores(self, w: WorkerInfo) -> int:
        if w.cpu_cap_threads and w.cpu_cap_threads > 0:
            return min(w.cores, w.cpu_cap_threads)
        return max(1, w.cores)

    def _max_concurrent(self, w: WorkerInfo) -> int:
        if w.max_tasks and w.max_tasks > 0:
            return max(1, w.max_tasks)
        return max(1, self._effective_cores(w))

    def effective_memory_mb(self, w: WorkerInfo) -> int:
        if w.memory_cap_mb and w.memory_cap_mb > 0:
            return min(w.memory_mb, w.memory_cap_mb)
        return max(0, w.memory_mb)

    def _sort_pool(self, pool: List[WorkerInfo], placement: str) -> List[WorkerInfo]:
        if placement == "pack":
            # Fill busiest eligible node first (locality / PACK spirit)
            return sorted(pool, key=lambda w: (-self._load(w), -self._effective_cores(w)))
        # SPREAD (default): least loaded, then biggest capacity
        return sorted(pool, key=lambda w: (self._load(w), -self._effective_cores(w)))

    def assign_next(
        self,
        peer_first: bool = True,
        cloud_only: bool = False,
        campus_only: bool = False,
        placement: Optional[str] = None,
    ) -> List[Tuple[WorkerInfo, Task]]:
        assignments: List[Tuple[WorkerInfo, Task]] = []
        if not self.pending:
            return assignments

        if cloud_only:
            pool = self.eligible_workers("cloud")
        elif campus_only:
            pool = self.eligible_workers("campus")
        elif peer_first:
            pool = self.eligible_workers("campus")
            if not pool:
                pool = self.eligible_workers("cloud")
        else:
            pool = self.eligible_workers()

        if not pool:
            return assignments

        place = placement
        if place is None and self.pending:
            job = self.jobs.get(self.task_index[self.pending[0]].job_id)
            place = job.placement if job else "spread"
        place = place or "spread"
        pool = self._sort_pool(pool, place)

        # One new task per worker per tick (fair dispatch); resource-aware admission.
        used_workers: set[str] = set()
        still_pending: List[str] = []
        for tid in list(self.pending):
            task = self.task_index[tid]
            placed = False
            for w in pool:
                if w.worker_id in used_workers:
                    continue
                if self._load(w) >= self._max_concurrent(w):
                    continue
                nr = w.node_resources or self._refresh_node_resources(w)
                if not nr.can_fit(task.resources):
                    continue
                task.state = TaskState.ASSIGNED
                task.worker_id = w.worker_id
                task.attempts += 1
                task.assigned_at = time.time()
                self.assigned[tid] = w.worker_id
                nr.reserve(task.resources)
                task.params = dict(task.params)
                task.params["threads"] = self._effective_cores(w)
                task.params["num_cpus"] = task.resources.num_cpus
                if task.checkpoint_ref:
                    task.params["checkpoint_ref"] = task.checkpoint_ref
                assignments.append((w, task))
                used_workers.add(w.worker_id)
                placed = True
                break
            if not placed:
                still_pending.append(tid)
        self.pending = still_pending
        return assignments

    def complete_task(
        self,
        task_id: str,
        result: Dict[str, Any],
        worker_id: Optional[str] = None,
        result_uri: Optional[str] = None,
    ) -> Tuple[Optional[Job], Optional[float], Optional[ObjectRef]]:
        """Returns (job, reclaim_recovery_sec, result ObjectRef)."""
        task = self.task_index.get(task_id)
        if not task:
            return None, None, None
        current = self.assigned.get(task_id)
        if current is None:
            return None, None, None
        if worker_id is not None and worker_id != current:
            return None, None, None
        recovery: Optional[float] = None
        if task.reclaimed_at is not None:
            recovery = time.time() - task.reclaimed_at
            task.reclaimed_at = None
        # release logical resources
        w = self.workers.get(task.worker_id or "")
        if w and w.node_resources:
            w.node_resources.release(task.resources)
        task.state = TaskState.DONE
        task.result = result
        self.assigned.pop(task_id, None)
        if w:
            w.tasks_done += 1
        ref = ObjectRef.new(
            kind="result",
            task_id=task_id,
            uri=result_uri,
            size_bytes=len(str(result)),
        )
        task.result_ref = ref.ref_id
        self.gcs.put_object(ref, location=worker_id or "master")
        job = self.jobs[task.job_id]
        terminal = (TaskState.DONE, TaskState.FAILED)
        if all(t.state in terminal for t in job.tasks):
            job.finished_at = time.time()
            job.checksum = sum(
                float(t.result.get("checksum", 0.0)) for t in job.tasks if t.result
            )
        return job, recovery, ref

    def checkpoint_task(
        self,
        task_id: str,
        checkpoint: Dict[str, Any],
        uri: Optional[str] = None,
    ) -> Optional[ObjectRef]:
        task = self.task_index.get(task_id)
        if not task:
            return None
        task.checkpoint = checkpoint
        ref = ObjectRef.new(kind="checkpoint", task_id=task_id, uri=uri, size_bytes=len(str(checkpoint)))
        task.checkpoint_ref = ref.ref_id
        self.gcs.put_object(ref, location="master")
        return ref

    def reclaim_task(
        self,
        worker_id: str,
        task_id: str,
        reason: str = "pause",
    ) -> Optional[Task]:
        task = self.task_index.get(task_id)
        if not task or self.assigned.get(task_id) != worker_id:
            return None
        now = time.time()
        w = self.workers.get(worker_id)
        if w and w.node_resources:
            w.node_resources.release(task.resources)
        # Mark result object lost if any (lineage can reconstruct via re-run)
        if task.result_ref:
            self.gcs.mark_object_lost(task.result_ref)
        task.state = TaskState.RECLAIMED
        task.worker_id = None
        task.reclaimed_at = now
        self.assigned.pop(task_id, None)

        # Ray: re-execute only up to max_retries (attempts already counted on assign)
        if task.attempts > task.max_retries:
            task.state = TaskState.FAILED
            self.failed_tasks += 1
            job = self.jobs.get(task.job_id)
            if job and all(t.state in (TaskState.DONE, TaskState.FAILED) for t in job.tasks):
                job.finished_at = time.time()
                job.checksum = sum(
                    float(t.result.get("checksum", 0.0)) for t in job.tasks if t.result
                )
            self.reclaim_events += 1
            self.reclaim_timestamps.append(now)
            return task

        # Lineage reconstruction path: requeue with checkpoint_ref if present
        if task.checkpoint_ref and self.gcs.reconstructable(task.checkpoint_ref):
            self.lineage_reconstructions += 1
        self.pending.append(task_id)
        task.state = TaskState.PENDING
        self.reclaim_events += 1
        self.reclaim_timestamps.append(now)
        self.retry_events += 1
        return task

    def reclaim_worker(
        self,
        worker_id: str,
        reason: str = "leave",
        info: Optional[WorkerInfo] = None,
    ) -> List[Task]:
        reclaimed: List[Task] = []
        to_drop = [tid for tid, wid in self.assigned.items() if wid == worker_id]
        for tid in to_drop:
            task = self.reclaim_task(worker_id, tid, reason=reason)
            if task is not None:
                reclaimed.append(task)
        return reclaimed

    def reclaim_rate(self, window_sec: float = 30.0) -> float:
        now = time.time()
        recent = [t for t in self.reclaim_timestamps if now - t <= window_sec]
        campus = max(1, sum(1 for w in self.workers.values() if w.kind == "campus"))
        return len(recent) / campus

    def job_progress(self, job_id: str) -> Dict[str, Any]:
        job = self.jobs[job_id]
        done = sum(1 for t in job.tasks if t.state == TaskState.DONE)
        failed = sum(1 for t in job.tasks if t.state == TaskState.FAILED)
        return {
            "job_id": job_id,
            "kernel": job.kernel,
            "policy": job.policy,
            "done": done,
            "failed": failed,
            "total": len(job.tasks),
            "finished": job.finished_at is not None,
            "checksum": job.checksum,
            "deadline_ts": job.deadline_ts,
            "placement": job.placement,
            "gcs": self.gcs.snapshot(),
        }

    def projected_finish(self, job_id: str) -> float:
        job = self.jobs.get(job_id)
        if not job:
            return float("inf")
        remaining = [t for t in job.tasks if t.state not in (TaskState.DONE, TaskState.FAILED)]
        if not remaining:
            return time.time()
        done = len(job.tasks) - len(remaining)
        elapsed = max(0.001, time.time() - job.created_at)
        rate = done / elapsed if done else 0.05
        active = max(1, len(self.eligible_workers()))
        return time.time() + (len(remaining) / max(rate * active, 0.01))

    def campus_peer_count(self) -> int:
        return sum(
            1
            for w in self.workers.values()
            if w.kind == "campus" and w.consented and not w.paused
        )

    def cloud_peer_count(self) -> int:
        return sum(1 for w in self.workers.values() if w.kind == "cloud" and not w.paused)
