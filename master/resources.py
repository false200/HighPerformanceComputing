"""Ray-inspired logical resources (admission control, not OS pinning).

Knowledge adapted from Ray Core: tasks declare CPU / memory / custom resources;
the scheduler only places work where enough *logical* capacity remains.
Physical OpenMP thread use is still capped by owner QoS on the worker.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class ResourceSpec:
    """Logical resource request attached to a task (Ray-style)."""

    num_cpus: float = 1.0
    memory_mb: float = 0.0  # 0 = do not gate on memory
    custom: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "num_cpus": self.num_cpus,
            "memory_mb": self.memory_mb,
            "custom": dict(self.custom),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any] | None) -> "ResourceSpec":
        if not data:
            return cls()
        custom = data.get("custom") or {}
        return cls(
            num_cpus=float(data.get("num_cpus", 1.0)),
            memory_mb=float(data.get("memory_mb", 0.0)),
            custom={str(k): float(v) for k, v in custom.items()},
        )


@dataclass
class NodeResources:
    """Logical capacity advertised by a worker node."""

    total_cpus: float
    total_memory_mb: float
    custom: Dict[str, float] = field(default_factory=dict)
    reserved_cpus: float = 0.0
    reserved_memory_mb: float = 0.0
    reserved_custom: Dict[str, float] = field(default_factory=dict)

    def available_cpus(self) -> float:
        return max(0.0, self.total_cpus - self.reserved_cpus)

    def available_memory_mb(self) -> float:
        return max(0.0, self.total_memory_mb - self.reserved_memory_mb)

    def can_fit(self, req: ResourceSpec) -> bool:
        if req.num_cpus > self.available_cpus() + 1e-9:
            return False
        if req.memory_mb > 0 and req.memory_mb > self.available_memory_mb() + 1e-9:
            return False
        for name, need in req.custom.items():
            have = self.custom.get(name, 0.0) - self.reserved_custom.get(name, 0.0)
            if need > have + 1e-9:
                return False
        return True

    def reserve(self, req: ResourceSpec) -> None:
        self.reserved_cpus += req.num_cpus
        self.reserved_memory_mb += max(0.0, req.memory_mb)
        for name, need in req.custom.items():
            self.reserved_custom[name] = self.reserved_custom.get(name, 0.0) + need

    def release(self, req: ResourceSpec) -> None:
        self.reserved_cpus = max(0.0, self.reserved_cpus - req.num_cpus)
        self.reserved_memory_mb = max(0.0, self.reserved_memory_mb - max(0.0, req.memory_mb))
        for name, need in req.custom.items():
            left = self.reserved_custom.get(name, 0.0) - need
            if left <= 1e-9:
                self.reserved_custom.pop(name, None)
            else:
                self.reserved_custom[name] = left
