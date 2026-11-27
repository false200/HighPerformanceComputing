"""Simple sharded ML trainers for the desktop grid (stdlib only).

Each task trains on a synthetic data shard and returns local weights.
The master averages shard weights (parameter-server style) into one model.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import time
from typing import Any, Dict, List, Tuple


def _sigmoid(z: float) -> float:
    if z >= 30:
        return 1.0
    if z <= -30:
        return 0.0
    return 1.0 / (1.0 + math.exp(-z))


def _make_shard(
    seed: int,
    n_samples: int,
    n_features: int,
    kind: str,
) -> Tuple[List[List[float]], List[float]]:
    rng = random.Random(seed)
    # Plant a shared "true" model so shards are consistent enough to average.
    true_w = [math.sin(0.7 * (j + 1)) for j in range(n_features)]
    true_b = 0.35
    X: List[List[float]] = []
    y: List[float] = []
    for _ in range(n_samples):
        row = [rng.uniform(-1.0, 1.0) for _ in range(n_features)]
        z = true_b + sum(wj * xj for wj, xj in zip(true_w, row)) + rng.gauss(0, 0.15)
        if kind == "logreg":
            label = 1.0 if _sigmoid(z) >= 0.5 else 0.0
        else:
            label = z  # linear target
        X.append(row)
        y.append(label)
    return X, y


def train_logreg(
    X: List[List[float]],
    y: List[float],
    epochs: int,
    lr: float,
    threads: int = 1,
) -> Dict[str, Any]:
    n_features = len(X[0]) if X else 0
    w = [0.0] * n_features
    b = 0.0
    # threads reserved for future OpenMP parity; SGD is sequential here
    _ = max(1, threads)
    last_loss = 0.0
    for _ep in range(max(1, epochs)):
        loss = 0.0
        correct = 0
        for row, label in zip(X, y):
            z = b + sum(wj * xj for wj, xj in zip(w, row))
            p = _sigmoid(z)
            err = p - label
            loss += -(label * math.log(max(p, 1e-9)) + (1 - label) * math.log(max(1 - p, 1e-9)))
            for j in range(n_features):
                w[j] -= lr * err * row[j]
            b -= lr * err
            pred = 1.0 if p >= 0.5 else 0.0
            if pred == label:
                correct += 1
        last_loss = loss / max(1, len(X))
        acc = correct / max(1, len(X))
    checksum = sum((j + 1) * abs(wj) for j, wj in enumerate(w)) + abs(b)
    return {
        "kernel": "logreg",
        "weights": w,
        "bias": b,
        "train_acc": acc,
        "loss": last_loss,
        "n_samples": len(X),
        "n_features": n_features,
        "checksum": checksum,
    }


def train_linreg(
    X: List[List[float]],
    y: List[float],
    epochs: int,
    lr: float,
    threads: int = 1,
) -> Dict[str, Any]:
    n_features = len(X[0]) if X else 0
    w = [0.0] * n_features
    b = 0.0
    _ = max(1, threads)
    last_mse = 0.0
    for _ep in range(max(1, epochs)):
        sse = 0.0
        for row, label in zip(X, y):
            pred = b + sum(wj * xj for wj, xj in zip(w, row))
            err = pred - label
            sse += err * err
            for j in range(n_features):
                w[j] -= lr * err * row[j]
            b -= lr * err
        last_mse = sse / max(1, len(X))
    checksum = sum((j + 1) * abs(wj) for j, wj in enumerate(w)) + abs(b)
    return {
        "kernel": "linreg",
        "weights": w,
        "bias": b,
        "mse": last_mse,
        "n_samples": len(X),
        "n_features": n_features,
        "checksum": checksum,
    }


def run(params: Dict[str, Any]) -> Dict[str, Any]:
    kind = str(params.get("kernel") or params.get("mode") or "logreg")
    seed = int(params.get("seed", 1))
    n_samples = int(params.get("n_samples", 400))
    n_features = int(params.get("n_features", 8))
    epochs = int(params.get("epochs", 25))
    lr = float(params.get("lr", 0.05))
    threads = int(params.get("threads") or 1)
    t0 = time.perf_counter()
    X, y = _make_shard(seed, n_samples, n_features, kind)
    if kind == "linreg":
        out = train_linreg(X, y, epochs, lr, threads)
    else:
        out = train_logreg(X, y, epochs, lr, threads)
    out["elapsed_ms"] = (time.perf_counter() - t0) * 1000.0
    out["seed"] = seed
    out["shard"] = int(params.get("shard", 0))
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=["logreg", "linreg"])
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--shard", type=int, default=0)
    p.add_argument("--n-samples", type=int, default=400)
    p.add_argument("--n-features", type=int, default=8)
    p.add_argument("--epochs", type=int, default=25)
    p.add_argument("--lr", type=float, default=0.05)
    p.add_argument("--threads", type=int, default=1)
    args = p.parse_args()
    result = run({
        "kernel": args.mode,
        "seed": args.seed,
        "shard": args.shard,
        "n_samples": args.n_samples,
        "n_features": args.n_features,
        "epochs": args.epochs,
        "lr": args.lr,
        "threads": args.threads,
    })
    print(json.dumps(result, separators=(",", ":")))


if __name__ == "__main__":
    main()
