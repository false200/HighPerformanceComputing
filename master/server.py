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

from master.burst import BurstController
from master.metrics import MetricsCollector, RunMetrics
from master.scheduler import Job, Scheduler, WorkerInfo
from master.storage import ObjectStore
from protocol.messages import MessageType, decode, encode, make


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
        self.hb_timeout = float(cfg.get("scheduling", {}).get("heartbeat_timeout_sec", 6.0))
        self.peer_first = bool(cfg.get("scheduling", {}).get("peer_first", True))
        self.active_job_id: Optional[str] = None
        self._job_metrics: Dict[str, RunMetrics] = {}
        self._leave_latencies: List[float] = []
        self._server: Optional[asyncio.AbstractServer] = None
        self._lock = asyncio.Lock()
        self.state: Dict[str, Any] = {"running": False}

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle_client, self.host, self.port)
        self.state["running"] = True
        asyncio.create_task(self._control_loop())
        sockets = self._server.sockets or []
        addr = sockets[0].getsockname() if sockets else (self.host, self.port)
        print(f"[master] listening on {addr[0]}:{addr[1]}", flush=True)

    async def serve_forever(self) -> None:
        assert self._server is not None
        async with self._server:
            await self._server.serve_forever()

    async def stop(self) -> None:
        self.burst.shutdown_all()
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        self.state["running"] = False

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
                msg = decode(line)
                if not msg:
                    continue
                resp = await self._dispatch(msg, writer)
                if resp is not None:
                    writer.write(encode(resp))
                    await writer.drain()
                if msg.get("type") == MessageType.REGISTER.value:
                    worker_id = msg.get("worker_id")
        except Exception as exc:
            print(f"[master] client error {peer}: {exc}", flush=True)
        finally:
            if worker_id:
                async with self._lock:
                    self.scheduler.unregister_worker(worker_id)
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
            if mtype == MessageType.LEAVE.value:
                return self._on_leave(msg)
            if mtype == MessageType.PAUSE.value:
                self.scheduler.set_paused(msg["worker_id"], True)
                return make(MessageType.PAUSE, ok=True)
            if mtype == MessageType.RESUME.value:
                self.scheduler.set_paused(msg["worker_id"], False)
                return make(MessageType.RESUME, ok=True)
            if mtype == MessageType.JOB_SUBMIT.value:
                return self._on_job_submit(msg)
            if mtype == MessageType.JOB_STATUS.value:
                jid = msg.get("job_id") or self.active_job_id
                if not jid or jid not in self.scheduler.jobs:
                    return make(MessageType.ERROR, error="no job")
                return make(MessageType.JOB_STATUS, **self.scheduler.job_progress(jid))
            if mtype == MessageType.FORCE_BURST.value:
                self.burst.force_burst = bool(msg.get("enabled", True))
                return make(MessageType.FORCE_BURST, force_burst=self.burst.force_burst)
            if mtype == MessageType.METRICS.value:
                return make(MessageType.METRICS, burst=self.burst.status(), workers=self._worker_snapshot())
            if mtype == MessageType.SHUTDOWN.value:
                asyncio.create_task(self.stop())
                return make(MessageType.SHUTDOWN, ok=True)
            return make(MessageType.ERROR, error=f"unknown type {mtype}")

    def _on_register(self, msg: Dict[str, Any], writer: asyncio.StreamWriter) -> Dict[str, Any]:
        wid = msg.get("worker_id") or uuid.uuid4().hex[:10]
        info = WorkerInfo(
            worker_id=wid,
            kind=msg.get("kind", "campus"),
            cores=int(msg.get("cores", 1)),
            memory_mb=int(msg.get("memory_mb", 1024)),
            os_name=str(msg.get("os", "unknown")),
            cpu_cap_threads=int(msg.get("cpu_cap_threads", 0)),
            idle_only=bool(msg.get("idle_only", False)),
            consented=bool(msg.get("consented", False)),
            instance_type=msg.get("instance_type"),
            region=msg.get("region"),
            writer=writer,
        )
        if info.kind == "cloud":
            info.consented = True  # system-launched
        self.scheduler.register_worker(info)
        print(f"[master] registered {info.kind} worker {wid} cores={info.cores}", flush=True)
        return make(MessageType.REGISTER_ACK, worker_id=wid, ok=True, consented=info.consented)

    def _on_result(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        tid = msg["task_id"]
        result = msg.get("result", {})
        job, recovery = self.scheduler.complete_task(tid, result)
        if recovery is not None and self.active_job_id and self.active_job_id in self._job_metrics:
            self._job_metrics[self.active_job_id].reclaim_recovery_sec += recovery
        uri = self.store.put_json("results", tid, {"task_id": tid, "result": result})
        if job and job.finished_at:
            self._finalize_job(job)
        return make(MessageType.TASK_RESULT, ok=True, stored=uri)

    def _on_checkpoint(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        tid = msg["task_id"]
        cp = msg.get("checkpoint", {})
        self.scheduler.checkpoint_task(tid, cp)
        uri = self.store.put_json("checkpoints", tid, {"task_id": tid, "checkpoint": cp})
        if self.active_job_id and self.active_job_id in self._job_metrics:
            self._job_metrics[self.active_job_id].checkpoint_uris.append(uri)
        return make(MessageType.TASK_CHECKPOINT, ok=True, stored=uri)

    def _on_leave(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        wid = msg["worker_id"]
        t0 = time.time()
        reclaimed = self.scheduler.unregister_worker(wid)
        latency_ms = (time.time() - t0) * 1000.0
        self._leave_latencies.append(latency_ms)
        if self.active_job_id and self.active_job_id in self._job_metrics:
            m = self._job_metrics[self.active_job_id]
            m.reclaim_events += 1
            # leave_latency = owner leave ACK time; end-to-end recovery accrues on re-complete
            m.leave_latency_ms = latency_ms
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
        deadline = float(msg.get("deadline_sec", self.cfg.get("scheduling", {}).get("default_deadline_sec", 120)))
        specs = partition_job(kernel, self.cfg, n_chunks)
        job = self.scheduler.create_job(kernel, specs, policy=policy, deadline_sec=deadline)
        self.active_job_id = job.job_id
        serial_proxy = self._serial_proxy(kernel, specs)
        self._job_metrics[job.job_id] = RunMetrics(
            job_id=job.job_id,
            policy=policy,
            kernel=kernel,
            n_tasks=len(job.tasks),
            serial_proxy_sec=serial_proxy,
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
        # Prefer measured sequential proxy = sum of per-task OpenMP wall times
        measured = 0.0
        for t in job.tasks:
            if t.result and "elapsed_ms" in t.result:
                measured += float(t.result["elapsed_ms"]) / 1000.0
        if measured > 0:
            m.serial_proxy_sec = measured
        m.campus_workers = max(
            m.campus_workers,
            sum(1 for w in self.scheduler.workers.values() if w.kind == "campus"),
        )
        # peak cloud launches during job
        m.cloud_workers = max(m.cloud_workers, self.burst.launches)
        m.cloud_vm_seconds = self.burst.vm_seconds
        m.reclaim_events = max(m.reclaim_events, self.scheduler.reclaim_events)
        if self._leave_latencies:
            m.leave_latency_ms = sum(self._leave_latencies) / len(self._leave_latencies)
        path = self.metrics.record(m)
        self.store.put_json("results", f"job_{job.job_id}", {
            "job_id": job.job_id,
            "checksum": job.checksum,
            "progress": self.scheduler.job_progress(job.job_id),
            "metrics_path": str(path),
        })
        print(f"[master] job {job.job_id} DONE checksum={job.checksum:.6f} wall={m.wall_time_sec:.3f}s", flush=True)

    def _worker_snapshot(self) -> List[Dict[str, Any]]:
        out = []
        for w in self.scheduler.workers.values():
            out.append({
                "worker_id": w.worker_id,
                "kind": w.kind,
                "cores": w.cores,
                "consented": w.consented,
                "paused": w.paused,
                "tasks_done": w.tasks_done,
                "cpu_cap_threads": w.cpu_cap_threads,
            })
        return out

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
            if self.active_job_id:
                job = self.scheduler.jobs.get(self.active_job_id)
                if job and job.policy == "cloud_only":
                    prefer_peer = False
                    cloud_only = True
                if job and job.policy == "campus_only":
                    prefer_peer = True
                    cloud_only = False

            assignments = self.scheduler.assign_next(
                peer_first=prefer_peer, cloud_only=cloud_only
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
        connect_host = "127.0.0.1"
        vm = await self.burst.maybe_burst(reason, connect_host, self.port)
        if vm:
            print(f"[master] cloud-burst launch {vm.vm_id} reason={reason}", flush=True)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Hybrid desktop-grid master")
    parser.add_argument("--config", default=str(ROOT / "config" / "default.yaml"))
    args = parser.parse_args()
    cfg = load_config(Path(args.config))
    master = MasterServer(cfg, ROOT)
    await master.start()
    try:
        await master.serve_forever()
    except KeyboardInterrupt:
        await master.stop()


if __name__ == "__main__":
    asyncio.run(main())
