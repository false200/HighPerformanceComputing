from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class TaskState(str, Enum):
    PENDING = "PENDING"
    ASSIGNED = "ASSIGNED"
    DONE = "DONE"
    RECLAIMED = "RECLAIMED"


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
    result: Optional[Dict[str, Any]] = None
    checkpoint: Optional[Dict[str, Any]] = None
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


class Scheduler:
    """Peer-first, capability-aware task scheduler with reclaim support."""

    def __init__(self):
        self.workers: Dict[str, WorkerInfo] = {}
        self.jobs: Dict[str, Job] = {}
        self.pending: List[str] = []  # task ids
        self.assigned: Dict[str, str] = {}  # task_id -> worker_id
        self.task_index: Dict[str, Task] = {}
        self.reclaim_events = 0
        self.reclaim_timestamps: List[float] = []
        self.retry_events = 0

    def register_worker(self, info: WorkerInfo) -> None:
        self.workers[info.worker_id] = info

    def unregister_worker(self, worker_id: str) -> List[Task]:
        info = self.workers.pop(worker_id, None)
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

    def create_job(
        self,
        kernel: str,
        task_specs: List[Dict[str, Any]],
        policy: str = "hybrid",
        deadline_sec: float = 120.0,
    ) -> Job:
        job_id = uuid.uuid4().hex[:12]
        job = Job(
            job_id=job_id,
            kernel=kernel,
            policy=policy,
            deadline_ts=time.time() + deadline_sec,
        )
        for spec in task_specs:
            tid = f"{job_id}-{uuid.uuid4().hex[:8]}"
            task = Task(
                task_id=tid,
                job_id=job_id,
                kernel=kernel,
                params=spec.get("params", {}),
                weight=float(spec.get("weight", 1.0)),
            )
            job.tasks.append(task)
            self.task_index[tid] = task
            self.pending.append(tid)
        self.jobs[job_id] = job
        return job

    def eligible_workers(self, prefer: Optional[str] = None) -> List[WorkerInfo]:
        now = time.time()
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
            # load estimate: assigned tasks
            out.append(w)
        out.sort(key=lambda w: (self._load(w), -self._effective_cores(w)))
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

    def assign_next(
        self,
        peer_first: bool = True,
        cloud_only: bool = False,
        campus_only: bool = False,
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

        # Round-robin lightly: give one task per free-ish worker per call
        for w in pool:
            if not self.pending:
                break
            if self._load(w) >= self._max_concurrent(w):
                continue
            tid = self.pending.pop(0)
            task = self.task_index[tid]
            task.state = TaskState.ASSIGNED
            task.worker_id = w.worker_id
            task.attempts += 1
            task.assigned_at = time.time()
            self.assigned[tid] = w.worker_id
            # capability-aware hint
            task.params = dict(task.params)
            task.params["threads"] = self._effective_cores(w)
            assignments.append((w, task))
        return assignments

    def complete_task(
        self,
        task_id: str,
        result: Dict[str, Any],
        worker_id: Optional[str] = None,
    ) -> Tuple[Optional[Job], Optional[float]]:
        """Returns (job, reclaim_recovery_sec if this task was previously reclaimed).

        Rejects unknown tasks, unassigned tasks, and stale results whose worker_id
        does not match the current assignee.
        """
        task = self.task_index.get(task_id)
        if not task:
            return None, None
        current = self.assigned.get(task_id)
        if current is None:
            return None, None
        if worker_id is not None and worker_id != current:
            return None, None
        recovery: Optional[float] = None
        if task.reclaimed_at is not None:
            recovery = time.time() - task.reclaimed_at
            task.reclaimed_at = None
        task.state = TaskState.DONE
        task.result = result
        self.assigned.pop(task_id, None)
        w = self.workers.get(task.worker_id or "")
        if w:
            w.tasks_done += 1
        job = self.jobs[task.job_id]
        if all(t.state == TaskState.DONE for t in job.tasks):
            job.finished_at = time.time()
            job.checksum = sum(float(t.result.get("checksum", 0.0)) for t in job.tasks if t.result)
        return job, recovery

    def checkpoint_task(self, task_id: str, checkpoint: Dict[str, Any]) -> None:
        task = self.task_index.get(task_id)
        if task:
            task.checkpoint = checkpoint

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
        task.state = TaskState.RECLAIMED
        task.worker_id = None
        task.reclaimed_at = now
        self.assigned.pop(task_id, None)
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
        # normalize vs active campus workers + 1
        campus = max(1, sum(1 for w in self.workers.values() if w.kind == "campus"))
        return len(recent) / campus

    def job_progress(self, job_id: str) -> Dict[str, Any]:
        job = self.jobs[job_id]
        done = sum(1 for t in job.tasks if t.state == TaskState.DONE)
        return {
            "job_id": job_id,
            "kernel": job.kernel,
            "policy": job.policy,
            "done": done,
            "total": len(job.tasks),
            "finished": job.finished_at is not None,
            "checksum": job.checksum,
            "deadline_ts": job.deadline_ts,
        }

    def projected_finish(self, job_id: str) -> float:
        job = self.jobs.get(job_id)
        if not job:
            return float("inf")
        remaining = [t for t in job.tasks if t.state != TaskState.DONE]
        if not remaining:
            return time.time()
        # crude throughput: tasks completed / elapsed
        done = len(job.tasks) - len(remaining)
        elapsed = max(0.001, time.time() - job.created_at)
        rate = done / elapsed if done else 0.05  # tasks/sec guess
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
