"""Couche streaming temps reel (architecture Lambda, competence C2.2).

Ce sous-module simule l'arrivee de nouvelles transactions immobilieres au fil
de l'eau et les traite en flux :

- `producer` : rejoue des transactions DVF dans un topic Kafka, une par une,
  pour simuler un flux temps reel ;
- `consumer` : lit le flux, maintient un etat par groupe et recalcule les
  agregats a chaque fenetre en reutilisant la logique batch
  (`aggregate_sales_metrics`), garantissant des resultats coherents entre la
  couche batch et la couche streaming.

La couche batch (pipeline pandas / Spark) et la couche streaming alimentent la
meme couche de service (MySQL / Mongo + API), ce qui constitue une architecture
Lambda complete.
"""

from .config import (
    KAFKA_BOOTSTRAP,
    SALES_TOPIC,
    kafka_bootstrap_servers,
    sales_topic,
)
from .state import StreamingSalesState

__all__ = [
    "KAFKA_BOOTSTRAP",
    "SALES_TOPIC",
    "kafka_bootstrap_servers",
    "sales_topic",
    "StreamingSalesState",
]
