"""Tests de la couche streaming.

Verifient que les agregats calcules a partir d'un flux d'evenements sont
strictement identiques a ceux de la couche batch, et que la deduplication par
`transaction_id` fonctionne (coherence Lambda batch / streaming, competence C2.2).
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
from urban_data_explorer.streaming.state import (
    EVENT_COLUMNS,
    GROUP_COLUMNS,
    StreamingSalesState,
)


def sample_events(rows: int = 4000, seed: int = 5) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        {
            "arrondissement": rng.integers(1, 21, rows),
            "year": rng.choice([2024, 2025], rows),
            "transaction_id": [f"t{index}" for index in range(rows)],
            "price_per_m2": rng.uniform(3000, 20000, rows),
            "sale_value_eur": rng.uniform(100000, 2000000, rows),
            "built_surface_m2": rng.uniform(15, 200, rows),
            "rooms": rng.integers(1, 6, rows).astype(float),
            "Type local": rng.choice(["Appartement", "Maison"], rows, p=[0.9, 0.1]),
        }
    )


class StreamingStateTests(unittest.TestCase):
    def test_stream_aggregates_match_batch(self) -> None:
        data = sample_events()
        state = StreamingSalesState()
        for record in data[EVENT_COLUMNS].to_dict(orient="records"):
            state.add_event(record)

        stream_agg = state.compute_aggregates().sort_values(GROUP_COLUMNS).reset_index(drop=True)
        batch_agg = (
            aggregate_sales_metrics(data, GROUP_COLUMNS)
            .sort_values(GROUP_COLUMNS)
            .reset_index(drop=True)
        )
        pd.testing.assert_frame_equal(stream_agg, batch_agg, check_dtype=False, atol=1e-6)

    def test_duplicate_transactions_are_ignored(self) -> None:
        data = sample_events(rows=200)
        state = StreamingSalesState()
        records = data[EVENT_COLUMNS].to_dict(orient="records")
        for record in records:
            state.add_event(record)

        rejected = sum(not state.add_event(record) for record in records[:50])
        self.assertEqual(rejected, 50)
        self.assertEqual(state.event_count, 200)

    def test_incomplete_event_is_rejected(self) -> None:
        state = StreamingSalesState()
        self.assertFalse(state.add_event({"arrondissement": 1, "year": 2025}))
        self.assertEqual(state.event_count, 0)


if __name__ == "__main__":
    unittest.main()
