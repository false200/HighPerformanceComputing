"""Ray-inspired core: resources, GCS, ObjectRef lineage, max_retries, placement."""

from master.gcs import GlobalControlStore
from master.object_ref import ObjectRef, TaskLineage
from master.resources import NodeResources, ResourceSpec
from master.scheduler import Scheduler, TaskState, WorkerInfo


def test_resource_admission_blocks_overcommit():
    s = Scheduler()
    s.register_worker(
        WorkerInfo("c1", "campus", 2, 1024, "win", consented=True, cpu_cap_threads=2, max_tasks=4)
    )
    # Each task wants 2 CPUs; node only has 2 → only one concurrent
    specs = [
        {"params": {"i": 0}, "resources": {"num_cpus": 2.0}},
        {"params": {"i": 1}, "resources": {"num_cpus": 2.0}},
    ]
    s.create_job("batch", specs)
    a1 = s.assign_next(peer_first=True)
    assert len(a1) == 1
    a2 = s.assign_next(peer_first=True)
    assert a2 == []  # no capacity left


def test_memory_gate():
    s = Scheduler()
    s.register_worker(
        WorkerInfo("c1", "campus", 8, 512, "win", consented=True, memory_cap_mb=512)
    )
    s.create_job(
        "batch",
        [{"params": {}, "resources": {"num_cpus": 1.0, "memory_mb": 4096}}],
    )
    assert s.assign_next() == []


def test_object_ref_and_gcs_on_complete():
    s = Scheduler()
    s.register_worker(WorkerInfo("c1", "campus", 4, 4096, "win", consented=True))
    job = s.create_job("batch", [{"params": {"offset": 0, "count": 1}}])
    assigns = s.assign_next()
    tid = assigns[0][1].task_id
    job2, recovery, ref = s.complete_task(tid, {"checksum": 1.5}, worker_id="c1", result_uri="file://x")
    assert job2 is not None and job2.job_id == job.job_id
    assert recovery is None
    assert ref is not None
    assert s.gcs.get_object(ref.ref_id) is not None
    assert s.gcs.get_lineage(tid) is not None


def test_checkpoint_ref_survives_reclaim():
    s = Scheduler()
    s.register_worker(WorkerInfo("c1", "campus", 2, 2048, "win", consented=True))
    s.create_job("batch", [{"params": {}}])
    tid = s.assign_next()[0][1].task_id
    cref = s.checkpoint_task(tid, {"step": 1}, uri="file://cp")
    assert cref is not None
    s.reclaim_worker("c1")
    assert tid in s.pending
    task = s.task_index[tid]
    assert task.checkpoint_ref == cref.ref_id
    assert s.lineage_reconstructions >= 1


def test_max_retries_marks_failed():
    s = Scheduler()
    s.register_worker(WorkerInfo("c1", "campus", 2, 2048, "win", consented=True))
    s.create_job("batch", [{"params": {}}], max_retries=1)
    tid = s.assign_next()[0][1].task_id
    # attempts=1; reclaim → still requeue (1 > 1 is false)
    s.reclaim_task("c1", tid)
    assert s.task_index[tid].state == TaskState.PENDING
    # second assign attempts=2; reclaim → 2 > 1 → FAILED
    s.assign_next()
    s.reclaim_task("c1", tid)
    assert s.task_index[tid].state == TaskState.FAILED
    assert s.failed_tasks == 1


def test_placement_pack_prefers_busy_worker():
    s = Scheduler()
    s.register_worker(WorkerInfo("c1", "campus", 4, 4096, "win", consented=True, max_tasks=4))
    s.register_worker(WorkerInfo("c2", "campus", 4, 4096, "win", consented=True, max_tasks=4))
    s.create_job(
        "batch",
        [{"params": {"i": i}} for i in range(3)],
        placement="pack",
    )
    a1 = s.assign_next(placement="pack")
    assert len(a1) >= 1
    first = a1[0][0].worker_id
    # next assignments under pack should prefer same node while capacity remains
    a2 = s.assign_next(placement="pack")
    assert a2
    assert a2[0][0].worker_id == first


def test_gcs_reconstructable():
    gcs = GlobalControlStore()
    lin = TaskLineage(
        task_id="t1",
        job_id="j1",
        kernel="batch",
        params={},
        resources=ResourceSpec().to_dict(),
    )
    gcs.put_lineage(lin)
    ref = ObjectRef.new(kind="result", task_id="t1", uri="file://r")
    gcs.put_object(ref)
    assert gcs.reconstructable(ref.ref_id)
    gcs.mark_object_lost(ref.ref_id)
    assert gcs.get_object(ref.ref_id).lost is True


def test_node_resources_reserve_release():
    nr = NodeResources(total_cpus=4.0, total_memory_mb=1024.0)
    req = ResourceSpec(num_cpus=2.0, memory_mb=256.0)
    assert nr.can_fit(req)
    nr.reserve(req)
    assert nr.available_cpus() == 2.0
    assert not nr.can_fit(ResourceSpec(num_cpus=3.0))
    nr.release(req)
    assert nr.available_cpus() == 4.0
