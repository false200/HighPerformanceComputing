from __future__ import annotations

import asyncio
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class CloudVM:
    vm_id: str
    launched_at: float
    process: Optional[subprocess.Popen] = None
    kind: str = "local_sim"
    last_busy_at: float = field(default_factory=time.time)
    instance_id: Optional[str] = None  # AWS


class BurstController:
    """
    Policy-driven cloud-burst overflow.
    Modes:
      - local_sim: spawn extra campus-like workers tagged as cloud
      - aws: invoke scripts/aws_launch_worker.(sh|ps1) (operator-run path)
    """

    def __init__(self, cfg: Dict[str, Any], project_root: Path):
        self.cfg = cfg
        self.sched_cfg = cfg.get("scheduling", {})
        self.burst_cfg = cfg.get("burst", {})
        self.mode = self.burst_cfg.get("mode", "local_sim")
        self.max_vms = int(self.sched_cfg.get("max_cloud_vms", 2))
        self.idle_timeout = float(self.sched_cfg.get("cloud_idle_timeout_sec", 15.0))
        self.min_peers = int(self.sched_cfg.get("min_campus_peers", 1))
        self.reclaim_threshold = float(self.sched_cfg.get("reclaim_rate_threshold", 0.3))
        self.project_root = project_root
        self.vms: Dict[str, CloudVM] = {}
        self.force_burst = False
        self.launches = 0
        self.retirements = 0
        self.vm_seconds = 0.0
        self._events: List[Dict[str, Any]] = []

    def _aws_master_host(self, fallback_host: str) -> str:
        host = str(self.burst_cfg.get("aws_master_host") or "").strip()
        if not host:
            host = str(self.cfg.get("master", {}).get("advertise_host") or "").strip()
        if not host:
            host = fallback_host.strip()
        if host in {"", "127.0.0.1", "0.0.0.0", "::", "localhost"}:
            raise RuntimeError(
                "AWS burst requires a reachable master host; set burst.aws_master_host or master.advertise_host"
            )
        return host

    @staticmethod
    def _extract_instance_id(output: str) -> Optional[str]:
        match = re.search(r"\bi-[0-9a-fA-F]+\b", output)
        if match:
            return match.group(0)
        output = output.strip()
        if output.startswith("i-"):
            return output.split()[0]
        return None

    def evaluate(
        self,
        campus_peers: int,
        reclaim_rate: float,
        projected_finish: float,
        deadline_ts: float,
        pending_tasks: int,
    ) -> bool:
        if pending_tasks <= 0:
            return False
        if len(self.vms) >= self.max_vms:
            return False
        if self.force_burst:
            return True
        if campus_peers < self.min_peers:
            return True
        if reclaim_rate >= self.reclaim_threshold:
            return True
        if projected_finish > deadline_ts:
            return True
        return False

    async def maybe_burst(self, reason: str, master_host: str, master_port: int) -> Optional[CloudVM]:
        if len(self.vms) >= self.max_vms:
            return None
        vm_id = f"cloud-{self.launches + 1}-{int(time.time()) % 100000}"
        if self.mode == "aws":
            vm = await self._launch_aws(vm_id, master_host, master_port)
        else:
            vm = await self._launch_local(vm_id, master_host, master_port)
        if vm:
            self.vms[vm_id] = vm
            self.launches += 1
            self._events.append({"ts": time.time(), "event": "launch", "vm_id": vm_id, "reason": reason})
        return vm

    async def _launch_local(self, vm_id: str, host: str, port: int) -> CloudVM:
        py = sys.executable
        connect_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
        cmd = [
            py,
            "-m",
            "worker",
            "--master", f"{connect_host}:{port}",
            "--kind", "cloud",
            "--worker-id", vm_id,
            "--auto-consent",
            "--no-controls",
            "--name", vm_id,
        ]
        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        proc = subprocess.Popen(
            cmd,
            cwd=str(self.project_root),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        return CloudVM(vm_id=vm_id, launched_at=time.time(), process=proc, kind="local_sim")

    async def _launch_aws(self, vm_id: str, host: str, port: int) -> Optional[CloudVM]:
        script = self.project_root / "scripts" / ("aws_launch_worker.ps1" if os.name == "nt" else "aws_launch_worker.sh")
        if not script.exists():
            raise RuntimeError(f"AWS launch script missing: {script}")
        master_host = self._aws_master_host(host)
        env = os.environ.copy()
        env.update({
            "HPC_MASTER_HOST": master_host,
            "HPC_MASTER_PORT": str(port),
            "HPC_WORKER_ID": vm_id,
            "HPC_AMI": str(self.burst_cfg.get("aws_ami", "")),
            "HPC_INSTANCE_TYPE": str(self.burst_cfg.get("aws_instance_type", "t3.micro")),
            "HPC_REGION": str(self.burst_cfg.get("aws_region", "us-east-1")),
        })
        if os.name == "nt":
            result = subprocess.run(
                ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                cwd=str(self.project_root),
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )
        else:
            result = subprocess.run(
                ["bash", str(script)],
                cwd=str(self.project_root),
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )
        if result.returncode != 0:
            return None
        instance_id = self._extract_instance_id(result.stdout or "")
        if not instance_id:
            return None
        return CloudVM(vm_id=vm_id, launched_at=time.time(), process=None, kind="aws", instance_id=instance_id)

    def mark_busy(self, vm_id: str) -> None:
        vm = self.vms.get(vm_id)
        if vm:
            vm.last_busy_at = time.time()

    async def retire_idle(self, busy_worker_ids: set[str]) -> List[str]:
        retired: List[str] = []
        now = time.time()
        for vm_id, vm in list(self.vms.items()):
            if vm_id in busy_worker_ids:
                vm.last_busy_at = now
                continue
            idle_for = now - vm.last_busy_at
            if idle_for >= self.idle_timeout:
                await self._stop_vm(vm)
                self.vm_seconds += now - vm.launched_at
                del self.vms[vm_id]
                self.retirements += 1
                retired.append(vm_id)
                self._events.append({"ts": now, "event": "retire", "vm_id": vm_id})
        return retired

    async def _stop_vm(self, vm: CloudVM) -> None:
        if vm.process and vm.process.poll() is None:
            try:
                vm.process.terminate()
                await asyncio.sleep(0.2)
                if vm.process.poll() is None:
                    vm.process.kill()
            except Exception:
                pass
        if vm.kind == "aws" and vm.instance_id:
            # Operator path: best-effort terminate via CLI if present
            try:
                subprocess.run(
                    [
                        "aws", "ec2", "terminate-instances",
                        "--instance-ids", vm.instance_id,
                        "--region", str(self.burst_cfg.get("aws_region", "us-east-1")),
                    ],
                    check=False,
                    capture_output=True,
                )
            except Exception:
                pass

    def shutdown_all(self) -> None:
        now = time.time()
        for vm in list(self.vms.values()):
            self.vm_seconds += now - vm.launched_at
            if vm.process and vm.process.poll() is None:
                try:
                    vm.process.terminate()
                except Exception:
                    pass
        self.vms.clear()

    def status(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "active_vms": list(self.vms.keys()),
            "launches": self.launches,
            "retirements": self.retirements,
            "vm_seconds": self.vm_seconds,
            "force_burst": self.force_burst,
            "events": self._events[-20:],
        }
