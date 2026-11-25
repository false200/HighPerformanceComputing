from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional


class ObjectStore:
    """Local filesystem store with optional S3-compatible backend."""

    def __init__(self, cfg: Dict[str, Any]):
        self.backend = cfg.get("backend", "local")
        self.local_root = Path(cfg.get("local_root", "data"))
        self.local_root.mkdir(parents=True, exist_ok=True)
        (self.local_root / "checkpoints").mkdir(exist_ok=True)
        (self.local_root / "results").mkdir(exist_ok=True)
        self.s3_bucket = cfg.get("s3_bucket")
        self.s3_prefix = cfg.get("s3_prefix", "runs/")
        self.s3_endpoint = cfg.get("s3_endpoint_url")
        self._s3 = None
        if self.backend == "s3":
            self._init_s3()

    def _init_s3(self) -> None:
        try:
            import boto3  # type: ignore
        except ImportError as exc:
            raise RuntimeError("boto3 required for S3 backend") from exc
        kwargs = {}
        if self.s3_endpoint:
            kwargs["endpoint_url"] = self.s3_endpoint
        self._s3 = boto3.client("s3", **kwargs)

    def put_json(self, kind: str, key: str, payload: Dict[str, Any]) -> str:
        rel = f"{kind}/{key}.json"
        local_path = self.local_root / rel
        local_path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(payload, indent=2)
        tmp_path = local_path.with_name(f"{local_path.name}.tmp")
        tmp_path.write_text(text, encoding="utf-8")
        tmp_path.replace(local_path)
        uri = f"file://{local_path.resolve()}"
        if self.backend == "s3" and self._s3 is not None:
            s3_key = f"{self.s3_prefix}{rel}"
            self._s3.put_object(
                Bucket=self.s3_bucket,
                Key=s3_key,
                Body=text.encode("utf-8"),
                ContentType="application/json",
            )
            uri = f"s3://{self.s3_bucket}/{s3_key}"
        return uri

    def get_json(self, kind: str, key: str) -> Optional[Dict[str, Any]]:
        local_path = self.local_root / kind / f"{key}.json"
        if self.backend == "s3" and self._s3 is not None:
            s3_key = f"{self.s3_prefix}{kind}/{key}.json"
            try:
                obj = self._s3.get_object(Bucket=self.s3_bucket, Key=s3_key)
                return json.loads(obj["Body"].read().decode("utf-8"))
            except Exception:
                pass
        if local_path.exists():
            return json.loads(local_path.read_text(encoding="utf-8"))
        return None
