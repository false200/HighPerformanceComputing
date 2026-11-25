from pathlib import Path
import json

from master.metrics import MetricsCollector, RunMetrics
from master.storage import ObjectStore


def test_local_object_store(tmp_path):
    store = ObjectStore({"backend": "local", "local_root": str(tmp_path)})
    uri = store.put_json("checkpoints", "t1", {"progress": 0.5})
    assert uri.startswith("file://")
    data = store.get_json("checkpoints", "t1")
    assert data["progress"] == 0.5


def test_local_object_store_writes_atomically(tmp_path, monkeypatch):
    store = ObjectStore({"backend": "local", "local_root": str(tmp_path)})
    final_path = tmp_path / "checkpoints" / "t1.json"
    original_write_text = Path.write_text

    def guarded_write_text(self, *args, **kwargs):
        if self == final_path:
            raise AssertionError("final JSON path should not be written directly")
        return original_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", guarded_write_text)

    uri = store.put_json("checkpoints", "t1", {"progress": 0.5})
    assert uri == f"file://{final_path.resolve()}"
    assert final_path.read_text(encoding="utf-8").strip().startswith("{")
    assert store.get_json("checkpoints", "t1") == {"progress": 0.5}


def test_s3_reads_remote_before_local(tmp_path):
    store = ObjectStore({"backend": "local", "local_root": str(tmp_path)})
    store.backend = "s3"
    store.s3_bucket = "bucket"
    store.s3_prefix = "runs/"

    class FakeBody:
        def __init__(self, payload: bytes):
            self._payload = payload

        def read(self) -> bytes:
            return self._payload

    class FakeS3:
        def __init__(self, payload: bytes):
            self._payload = payload

        def get_object(self, Bucket, Key):  # noqa: N803 - boto3-style args
            return {"Body": FakeBody(self._payload)}

    remote_payload = {"progress": 0.9}
    store._s3 = FakeS3(json.dumps(remote_payload).encode("utf-8"))

    local_path = tmp_path / "checkpoints" / "t1.json"
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_text('{"progress": 0.1}', encoding="utf-8")

    data = store.get_json("checkpoints", "t1")
    assert data == remote_payload


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
