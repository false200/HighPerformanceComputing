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
            return 1.0
        time.sleep(max(0.05, sample_sec))
        b = _windows_idle_times()
        if b is None:
            return 1.0
        d_idle = b[0] - a[0]
        d_total = b[1] - a[1]
        if d_total <= 0:
            return 1.0
        idle_ratio = max(0.0, min(1.0, d_idle / d_total))
        return 1.0 - idle_ratio

    try:
        load1, _, _ = os.getloadavg()
        cores = max(1, os.cpu_count() or 1)
        return max(0.0, min(1.0, load1 / cores))
    except Exception:
        return 1.0


def system_is_idle(busy_threshold: float = 0.45) -> bool:
    """True when the machine looks idle enough for idle-only campus work."""
    return cpu_busy_ratio() < busy_threshold


def apply_memory_cap_mb(mb: int) -> bool:
    """
    Best-effort process memory ceiling (Windows Job Object).
    Returns True if a hard-ish limit was applied; False if unsupported/skipped.
    """
    if not mb or mb <= 0:
        return False
    limit_bytes = int(mb) * 1024 * 1024
    if os.name != "nt":
        # Linux soft hint via environment for child kernels; no hard cgroup without root.
        os.environ["HPC_RAM_CAP_MB"] = str(int(mb))
        return False
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        JobObjectExtendedLimitInformation = 9
        JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_uint64),
                ("WriteOperationCount", ctypes.c_uint64),
                ("OtherOperationCount", ctypes.c_uint64),
                ("ReadTransferCount", ctypes.c_uint64),
                ("WriteTransferCount", ctypes.c_uint64),
                ("OtherTransferCount", ctypes.c_uint64),
            ]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            return False
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_PROCESS_MEMORY
        info.ProcessMemoryLimit = limit_bytes
        ok = kernel32.SetInformationJobObject(
            handle,
            JobObjectExtendedLimitInformation,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not ok:
            kernel32.CloseHandle(handle)
            return False
        proc = kernel32.GetCurrentProcess()
        if not kernel32.AssignProcessToJobObject(handle, proc):
            kernel32.CloseHandle(handle)
            return False
        os.environ["HPC_RAM_CAP_MB"] = str(int(mb))
        # Keep job handle alive for process lifetime
        apply_memory_cap_mb._job_handle = handle  # type: ignore[attr-defined]
        return True
    except Exception:
        return False


def detect_gpu_count() -> int:
    """Best-effort GPU inventory (not used by current OpenMP kernels)."""
    if os.environ.get("HPC_GPU_COUNT"):
        try:
            return max(0, int(os.environ["HPC_GPU_COUNT"]))
        except ValueError:
            pass
    try:
        if os.name == "nt":
            import subprocess
            out = subprocess.run(
                ["wmic", "path", "win32_VideoController", "get", "Name"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            lines = [ln.strip() for ln in (out.stdout or "").splitlines() if ln.strip() and ln.strip().lower() != "name"]
            # Filter out basic Microsoft Basic Display adapters when others exist
            real = [ln for ln in lines if "basic render" not in ln.lower()]
            return len(real or lines)
    except Exception:
        pass
    return 0
