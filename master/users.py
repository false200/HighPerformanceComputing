"""Connected job-submitter (user) sessions — visible on the console like workers."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class UserSession:
    user_id: str
    name: str
    connected_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    job_id: Optional[str] = None
    package_id: Optional[str] = None
    status: str = "online"  # online | submitting | waiting | done


class UserRegistry:
    def __init__(self, heartbeat_timeout_sec: float = 20.0):
        self.users: Dict[str, UserSession] = {}
        self.heartbeat_timeout_sec = heartbeat_timeout_sec

    def hello(self, name: str = "user", user_id: Optional[str] = None) -> UserSession:
        uid = user_id or f"user-{uuid.uuid4().hex[:10]}"
        sess = UserSession(user_id=uid, name=(name or "user")[:64])
        self.users[uid] = sess
        return sess

    def heartbeat(self, user_id: str) -> bool:
        u = self.users.get(user_id)
        if not u:
            return False
        u.last_seen = time.time()
        return True

    def bind_job(self, user_id: str, job_id: str, package_id: Optional[str] = None) -> None:
        u = self.users.get(user_id)
        if not u:
            return
        u.job_id = job_id
        u.package_id = package_id
        u.status = "waiting"
        u.last_seen = time.time()

    def bye(self, user_id: str) -> Optional[UserSession]:
        return self.users.pop(user_id, None)

    def sweep_stale(self) -> List[str]:
        now = time.time()
        dead = [
            uid
            for uid, u in self.users.items()
            if now - u.last_seen > self.heartbeat_timeout_sec
        ]
        for uid in dead:
            self.users.pop(uid, None)
        return dead

    def snapshot(self) -> List[Dict[str, Any]]:
        now = time.time()
        out = []
        for u in self.users.values():
            out.append({
                "user_id": u.user_id,
                "name": u.name,
                "status": u.status,
                "job_id": u.job_id,
                "package_id": u.package_id,
                "connected_for_sec": round(max(0.0, now - u.connected_at), 1),
                "heartbeat_age_sec": round(max(0.0, now - u.last_seen), 2),
            })
        return out
