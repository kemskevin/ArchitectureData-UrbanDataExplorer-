"""Benchmark des moteurs d'agregation : pandas vs distribue.

Mesure et compare le temps d'execution de l'agregation des ventes selon le
moteur choisi. Sert deux competences :
- C2.2 : preuve qu'un calcul distribue (Dask / Spark) est operationnel ;
- C2.4 : mesure de performance des pipelines, avec une lecture honnete du
  seuil a partir duquel le distribue devient pertinent.

Usage :
    python pipeline/benchmarks/aggregation_benchmark.py --rows 500000 --engines pandas spark
    python pipeline/benchmarks/aggregation_benchmark.py --rows 2000000 --engines pandas dask

Le script genere un dataset synthetique au schema DVF, execute chaque moteur,
verifie l'equivalence des resultats, puis affiche un tableau comparatif.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "pipeline" / "src"
for path in (ROOT, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import numpy as np
import pandas as pd


GROUP_COLUMNS = ["arrondissement", "year"]


def make_dataset(rows: int, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        {
            "arrondissement": rng.integers(1, 21, rows),
            "year": rng.choice([2023, 2024, 2025], rows),
            "transaction_id": [f"t{index % max(1, rows * 3 // 4)}" for index in range(rows)],
            "price_per_m2": rng.uniform(3000, 20000, rows),
            "sale_value_eur": rng.uniform(100000, 2000000, rows),
            "built_surface_m2": rng.uniform(15, 200, rows),
            "rooms": rng.integers(1, 6, rows).astype(float),
            "Type local": rng.choice(["Appartement", "Maison"], rows, p=[0.9, 0.1]),
        }
    )


def run_engine(engine: str, data: pd.DataFrame) -> tuple[pd.DataFrame, float]:
    from urban_data_explorer.build import aggregate_sales_metrics

    start = time.perf_counter()
    result = aggregate_sales_metrics(data, GROUP_COLUMNS, engine=engine)
    elapsed = time.perf_counter() - start
    return result.sort_values(GROUP_COLUMNS).reset_index(drop=True), elapsed


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark des moteurs d'agregation")
    parser.add_argument("--rows", type=int, default=500_000)
    parser.add_argument(
        "--engines",
        nargs="+",
        default=["pandas", "spark"],
        choices=["pandas", "dask", "spark"],
    )
    args = parser.parse_args()

    print(f"Dataset synthetique : {args.rows:,} lignes")
    data = make_dataset(args.rows)

    reference: pd.DataFrame | None = None
    timings: dict[str, float] = {}

    for engine in args.engines:
        print(f"\n[{engine}] execution...")
        result, elapsed = run_engine(engine, data)
        timings[engine] = elapsed
        print(f"[{engine}] {elapsed:.2f}s -> {len(result)} groupes")

        if reference is None:
            reference = result
        else:
            try:
                pd.testing.assert_frame_equal(reference, result, check_dtype=False, atol=1e-6)
                print(f"[{engine}] equivalence avec le moteur de reference : OK")
            except AssertionError:
                print(f"[{engine}] ATTENTION : resultats differents du moteur de reference")

    print("\nResume")
    baseline = timings.get("pandas")
    for engine, elapsed in timings.items():
        speedup = f"x{baseline / elapsed:.2f}" if baseline else "-"
        print(f"  {engine:<7} {elapsed:>8.2f}s   speedup vs pandas: {speedup}")

    print(
        "\nLecture : sur de faibles volumes, l'overhead du distribue (serialisation,"
        " JVM, reseau) domine et pandas reste plus rapide. Le distribue devient"
        " pertinent quand les donnees depassent la memoire d'une machine ou que"
        " le calcul par groupe est plus lourd."
    )


if __name__ == "__main__":
    main()
