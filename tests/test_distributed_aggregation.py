"""Tests d'equivalence entre le moteur pandas et les moteurs distribues.

Ces tests prouvent que les implementations distribuees (Dask, Spark) produisent
exactement le meme resultat que la version pandas de reference. C'est la preuve
de non-regression demandee pour la competence C2.2.

Les moteurs distribues sont optionnels : si `dask` ou `pyspark` ne sont pas
installes, le test correspondant est ignore (skip) plutot qu'echoue.
"""

from __future__ import annotations

import sys
from pathlib import Path
import unittest

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "pipeline" / "src"
for path in (ROOT, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from urban_data_explorer.build import aggregate_sales_metrics


GROUP_COLUMNS = ["arrondissement", "year"]


def sample_transactions(rows: int = 20_000, seed: int = 11) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        {
            "arrondissement": rng.integers(1, 21, rows),
            "year": rng.choice([2023, 2024, 2025], rows),
            "transaction_id": [f"t{index % 15000}" for index in range(rows)],
            "price_per_m2": rng.uniform(3000, 20000, rows),
            "sale_value_eur": rng.uniform(100000, 2000000, rows),
            "built_surface_m2": rng.uniform(15, 200, rows),
            "rooms": rng.integers(1, 6, rows).astype(float),
            "Type local": rng.choice(["Appartement", "Maison"], rows, p=[0.9, 0.1]),
        }
    )


class DistributedEquivalenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.data = sample_transactions()
        self.reference = aggregate_sales_metrics(
            self.data, GROUP_COLUMNS, engine="pandas"
        ).sort_values(GROUP_COLUMNS).reset_index(drop=True)

    def test_dask_matches_pandas(self) -> None:
        try:
            import dask  # noqa: F401
        except ImportError:
            self.skipTest("dask non installe")

        result = aggregate_sales_metrics(self.data, GROUP_COLUMNS, engine="dask")
        result = result.sort_values(GROUP_COLUMNS).reset_index(drop=True)
        pd.testing.assert_frame_equal(self.reference, result, check_dtype=False, atol=1e-6)

    def test_spark_matches_pandas(self) -> None:
        try:
            import pyspark  # noqa: F401
        except ImportError:
            self.skipTest("pyspark non installe")

        result = aggregate_sales_metrics(self.data, GROUP_COLUMNS, engine="spark")
        result = result.sort_values(GROUP_COLUMNS).reset_index(drop=True)
        pd.testing.assert_frame_equal(self.reference, result, check_dtype=False, atol=1e-6)


if __name__ == "__main__":
    unittest.main()
