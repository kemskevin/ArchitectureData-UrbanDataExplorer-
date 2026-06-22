"""Etat de la couche streaming.

`StreamingSalesState` accumule les transactions recues en flux et recalcule les
agregats par arrondissement / annee a la demande, en reutilisant exactement la
meme fonction que la couche batch (`aggregate_sales_metrics`).

Pourquoi un etat plutot qu'un calcul purement incremental : les indicateurs
incluent des medianes (prix/m2, surface, etc.), qui ne sont pas mises a jour de
facon incrementale sans conserver l'historique des valeurs. On conserve donc les
transactions recues et on recalcule l'agregat sur la fenetre courante. Cela
garantit que la couche streaming et la couche batch produisent des resultats
strictement coherents.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

GROUP_COLUMNS = ["arrondissement", "year"]

# Colonnes minimales d'un evenement de vente attendu dans le flux.
EVENT_COLUMNS = [
    "arrondissement",
    "year",
    "transaction_id",
    "price_per_m2",
    "sale_value_eur",
    "built_surface_m2",
    "rooms",
    "Type local",
]


class StreamingSalesState:
    """Accumulateur de transactions et calculateur d'agregats de fenetre."""

    def __init__(self) -> None:
        self._events: list[dict[str, Any]] = []
        self._seen_ids: set[str] = set()

    @property
    def event_count(self) -> int:
        return len(self._events)

    def add_event(self, event: dict[str, Any]) -> bool:
        """Ajoute un evenement au flux.

        Retourne `True` si l'evenement est nouveau, `False` s'il est ignore
        (doublon de `transaction_id` ou payload incomplet). La deduplication
        reproduit le `nunique` de la couche batch.
        """

        if any(column not in event for column in EVENT_COLUMNS):
            return False

        transaction_id = str(event["transaction_id"])
        if transaction_id in self._seen_ids:
            return False

        self._seen_ids.add(transaction_id)
        self._events.append({column: event[column] for column in EVENT_COLUMNS})
        return True

    def to_frame(self) -> pd.DataFrame:
        if not self._events:
            return pd.DataFrame(columns=EVENT_COLUMNS)
        return pd.DataFrame(self._events)

    def compute_aggregates(self) -> pd.DataFrame:
        """Recalcule les agregats sur la fenetre courante via la logique batch."""

        from urban_data_explorer.build import aggregate_sales_metrics

        return aggregate_sales_metrics(self.to_frame(), GROUP_COLUMNS, engine="pandas")
