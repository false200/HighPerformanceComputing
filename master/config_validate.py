from __future__ import annotations

from typing import Any, Dict, List


def validate_config(cfg: Dict[str, Any]) -> List[str]:
    """Return list of hard errors (empty = OK)."""
    errors: List[str] = []
    master = cfg.get("master") or {}
    if "port" in master:
        try:
            p = int(master["port"])
            if not (1 <= p <= 65535):
                errors.append("master.port out of range")
        except Exception:
            errors.append("master.port must be int")

    sched = cfg.get("scheduling") or {}
    for key in ("heartbeat_timeout_sec", "max_cloud_vms", "min_campus_peers"):
        if key in sched:
            try:
                float(sched[key]) if "sec" in key else int(sched[key])
            except Exception:
                errors.append(f"scheduling.{key} invalid")

    storage = cfg.get("storage") or {}
    backend = storage.get("backend", "local")
    if backend not in ("local", "s3"):
        errors.append("storage.backend must be local|s3")
    if backend == "s3" and not storage.get("s3_bucket"):
        errors.append("storage.s3_bucket required when backend=s3")

    burst = cfg.get("burst") or {}
    mode = burst.get("mode", "local_sim")
    if mode not in ("local_sim", "aws"):
        errors.append("burst.mode must be local_sim|aws")

    auth = cfg.get("auth") or {}
    if auth.get("require_token") and not (
        (auth.get("join_token") or "").strip()
    ):
        # env may still satisfy at runtime — warn via empty check in server
        pass

    return errors
