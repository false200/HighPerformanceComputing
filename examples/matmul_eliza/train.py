"""Eliza job: classic row-shard dense matrix multiply C = A @ B.

CSV rows are rows of A (last column is a row tag). B is built from a fixed seed
inside this file so Eliza's package is distinct from Bob's.
"""

from __future__ import annotations

import math
import random
from typing import Any, Dict, List, Sequence


def _parse_A(header: Sequence[str], rows: Sequence[str]) -> List[List[float]]:
    # drop trailing tag column
    width = max(1, len(header) - 1)
    out: List[List[float]] = []
    for line in rows:
        parts = line.split(",")
        out.append([float(parts[j]) for j in range(width)])
    return out


def _make_B(n: int, seed: int = 2026) -> List[List[float]]:
    rng = random.Random(seed)
    return [[rng.uniform(-1.0, 1.0) for _ in range(n)] for _ in range(n)]


def train_shard(header: List[str], rows: List[str], params: Dict[str, Any]) -> Dict[str, Any]:
    A = _parse_A(header, rows)
    n = len(A[0]) if A else 0
    B = _make_B(n, seed=2026)
    # classic ijk matmul for this A-row shard
    C: List[List[float]] = []
    flops = 0
    for row in A:
        out_row = [0.0] * n
        for j in range(n):
            s = 0.0
            for k in range(n):
                s += row[k] * B[k][j]
                flops += 2
            out_row[j] = s
        C.append(out_row)
    checksum = sum(abs(v) for row in C for v in row) / max(1, len(C) * n)
    frobenius = math.sqrt(sum(v * v for row in C for v in row))
    return {
        "kernel": "userjob",
        "model_type": "matmul_classic",
        "user": "eliza",
        "algorithm": "ijk",
        "n": n,
        "rows": len(A),
        "flops": flops,
        "frobenius": frobenius,
        "checksum": checksum,
        "mean_abs_c": checksum,
        "weights": [checksum, frobenius / max(1.0, n)],
        "bias": float(len(A)),
        "mse": 0.0,
        "epochs": 1,
        "n_samples": len(A),
        "n_features": n,
    }
