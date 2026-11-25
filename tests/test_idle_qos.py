import os

from worker.qos import cpu_busy_ratio, system_is_idle


def test_force_busy_env(monkeypatch):
    monkeypatch.setenv("HPC_FORCE_BUSY", "1")
    monkeypatch.delenv("HPC_FORCE_IDLE", raising=False)
    assert cpu_busy_ratio() == 1.0
    assert system_is_idle() is False


def test_force_idle_env(monkeypatch):
    monkeypatch.delenv("HPC_FORCE_BUSY", raising=False)
    monkeypatch.setenv("HPC_FORCE_IDLE", "1")
    assert cpu_busy_ratio() == 0.0
    assert system_is_idle() is True


def test_windows_sampling_failure_fails_closed(monkeypatch):
    monkeypatch.delenv("HPC_FORCE_BUSY", raising=False)
    monkeypatch.delenv("HPC_FORCE_IDLE", raising=False)
    monkeypatch.setattr("worker.qos.os.name", "nt", raising=False)
    monkeypatch.setattr("worker.qos._windows_idle_times", lambda: None)

    assert cpu_busy_ratio() == 1.0
    assert system_is_idle() is False
