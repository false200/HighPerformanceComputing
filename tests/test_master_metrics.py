from pathlib import Path

from master.burst import BurstController, CloudVM
from master.job_queue import JobIntakeQueue
from master.metrics import MetricsCollector, RunMetrics
from master.scheduler import Scheduler
from master.server import MasterServer
from master.storage import ObjectStore
from master.users import UserRegistry


def _server(tmp_path):
    cfg = {
        "scheduling": {"max_cloud_vms": 2, "cloud_idle_timeout_sec": 15},
        "burst": {"mode": "local_sim"},
        "logging": {
            "dir": str(tmp_path / "logs"),
            "metrics_csv": str(tmp_path / "metrics.csv"),
        },
        "storage": {"backend": "local", "local_root": str(tmp_path / "store")},
    }
    server = MasterServer.__new__(MasterServer)
    server.cfg = cfg
    server.project_root = Path(".")
    server.scheduler = Scheduler()
    server.users = UserRegistry()
    server.job_queue = JobIntakeQueue({"backend": "test", "max_running_jobs": 4})
    server.store = ObjectStore(cfg["storage"])
    server.metrics = MetricsCollector(cfg["logging"]["dir"], cfg["logging"]["metrics_csv"])
    server.burst = BurstController(cfg, Path("."))
    server._job_metrics = {}
    server._job_burst_baselines = {}
    server._leave_latencies = []
    return server


def test_finalize_job_preserves_submission_serial_proxy_and_live_vm_seconds(tmp_path):
    server = _server(tmp_path)
    job = server.scheduler.create_job("batch", [{"params": {"offset": 0, "count": 1}}])
    job.created_at = 100.0
    job.finished_at = 101.0
    server.burst.vm_seconds = 5.0
    server.burst.vms["cloud-1"] = CloudVM(vm_id="cloud-1", launched_at=96.0, process=None)
    server._job_metrics[job.job_id] = RunMetrics(
        job_id=job.job_id,
        policy=job.policy,
        kernel=job.kernel,
        n_tasks=len(job.tasks),
        serial_proxy_sec=8.0,
    )
    job.tasks[0].result = {"checksum": 1.0, "elapsed_ms": 2500}

    server._finalize_job(job)

    metrics = server._job_metrics[job.job_id]
    assert metrics.serial_proxy_sec == 8.0
    assert metrics.cloud_vm_seconds == 10.0


def test_finalize_job_uses_job_scoped_burst_deltas(tmp_path):
    server = _server(tmp_path)
    job = server.scheduler.create_job("batch", [{"params": {"offset": 0, "count": 1}}])
    job.created_at = 100.0
    job.finished_at = 110.0
    server.burst.launches = 5
    server.burst.vm_seconds = 45.0
    server.burst.vms["cloud-1"] = CloudVM(vm_id="cloud-1", launched_at=100.0, process=None)
    server._job_metrics[job.job_id] = RunMetrics(
        job_id=job.job_id,
        policy=job.policy,
        kernel=job.kernel,
        n_tasks=len(job.tasks),
        serial_proxy_sec=1.0,
    )
    server._job_burst_baselines[job.job_id] = (3, 40.0)

    server._finalize_job(job)

    metrics = server._job_metrics[job.job_id]
    assert metrics.cloud_workers == 2
    assert metrics.cloud_vm_seconds == 15.0
