from __future__ import annotations

import os
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

    queue = cfg.get("queue") or {}
    if queue:
        qb = str(queue.get("backend") or "rabbitmq").lower()
        allow_test = os.environ.get("HPC_ALLOW_TEST_QUEUE", "").strip().lower() in ("1", "true", "yes")
        if qb == "test" and allow_test:
            pass
        elif qb != "rabbitmq":
            errors.append("queue.backend must be rabbitmq (memory intake removed)")
        if "max_running_jobs" in queue:
            try:
                if int(queue["max_running_jobs"]) < 1:
                    errors.append("queue.max_running_jobs must be >= 1")
            except Exception:
                errors.append("queue.max_running_jobs must be int")
        if qb == "rabbitmq" and not (queue.get("rabbitmq_url") or "").strip():
            errors.append("queue.rabbitmq_url required")

    return errors
