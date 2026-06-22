"""Agregation distribuee des ventes avec Apache Spark.

Cette implementation calcule exactement les memes indicateurs que la version
pandas `aggregate_sales_metrics`, mais en repartissant le `groupBy` sur un
cluster Spark (master + workers). Elle alimente la competence C2.2 (systeme
distribue) et illustre une architecture scalable horizontalement (C1.4).

Deux modes d'execution :
- `local[*]` : Spark demarre un mini-cluster dans le process courant, pratique
  pour les tests et le developpement ;
- `spark://master:7077` : Spark se connecte au cluster declare dans
  `docker-compose.yml`, ce qui constitue la vraie demonstration distribuee.

Le master est lu dans la variable d'environnement `UDE_SPARK_MASTER`.
La sortie est garantie identique a la version pandas (memes colonnes, memes
valeurs, meme tri), ce qui est verifie par un test d'equivalence.
"""

from __future__ import annotations

from contextlib import contextmanager
import os
from typing import Iterator

import pandas as pd

METRIC_COLUMNS = [
    "median_price_m2",
    "median_sale_value_eur",
    "median_surface_m2",
    "median_rooms",
    "apartment_share_pct",
    "house_share_pct",
]

# Colonnes minimales necessaires au calcul cote Spark.
INPUT_COLUMNS = [
    "transaction_id",
    "price_per_m2",
    "sale_value_eur",
    "built_surface_m2",
    "rooms",
    "Type local",
]


def spark_master() -> str:
    """Adresse du master Spark.

    Defaut `local[*]` (cluster local multi-coeurs). En contexte Docker, on
    passe `spark://spark-master:7077` via `UDE_SPARK_MASTER`.
    """

    return os.environ.get("UDE_SPARK_MASTER", "local[*]").strip()


@contextmanager
def spark_session(app_name: str = "urban-data-explorer") -> Iterator[object]:
    """Cree une SparkSession et la ferme proprement a la sortie.

    Le shuffle partitions est aligne sur un petit nombre car les agregats du
    projet produisent peu de groupes (au plus quelques milliers).
    """

    from pyspark.sql import SparkSession

    builder = (
        SparkSession.builder.appName(app_name)
        .master(spark_master())
        .config("spark.sql.shuffle.partitions", os.environ.get("UDE_SPARK_SHUFFLE", "16"))
        .config("spark.ui.showConsoleProgress", "false")
    )
    session = builder.getOrCreate()
    session.sparkContext.setLogLevel("WARN")
    try:
        yield session
    finally:
        session.stop()


def aggregate_sales_metrics_spark(
    data: pd.DataFrame,
    group_columns: list[str],
    session: object | None = None,
) -> pd.DataFrame:
    """Version Spark de `aggregate_sales_metrics`.

    Semantique reproduite a l'identique :
    - `transactions` = nombre de `transaction_id` distincts par groupe ;
    - medianes (prix/m2, valeur, surface, pieces) via `percentile(col, 0.5)` ;
    - parts appartement / maison en pourcentage arrondi a 1 decimale ;
    - metriques arrondies a 2 decimales, tri par cles de groupe.

    `session` permet de reutiliser une SparkSession existante (cluster Docker).
    Si `None`, une session locale est creee pour la duree de l'appel.
    """

    from pyspark.sql import functions as F

    if data.empty:
        return pd.DataFrame(columns=[*group_columns, "transactions", *METRIC_COLUMNS])

    needed = [*group_columns, *INPUT_COLUMNS]
    frame = data[needed].copy()

    own_session = session is None
    ctx = spark_session() if own_session else _null_cm(session)

    with ctx as active:
        sdf = active.createDataFrame(frame)

        sdf = sdf.withColumn(
            "is_apartment", (F.col("`Type local`") == F.lit("Appartement")).cast("double")
        ).withColumn(
            "is_house", (F.col("`Type local`") == F.lit("Maison")).cast("double")
        )

        aggregated = sdf.groupBy(*group_columns).agg(
            F.countDistinct("transaction_id").alias("transactions"),
            F.expr("percentile(price_per_m2, 0.5)").alias("median_price_m2"),
            F.expr("percentile(sale_value_eur, 0.5)").alias("median_sale_value_eur"),
            F.expr("percentile(built_surface_m2, 0.5)").alias("median_surface_m2"),
            F.expr("percentile(rooms, 0.5)").alias("median_rooms"),
            F.avg("is_apartment").alias("apartment_share_raw"),
            F.avg("is_house").alias("house_share_raw"),
        )

        aggregated = (
            aggregated.withColumn(
                "apartment_share_pct", F.round(F.col("apartment_share_raw") * 100.0, 1)
            )
            .withColumn("house_share_pct", F.round(F.col("house_share_raw") * 100.0, 1))
            .withColumn("median_price_m2", F.round("median_price_m2", 2))
            .withColumn("median_sale_value_eur", F.round("median_sale_value_eur", 2))
            .withColumn("median_surface_m2", F.round("median_surface_m2", 2))
            .withColumn("median_rooms", F.round("median_rooms", 2))
        )

        ordered_columns = [*group_columns, "transactions", *METRIC_COLUMNS]
        result = aggregated.select(*ordered_columns).toPandas()

    result["transactions"] = result["transactions"].astype("int64")
    return result.sort_values(group_columns).reset_index(drop=True)


@contextmanager
def _null_cm(value: object) -> Iterator[object]:
    yield value
