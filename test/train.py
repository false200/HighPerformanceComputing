"""User job: linear regression for 100 epochs on a CSV shard.

Workers call: train_shard(header, rows, params) -> dict with weights/bias/mse
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple


def _parse(
    header: Sequence[str],
    rows: Sequence[str],
    label_col: str,
) -> Tuple[List[List[float]], List[float], List[str]]:
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
    label_col = str(params.get("label_col") or "price_k")
    epochs = int(params.get("epochs", 100))
    lr = float(params.get("lr", 0.0005))
    X, y, features = _parse(header, rows, label_col)
    n_features = len(features)
    w = [0.0] * n_features
    b = 0.0
    last_mse = 0.0
    for _ in range(max(1, epochs)):
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
        "kernel": "userjob",
        "model_type": "linreg",
        "weights": w,
        "bias": b,
        "mse": last_mse,
        "epochs": epochs,
        "n_samples": len(X),
        "n_features": n_features,
        "features": features,
        "checksum": checksum,
    }
