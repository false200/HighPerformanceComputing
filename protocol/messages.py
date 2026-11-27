from __future__ import annotations

import json
from enum import Enum
from typing import Any, Dict, Optional


class MessageType(str, Enum):
    REGISTER = "REGISTER"
    REGISTER_ACK = "REGISTER_ACK"
    HEARTBEAT = "HEARTBEAT"
    TASK_ASSIGN = "TASK_ASSIGN"
    TASK_RESULT = "TASK_RESULT"
    TASK_CHECKPOINT = "TASK_CHECKPOINT"
    TASK_RECLAIM = "TASK_RECLAIM"
    LEAVE = "LEAVE"
    PAUSE = "PAUSE"
    RESUME = "RESUME"
    JOB_SUBMIT = "JOB_SUBMIT"
    JOB_STATUS = "JOB_STATUS"
    PACKAGE_PUT = "PACKAGE_PUT"  # user uploads code+data to live platform
    PACKAGE_GET = "PACKAGE_GET"
    USER_HELLO = "USER_HELLO"  # job submitter joins console
    USER_HEARTBEAT = "USER_HEARTBEAT"
    USER_BYE = "USER_BYE"
    FORCE_BURST = "FORCE_BURST"
    METRICS = "METRICS"
    ERROR = "ERROR"
    SHUTDOWN = "SHUTDOWN"


def make(msg_type: MessageType | str, **payload: Any) -> Dict[str, Any]:
    # Prefer .value — str(Enum) can yield "MessageType.X" on some Python versions.
    type_str = msg_type.value if isinstance(msg_type, MessageType) else str(msg_type)
    return {"type": type_str, **payload}


def encode(msg: Dict[str, Any]) -> bytes:
    return (json.dumps(msg, separators=(",", ":")) + "\n").encode("utf-8")


MAX_MESSAGE_BYTES = 5_000_000  # allow job package uploads (code + CSV)


def decode(line: bytes | str) -> Optional[Dict[str, Any]]:
    if isinstance(line, bytes):
        if len(line) > MAX_MESSAGE_BYTES:
            raise ValueError("message too large")
        line = line.decode("utf-8", errors="replace")
    elif len(line) > MAX_MESSAGE_BYTES:
        raise ValueError("message too large")
    line = line.strip()
    if not line:
        return None
    return json.loads(line)
