from master.scheduler import Scheduler, WorkerInfo
from master.server import MasterServer


def test_topology_snapshot_shape(tmp_path):
    cfg = {
        "master": {"host": "0.0.0.0", "port": 9100, "health_port": 9101, "advertise_host": "1.2.3.4"},
        "auth": {"require_token": False},
        "scheduling": {},
        "storage": {"backend": "local", "local_root": str(tmp_path)},
        "logging": {"dir": str(tmp_path), "metrics_csv": str(tmp_path / "m.csv")},
        "burst": {"mode": "local_sim", "max_cloud_vms": 1},
        "queue": {"backend": "test", "max_running_jobs": 4},
    }
    m = MasterServer(cfg, tmp_path)
    m.scheduler.register_worker(
        WorkerInfo("c1", "campus", 4, 4096, "win", consented=True, cpu_cap_threads=2)
    )
    m.scheduler.create_job("batch", [{"params": {"offset": 0, "count": 1}}])
    m.scheduler.assign_next()
    topo = m._topology_snapshot()
    assert topo["gateway"]["worker_count"] == 1
    assert topo["gateway"]["campus_count"] == 1
    assert topo["gateway"]["user_count"] == 0
    assert len(topo["workers"]) == 1
    assert topo["users"] == []
    assert topo["links"][0]["from"] == "c1"
    assert topo["jobs"]
    assert topo["gateway"]["assigned_tasks"] >= 1
    assert "intake" in topo
