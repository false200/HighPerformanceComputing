import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

# Unit tests use queue.backend=test (in-process). Production requires RabbitMQ.
os.environ.setdefault("HPC_ALLOW_TEST_QUEUE", "1")
