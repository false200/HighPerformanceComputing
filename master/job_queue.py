"""Job intake queue — RabbitMQ is required (not optional).

All submitted jobs that cannot run immediately are persisted on the broker
until the coordinator drains capacity. Tests may pass backend=\"test\" for an
in-process stand-in; production configs must use rabbitmq.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional, Set


@dataclass
class QueuedJob:
    queue_id: str
    payload: Dict[str, Any]
    enqueued_at: float = field(default_factory=time.time)
    user_id: Optional[str] = None


class JobIntakeQueue:
    """RabbitMQ-backed intake. ``backend=test`` is pytest-only."""

    def __init__(self, cfg: Optional[Dict[str, Any]] = None):
        cfg = cfg or {}
        backend = str(cfg.get("backend") or "rabbitmq").lower().strip()
        self.max_running_jobs = int(cfg.get("max_running_jobs") or 4)
        self._queue_name = str(cfg.get("rabbitmq_queue") or "lattice.jobs")
        self._cancelled_users: Set[str] = set()
        self._waiting_meta: Deque[Dict[str, Any]] = deque()  # for dashboard snapshot
        self._rabbit = None
        self._channel = None
        self._q: Deque[QueuedJob] = deque()

        if backend == "test":
            if os.environ.get("HPC_ALLOW_TEST_QUEUE", "").strip() not in ("1", "true", "yes"):
                raise RuntimeError(
                    "queue.backend=test is only allowed when HPC_ALLOW_TEST_QUEUE=1"
                )
            self.backend = "test"
            return

        if backend != "rabbitmq":
            raise RuntimeError(
                f"queue.backend must be 'rabbitmq' (got {backend!r}). "
                "In-memory intake was removed — start RabbitMQ and set queue.rabbitmq_url."
            )
        self.backend = "rabbitmq"
        self._init_rabbit(str(cfg.get("rabbitmq_url") or "amqp://guest:guest@localhost:5672/"))

    def _init_rabbit(self, url: str) -> None:
        try:
            import pika  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "RabbitMQ intake requires pika — pip install pika"
            ) from exc
        try:
            params = pika.URLParameters(url)
            self._rabbit = pika.BlockingConnection(params)
            ch = self._rabbit.channel()
            ch.queue_declare(queue=self._queue_name, durable=True)
            self._channel = ch
        except Exception as exc:
            raise RuntimeError(
                f"cannot connect to RabbitMQ at {url}: {exc}. "
                "Install/start the broker before launching the master."
            ) from exc

    def enqueue(self, payload: Dict[str, Any], user_id: Optional[str] = None) -> QueuedJob:
        if user_id:
            self._cancelled_users.discard(user_id)
        item = QueuedJob(
            queue_id=f"q-{uuid.uuid4().hex[:10]}",
            payload=dict(payload),
            user_id=user_id,
        )
        meta = {
            "queue_id": item.queue_id,
            "user_id": user_id,
            "kernel": (item.payload or {}).get("kernel"),
            "enqueued_at": item.enqueued_at,
        }
        body = json.dumps({
            "queue_id": item.queue_id,
            "user_id": user_id,
            "payload": item.payload,
            "enqueued_at": item.enqueued_at,
        }).encode("utf-8")

        if self.backend == "test":
            self._q.append(item)
            self._waiting_meta.append(meta)
            return item

        import pika  # type: ignore

        assert self._channel is not None
        self._channel.basic_publish(
            exchange="",
            routing_key=self._queue_name,
            body=body,
            properties=pika.BasicProperties(delivery_mode=2),
        )
        self._waiting_meta.append(meta)
        return item

    def dequeue(self) -> Optional[QueuedJob]:
        while True:
            item = self._dequeue_one()
            if item is None:
                return None
            if item.user_id and item.user_id in self._cancelled_users:
                self._drop_meta(item.queue_id)
                continue
            self._drop_meta(item.queue_id)
            return item

    def _dequeue_one(self) -> Optional[QueuedJob]:
        if self.backend == "test":
            if not self._q:
                return None
            return self._q.popleft()

        assert self._channel is not None
        method, _props, body = self._channel.basic_get(queue=self._queue_name, auto_ack=True)
        if method is None or body is None:
            return None
        data = json.loads(body.decode("utf-8"))
        return QueuedJob(
            queue_id=data["queue_id"],
            payload=data["payload"],
            enqueued_at=float(data.get("enqueued_at") or time.time()),
            user_id=data.get("user_id"),
        )

    def _drop_meta(self, queue_id: str) -> None:
        self._waiting_meta = deque(m for m in self._waiting_meta if m.get("queue_id") != queue_id)

    def cancel_for_user(self, user_id: str) -> int:
        """Mark user cancelled; matching messages are skipped on dequeue."""
        if not user_id:
            return 0
        self._cancelled_users.add(user_id)
        removed = 0
        if self.backend == "test":
            kept: Deque[QueuedJob] = deque()
            while self._q:
                item = self._q.popleft()
                if item.user_id == user_id:
                    removed += 1
                    self._drop_meta(item.queue_id)
                else:
                    kept.append(item)
            self._q = kept
            return removed
        # RabbitMQ: count local meta and skip later on dequeue
        still: Deque[Dict[str, Any]] = deque()
        for m in list(self._waiting_meta):
            if m.get("user_id") == user_id:
                removed += 1
            else:
                still.append(m)
        self._waiting_meta = still
        return removed

    def depth(self) -> int:
        if self.backend == "test":
            return len(self._q)
        assert self._channel is not None
        try:
            return int(
                self._channel.queue_declare(queue=self._queue_name, durable=True).method.message_count
            )
        except Exception:
            return len(self._waiting_meta)

    def snapshot(self) -> Dict[str, Any]:
        now = time.time()
        waiting = []
        for m in list(self._waiting_meta)[:30]:
            waiting.append({
                "queue_id": m.get("queue_id"),
                "user_id": m.get("user_id"),
                "kernel": m.get("kernel"),
                "wait_sec": round(now - float(m.get("enqueued_at") or now), 1),
            })
        return {
            "backend": self.backend,
            "depth": self.depth(),
            "max_running_jobs": self.max_running_jobs,
            "waiting": waiting,
        }

    def close(self) -> None:
        try:
            if self._rabbit is not None:
                self._rabbit.close()
        except Exception:
            pass
