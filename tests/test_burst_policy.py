from pathlib import Path

from master.burst import BurstController


def _ctrl(**overrides):
    cfg = {
        "scheduling": {
            "max_cloud_vms": 2,
            "min_campus_peers": 2,
            "reclaim_rate_threshold": 0.3,
            "cloud_idle_timeout_sec": 15,
        },
        "burst": {"mode": "local_sim"},
    }
    cfg["scheduling"].update(overrides)
    return BurstController(cfg, Path("."))


def test_burst_on_peer_shortage():
    c = _ctrl()
    assert c.evaluate(campus_peers=0, reclaim_rate=0.0, projected_finish=10, deadline_ts=100, pending_tasks=3)


def test_burst_on_reclaim_storm():
    c = _ctrl()
    assert c.evaluate(campus_peers=5, reclaim_rate=0.9, projected_finish=10, deadline_ts=100, pending_tasks=3)


def test_burst_on_deadline_risk():
    c = _ctrl()
    assert c.evaluate(campus_peers=5, reclaim_rate=0.0, projected_finish=200, deadline_ts=100, pending_tasks=3)


def test_no_burst_when_healthy():
    c = _ctrl()
    assert not c.evaluate(campus_peers=5, reclaim_rate=0.0, projected_finish=50, deadline_ts=100, pending_tasks=3)


def test_force_burst():
    c = _ctrl()
    c.force_burst = True
    assert c.evaluate(campus_peers=5, reclaim_rate=0.0, projected_finish=10, deadline_ts=100, pending_tasks=1)


def test_cap_blocks():
    c = _ctrl()
    c.vms["x"] = type("V", (), {})()  # stub
    c.vms["y"] = type("V", (), {})()
    assert not c.evaluate(campus_peers=0, reclaim_rate=1.0, projected_finish=999, deadline_ts=1, pending_tasks=10)
