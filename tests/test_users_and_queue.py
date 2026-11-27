from master.job_queue import JobIntakeQueue
from master.scheduler import Scheduler, WorkerInfo
from master.server import MasterServer
from master.users import UserRegistry


def test_user_hello_bye_and_stale():
    reg = UserRegistry(heartbeat_timeout_sec=0.05)
    u = reg.hello(name="alice")
    assert u.user_id in reg.users
    assert len(reg.snapshot()) == 1
    reg.heartbeat(u.user_id)
    assert reg.bye(u.user_id) is not None
    assert u.user_id not in reg.users
    a = reg.hello(name="bob")
    a.last_seen = 0.0
    dead = reg.sweep_stale()
    assert a.user_id in dead
    assert a.user_id not in reg.users


def test_intake_queue_fifo_and_cancel():
    q = JobIntakeQueue({"backend": "test", "max_running_jobs": 2})
    a = q.enqueue({"kernel": "batch"}, user_id="u1")
    b = q.enqueue({"kernel": "heat2d"}, user_id="u2")
    assert q.depth() == 2
    assert q.dequeue().queue_id == a.queue_id
    dropped = q.cancel_for_user("u2")
    assert dropped == 1
    assert q.depth() == 0
    assert q.dequeue() is None


def test_fair_pending_round_robin():
    s = Scheduler()
    s.register_worker(WorkerInfo("w1", "campus", 8, 8192, "win", consented=True))
    s.register_worker(WorkerInfo("w2", "campus", 8, 8192, "win", consented=True))
    j1 = s.create_job("batch", [{"params": {"offset": i, "count": 1}} for i in range(3)])
    j2 = s.create_job("batch", [{"params": {"offset": 10 + i, "count": 1}} for i in range(3)])
    order = s._fair_pending_order()
    jobs = [s.task_index[tid].job_id for tid in order]
    # interleaved: j1, j2, j1, j2, ...
    assert jobs[0] == j1.job_id
    assert jobs[1] == j2.job_id
    assert jobs[2] == j1.job_id


def test_topology_includes_users(tmp_path):
    cfg = {
        "master": {"host": "0.0.0.0", "port": 9100, "health_port": 9101},
        "auth": {"require_token": False},
        "scheduling": {},
        "queue": {"backend": "test", "max_running_jobs": 2},
        "storage": {"backend": "local", "local_root": str(tmp_path)},
        "logging": {"dir": str(tmp_path), "metrics_csv": str(tmp_path / "m.csv")},
        "burst": {"mode": "local_sim", "max_cloud_vms": 1},
    }
    m = MasterServer(cfg, tmp_path)
    sess = m.users.hello(name="carol")
    m.scheduler.register_worker(
        WorkerInfo("c1", "campus", 4, 4096, "win", consented=True, cpu_cap_threads=2)
    )
    topo = m._topology_snapshot()
    assert topo["gateway"]["user_count"] == 1
    assert topo["users"][0]["user_id"] == sess.user_id
    assert any(l["role"] == "user" for l in topo["links"])
    assert topo["intake"]["backend"] == "test"


def test_submit_queues_when_at_capacity(tmp_path):
    cfg = {
        "master": {"host": "0.0.0.0", "port": 9100, "health_port": 9101},
        "auth": {"require_token": False},
        "scheduling": {"default_deadline_sec": 60},
        "queue": {"backend": "test", "max_running_jobs": 1},
        "workloads": {"batch": {"arrays": 2, "length": 10}},
        "storage": {"backend": "local", "local_root": str(tmp_path)},
        "logging": {"dir": str(tmp_path), "metrics_csv": str(tmp_path / "m.csv")},
        "burst": {"mode": "local_sim", "max_cloud_vms": 1},
    }
    m = MasterServer(cfg, tmp_path)
    u1 = m.users.hello(name="u1")
    u2 = m.users.hello(name="u2")
    r1 = m._on_job_submit({"kernel": "batch", "chunks": 2, "user_id": u1.user_id, "policy": "campus_only"})
    assert r1.get("ok") and not r1.get("queued")
    r2 = m._on_job_submit({"kernel": "batch", "chunks": 2, "user_id": u2.user_id, "policy": "campus_only"})
    assert r2.get("ok") and r2.get("queued")
    assert m.job_queue.depth() == 1
    # finish first job → drain
    job = m.scheduler.jobs[r1["job_id"]]
    job.finished_at = 1.0
    m._drain_intake()
    assert m.job_queue.depth() == 0
    assert m.users.users[u2.user_id].job_id is not None
