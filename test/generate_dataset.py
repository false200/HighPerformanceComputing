"""Create a small house-price style dataset for linear regression."""

from __future__ import annotations

import csv
import random
from pathlib import Path

OUT = Path(__file__).resolve().parent / "data.csv"


def main() -> None:
    random.seed(7)
    # y ≈ 50 + 3.5*sqft_100 + 15*beds + 12*baths + 8*age_inv + noise
    header = ["sqft_100", "bedrooms", "bathrooms", "age_years", "price_k"]
    rows = []
    for _ in range(600):
        sqft = random.uniform(8.0, 35.0)  # hundreds of sqft
        beds = float(random.randint(1, 5))
        baths = float(random.choice([1.0, 1.5, 2.0, 2.5, 3.0]))
        age = random.uniform(0, 40)
        noise = random.gauss(0, 4.0)
        price = 50.0 + 3.5 * sqft + 15.0 * beds + 12.0 * baths - 0.35 * age + noise
        rows.append([sqft, beds, baths, age, price])
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    print(f"wrote {OUT} rows={len(rows)}")


if __name__ == "__main__":
    main()
