import csv
import random
from pathlib import Path


def write_A(path: Path, n: int, seed: int) -> None:
    rng = random.Random(seed)
    path.parent.mkdir(parents=True, exist_ok=True)
    header = [f"c{j}" for j in range(n)] + ["tag"]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        for i in range(n):
            row = [round(rng.uniform(-1.0, 1.0), 6) for _ in range(n)] + [float(i)]
            w.writerow(row)
    print(path, "n=", n)


if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    write_A(root / "matmul_eliza" / "A.csv", 64, seed=7)
    write_A(root / "matmul_bob" / "A.csv", 80, seed=99)
