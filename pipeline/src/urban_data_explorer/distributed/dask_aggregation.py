"""Agregation distribuee des ventes avec Dask.

L'objectif est de calculer exactement les memes indicateurs que la version
pandas `aggregate_sales_metrics`, mais en repartissant le `groupby` sur les
workers d'un cluster Dask local. La sortie est garantie identique (memes
colonnes, memes valeurs, meme tri), ce qui est verifie par un test
d'equivalence.

Concepts distribues mis en oeuvre :
- partitionnement du DataFrame en N partitions (une unite de travail par
  partition) ;
- execution sur un `LocalCluster` multi-workers (scheduler + workers) ;
- agregation en deux passes (combine puis aggregate) geree par Dask, qui
  construit un graphe de taches distribue.
"""

from __future__ import annotations

from contextlib import contextmanager, nullcontext
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

OUTPUT_DTYPES = {
    "transactions": "int64",
}


def resolve_engine(engine: str | None = None) -> str:
    """Determine le moteur d'agregation a utiliser.

    Priorite : argument explicite > variable d'environnement `UDE_AGG_ENGINE` >
    defaut `pandas`. Toute valeur inconnue retombe sur `pandas` pour ne jamais
    casser le build existant.
    """

    chosen = (engine or os.environ.get("UDE_AGG_ENGINE") or "pandas").strip().lower()
    return chosen if chosen in {"pandas", "dask"} else "pandas"


def _worker_count() -> int:
    """Nombre de workers du cluster local, configurable via `UDE_DASK_WORKERS`."""

    raw = os.environ.get("UDE_DASK_WORKERS", "4")
    try:
        value = int(raw)
    except ValueError:
        value = 4
    return max(1, value)


def _partition_count(row_count: int, worker_count: int) -> int:
    """Choisit un nombre de partitions adapte au volume et aux workers.

    On vise au moins deux partitions par worker pour permettre un vrai
    equilibrage de charge, sans descendre sous une partition.
    """

    target = max(worker_count * 2, 1)
    if row_count <= 0:
        return 1
    # Evite des partitions minuscules quand le dataset est petit.
    return max(1, min(target, row_count))


@contextmanager
def distributed_cluster() -> Iterator[object]:
    """Demarre un cluster Dask local et fournit un client connecte.

    Le cluster est ferme proprement a la sortie. Le nombre de workers est lu
    dans `UDE_DASK_WORKERS`. Si `dask.distributed` n'est pas disponible, on
    retombe silencieusement sur le scheduler par defaut de Dask (threads),
    ce qui reste un calcul parallelise par graphe de taches.
    """

    try:
        from dask.distributed import Client, LocalCluster
    except ImportError:
        yield None
        return

    cluster = LocalCluster(
        n_workers=_worker_count(),
        threads_per_worker=1,
        processes=True,
        dashboard_address=os.environ.get("UDE_DASK_DASHBOARD", ":8787"),
    )
    client = Client(cluster)
    try:
        yield client
    finally:
        client.close()
        cluster.close()


def aggregate_sales_metrics_distributed(
    data: pd.DataFrame,
    group_columns: list[str],
    client: object | None = None,
) -> pd.DataFrame:
    """Version distribuee de `aggregate_sales_metrics`.

    Reproduit fidelement la logique pandas :
    - `transactions` = nombre de `transaction_id` distincts ;
    - medianes de prix/m2, valeur, surface, pieces ;
    - parts appartement / maison en pourcentage arrondi a 1 decimale ;
    - arrondi des metriques a 2 decimales et tri par cles de groupe.

    Le parametre `client` permet de reutiliser un cluster deja demarre. S'il
    est `None`, Dask utilise son scheduler par defaut.
    """

    import dask.dataframe as dd

    if data.empty:
        return pd.DataFrame(columns=[*group_columns, "transactions", *METRIC_COLUMNS])

    worker_count = _worker_count()
    npartitions = _partition_count(len(data), worker_count)

    frame = data.copy()
    frame["is_apartment"] = frame["Type local"].eq("Appartement")
    frame["is_house"] = frame["Type local"].eq("Maison")

    ddf = dd.from_pandas(frame, npartitions=npartitions)

    aggregated = (
        ddf.groupby(group_columns)
        .agg(
            transactions=("transaction_id", "nunique"),
            median_price_m2=("price_per_m2", "median"),
            median_sale_value_eur=("sale_value_eur", "median"),
            median_surface_m2=("built_surface_m2", "median"),
            median_rooms=("rooms", "median"),
            apartment_share_pct=("is_apartment", "mean"),
            house_share_pct=("is_house", "mean"),
        )
    )

    # Declenche le calcul distribue (graphe de taches execute sur les workers).
    result = aggregated.compute()
    result = result.reset_index()

    result["apartment_share_pct"] = (result["apartment_share_pct"] * 100.0).round(1)
    result["house_share_pct"] = (result["house_share_pct"] * 100.0).round(1)
    result[METRIC_COLUMNS] = result[METRIC_COLUMNS].round(2)
    result["transactions"] = result["transactions"].astype("int64")

    ordered_columns = [*group_columns, "transactions", *METRIC_COLUMNS]
    result = result[ordered_columns]
    return result.sort_values(group_columns).reset_index(drop=True)
