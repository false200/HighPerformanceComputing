import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Unit tests use queue.backend=test (in-process). Production requires RabbitMQ.
os.environ.setdefault("HPC_ALLOW_TEST_QUEUE", "1")
