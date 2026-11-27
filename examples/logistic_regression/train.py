"""User-submitted trainer. Workers call train_shard(header, rows, params)."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Sequence, Tuple


def _sigmoid(z: float) -> float:
    if z >= 30:
        return 1.0
    if z <= -30:
        return 0.0
    return 1.0 / (1.0 + math.exp(-z))


def _parse(header: Sequence[str], rows: Sequence[str], label_col: str) -> Tuple[List[List[float]], List[float], List[str]]:
    idx = {name: i for i, name in enumerate(header)}
    if label_col not in idx:
        label_col = header[-1]
    y_i = idx[label_col]
    x_names = [c for c in header if c != label_col]
    x_idx = [idx[c] for c in x_names]
    X: List[List[float]] = []
    y: List[float] = []
    for line in rows:
        parts = line.split(",")
        X.append([float(parts[j]) for j in x_idx])
        y.append(float(parts[y_i]))
    return X, y, x_names


def train_shard(header: List[str], rows: List[str], params: Dict[str, Any]) -> Dict[str, Any]:
    """Train logistic regression on one CSV shard; return weights for master merge."""
    label_col = str(params.get("label_col") or (header[-1] if header else "label"))
    epochs = int(params.get("epochs", 40))
    lr = float(params.get("lr", 0.08))
    X, y, features = _parse(header, rows, label_col)
    n_features = len(features)
    w = [0.0] * n_features
    b = 0.0
    acc = 0.0
    last_loss = 0.0
    for _ in range(max(1, epochs)):
        loss = 0.0
        correct = 0
        for row, label in zip(X, y):
            z = b + sum(wj * xj for wj, xj in zip(w, row))
            p = _sigmoid(z)
            err = p - label
            loss += -(
                label * math.log(max(p, 1e-9))
                + (1 - label) * math.log(max(1 - p, 1e-9))
            )
            for j in range(n_features):
                w[j] -= lr * err * row[j]
            b -= lr * err
            if (1.0 if p >= 0.5 else 0.0) == label:
                correct += 1
        last_loss = loss / max(1, len(X))
        acc = correct / max(1, len(X))
    checksum = sum((j + 1) * abs(wj) for j, wj in enumerate(w)) + abs(b)
    return {
        "kernel": "userjob",
        "weights": w,
        "bias": b,
        "train_acc": acc,
        "loss": last_loss,
        "n_samples": len(X),
        "n_features": n_features,
        "features": features,
        "checksum": checksum,
    }
