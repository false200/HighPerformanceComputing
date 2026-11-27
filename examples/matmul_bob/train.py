"""Bob job: blocked (tiled) matrix multiply C = A @ B.

Different Python file + algorithm from Eliza — same cluster, competing for workers.
"""

from __future__ import annotations

import math
import random
from typing import Any, Dict, List, Sequence


def _parse_A(header: Sequence[str], rows: Sequence[str]) -> List[List[float]]:
    width = max(1, len(header) - 1)
    out: List[List[float]] = []
    for line in rows:
        parts = line.split(",")
        out.append([float(parts[j]) for j in range(width)])
    return out


def _make_B(n: int, seed: int = 4242) -> List[List[float]]:
    rng = random.Random(seed)
    return [[rng.uniform(-1.0, 1.0) for _ in range(n)] for _ in range(n)]


def train_shard(header: List[str], rows: List[str], params: Dict[str, Any]) -> Dict[str, Any]:
    A = _parse_A(header, rows)
    n = len(A[0]) if A else 0
    B = _make_B(n, seed=4242)
    tile = max(8, min(16, n // 4 or 8))
    C = [[0.0 for _ in range(n)] for _ in range(len(A))]
    flops = 0
    # blocked ikj-style multiply over this A-row shard
    for i0 in range(0, len(A), tile):
        for k0 in range(0, n, tile):
            for j0 in range(0, n, tile):
                i1 = min(i0 + tile, len(A))
                k1 = min(k0 + tile, n)
                j1 = min(j0 + tile, n)
                for i in range(i0, i1):
                    Ai = A[i]
                    Ci = C[i]
                    for k in range(k0, k1):
                        aik = Ai[k]
                        Bk = B[k]
                        for j in range(j0, j1):
                            Ci[j] += aik * Bk[j]
                            flops += 2
    checksum = sum(abs(v) for row in C for v in row) / max(1, len(C) * n)
    frobenius = math.sqrt(sum(v * v for row in C for v in row))
    return {
        "kernel": "userjob",
        "model_type": "matmul_blocked",
        "user": "bob",
        "algorithm": "blocked_ikj",
        "tile": tile,
        "n": n,
        "rows": len(A),
        "flops": flops,
        "frobenius": frobenius,
        "checksum": checksum,
        "mean_abs_c": checksum,
        "weights": [checksum, frobenius / max(1.0, n), float(tile)],
        "bias": float(len(A)),
        "mse": 0.0,
        "epochs": 1,
        "n_samples": len(A),
        "n_features": n,
    }
