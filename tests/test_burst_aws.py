import asyncio
import subprocess
from pathlib import Path

from master.burst import BurstController, CloudVM


def _ctrl():
    cfg = {
        "master": {"host": "0.0.0.0", "port": 9100},
        "scheduling": {
            "max_cloud_vms": 2,
            "min_campus_peers": 1,
            "reclaim_rate_threshold": 0.3,
            "cloud_idle_timeout_sec": 15,
        },
        "burst": {
            "mode": "aws",
            "aws_master_host": "10.0.0.42",
            "aws_ami": "ami-12345678",
            "aws_instance_type": "t3.micro",
            "aws_region": "us-east-1",
        },
    }
    return BurstController(cfg, Path("."))


def test_aws_launch_uses_configured_master_host_and_instance_id(monkeypatch):
    c = _ctrl()
    calls = {}

    class FakeCompletedProcess:
        def __init__(self, stdout: str = "", returncode: int = 0):
            self.stdout = stdout
            self.stderr = ""
            self.returncode = returncode

    def fake_run(cmd, cwd=None, env=None, check=None, capture_output=None, text=None):
        calls["cmd"] = cmd
        calls["env"] = env
        return FakeCompletedProcess(stdout="i-0abc123def4567890\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    vm = asyncio.run(c._launch_aws("cloud-1-12345", "127.0.0.1", 9100))

    assert vm is not None
    assert vm.kind == "aws"
    assert vm.instance_id == "i-0abc123def4567890"
    assert calls["env"]["HPC_MASTER_HOST"] == "10.0.0.42"


def test_aws_placeholder_launch_does_not_consume_slot(monkeypatch):
    c = _ctrl()

    class FakeCompletedProcess:
        def __init__(self, stdout: str = "", returncode: int = 0):
            self.stdout = stdout
            self.stderr = ""
            self.returncode = returncode

    def fake_run(*args, **kwargs):
        return FakeCompletedProcess(stdout="\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    vm = asyncio.run(c.maybe_burst("policy", "127.0.0.1", 9100))

    assert vm is None
    assert c.launches == 0
    assert c.vms == {}


def test_maybe_burst_serializes_vm_id_assignment(monkeypatch):
    c = _ctrl()
    seen = []
    started = asyncio.Event()
    release = asyncio.Event()

    async def fake_launch(vm_id, host, port):
        seen.append(vm_id)
        if len(seen) == 1:
            started.set()
            await release.wait()
        return CloudVM(vm_id=vm_id, launched_at=0.0, process=None, kind="aws", instance_id=vm_id)

    monkeypatch.setattr(c, "_launch_aws", fake_launch)

    async def run_two_launches():
        first = asyncio.create_task(c.maybe_burst("policy", "127.0.0.1", 9100))
        second = asyncio.create_task(c.maybe_burst("policy", "127.0.0.1", 9100))
        await started.wait()
        assert len(seen) == 1
        release.set()
        return await asyncio.gather(first, second)

    vm1, vm2 = asyncio.run(run_two_launches())

    assert vm1 is not None
    assert vm2 is not None
    assert vm1.vm_id != vm2.vm_id
    assert c.launches == 2
    assert len(c.vms) == 2


def test_stop_vm_terminates_aws_instance_id(monkeypatch):
    c = _ctrl()
    calls = []

    def fake_run(cmd, check=None, capture_output=None):
        calls.append(cmd)

    monkeypatch.setattr(subprocess, "run", fake_run)

    vm = CloudVM(
        vm_id="cloud-1-12345",
        launched_at=0.0,
        process=None,
        kind="aws",
        instance_id="i-0abc123def4567890",
    )

    asyncio.run(c._stop_vm(vm))

    assert calls == [
        [
            "aws",
            "ec2",
            "terminate-instances",
            "--instance-ids",
            "i-0abc123def4567890",
            "--region",
            "us-east-1",
        ]
    ]
