"""Calcul distribue des agregats de ventes.

Ce sous-module fournit une implementation distribuee (Dask) de
`aggregate_sales_metrics`. Elle reproduit a l'identique la semantique de la
version pandas tout en repartissant le travail sur plusieurs workers d'un
cluster local, afin de demontrer la competence C2.2 (systeme distribue) et
d'alimenter la mesure de performance C2.4.
"""

from .dask_aggregation import (
    aggregate_sales_metrics_distributed,
    distributed_cluster,
    resolve_engine,
)

__all__ = [
    "aggregate_sales_metrics_distributed",
    "distributed_cluster",
    "resolve_engine",
]
