from master.scheduler import Scheduler, WorkerInfo


def test_max_tasks_limits_assignment():
    s = Scheduler()
    s.register_worker(
        WorkerInfo(
            "c1", "campus", cores=8, memory_mb=16000, os_name="win",
            consented=True, cpu_cap_threads=4, max_tasks=1, memory_cap_mb=4096,
        )
    )
    s.create_job("batch", [{"params": {}} for _ in range(3)])
    a1 = s.assign_next()
    assert len(a1) == 1
    assert a1[0][1].params["threads"] == 4
    a2 = s.assign_next()
    assert a2 == []  # capped at max_tasks=1


def test_effective_memory_respects_cap():
    s = Scheduler()
    w = WorkerInfo(
        "c1", "campus", cores=4, memory_mb=16000, os_name="win",
        consented=True, memory_cap_mb=2048,
    )
    assert s.effective_memory_mb(w) == 2048
