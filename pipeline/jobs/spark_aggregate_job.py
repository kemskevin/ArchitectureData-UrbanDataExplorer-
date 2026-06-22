"""Job Spark soumis au cluster pour l'agregation distribuee des ventes.

Ce script est lance via `spark-submit` sur le cluster declare dans
`docker-compose.spark.yml`. Il :

1. charge les transactions DVF preparees (zone Silver, via le pipeline) ;
2. calcule les agregats par arrondissement / annee de facon distribuee ;
3. affiche un resume et, en option, ecrit la table dans MySQL.

Il sert de preuve concrete de la competence C2.2 : le meme calcul que le build
pandas est ici reparti sur plusieurs workers Spark.

Execution locale (sans Docker), utile pour tester :
    UDE_SPARK_MASTER=local[*] python pipeline/jobs/spark_aggregate_job.py

Execution sur le cluster Docker :
    docker compose -f docker-compose.yml -f docker-compose.spark.yml run --rm spark-submit
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "pipeline" / "src"
for path in (ROOT, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import pandas as pd

from urban_data_explorer.distributed.spark_aggregation import (
    aggregate_sales_metrics_spark,
    spark_master,
    spark_session,
)


def _load_transactions() -> pd.DataFrame:
    """Charge les transactions DVF preparees.

    On reutilise la fonction du pipeline si les sources Bronze sont presentes.
    Sinon, on retombe sur un petit echantillon synthetique pour que la demo
    fonctionne meme sans donnees telechargees.
    """

    try:
        from urban_data_explorer.build import load_sales_transactions

        return load_sales_transactions()
    except Exception as error:  # noqa: BLE001 - demo resiliente
        print(f"[info] sources DVF indisponibles ({error}); usage d'un echantillon synthetique.")
        import numpy as np

        rng = np.random.default_rng(0)
        size = 50_000
        return pd.DataFrame(
            {
                "arrondissement": rng.integers(1, 21, size),
                "year": rng.choice([2023, 2024, 2025], size),
                "transaction_id": [f"t{index}" for index in range(size)],
                "price_per_m2": rng.uniform(3000, 20000, size),
                "sale_value_eur": rng.uniform(100000, 2000000, size),
                "built_surface_m2": rng.uniform(15, 200, size),
                "rooms": rng.integers(1, 6, size).astype(float),
                "Type local": rng.choice(["Appartement", "Maison"], size, p=[0.9, 0.1]),
            }
        )


def main() -> None:
    print(f"[spark] master = {spark_master()}")
    transactions = _load_transactions()
    print(f"[spark] {len(transactions):,} transactions chargees")

    group_columns = ["arrondissement", "year"]
    with spark_session(app_name="ude-aggregate-job") as session:
        workers = session.sparkContext.defaultParallelism
        print(f"[spark] parallelisme par defaut = {workers}")
        result = aggregate_sales_metrics_spark(transactions, group_columns, session=session)

    print(f"[spark] {len(result)} groupes agreges (distribue)")
    print(result.head(10).to_string(index=False))


if __name__ == "__main__":
    main()
