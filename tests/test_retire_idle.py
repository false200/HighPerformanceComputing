import asyncio
import time
from pathlib import Path

from master.burst import BurstController, CloudVM


def test_retire_idle_removes_stale_vm():
    cfg = {
        "scheduling": {
            "max_cloud_vms": 2,
            "min_campus_peers": 1,
            "reclaim_rate_threshold": 0.3,
            "cloud_idle_timeout_sec": 0.2,
        },
        "burst": {"mode": "local_sim"},
    }
    c = BurstController(cfg, Path("."))
    vm = CloudVM(vm_id="cloud-x", launched_at=time.time() - 10, process=None)
    vm.last_busy_at = time.time() - 5
    c.vms["cloud-x"] = vm

    async def run():
        return await c.retire_idle(busy_worker_ids=set())

    retired = asyncio.run(run())
    assert "cloud-x" in retired
    assert "cloud-x" not in c.vms
    assert c.retirements == 1


def test_retire_skips_busy_vm():
    cfg = {
        "scheduling": {"cloud_idle_timeout_sec": 0.01, "max_cloud_vms": 2},
        "burst": {"mode": "local_sim"},
    }
    c = BurstController(cfg, Path("."))
    vm = CloudVM(vm_id="cloud-y", launched_at=time.time() - 10, process=None)
    vm.last_busy_at = time.time() - 5
    c.vms["cloud-y"] = vm

    async def run():
        return await c.retire_idle(busy_worker_ids={"cloud-y"})

    retired = asyncio.run(run())
    assert retired == []
    assert "cloud-y" in c.vms
