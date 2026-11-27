from kernels.ml_train import run
from master.scheduler import Job, Task, TaskState, average_ml_model
from master.server import partition_job


def test_logreg_shard_trains():
    out = run({
        "kernel": "logreg",
        "seed": 7,
        "n_samples": 120,
        "n_features": 4,
        "epochs": 10,
        "lr": 0.1,
    })
    assert out["kernel"] == "logreg"
    assert len(out["weights"]) == 4
    assert 0.0 <= out["train_acc"] <= 1.0
    assert "checksum" in out


def test_partition_logreg():
    specs = partition_job("logreg", {"workloads": {"logreg": {"n_samples": 50, "n_features": 3, "epochs": 5, "lr": 0.05}}}, 4)
    assert len(specs) == 4
    assert specs[0]["params"]["shard"] == 0
    assert specs[3]["params"]["n_features"] == 3


def test_partition_logreg_dataset(tmp_path):
    csv_path = tmp_path / "tiny.csv"
    csv_path.write_text(
        "a,b,label\n1,2,0\n3,4,1\n5,6,0\n7,8,1\n",
        encoding="utf-8",
    )
    # path relative won't resolve under ROOT; pass absolute via overrides + monkey by using n_rows
    cfg = {
        "workloads": {"logreg": {}},
        "_job_overrides": {
            "dataset": str(csv_path),
            "label_col": "label",
            "n_rows": 4,
            "epochs": 5,
            "lr": 0.1,
        },
    }
    specs = partition_job("logreg", cfg, 2)
    assert len(specs) == 2
    assert specs[0]["params"]["offset"] == 0
    assert specs[0]["params"]["count"] == 2
    assert specs[1]["params"]["offset"] == 2


def test_average_ml_model():
    job = Job(job_id="j", kernel="logreg", policy="campus_only", deadline_ts=0)
    for i, (w, b, acc) in enumerate([([1.0, 2.0], 0.5, 0.8), ([3.0, 4.0], 1.5, 0.9)]):
        t = Task(task_id=f"t{i}", job_id="j", kernel="logreg", params={})
        t.state = TaskState.DONE
        t.result = {"weights": w, "bias": b, "train_acc": acc, "loss": 0.2, "checksum": 1.0}
        job.tasks.append(t)
    model = average_ml_model(job)
    assert model is not None
    assert model["weights"] == [2.0, 3.0]
    assert abs(model["bias"] - 1.0) < 1e-9
    assert abs(model["mean_train_acc"] - 0.85) < 1e-9
