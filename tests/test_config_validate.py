from master.config_validate import validate_config


def test_default_like_config_ok():
    cfg = {
        "master": {"port": 9100},
        "scheduling": {"heartbeat_timeout_sec": 6, "max_cloud_vms": 2, "min_campus_peers": 1},
        "storage": {"backend": "local"},
        "burst": {"mode": "local_sim"},
        "queue": {
            "backend": "rabbitmq",
            "max_running_jobs": 4,
            "rabbitmq_url": "amqp://guest:guest@localhost:5672/",
        },
    }
    assert validate_config(cfg) == []


def test_s3_requires_bucket():
    cfg = {"storage": {"backend": "s3"}, "burst": {"mode": "local_sim"}, "master": {"port": 9100}}
    errs = validate_config(cfg)
    assert any("s3_bucket" in e for e in errs)


def test_queue_rejects_memory_backend():
    cfg = {
        "master": {"port": 9100},
        "storage": {"backend": "local"},
        "burst": {"mode": "local_sim"},
        "queue": {"backend": "memory", "rabbitmq_url": "amqp://guest:guest@localhost:5672/"},
    }
    errs = validate_config(cfg)
    assert any("rabbitmq" in e for e in errs)
