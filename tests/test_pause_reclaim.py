import asyncio
import threading
from types import SimpleNamespace

from master.scheduler import Scheduler, WorkerInfo
from protocol.messages import MessageType, make
from worker.agent import WorkerAgent


def test_pause_reclaims_assigned_task():
    s = Scheduler()
    s.register_worker(WorkerInfo("c1", "campus", 2, 2048, "win", consented=True))
    s.register_worker(WorkerInfo("c2", "campus", 2, 2048, "win", consented=True))

    job = s.create_job("batch", [{"params": {"offset": 0, "count": 1}}])
    assigns = s.assign_next()
    assert assigns
    tid = assigns[0][1].task_id

    s.set_paused("c1", True)

    task = s.task_index[tid]
    assert task.worker_id is None
    assert tid in s.pending
    assert s.workers["c1"].paused is True

    reassigned = s.assign_next()
    assert reassigned
    assert reassigned[0][1].task_id == tid
    assert reassigned[0][0].worker_id == "c2"
    assert job.job_id


def test_worker_pause_drop_requests_single_task_reclaim():
    args = SimpleNamespace(
        kind="campus",
        worker_id="w1",
        cpu_cap=0,
        idle_only=False,
        no_controls=True,
        controls=False,
        auto_consent=False,
        master="127.0.0.1:9100",
        below_normal_priority=False,
        demo_leave_after=0.0,
        instance_type=None,
        region=None,
        name="worker",
        heartbeat=2.0,
    )
    agent = WorkerAgent(args)
    agent.paused = True

    sent = []

    async def fake_request(msg, timeout=30.0):
        sent.append(msg)
        return make(MessageType.TASK_RECLAIM, ok=True)

    executed = False

    async def fake_execute(msg):
        nonlocal executed
        executed = True

    agent._request = fake_request  # type: ignore[assignment]
    agent._execute_task = fake_execute  # type: ignore[assignment]

    async def run_loop():
        await agent._inbox.put(make(
            MessageType.TASK_ASSIGN,
            task_id="t1",
            job_id="j1",
            kernel="batch",
            params={},
        ))
        await agent._inbox.put(None)
        await agent._work_loop()

    asyncio.run(run_loop())

    assert not executed
    assert len(sent) == 1
    assert sent[0]["type"] == MessageType.TASK_RECLAIM.value
    assert sent[0]["task_id"] == "t1"
    assert sent[0]["worker_id"] == "w1"


def test_worker_leave_terminates_inflight_kernel(monkeypatch):
    args = SimpleNamespace(
        kind="campus",
        worker_id="w1",
        cpu_cap=0,
        idle_only=False,
        no_controls=True,
        controls=False,
        auto_consent=False,
        master="127.0.0.1:9100",
        below_normal_priority=False,
        demo_leave_after=0.0,
        instance_type=None,
        region=None,
        name="worker",
        heartbeat=2.0,
    )
    agent = WorkerAgent(args)

    sent = []

    async def fake_request(msg, timeout=30.0):
        sent.append(msg)
        if msg["type"] == MessageType.TASK_CHECKPOINT.value:
            return make(MessageType.TASK_CHECKPOINT, ok=True)
        if msg["type"] == MessageType.LEAVE.value:
            return make(MessageType.LEAVE, ok=True, requeued=1)
        raise AssertionError(f"unexpected request: {msg['type']}")

    agent._request = fake_request  # type: ignore[assignment]

    started = threading.Event()
    released = threading.Event()

    class FakeProc:
        def __init__(self, *args, **kwargs):
            self.returncode = None
            self.terminated = False
            self.killed = False
            started.set()

        def poll(self):
            return self.returncode

        def communicate(self):
            assert released.wait(timeout=1), "leave did not stop the kernel"
            return (
                '{"kernel":"batch","checksum":1.0,"elapsed_ms":5.0}\n',
                "",
            )

        def terminate(self):
            self.terminated = True
            self.returncode = -15
            released.set()

        def kill(self):
            self.killed = True
            self.returncode = -9
            released.set()

        def wait(self, timeout=None):
            if not released.wait(timeout=timeout):
                raise TimeoutError("kernel still running")
            return self.returncode

    monkeypatch.setattr("worker.agent.find_kernel_binary", lambda: "fake-kernel")
    monkeypatch.setattr("worker.agent.subprocess.Popen", lambda *args, **kwargs: FakeProc())

    async def run_case():
        task = asyncio.create_task(
            agent._execute_task(
                {
                    "task_id": "t1",
                    "job_id": "j1",
                    "kernel": "batch",
                    "params": {},
                }
            )
        )
        await asyncio.wait_for(asyncio.to_thread(started.wait), timeout=1)
        await agent._leave()
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(run_case())

    assert any(msg["type"] == MessageType.LEAVE.value for msg in sent)
    assert not any(msg["type"] == MessageType.TASK_RESULT.value for msg in sent)
    assert agent._kernel_proc is None


def test_worker_idle_only_uses_short_polling(monkeypatch):
    args = SimpleNamespace(
        kind="campus",
        worker_id="w1",
        cpu_cap=0,
        idle_only=True,
        no_controls=True,
        controls=False,
        auto_consent=False,
        master="127.0.0.1:9100",
        below_normal_priority=False,
        demo_leave_after=0.0,
        instance_type=None,
        region=None,
        name="worker",
        heartbeat=2.0,
    )
    agent = WorkerAgent(args)

    sent = []
    wait_timeouts = []

    async def fake_request(msg, timeout=30.0):
        sent.append(msg)
        return make(MessageType.TASK_RECLAIM, ok=True)

    real_wait_for = asyncio.wait_for

    async def fake_wait_for(awaitable, timeout=None):
        wait_timeouts.append(timeout)
        agent.leaving = True
        agent._idle_wait_event.set()
        return await real_wait_for(awaitable, timeout=timeout)

    monkeypatch.setattr("worker.agent.system_is_idle", lambda: False)
    monkeypatch.setattr("worker.agent.asyncio.wait_for", fake_wait_for)
    agent._request = fake_request  # type: ignore[assignment]

    async def run_loop():
        await agent._inbox.put(
            make(
                MessageType.TASK_ASSIGN,
                task_id="t1",
                job_id="j1",
                kernel="batch",
                params={},
            )
        )
        await agent._inbox.put(None)
        await agent._work_loop()

    asyncio.run(run_loop())

    assert wait_timeouts
    assert wait_timeouts[0] is not None and wait_timeouts[0] <= 0.5
    assert any(msg["type"] == MessageType.TASK_RECLAIM.value for msg in sent)


def test_worker_sends_result_when_leave_arrives_after_kernel_completion(monkeypatch):
    args = SimpleNamespace(
        kind="campus",
        worker_id="w1",
        cpu_cap=0,
        idle_only=False,
        no_controls=True,
        controls=False,
        auto_consent=False,
        master="127.0.0.1:9100",
        below_normal_priority=False,
        demo_leave_after=0.0,
        instance_type=None,
        region=None,
        name="worker",
        heartbeat=2.0,
    )
    agent = WorkerAgent(args)

    sent = []

    async def fake_request(msg, timeout=30.0):
        sent.append(msg)
        if msg["type"] == MessageType.TASK_CHECKPOINT.value:
            return make(MessageType.TASK_CHECKPOINT, ok=True)
        if msg["type"] == MessageType.TASK_RESULT.value:
            return make(MessageType.TASK_RESULT, ok=True)
        raise AssertionError(f"unexpected request: {msg['type']}")

    async def fake_to_thread(fn, *args):
        result = fn(*args)
        agent.leaving = True
        return result

    monkeypatch.setattr("worker.agent.asyncio.to_thread", fake_to_thread)
    monkeypatch.setattr(
        "worker.agent.run_kernel",
        lambda *args, **kwargs: {"kernel": "batch", "checksum": 1.0, "elapsed_ms": 1.0},
    )
    agent._request = fake_request  # type: ignore[assignment]

    asyncio.run(
        agent._execute_task(
            {
                "task_id": "t1",
                "job_id": "j1",
                "kernel": "batch",
                "params": {},
            }
        )
    )

    assert any(msg["type"] == MessageType.TASK_RESULT.value for msg in sent)


def test_worker_clamps_task_threads_to_cpu_cap(monkeypatch):
    args = SimpleNamespace(
        kind="campus",
        worker_id="w1",
        cpu_cap=2,
        idle_only=False,
        no_controls=True,
        controls=False,
        auto_consent=False,
        master="127.0.0.1:9100",
        below_normal_priority=False,
        demo_leave_after=0.0,
        instance_type=None,
        region=None,
        name="worker",
        heartbeat=2.0,
    )
    agent = WorkerAgent(args)

    sent = []
    captured = {}

    async def fake_request(msg, timeout=30.0):
        sent.append(msg)
        if msg["type"] in {MessageType.TASK_CHECKPOINT.value, MessageType.TASK_RESULT.value}:
            return make(MessageType(msg["type"]), ok=True)
        return make(MessageType(msg["type"]), ok=True)

    def fake_run_kernel(kernel, params, proc_setter=None, proc_clearer=None):
        captured["threads"] = params["threads"]
        return {"kernel": kernel, "checksum": 1.0, "elapsed_ms": 1.0}

    agent._request = fake_request  # type: ignore[assignment]
    monkeypatch.setattr("worker.agent.run_kernel", fake_run_kernel)

    asyncio.run(
        agent._execute_task(
            {
                "task_id": "t1",
                "job_id": "j1",
                "kernel": "batch",
                "params": {"threads": 8},
            }
        )
    )

    assert captured["threads"] == 2
    assert any(msg["type"] == MessageType.TASK_RESULT.value for msg in sent)
