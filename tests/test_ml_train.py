"""Built-in logreg/linreg kernels are gone — only user packages remain."""

import pytest

from master.scheduler import Job, Task, TaskState, merge_user_shard_results
from master.server import partition_job
from worker.user_runtime import run_user_shard


def test_builtin_logreg_rejected():
    with pytest.raises(ValueError, match="removed"):
        partition_job("logreg", {"workloads": {}}, 2)


def test_merge_user_shard_results():
    job = Job(job_id="j", kernel="userjob", policy="campus_only", deadline_ts=0)
    for i in range(2):
        t = Task(task_id=f"t{i}", job_id="j", kernel="userjob", params={})
        t.state = TaskState.DONE
        t.result = {"weights": [1.0, 3.0], "bias": 2.0, "mse": 0.5}
        job.tasks.append(t)
    model = merge_user_shard_results(job)
    assert model is not None
    assert model["weights"] == [1.0, 3.0]
    assert model["bias"] == 2.0
    assert model["shards"] == 2


def test_user_runtime_subprocess():
    src = (
        "def train_shard(header, rows, params):\n"
        "    return {'kernel': 'userjob', 'checksum': float(len(rows)), 'weights': [1.0], 'bias': 0.0}\n"
    )
    out = run_user_shard(src, ["a", "b"], ["1,2", "3,4"], {"shard": 0})
    assert out["checksum"] == 2.0
    assert out["weights"] == [1.0]
