"""Configuration de la couche streaming.

Les parametres sont lus dans l'environnement pour fonctionner aussi bien en
local que dans Docker, ou Kafka est joignable via le nom de service
`kafka:9092`.
"""

from __future__ import annotations

import os

KAFKA_BOOTSTRAP = "localhost:9092"
SALES_TOPIC = "dvf-sales"


def kafka_bootstrap_servers() -> str:
    """Adresse du broker Kafka (`UDE_KAFKA_BOOTSTRAP`, defaut localhost:9092)."""

    return os.environ.get("UDE_KAFKA_BOOTSTRAP", KAFKA_BOOTSTRAP).strip()


def sales_topic() -> str:
    """Nom du topic des ventes (`UDE_KAFKA_TOPIC`, defaut dvf-sales)."""

    return os.environ.get("UDE_KAFKA_TOPIC", SALES_TOPIC).strip()
