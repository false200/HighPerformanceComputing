from __future__ import annotations

import os
import time
from typing import Optional, Tuple


def apply_below_normal_priority() -> bool:
    """Lower process priority so interactive owner apps stay responsive."""
    try:
        if os.name == "nt":
            import ctypes
            # BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            return bool(ctypes.windll.kernel32.SetPriorityClass(handle, 0x00004000))
        os.nice(10)
        return True
    except Exception:
        return False


def effective_threads(reported_cores: int, cpu_cap: int) -> int:
    if cpu_cap and cpu_cap > 0:
        return max(1, min(reported_cores, cpu_cap))
    return max(1, reported_cores)


def set_omp_threads(n: int) -> None:
    os.environ["OMP_NUM_THREADS"] = str(max(1, n))


def _windows_idle_times() -> Optional[Tuple[int, int]]:
    """Return (idle, total) FILETIME-derived ints, or None."""
    try:
        import ctypes
        from ctypes import wintypes

        class FILETIME(ctypes.Structure):
            _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]

        idle = FILETIME()
        kernel = FILETIME()
        user = FILETIME()
        if not ctypes.windll.kernel32.GetSystemTimes(
            ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
        ):
            return None

        def ft_to_int(ft: FILETIME) -> int:
            return (ft.dwHighDateTime << 32) | ft.dwLowDateTime

        idle_i = ft_to_int(idle)
        total_i = ft_to_int(kernel) + ft_to_int(user)
        return idle_i, total_i
    except Exception:
        return None


def cpu_busy_ratio(sample_sec: float = 0.15) -> float:
    """
    Approximate system busy ratio in [0, 1].
    Override with HPC_FORCE_BUSY=1 or HPC_FORCE_IDLE=1 for demos/tests.
    """
    if os.environ.get("HPC_FORCE_BUSY"):
        return 1.0
    if os.environ.get("HPC_FORCE_IDLE"):
        return 0.0

    if os.name == "nt":
        a = _windows_idle_times()
        if a is None:
            return 0.0
        time.sleep(max(0.05, sample_sec))
        b = _windows_idle_times()
        if b is None:
            return 0.0
        d_idle = b[0] - a[0]
        d_total = b[1] - a[1]
        if d_total <= 0:
            return 0.0
        idle_ratio = max(0.0, min(1.0, d_idle / d_total))
        return 1.0 - idle_ratio

    try:
        load1, _, _ = os.getloadavg()
        cores = max(1, os.cpu_count() or 1)
        return max(0.0, min(1.0, load1 / cores))
    except Exception:
        return 0.0


def system_is_idle(busy_threshold: float = 0.45) -> bool:
    """True when the machine looks idle enough for idle-only campus work."""
    return cpu_busy_ratio() < busy_threshold
