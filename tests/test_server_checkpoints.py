from pathlib import Path

from master.burst import BurstController
from master.metrics import MetricsCollector, RunMetrics
from master.scheduler import Scheduler, WorkerInfo
from master.server import MasterServer
from master.storage import ObjectStore
from protocol.messages import MessageType


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
    server.store = ObjectStore(cfg["storage"])
    server.metrics = MetricsCollector(cfg["logging"]["dir"], cfg["logging"]["metrics_csv"])
    server.burst = BurstController(cfg, Path("."))
    server.active_job_id = None
    server._job_metrics = {}
    server._job_burst_baselines = {}
    server._leave_latencies = []
    return server


def test_checkpoint_rejects_unknown_task_id(tmp_path):
    server = _server(tmp_path)

    resp = server._on_checkpoint({"task_id": "missing", "checkpoint": {"phase": "start"}})

    assert resp["type"] == MessageType.ERROR.value
    assert "unknown task" in resp["error"]


def test_checkpoint_metrics_follow_task_job_not_active_job(tmp_path):
    server = _server(tmp_path)
    job1 = server.scheduler.create_job("batch", [{"params": {"offset": 0, "count": 1}}])
    job2 = server.scheduler.create_job("batch", [{"params": {"offset": 1, "count": 1}}])
    task1 = job1.tasks[0].task_id
    server.active_job_id = job2.job_id
    server._job_metrics[job1.job_id] = RunMetrics(
        job_id=job1.job_id,
        policy=job1.policy,
        kernel=job1.kernel,
        n_tasks=len(job1.tasks),
    )
    server._job_metrics[job2.job_id] = RunMetrics(
        job_id=job2.job_id,
        policy=job2.policy,
        kernel=job2.kernel,
        n_tasks=len(job2.tasks),
    )

    resp = server._on_checkpoint({"task_id": task1, "checkpoint": {"phase": "start"}})

    assert resp["type"] == MessageType.TASK_CHECKPOINT.value
    assert resp["ok"] is True
    assert server.scheduler.task_index[task1].checkpoint == {"phase": "start"}
    assert len(server._job_metrics[job1.job_id].checkpoint_uris) == 1
    assert server._job_metrics[job2.job_id].checkpoint_uris == []


def test_result_recovery_metrics_follow_task_job_not_active_job(tmp_path):
    server = _server(tmp_path)
    worker1 = WorkerInfo("c1", "campus", 2, 2048, "win", consented=True)
    worker2 = WorkerInfo("c2", "campus", 2, 2048, "win", consented=True)
    server.scheduler.register_worker(worker1)
    server.scheduler.register_worker(worker2)

    job1 = server.scheduler.create_job("batch", [{"params": {"offset": 0, "count": 1}}])
    task1 = job1.tasks[0].task_id
    assigns = server.scheduler.assign_next()
    assert assigns and assigns[0][1].task_id == task1
    server.scheduler.reclaim_worker("c1")
    server.scheduler.unregister_worker("c1")
    assert task1 in server.scheduler.pending

    assigns2 = server.scheduler.assign_next()
    assert assigns2 and assigns2[0][0].worker_id == "c2"
    assert assigns2[0][1].task_id == task1

    job2 = server.scheduler.create_job("batch", [{"params": {"offset": 1, "count": 1}}])
    server.active_job_id = job2.job_id
    server._job_metrics[job1.job_id] = RunMetrics(
        job_id=job1.job_id,
        policy=job1.policy,
        kernel=job1.kernel,
        n_tasks=len(job1.tasks),
    )
    server._job_metrics[job2.job_id] = RunMetrics(
        job_id=job2.job_id,
        policy=job2.policy,
        kernel=job2.kernel,
        n_tasks=len(job2.tasks),
    )

    resp = server._on_result(
        {"task_id": task1, "worker_id": "c2", "result": {"checksum": 1.0, "elapsed_ms": 5.0}}
    )

    assert resp["type"] == MessageType.TASK_RESULT.value
    assert resp["ok"] is True
    assert server._job_metrics[job1.job_id].reclaim_recovery_sec >= 0.0
    assert server._job_metrics[job2.job_id].reclaim_recovery_sec == 0.0
