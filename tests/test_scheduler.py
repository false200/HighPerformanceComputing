import time

from master.scheduler import Scheduler, WorkerInfo


def test_peer_first_assignment():
    s = Scheduler()
    s.register_worker(WorkerInfo("c1", "campus", 4, 4096, "win", consented=True))
    s.register_worker(WorkerInfo("k1", "cloud", 2, 2048, "linux", consented=True))
    job = s.create_job("batch", [{"params": {"offset": 0, "count": 2}, "weight": 2}])
    assigns = s.assign_next(peer_first=True)
    assert len(assigns) == 1
    assert assigns[0][0].worker_id == "c1"
    assert job.job_id


def test_campus_only_blocks_cloud_fallback():
    s = Scheduler()
    s.register_worker(WorkerInfo("k1", "cloud", 2, 2048, "linux", consented=True))
    s.create_job("batch", [{"params": {"offset": 0, "count": 1}}])
    assigns = s.assign_next(peer_first=True, campus_only=True)
    assert assigns == []


def test_campus_only_prefers_campus_when_available():
    s = Scheduler()
    s.register_worker(WorkerInfo("c1", "campus", 4, 4096, "win", consented=True))
    s.register_worker(WorkerInfo("k1", "cloud", 2, 2048, "linux", consented=True))
    s.create_job("batch", [{"params": {"offset": 0, "count": 1}}])
    assigns = s.assign_next(peer_first=True, campus_only=True)
    assert len(assigns) == 1
    assert assigns[0][0].worker_id == "c1"


def test_reclaim_requeues():
    s = Scheduler()
    s.register_worker(WorkerInfo("c1", "campus", 2, 2048, "win", consented=True))
    s.create_job("batch", [{"params": {"offset": 0, "count": 1}}])
    assigns = s.assign_next()
    assert assigns
    tid = assigns[0][1].task_id
    reclaimed = s.reclaim_worker("c1")
    assert len(reclaimed) == 1
    assert tid in s.pending
    assert s.reclaim_events == 1


def test_capability_thread_hint():
    s = Scheduler()
    s.register_worker(WorkerInfo("c1", "campus", 8, 4096, "win", consented=True, cpu_cap_threads=2))
    s.create_job("heat2d", [{"params": {"grid": 16, "rows": 16, "start_row": 0}}])
    assigns = s.assign_next()
    assert assigns[0][1].params["threads"] == 2


def test_deadline_projection():
    s = Scheduler()
    s.register_worker(WorkerInfo("c1", "campus", 2, 2048, "win", consented=True))
    job = s.create_job("batch", [{"params": {}} for _ in range(4)], deadline_sec=30)
    # no completions yet -> finite projection
    assert s.projected_finish(job.job_id) > time.time()
