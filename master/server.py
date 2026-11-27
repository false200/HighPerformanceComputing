from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from master.audit import AuditLog
from master.auth import resolve_join_token, token_ok
from master.burst import BurstController
from master.config_validate import validate_config
from master.health import HealthServer
from master.metrics import MetricsCollector, RunMetrics
from master.scheduler import Job, Scheduler, WorkerInfo
from master.storage import ObjectStore
from protocol.messages import MAX_MESSAGE_BYTES, MessageType, decode, encode, make


def load_config(path: Path) -> Dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def partition_job(kernel: str, cfg: Dict[str, Any], n_chunks: int) -> List[Dict[str, Any]]:
    wl = cfg.get("workloads", {})
    specs: List[Dict[str, Any]] = []
    n_chunks = max(1, n_chunks)
    if kernel == "heat2d":
        g = int(wl.get("heat2d", {}).get("grid", 128))
        steps = int(wl.get("heat2d", {}).get("steps", 40))
        tile = int(wl.get("heat2d", {}).get("tiles", 16))
        rows_each = max(1, math.ceil(g / n_chunks))
        for i in range(n_chunks):
            start = i * rows_each
            if start >= g:
                break
            rows = min(rows_each, g - start)
            specs.append({
                "weight": rows,
                "params": {
                    "grid": g, "steps": steps, "tile": tile,
                    "start_row": start, "rows": rows,
                },
            })
    elif kernel == "batch":
        arrays = int(wl.get("batch", {}).get("arrays", 32))
        length = int(wl.get("batch", {}).get("length", 100000))
        each = max(1, math.ceil(arrays / n_chunks))
        for i in range(n_chunks):
            offset = i * each
            if offset >= arrays:
                break
            count = min(each, arrays - offset)
            specs.append({
                "weight": count,
                "params": {"offset": offset, "count": count, "length": length},
            })
    elif kernel in ("logreg", "linreg"):
        ml = dict(wl.get(kernel, {}) or wl.get("logreg", {}) or {})
        # Optional per-submit overrides (from job YAML / JOB_SUBMIT)
        overrides = cfg.get("_job_overrides") or {}
        ml.update({k: v for k, v in overrides.items() if v is not None})
        epochs = int(ml.get("epochs", 25))
        lr = float(ml.get("lr", 0.05))
        dataset = str(ml.get("dataset") or "").strip()
        label_col = ml.get("label_col")
        if dataset:
            total_rows = int(ml.get("n_rows") or 0)
            if total_rows <= 0:
                try:
                    from kernels.ml_train import count_csv_rows

                    total_rows = count_csv_rows(dataset)
                except Exception:
                    total_rows = int(ml.get("n_samples", 400)) * n_chunks
            each = max(1, math.ceil(total_rows / n_chunks))
            for i in range(n_chunks):
                offset = i * each
                if offset >= total_rows:
                    break
                count = min(each, total_rows - offset)
                params = {
                    "shard": i,
                    "dataset": dataset,
                    "offset": offset,
                    "count": count,
                    "n_samples": count,
                    "epochs": epochs,
                    "lr": lr,
                }
                if label_col:
                    params["label_col"] = label_col
                specs.append({"weight": count, "params": params})
        else:
            n_samples = int(ml.get("n_samples", 400))
            n_features = int(ml.get("n_features", 8))
            for i in range(n_chunks):
                specs.append({
                    "weight": n_samples,
                    "params": {
                        "shard": i,
                        "seed": 1000 + i * 17,
                        "n_samples": n_samples,
                        "n_features": n_features,
                        "epochs": epochs,
                        "lr": lr,
                    },
                })
    else:  # irregular
        tasks = int(wl.get("irregular", {}).get("tasks", 24))
        max_work = int(wl.get("irregular", {}).get("max_work", 50000))
        n = min(n_chunks, tasks)
        for i in range(n):
            work = max_work // 2 + (i * 9973) % (max_work // 2 + 1)
            specs.append({"weight": work, "params": {"seed": i + 1, "work": work}})
    return specs


class MasterServer:
    def __init__(self, cfg: Dict[str, Any], project_root: Path):
        self.cfg = cfg
        self.project_root = project_root
        self.scheduler = Scheduler()
        self.store = ObjectStore(cfg.get("storage", {}))
        log_cfg = cfg.get("logging", {})
        self.metrics = MetricsCollector(
            log_cfg.get("dir", "data/logs"),
            log_cfg.get("metrics_csv", "data/logs/metrics.csv"),
        )
        self.burst = BurstController(cfg, project_root)
        self.host = cfg.get("master", {}).get("host", "0.0.0.0")
        self.port = int(cfg.get("master", {}).get("port", 9100))
        self.health_port = int(cfg.get("master", {}).get("health_port", 9101))
        self.hb_timeout = float(cfg.get("scheduling", {}).get("heartbeat_timeout_sec", 6.0))
        self.peer_first = bool(cfg.get("scheduling", {}).get("peer_first", True))
        self.join_token = resolve_join_token(cfg)
        self.require_token = bool((cfg.get("auth") or {}).get("require_token", False)) or bool(self.join_token)
        log_dir = Path(cfg.get("logging", {}).get("dir", "data/logs"))
        self.audit = AuditLog(log_dir / "audit.jsonl")
        self.active_job_id: Optional[str] = None
        self._job_metrics: Dict[str, RunMetrics] = {}
        self._job_burst_baselines: Dict[str, tuple[int, float]] = {}
        self._leave_latencies: List[float] = []
        self._server: Optional[asyncio.AbstractServer] = None
        self._health: Optional[HealthServer] = None
        self._lock = asyncio.Lock()
        self.state: Dict[str, Any] = {"running": False}
        if not self.join_token:
            print("[master] WARNING: no HPC_JOIN_TOKEN / auth.join_token — open registration (dev only)", flush=True)
        else:
            print("[master] join-token auth enabled", flush=True)

    def _job_metrics_for(self, job_id: Optional[str]) -> Optional[RunMetrics]:
        if not job_id:
            return None
        return self._job_metrics.get(job_id)

    def _job_metrics_for_task(self, task_id: str) -> Optional[RunMetrics]:
        task = self.scheduler.task_index.get(task_id)
        if not task:
            return None
        return self._job_metrics_for(task.job_id)

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle_client, self.host, self.port)
        self.state["running"] = True
        self._health = HealthServer(self.host, self.health_port, self._health_payload)
        await self._health.start()
        asyncio.create_task(self._control_loop())
        sockets = self._server.sockets or []
        addr = sockets[0].getsockname() if sockets else (self.host, self.port)
        print(f"[master] listening on {addr[0]}:{addr[1]}", flush=True)
        self.audit.emit("master_start", host=self.host, port=self.port)

    def _health_payload(self) -> Dict[str, Any]:
        return {
            "running": bool(self.state.get("running")),
            "workers": len(self.scheduler.workers),
            "active_job_id": self.active_job_id,
            "auth": bool(self.join_token),
            "storage": self.store.backend,
            "burst_mode": self.burst.mode,
            "gcs": self.scheduler.gcs.snapshot(),
        }

    async def serve_forever(self) -> None:
        assert self._server is not None
        async with self._server:
            await self._server.serve_forever()

    async def stop(self) -> None:
        self.burst.shutdown_all()
        if self._health:
            await self._health.stop()
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        self.state["running"] = False
        self.audit.emit("master_stop")

    def _operator_authed(self, msg: Dict[str, Any]) -> bool:
        if not self.require_token:
            return True
        return token_ok(msg.get("token"), self.join_token)

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        worker_id: Optional[str] = None
        peer = writer.get_extra_info("peername")
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                if len(line) > MAX_MESSAGE_BYTES:
                    writer.write(encode(make(MessageType.ERROR, error="message too large")))
                    await writer.drain()
                    break
                try:
                    msg = decode(line)
                except ValueError as exc:
                    writer.write(encode(make(MessageType.ERROR, error=str(exc))))
                    await writer.drain()
                    break
                if not msg:
                    continue
                resp = await self._dispatch(msg, writer)
                if resp is not None:
                    writer.write(encode(resp))
                    await writer.drain()
                if msg.get("type") == MessageType.REGISTER.value and resp and resp.get("ok"):
                    worker_id = resp.get("worker_id") or msg.get("worker_id")
        except Exception as exc:
            print(f"[master] client error {peer}: {exc}", flush=True)
        finally:
            if worker_id:
                async with self._lock:
                    self.scheduler.unregister_worker(worker_id)
                self.audit.emit("worker_disconnect", worker_id=worker_id, peer=str(peer))
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _dispatch(self, msg: Dict[str, Any], writer: asyncio.StreamWriter) -> Optional[Dict[str, Any]]:
        mtype = msg.get("type")
        async with self._lock:
            if mtype == MessageType.REGISTER.value:
                return self._on_register(msg, writer)
            if mtype == MessageType.HEARTBEAT.value:
                self.scheduler.heartbeat(msg["worker_id"])
                return None  # no ACK — avoids racing worker RPC waiters
            if mtype == MessageType.TASK_RESULT.value:
                return self._on_result(msg)
            if mtype == MessageType.TASK_CHECKPOINT.value:
                return self._on_checkpoint(msg)
            if mtype == MessageType.TASK_RECLAIM.value:
                reclaimed = self.scheduler.reclaim_task(
                    msg["worker_id"],
                    msg["task_id"],
                    reason=msg.get("reason", "pause"),
                )
                return make(
                    MessageType.TASK_RECLAIM,
                    ok=True,
                    requeued=1 if reclaimed is not None else 0,
                )
            if mtype == MessageType.LEAVE.value:
                return self._on_leave(msg)
            if mtype == MessageType.PAUSE.value:
                self.scheduler.set_paused(msg["worker_id"], True)
                return make(MessageType.PAUSE, ok=True)
            if mtype == MessageType.RESUME.value:
                self.scheduler.set_paused(msg["worker_id"], False)
                return make(MessageType.RESUME, ok=True)
            if mtype == MessageType.JOB_SUBMIT.value:
                if not self._operator_authed(msg):
                    self.audit.emit("auth_denied", action="JOB_SUBMIT")
                    return make(MessageType.ERROR, error="unauthorized")
                return self._on_job_submit(msg)
            if mtype == MessageType.JOB_STATUS.value:
                if self.require_token and not self._operator_authed(msg):
                    return make(MessageType.ERROR, error="unauthorized")
                jid = msg.get("job_id") or self.active_job_id
                if not jid or jid not in self.scheduler.jobs:
                    return make(MessageType.ERROR, error="no job")
                return make(MessageType.JOB_STATUS, **self.scheduler.job_progress(jid))
            if mtype == MessageType.FORCE_BURST.value:
                if not self._operator_authed(msg):
                    self.audit.emit("auth_denied", action="FORCE_BURST")
                    return make(MessageType.ERROR, error="unauthorized")
                self.burst.force_burst = bool(msg.get("enabled", True))
                return make(MessageType.FORCE_BURST, force_burst=self.burst.force_burst)
            if mtype == MessageType.METRICS.value:
                if self.require_token and not self._operator_authed(msg):
                    return make(MessageType.ERROR, error="unauthorized")
                return make(
                    MessageType.METRICS,
                    burst=self.burst.status(),
                    workers=self._worker_snapshot(),
                    topology=self._topology_snapshot(),
                )
            if mtype == MessageType.SHUTDOWN.value:
                if not self._operator_authed(msg):
                    return make(MessageType.ERROR, error="unauthorized")
                asyncio.create_task(self.stop())
                return make(MessageType.SHUTDOWN, ok=True)
            return make(MessageType.ERROR, error=f"unknown type {mtype}")

    def _on_register(self, msg: Dict[str, Any], writer: asyncio.StreamWriter) -> Dict[str, Any]:
        if not token_ok(msg.get("token"), self.join_token):
            self.audit.emit("auth_denied", action="REGISTER", kind=msg.get("kind"))
            return make(MessageType.ERROR, error="unauthorized: invalid or missing join token")
        if msg.get("kind", "campus") == "campus" and not bool(msg.get("consented", False)):
            return make(MessageType.ERROR, error="consent required")
        wid = msg.get("worker_id") or uuid.uuid4().hex[:10]
        info = WorkerInfo(
            worker_id=wid,
            kind=msg.get("kind", "campus"),
            cores=int(msg.get("cores", 1)),
            memory_mb=int(msg.get("memory_mb", 1024)),
            os_name=str(msg.get("os", "unknown")),
            cpu_cap_threads=int(msg.get("cpu_cap_threads", 0)),
            memory_cap_mb=int(msg.get("memory_cap_mb", 0) or 0),
            gpu_count=int(msg.get("gpu_count", 0) or 0),
            max_tasks=int(msg.get("max_tasks", 0) or 0),
            idle_only=bool(msg.get("idle_only", False)),
            consented=bool(msg.get("consented", False)),
            instance_type=msg.get("instance_type"),
            region=msg.get("region"),
            writer=writer,
        )
        if info.kind == "cloud":
            info.consented = True  # system-launched
        self.scheduler.register_worker(info)
        eff = self.scheduler._effective_cores(info)
        mem = self.scheduler.effective_memory_mb(info)
        print(
            f"[master] registered {info.kind} worker {wid} "
            f"cpu={eff}/{info.cores} ram={mem}MB gpus={info.gpu_count} "
            f"max_tasks={self.scheduler._max_concurrent(info)}",
            flush=True,
        )
        self.audit.emit(
            "worker_register",
            worker_id=wid,
            kind=info.kind,
            cores=eff,
            memory_mb=mem,
            gpus=info.gpu_count,
        )
        return make(
            MessageType.REGISTER_ACK,
            worker_id=wid,
            ok=True,
            consented=info.consented,
            effective_threads=eff,
            effective_memory_mb=mem,
            gpu_count=info.gpu_count,
            max_tasks=self.scheduler._max_concurrent(info),
        )

    def _on_result(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        tid = msg["task_id"]
        result = msg.get("result", {})
        worker_id = msg.get("worker_id")
        uri = self.store.put_json("results", tid, {"task_id": tid, "result": result})
        job, recovery, obj_ref = self.scheduler.complete_task(
            tid, result, worker_id=worker_id, result_uri=uri
        )
        if job is None:
            return make(MessageType.ERROR, error="stale or unknown task result", task_id=tid)
        metrics = self._job_metrics_for(job.job_id)
        if recovery is not None and metrics is not None:
            metrics.reclaim_recovery_sec += recovery
        if job.finished_at:
            self._finalize_job(job)
        return make(
            MessageType.TASK_RESULT,
            ok=True,
            stored=uri,
            object_ref=obj_ref.ref_id if obj_ref else None,
        )

    def _on_checkpoint(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        tid = msg["task_id"]
        cp = msg.get("checkpoint", {})
        if tid not in self.scheduler.task_index:
            return make(MessageType.ERROR, error="stale or unknown task checkpoint", task_id=tid)
        uri = self.store.put_json("checkpoints", tid, {"task_id": tid, "checkpoint": cp})
        obj_ref = self.scheduler.checkpoint_task(tid, cp, uri=uri)
        metrics = self._job_metrics_for_task(tid)
        if metrics is not None:
            metrics.checkpoint_uris.append(uri)
        return make(
            MessageType.TASK_CHECKPOINT,
            ok=True,
            stored=uri,
            object_ref=obj_ref.ref_id if obj_ref else None,
        )

    def _on_leave(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        wid = msg["worker_id"]
        t0 = time.time()
        reclaimed = self.scheduler.unregister_worker(wid)
        latency_ms = (time.time() - t0) * 1000.0
        self._leave_latencies.append(latency_ms)
        metrics_targets = []
        seen_job_ids = set()
        for task in reclaimed:
            if task.job_id in seen_job_ids:
                continue
            seen_job_ids.add(task.job_id)
            metrics = self._job_metrics_for(task.job_id)
            if metrics is not None:
                metrics_targets.append(metrics)
        if not metrics_targets:
            metrics = self._job_metrics_for(self.active_job_id)
            if metrics is not None:
                metrics_targets.append(metrics)
        for metrics in metrics_targets:
            metrics.reclaim_events += 1
            # leave_latency = owner leave ACK time; end-to-end recovery accrues on re-complete
            metrics.leave_latency_ms = latency_ms
        return make(
            MessageType.LEAVE,
            ok=True,
            requeued=len(reclaimed),
            leave_latency_ms=latency_ms,
        )

    def _on_job_submit(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        kernel = msg.get("kernel", "heat2d")
        policy = msg.get("policy", "hybrid")
        n_chunks = int(msg.get("chunks", 8))
        sched_cfg = self.cfg.get("scheduling", {})
        deadline = float(msg.get("deadline_sec", sched_cfg.get("default_deadline_sec", 120)))
        max_retries = int(msg.get("max_retries", sched_cfg.get("max_retries", 3)))
        placement = str(msg.get("placement", sched_cfg.get("placement", "spread")))
        # Shallow copy so per-job dataset/epochs overrides do not mutate process config
        cfg = dict(self.cfg)
        cfg["workloads"] = dict(self.cfg.get("workloads") or {})
        overrides = {
            "dataset": msg.get("dataset"),
            "label_col": msg.get("label_col"),
            "epochs": msg.get("epochs"),
            "lr": msg.get("lr"),
            "n_rows": msg.get("n_rows"),
            "n_samples": msg.get("n_samples"),
            "n_features": msg.get("n_features"),
        }
        cfg["_job_overrides"] = overrides
        specs = partition_job(kernel, cfg, n_chunks)
        job = self.scheduler.create_job(
            kernel,
            specs,
            policy=policy,
            deadline_sec=deadline,
            max_retries=max_retries,
            placement=placement,
        )
        self.active_job_id = job.job_id
        serial_proxy = self._serial_proxy(kernel, specs)
        self._job_metrics[job.job_id] = RunMetrics(
            job_id=job.job_id,
            policy=policy,
            kernel=kernel,
            n_tasks=len(job.tasks),
            serial_proxy_sec=serial_proxy,
        )
        self._job_burst_baselines[job.job_id] = (
            self.burst.launches,
            self.burst.snapshot_vm_seconds(),
        )
        print(f"[master] job {job.job_id} kernel={kernel} tasks={len(job.tasks)} policy={policy}", flush=True)
        return make(MessageType.JOB_SUBMIT, ok=True, job_id=job.job_id, tasks=len(job.tasks))

    def _serial_proxy(self, kernel: str, specs: List[Dict[str, Any]]) -> float:
        # rough proxy for speedup denominator (seconds)
        if kernel == "heat2d":
            total_rows = sum(int(s["params"].get("rows", 1)) for s in specs)
            steps = int(specs[0]["params"].get("steps", 40)) if specs else 40
            return max(0.05, total_rows * steps * 1e-5)
        if kernel == "batch":
            total = sum(int(s["params"].get("count", 1)) * int(s["params"].get("length", 1)) for s in specs)
            return max(0.05, total * 2e-8)
        total = sum(int(s["params"].get("work", 1)) for s in specs)
        return max(0.05, total * 5e-7)

    def _finalize_job(self, job: Job) -> None:
        m = self._job_metrics.get(job.job_id)
        if not m:
            return
        m.wall_time_sec = (job.finished_at or time.time()) - job.created_at
        m.campus_workers = max(
            m.campus_workers,
            sum(1 for w in self.scheduler.workers.values() if w.kind == "campus"),
        )
        baseline_launches, baseline_vm_seconds = self._job_burst_baselines.pop(job.job_id, (0, 0.0))
        m.cloud_workers = max(m.cloud_workers, max(0, self.burst.launches - baseline_launches))
        m.cloud_vm_seconds = max(
            m.cloud_vm_seconds,
            max(0.0, self.burst.snapshot_vm_seconds(job.finished_at or time.time()) - baseline_vm_seconds),
        )
        m.reclaim_events = max(m.reclaim_events, self.scheduler.reclaim_events)
        if self._leave_latencies:
            m.leave_latency_ms = sum(self._leave_latencies) / len(self._leave_latencies)
        path = self.metrics.record(m)
        payload = {
            "job_id": job.job_id,
            "checksum": job.checksum,
            "progress": self.scheduler.job_progress(job.job_id),
            "metrics_path": str(path),
        }
        if job.model:
            payload["model"] = job.model
        self.store.put_json("results", f"job_{job.job_id}", payload)
        if job.model:
            print(
                f"[master] job {job.job_id} DONE ML model shards={job.model.get('shards')} "
                f"bias={job.model.get('bias'):.4f} checksum={job.checksum:.6f} wall={m.wall_time_sec:.3f}s",
                flush=True,
            )
        else:
            print(f"[master] job {job.job_id} DONE checksum={job.checksum:.6f} wall={m.wall_time_sec:.3f}s", flush=True)

    def _worker_snapshot(self) -> List[Dict[str, Any]]:
        now = time.time()
        out = []
        for w in self.scheduler.workers.values():
            assigned_ids = [
                tid for tid, wid in self.scheduler.assigned.items() if wid == w.worker_id
            ]
            out.append({
                "worker_id": w.worker_id,
                "kind": w.kind,
                "cores": w.cores,
                "effective_threads": self.scheduler._effective_cores(w),
                "memory_mb": w.memory_mb,
                "effective_memory_mb": self.scheduler.effective_memory_mb(w),
                "gpu_count": w.gpu_count,
                "max_tasks": self.scheduler._max_concurrent(w),
                "consented": w.consented,
                "paused": w.paused,
                "tasks_done": w.tasks_done,
                "cpu_cap_threads": w.cpu_cap_threads,
                "load": len(assigned_ids),
                "assigned_tasks": assigned_ids,
                "heartbeat_age_sec": round(max(0.0, now - w.last_heartbeat), 2),
                "connected_for_sec": round(max(0.0, now - w.connected_at), 1),
            })
        return out

    def _topology_snapshot(self) -> Dict[str, Any]:
        """Live fabric view for the gateway dashboard (hub + workers + jobs)."""
        workers = self._worker_snapshot()
        links = [
            {
                "from": w["worker_id"],
                "to": "gateway",
                "kind": w["kind"],
                "active": int(w.get("load", 0)) > 0,
                "paused": bool(w.get("paused")),
            }
            for w in workers
        ]
        jobs_out: List[Dict[str, Any]] = []
        for job in sorted(
            self.scheduler.jobs.values(),
            key=lambda j: j.created_at,
            reverse=True,
        )[:12]:
            prog = self.scheduler.job_progress(job.job_id)
            task_rows = []
            for t in job.tasks:
                task_rows.append({
                    "task_id": t.task_id,
                    "state": t.state.value,
                    "worker_id": t.worker_id,
                    "attempts": t.attempts,
                    "kernel": t.kernel,
                })
            jobs_out.append({
                **prog,
                "created_at": job.created_at,
                "active": job.job_id == self.active_job_id and job.finished_at is None,
                "tasks": task_rows,
            })
        pending = list(self.scheduler.pending)
        assigned = [
            {"task_id": tid, "worker_id": wid}
            for tid, wid in self.scheduler.assigned.items()
        ]
        return {
            "gateway": {
                "id": "gateway",
                "role": "master",
                "host": self.cfg.get("master", {}).get("advertise_host") or self.host,
                "port": self.port,
                "active_job_id": self.active_job_id,
                "auth": bool(self.join_token),
                "storage": self.store.backend,
                "burst_mode": self.burst.mode,
                "pending_tasks": len(pending),
                "assigned_tasks": len(assigned),
                "worker_count": len(workers),
                "campus_count": sum(1 for w in workers if w["kind"] == "campus"),
                "cloud_count": sum(1 for w in workers if w["kind"] == "cloud"),
            },
            "workers": workers,
            "links": links,
            "jobs": jobs_out,
            "queue": {"pending": pending[:40], "assigned": assigned},
            "gcs": self.scheduler.gcs.snapshot(),
            "ts": time.time(),
        }

    async def _control_loop(self) -> None:
        while self.state.get("running", True):
            try:
                await self._tick()
            except Exception as exc:
                print(f"[master] control loop error: {exc}", flush=True)
            await asyncio.sleep(0.5)

    async def _tick(self) -> None:
        busy_workers: set[str] = set()
        async with self._lock:
            # heartbeat reclaim
            now = time.time()
            stale = [
                wid for wid, w in self.scheduler.workers.items()
                if now - w.last_heartbeat > self.hb_timeout
            ]
            for wid in stale:
                print(f"[master] heartbeat timeout reclaim {wid}", flush=True)
                self.scheduler.unregister_worker(wid)

            # assign tasks
            prefer_peer = self.peer_first
            cloud_only = False
            campus_only = False
            if self.active_job_id:
                job = self.scheduler.jobs.get(self.active_job_id)
                if job and job.policy == "cloud_only":
                    prefer_peer = False
                    cloud_only = True
                if job and job.policy == "campus_only":
                    campus_only = True

            place = None
            if self.active_job_id and self.active_job_id in self.scheduler.jobs:
                place = self.scheduler.jobs[self.active_job_id].placement
            assignments = self.scheduler.assign_next(
                peer_first=prefer_peer,
                cloud_only=cloud_only,
                campus_only=campus_only,
                placement=place,
            )
            for worker, task in assignments:
                if worker.writer is None:
                    continue
                payload = make(
                    MessageType.TASK_ASSIGN,
                    task_id=task.task_id,
                    job_id=task.job_id,
                    kernel=task.kernel,
                    params=task.params,
                    resources=task.resources.to_dict(),
                    object_ref=task.checkpoint_ref,
                    attempt=task.attempts,
                    max_retries=task.max_retries,
                )
                try:
                    worker.writer.write(encode(payload))
                    await worker.writer.drain()
                except Exception:
                    self.scheduler.unregister_worker(worker.worker_id)

            # burst policy
            if self.active_job_id and self.active_job_id in self.scheduler.jobs:
                job = self.scheduler.jobs[self.active_job_id]
                if job.finished_at is None and job.policy in ("hybrid", "cloud_only"):
                    pending = sum(1 for t in job.tasks if t.state.value != "DONE")
                    should = self.burst.evaluate(
                        campus_peers=self.scheduler.campus_peer_count(),
                        reclaim_rate=self.scheduler.reclaim_rate(),
                        projected_finish=self.scheduler.projected_finish(job.job_id),
                        deadline_ts=job.deadline_ts,
                        pending_tasks=pending,
                    )
                    if job.policy == "cloud_only":
                        should = pending > 0 and len(self.burst.vms) < self.burst.max_vms
                    if job.policy == "campus_only":
                        should = False
                    if should and self.scheduler.cloud_peer_count() < self.burst.max_vms:
                        reason = "policy"
                        if self.burst.force_burst:
                            reason = "force"
                        elif self.scheduler.campus_peer_count() < self.burst.min_peers:
                            reason = "peer_shortage"
                        elif self.scheduler.reclaim_rate() >= self.burst.reclaim_threshold:
                            reason = "reclaim_storm"
                        elif self.scheduler.projected_finish(job.job_id) > job.deadline_ts:
                            reason = "deadline_risk"
                        asyncio.create_task(self._do_burst(reason))

            busy_workers = set(self.scheduler.assigned.values())
            for wid in busy_workers:
                if wid in self.burst.vms:
                    self.burst.mark_busy(wid)

        retired = await self.burst.retire_idle(busy_workers)
        for vid in retired:
            print(f"[master] retired idle cloud worker {vid}", flush=True)

    async def _do_burst(self, reason: str) -> None:
        connect_host = (
            str(self.cfg.get("burst", {}).get("aws_master_host") or "").strip()
            or str(self.cfg.get("master", {}).get("advertise_host") or "").strip()
            or self.host
        )
        vm = await self.burst.maybe_burst(reason, connect_host, self.port)
        if vm:
            print(f"[master] cloud-burst launch {vm.vm_id} reason={reason}", flush=True)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Hybrid desktop-grid master")
    parser.add_argument("--config", default=str(ROOT / "config" / "default.yaml"))
    args = parser.parse_args()
    cfg = load_config(Path(args.config))
    errs = validate_config(cfg)
    if errs:
        raise SystemExit("config errors: " + "; ".join(errs))
    if bool((cfg.get("auth") or {}).get("require_token")) and not resolve_join_token(cfg):
        raise SystemExit("auth.require_token set but HPC_JOIN_TOKEN / auth.join_token missing")
    master = MasterServer(cfg, ROOT)
    await master.start()
    try:
        await master.serve_forever()
    except KeyboardInterrupt:
        await master.stop()


if __name__ == "__main__":
    asyncio.run(main())
