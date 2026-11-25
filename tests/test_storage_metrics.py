from master.metrics import MetricsCollector, RunMetrics
from master.storage import ObjectStore


def test_local_object_store(tmp_path):
    store = ObjectStore({"backend": "local", "local_root": str(tmp_path)})
    uri = store.put_json("checkpoints", "t1", {"progress": 0.5})
    assert uri.startswith("file://")
    data = store.get_json("checkpoints", "t1")
    assert data["progress"] == 0.5


def test_metrics_csv(tmp_path):
    csv_path = tmp_path / "m.csv"
    col = MetricsCollector(str(tmp_path), str(csv_path))
    m = RunMetrics(
        job_id="abc",
        policy="hybrid",
        kernel="heat2d",
        n_tasks=4,
        wall_time_sec=2.0,
        serial_proxy_sec=8.0,
        campus_workers=2,
        cloud_vm_seconds=10.0,
    )
    path = col.record(m)
    assert path.exists()
    assert m.speedup == 4.0
    text = csv_path.read_text(encoding="utf-8")
    assert "hybrid" in text
    assert "abc" in text
