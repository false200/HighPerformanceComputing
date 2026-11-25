from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from protocol.messages import MessageType, decode, encode, make
from worker.consent import prompt_consent
from worker.qos import (
    apply_below_normal_priority,
    apply_memory_cap_mb,
    detect_gpu_count,
    effective_threads,
    set_omp_threads,
    system_is_idle,
)


def find_kernel_binary() -> Path:
    candidates = [
        ROOT / "bin" / "omp_kernels.exe",
        ROOT / "bin" / "omp_kernels",
    ]
    for c in candidates:
        if c.exists():
            return c
    raise FileNotFoundError(
        "omp_kernels binary not found. Build with scripts/build_kernels.ps1 first."
    )


def cpu_count() -> int:
    return os.cpu_count() or 1


def memory_mb() -> int:
    try:
        if os.name == "nt":
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return int(stat.ullTotalPhys / (1024 * 1024))
    except Exception:
        pass
    return 4096


def run_kernel(
    kernel: str,
    params: Dict[str, Any],
    proc_setter=None,
    proc_clearer=None,
) -> Dict[str, Any]:
    binary = find_kernel_binary()
    threads = int(params.get("threads") or 0)
    cmd = [str(binary), kernel]
    if kernel == "heat2d":
        cmd += [
            "--grid", str(params.get("grid", 128)),
            "--steps", str(params.get("steps", 40)),
            "--tile", str(params.get("tile", 16)),
            "--start-row", str(params.get("start_row", 0)),
            "--rows", str(params.get("rows", 16)),
        ]
    elif kernel == "batch":
        cmd += [
            "--offset", str(params.get("offset", 0)),
            "--count", str(params.get("count", 8)),
            "--length", str(params.get("length", 100000)),
        ]
    else:
        cmd += [
            "--seed", str(params.get("seed", 1)),
            "--work", str(params.get("work", 20000)),
        ]
    if threads > 0:
        cmd += ["--threads", str(threads)]
        set_omp_threads(threads)

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(ROOT),
    )
    if proc_setter is not None:
        proc_setter(proc)
    try:
        stdout, stderr = proc.communicate()
    finally:
        if proc_clearer is not None:
            proc_clearer(proc)
    if proc.returncode != 0:
        raise RuntimeError(f"kernel failed: {stderr or stdout}")
    lines = [ln.strip() for ln in stdout.splitlines() if ln.strip().startswith("{")]
    if not lines:
        raise RuntimeError(f"no JSON from kernel: {stdout}")
    return json.loads(lines[-1])


class WorkerAgent:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.worker_id = args.worker_id or f"{args.kind}-{uuid.uuid4().hex[:8]}"
        self.paused = False
        self.leaving = False
        self.current_task: Optional[str] = None
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.cores = cpu_count()
        self.cpu_cap = int(args.cpu_cap or 0)
        self.ram_cap_mb = int(getattr(args, "ram_cap_mb", 0) or 0)
        self.gpu_count = int(getattr(args, "gpus", -1))
        if self.gpu_count < 0:
            self.gpu_count = detect_gpu_count()
        self.max_tasks = int(getattr(args, "max_tasks", 0) or 0)
        self.idle_only = bool(args.idle_only)
        self._inbox: asyncio.Queue = asyncio.Queue()
        self._replies: asyncio.Queue = asyncio.Queue()
        self._kernel_proc_lock = threading.Lock()
        self._kernel_proc: Optional[subprocess.Popen[Any]] = None
        self._send_lock = asyncio.Lock()
        self._rpc_lock = asyncio.Lock()
        self._expect_reply = False

    async def run(self) -> None:
        if self.args.kind == "campus":
            ok = prompt_consent(auto=self.args.auto_consent)
            if not ok:
                print("[worker] consent declined; exiting")
                return
            consented = True
        else:
            consented = True
            print(f"[worker] cloud worker {self.worker_id} starting (system-launched)")

        if self.args.below_normal_priority:
            apply_below_normal_priority()
        if self.ram_cap_mb > 0:
            if apply_memory_cap_mb(self.ram_cap_mb):
                print(f"[qos] RAM cap applied: {self.ram_cap_mb} MiB", flush=True)
            else:
                print(f"[qos] RAM cap advertised: {self.ram_cap_mb} MiB (soft)", flush=True)
        threads = effective_threads(self.cores, self.cpu_cap)
        set_omp_threads(threads)
        print(
            f"[qos] donate cpu={threads}/{self.cores} threads  "
            f"ram={self.ram_cap_mb or memory_mb()} MiB  "
            f"gpus={self.gpu_count} (inventory only)  "
            f"max_tasks={self.max_tasks or threads}",
            flush=True,
        )
        if self.gpu_count:
            print(
                "[qos] Note: current kernels are CPU/OpenMP — GPUs are recorded but not scheduled yet.",
                flush=True,
            )

        host, port_s = self.args.master.split(":")
        port = int(port_s)
        self.reader, self.writer = await asyncio.open_connection(host, port)

        reader_task = asyncio.create_task(self._reader_loop())

        reg = make(
            MessageType.REGISTER,
            worker_id=self.worker_id,
            kind=self.args.kind,
            cores=self.cores,
            memory_mb=memory_mb(),
            memory_cap_mb=self.ram_cap_mb,
            gpu_count=self.gpu_count,
            max_tasks=self.max_tasks,
            os=platform.platform(),
            consented=consented,
            cpu_cap_threads=self.cpu_cap,
            idle_only=self.idle_only,
            instance_type=self.args.instance_type,
            region=self.args.region,
            name=self.args.name,
        )
        ack = await self._request(reg)
        if not ack or ack.get("type") != MessageType.REGISTER_ACK.value:
            print(f"[worker] register failed: {ack}")
            reader_task.cancel()
            return
        self.worker_id = ack.get("worker_id", self.worker_id)
        print(f"[worker] registered as {self.worker_id}", flush=True)
        if self.args.kind == "campus" and self._controls_enabled():
            print(
                "[controls] keys: [p]ause  [r]esume  [l]eave  [s]tatus  (then Enter)",
                flush=True,
            )

        hb_task = asyncio.create_task(self._heartbeat_loop())
        work_task = asyncio.create_task(self._work_loop())
        ctrl_task = None
        if self._controls_enabled():
            ctrl_task = asyncio.create_task(self._stdin_control_loop())
        try:
            if self.args.demo_leave_after:
                asyncio.create_task(self._demo_leave(float(self.args.demo_leave_after)))
            await work_task
        finally:
            self.leaving = True
            hb_task.cancel()
            reader_task.cancel()
            if ctrl_task:
                ctrl_task.cancel()
            await self._close()

    def _controls_enabled(self) -> bool:
        if self.args.no_controls:
            return False
        if self.args.controls:
            return True
        return bool(sys.stdin and sys.stdin.isatty())

    def _set_kernel_proc(self, proc: Optional[subprocess.Popen[Any]]) -> None:
        with self._kernel_proc_lock:
            self._kernel_proc = proc

    def _get_kernel_proc(self) -> Optional[subprocess.Popen[Any]]:
        with self._kernel_proc_lock:
            return self._kernel_proc

    def _clear_kernel_proc(self, proc: subprocess.Popen[Any]) -> None:
        with self._kernel_proc_lock:
            if self._kernel_proc is proc:
                self._kernel_proc = None

    def _stop_kernel_proc(self) -> None:
        proc = self._get_kernel_proc()
        if proc is None:
            return
        if proc.poll() is not None:
            self._clear_kernel_proc(proc)
            return
        try:
            proc.terminate()
        except Exception:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except Exception:
                pass
            try:
                proc.wait(timeout=5)
            except Exception:
                pass
        finally:
            self._clear_kernel_proc(proc)

    async def _reader_loop(self) -> None:
        """Single demux reader — avoids heartbeat/work racing on StreamReader."""
        assert self.reader is not None
        while not self.leaving:
            line = await self.reader.readline()
            if not line:
                await self._inbox.put(None)
                break
            msg = decode(line)
            if msg is None:
                continue
            mtype = msg.get("type")
            if mtype == MessageType.TASK_ASSIGN.value:
                await self._inbox.put(msg)
            elif mtype == MessageType.SHUTDOWN.value:
                await self._inbox.put(msg)
            elif mtype == MessageType.HEARTBEAT.value and not self._expect_reply:
                # Fire-and-forget heartbeat ACK
                continue
            else:
                # RPC reply (register/checkpoint/result/leave) or unexpected
                if self._expect_reply:
                    await self._replies.put(msg)
                elif mtype in {MessageType.PAUSE.value, MessageType.RESUME.value}:
                    await self._inbox.put(msg)

    async def _request(self, msg: Dict[str, Any], timeout: float = 30.0) -> Optional[Dict[str, Any]]:
        async with self._rpc_lock:
            # Drain stale replies
            while not self._replies.empty():
                try:
                    self._replies.get_nowait()
                except Exception:
                    break
            self._expect_reply = True
            try:
                await self._send(msg)
                return await asyncio.wait_for(self._replies.get(), timeout=timeout)
            except asyncio.TimeoutError:
                return None
            finally:
                self._expect_reply = False

    async def _demo_leave(self, after: float) -> None:
        await asyncio.sleep(after)
        print(f"[worker] demo leave after {after}s", flush=True)
        await self._leave()

    async def _stdin_control_loop(self) -> None:
        """Owner QoS hotkeys: p=pause, r=resume, l=leave, s=status."""
        while not self.leaving:
            try:
                line = await asyncio.to_thread(sys.stdin.readline)
            except Exception:
                break
            if not line:
                await asyncio.sleep(0.2)
                continue
            cmd = line.strip().lower()
            if cmd in {"p", "pause"}:
                self.paused = True
                try:
                    await self._request(make(MessageType.PAUSE, worker_id=self.worker_id), timeout=5)
                except Exception:
                    pass
                print("[controls] paused — no new tasks", flush=True)
            elif cmd in {"r", "resume"}:
                self.paused = False
                try:
                    await self._request(make(MessageType.RESUME, worker_id=self.worker_id), timeout=5)
                except Exception:
                    pass
                print("[controls] resumed", flush=True)
            elif cmd in {"l", "leave", "q", "quit"}:
                print("[controls] leaving peer pool…", flush=True)
                await self._leave()
                break
            elif cmd in {"s", "status"}:
                print(
                    f"[status] id={self.worker_id} paused={self.paused} "
                    f"task={self.current_task or '-'} "
                    f"cpu={self.cpu_cap or self.cores}/{self.cores} "
                    f"ram_cap={self.ram_cap_mb or 'full'}MB "
                    f"gpus={self.gpu_count} max_tasks={self.max_tasks or 'auto'} "
                    f"idle_only={self.idle_only}",
                    flush=True,
                )
            elif cmd:
                print("[controls] unknown — use p/r/l/s", flush=True)

    async def _heartbeat_loop(self) -> None:
        interval = float(self.args.heartbeat)
        while not self.leaving:
            try:
                # Fire-and-forget so heartbeats never steal RPC replies
                await self._send(make(MessageType.HEARTBEAT, worker_id=self.worker_id))
            except Exception:
                break
            await asyncio.sleep(interval)

    async def _work_loop(self) -> None:
        while not self.leaving:
            msg = await self._inbox.get()
            if msg is None:
                break
            mtype = msg.get("type")
            if mtype == MessageType.TASK_ASSIGN.value:
                if self.paused or self.leaving:
                    await self._reclaim_dropped_task(msg)
                    continue
                if self.idle_only:
                    while not system_is_idle() and not self.leaving and not self.paused:
                        print("[worker] idle-only: system busy, waiting…", flush=True)
                        await asyncio.sleep(2.0)
                    if self.leaving or self.paused:
                        await self._reclaim_dropped_task(msg)
                        continue
                await self._execute_task(msg)
            elif mtype == MessageType.SHUTDOWN.value:
                break
            elif mtype == MessageType.PAUSE.value:
                self.paused = True
            elif mtype == MessageType.RESUME.value:
                self.paused = False

    async def _reclaim_dropped_task(self, msg: Dict[str, Any]) -> None:
        try:
            await self._request(
                make(
                    MessageType.TASK_RECLAIM,
                    worker_id=self.worker_id,
                    task_id=msg["task_id"],
                    reason="leave" if self.leaving else "pause",
                ),
                timeout=5,
            )
        except Exception:
            pass

    async def _execute_task(self, msg: Dict[str, Any]) -> None:
        tid = msg["task_id"]
        kernel = msg["kernel"]
        params = dict(msg.get("params") or {})
        threads = effective_threads(self.cores, self.cpu_cap)
        requested_threads = int(params.get("threads") or 0)
        params["threads"] = max(1, min(requested_threads or threads, threads))
        self.current_task = tid
        print(f"[worker] start task {tid} kernel={kernel}", flush=True)

        try:
            await self._request(make(
                MessageType.TASK_CHECKPOINT,
                worker_id=self.worker_id,
                task_id=tid,
                checkpoint={"phase": "start", "ts": time.time()},
            ))

            try:
                result = await asyncio.to_thread(
                    run_kernel,
                    kernel,
                    params,
                    self._set_kernel_proc,
                    self._clear_kernel_proc,
                )
            except Exception as exc:
                result = {"kernel": kernel, "checksum": 0.0, "error": str(exc), "elapsed_ms": 0.0}

            if self.leaving:
                return

            await self._request(make(
                MessageType.TASK_RESULT,
                worker_id=self.worker_id,
                task_id=tid,
                result=result,
            ))
            print(f"[worker] done task {tid} checksum={result.get('checksum')}", flush=True)
        finally:
            self.current_task = None

    async def _leave(self) -> None:
        self.leaving = True
        await asyncio.to_thread(self._stop_kernel_proc)
        if self.current_task:
            try:
                await self._request(make(
                    MessageType.TASK_CHECKPOINT,
                    worker_id=self.worker_id,
                    task_id=self.current_task,
                    checkpoint={"phase": "leave", "ts": time.time()},
                ), timeout=5)
            except Exception:
                pass
        try:
            await self._request(make(MessageType.LEAVE, worker_id=self.worker_id), timeout=5)
        except Exception:
            pass
        await self._inbox.put(None)

    async def _send(self, msg: Dict[str, Any]) -> None:
        assert self.writer is not None
        async with self._send_lock:
            self.writer.write(encode(msg))
            await self.writer.drain()

    async def _close(self) -> None:
        if self.writer:
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except Exception:
                pass


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Campus/cloud OpenMP worker")
    p.add_argument("--master", default="127.0.0.1:9100")
    p.add_argument("--kind", choices=["campus", "cloud"], default="campus")
    p.add_argument("--worker-id", default=None)
    p.add_argument("--name", default="worker")
    p.add_argument("--auto-consent", action="store_true")
    p.add_argument("--cpu-cap", type=int, default=0, help="Max OpenMP threads to donate (0=all)")
    p.add_argument("--ram-cap-mb", type=int, default=0, help="RAM budget MiB (0=full machine)")
    p.add_argument("--gpus", type=int, default=-1, help="GPU count to advertise (-1=auto-detect)")
    p.add_argument("--max-tasks", type=int, default=0, help="Max concurrent tasks (0=use CPU cap)")
    p.add_argument("--profile", default=None, help="YAML resource profile path")
    p.add_argument("--idle-only", action="store_true")
    p.add_argument("--below-normal-priority", action="store_true", default=True)
    p.add_argument("--no-below-normal-priority", action="store_false", dest="below_normal_priority")
    p.add_argument("--heartbeat", type=float, default=2.0)
    p.add_argument("--demo-leave-after", type=float, default=0.0)
    p.add_argument("--instance-type", default=None)
    p.add_argument("--region", default=None)
    p.add_argument("--controls", action="store_true", help="Force stdin p/r/l/s controls")
    p.add_argument(
        "--no-controls",
        action="store_true",
        help="Disable stdin controls (default off when non-TTY / automation)",
    )
    return p


def _apply_profile(args: argparse.Namespace) -> argparse.Namespace:
    path = args.profile
    if not path:
        default = ROOT / "config" / "worker_local.yaml"
        if default.exists():
            path = str(default)
    if not path:
        return args
    try:
        import yaml
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except Exception as exc:
        print(f"[qos] could not load profile {path}: {exc}")
        return args
    if args.cpu_cap == 0 and "cpu_cap" in data:
        args.cpu_cap = int(data.get("cpu_cap") or 0)
    if getattr(args, "ram_cap_mb", 0) == 0 and "ram_cap_mb" in data:
        args.ram_cap_mb = int(data.get("ram_cap_mb") or 0)
    if getattr(args, "gpus", -1) < 0 and "gpus" in data:
        args.gpus = int(data.get("gpus") if data.get("gpus") is not None else -1)
    if getattr(args, "max_tasks", 0) == 0 and "max_tasks" in data:
        args.max_tasks = int(data.get("max_tasks") or 0)
    if not args.idle_only and data.get("idle_only"):
        args.idle_only = True
    if data.get("below_normal_priority") is False:
        args.below_normal_priority = False
    print(f"[qos] loaded profile {path}", flush=True)
    return args


def main() -> None:
    args = _apply_profile(build_parser().parse_args())
    asyncio.run(WorkerAgent(args).run())


if __name__ == "__main__":
    main()
