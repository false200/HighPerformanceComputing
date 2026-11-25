import time

from master.scheduler import Scheduler, TaskState, WorkerInfo


def test_reclaim_sets_timestamp_and_recovery_on_complete():
    s = Scheduler()
    s.register_worker(WorkerInfo("c1", "campus", 2, 2048, "win", consented=True))
    s.register_worker(WorkerInfo("c2", "campus", 2, 2048, "win", consented=True))
    job = s.create_job("batch", [{"params": {"offset": 0, "count": 1}}])
    assigns = s.assign_next()
    tid = assigns[0][1].task_id
    s.reclaim_worker("c1")
    s.unregister_worker("c1")  # owner left; only c2 remains
    task = s.task_index[tid]
    assert task.reclaimed_at is not None
    assert tid in s.pending

    time.sleep(0.05)
    assigns2 = s.assign_next()
    assert assigns2 and assigns2[0][0].worker_id == "c2"
    job2, recovery, _ref = s.complete_task(tid, {"checksum": 1.0, "elapsed_ms": 10})
    assert recovery is not None and recovery >= 0.05
    assert task.reclaimed_at is None
    assert job2 is not None


def test_heartbeat_timeout_style_reclaim():
    s = Scheduler()
    s.register_worker(WorkerInfo("c1", "campus", 2, 2048, "win", consented=True))
    s.create_job("batch", [{"params": {}}])
    assigns = s.assign_next()
    tid = assigns[0][1].task_id
    s.workers["c1"].last_heartbeat = time.time() - 100
    stale = [
        wid for wid, w in list(s.workers.items())
        if time.time() - w.last_heartbeat > 6.0
    ]
    assert "c1" in stale
    s.unregister_worker("c1")
    assert tid in s.pending


def test_stale_result_after_reclaim_is_rejected():
    s = Scheduler()
    s.register_worker(WorkerInfo("c1", "campus", 2, 2048, "win", consented=True))
    s.register_worker(WorkerInfo("c2", "campus", 2, 2048, "win", consented=True))
    job = s.create_job("batch", [{"params": {"offset": 0, "count": 1}}])

    assigns = s.assign_next()
    assert assigns and assigns[0][0].worker_id == "c1"
    tid = assigns[0][1].task_id

    s.reclaim_worker("c1")
    s.unregister_worker("c1")
    assigns2 = s.assign_next()
    assert assigns2 and assigns2[0][0].worker_id == "c2"
    assert s.task_index[tid].state == TaskState.ASSIGNED
    assert s.task_index[tid].worker_id == "c2"

    stale_job, stale_recovery, stale_ref = s.complete_task(
        tid,
        {"checksum": 1.0, "elapsed_ms": 10},
        worker_id="c1",
    )
    assert stale_job is None
    assert stale_recovery is None
    assert stale_ref is None
    assert s.task_index[tid].state == TaskState.ASSIGNED
    assert s.task_index[tid].worker_id == "c2"
    assert s.assigned[tid] == "c2"
    assert not job.finished_at

    final_job, final_recovery, final_ref = s.complete_task(
        tid,
        {"checksum": 2.0, "elapsed_ms": 10},
        worker_id="c2",
    )
    assert final_ref is not None
    assert final_recovery is not None and final_recovery >= 0.0
    assert final_job is not None
    assert s.task_index[tid].state == TaskState.DONE
    assert s.task_index[tid].worker_id == "c2"
