from master.packages import PackageStore
from master.server import partition_job
from worker.agent import run_userjob


TRAIN = '''
def train_shard(header, rows, params):
    return {"weights": [1.0, 2.0], "bias": 0.5, "train_acc": 0.9, "loss": 0.1, "checksum": 3.5}
'''


def test_package_store_and_partition():
    store = PackageStore()
    csv = "a,b,passed\n1,2,0\n3,4,1\n5,6,0\n7,8,1\n"
    pkg = store.put(
        {"data.csv": csv, "train.py": TRAIN},
        name="demo",
        meta={"dataset": "data.csv", "entrypoint": "train.py", "label_col": "passed"},
    )
    cfg = {
        "workloads": {},
        "_packages": store,
        "_job_overrides": {
            "package_id": pkg.package_id,
            "dataset": "data.csv",
            "entrypoint": "train.py",
            "label_col": "passed",
            "epochs": 5,
            "lr": 0.1,
        },
    }
    specs = partition_job("userjob", cfg, 2)
    assert len(specs) == 2
    assert "train_source" in specs[0]["params"]
    assert specs[0]["params"]["shard_rows"]


def test_run_userjob_executes_uploaded_train():
    out = run_userjob({
        "train_source": TRAIN,
        "csv_header": "a,b,passed",
        "shard_rows": ["1,2,0", "3,4,1"],
        "shard": 0,
        "epochs": 5,
        "label_col": "passed",
    })
    assert out["weights"] == [1.0, 2.0]
    assert out["train_acc"] == 0.9
