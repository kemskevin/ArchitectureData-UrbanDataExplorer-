"""Producteur Kafka : rejoue des transactions DVF comme un flux temps reel.

Chaque transaction est envoyee comme un message JSON dans le topic des ventes,
avec un petit delai configurable pour simuler une arrivee au fil de l'eau.

Usage local :
    UDE_KAFKA_BOOTSTRAP=localhost:9092 \
    python pipeline/jobs/streaming/sales_producer.py --rate 20 --limit 2000

Usage Docker :
    docker compose -f docker-compose.yml -f docker-compose.kafka.yml \
      run --rm sales-producer
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "pipeline" / "src"
for path in (ROOT, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import pandas as pd

from urban_data_explorer.streaming.config import kafka_bootstrap_servers, sales_topic
from urban_data_explorer.streaming.state import EVENT_COLUMNS


def _load_events(limit: int | None) -> pd.DataFrame:
    """Charge les transactions a rejouer.

    Reutilise les sources DVF preparees si disponibles, sinon genere un
    echantillon synthetique pour que la demo fonctionne sans donnees.
    """

    try:
        from urban_data_explorer.build import load_sales_transactions

        frame = load_sales_transactions()
    except Exception as error:  # noqa: BLE001 - demo resiliente
        print(f"[producer] sources DVF indisponibles ({error}); echantillon synthetique.")
        import numpy as np

        rng = np.random.default_rng(0)
        size = limit or 2000
        frame = pd.DataFrame(
            {
                "arrondissement": rng.integers(1, 21, size),
                "year": rng.choice([2024, 2025], size),
                "transaction_id": [f"t{index}" for index in range(size)],
                "price_per_m2": rng.uniform(3000, 20000, size),
                "sale_value_eur": rng.uniform(100000, 2000000, size),
                "built_surface_m2": rng.uniform(15, 200, size),
                "rooms": rng.integers(1, 6, size).astype(float),
                "Type local": rng.choice(["Appartement", "Maison"], size, p=[0.9, 0.1]),
            }
        )

    frame = frame[EVENT_COLUMNS].copy()
    if limit is not None:
        frame = frame.head(limit)
    return frame


def main() -> None:
    parser = argparse.ArgumentParser(description="Producteur de flux de ventes DVF")
    parser.add_argument("--rate", type=float, default=20.0, help="messages par seconde")
    parser.add_argument("--limit", type=int, default=2000, help="nombre de transactions a envoyer")
    args = parser.parse_args()

    from kafka import KafkaProducer

    bootstrap = kafka_bootstrap_servers()
    topic = sales_topic()
    print(f"[producer] broker={bootstrap} topic={topic} rate={args.rate}/s")

    producer = KafkaProducer(
        bootstrap_servers=bootstrap,
        value_serializer=lambda value: json.dumps(value).encode("utf-8"),
        key_serializer=lambda value: str(value).encode("utf-8"),
        acks="all",
        retries=3,
    )

    events = _load_events(args.limit)
    delay = 1.0 / args.rate if args.rate > 0 else 0.0
    sent = 0
    for record in events.to_dict(orient="records"):
        producer.send(topic, key=record["arrondissement"], value=record)
        sent += 1
        if sent % 100 == 0:
            print(f"[producer] {sent} transactions envoyees")
        if delay:
            time.sleep(delay)

    producer.flush()
    producer.close()
    print(f"[producer] termine : {sent} transactions envoyees dans `{topic}`")


if __name__ == "__main__":
    main()
