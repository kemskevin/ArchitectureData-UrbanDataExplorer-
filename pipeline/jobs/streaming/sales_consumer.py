"""Consommateur Kafka : traite le flux de ventes en temps reel.

Le consumer lit les transactions du topic, les accumule dans un etat, et
recalcule les agregats par arrondissement / annee a intervalle regulier (fenetre
de traitement). Les agregats temps reel sont ecrits dans une table MySQL dediee
`stream_sales_yearly`, distincte des tables batch, conformement a une
architecture Lambda (couche batch + couche streaming alimentant la couche de
service).

Usage local :
    UDE_KAFKA_BOOTSTRAP=localhost:9092 \
    python pipeline/jobs/streaming/sales_consumer.py --window 50

Usage Docker :
    docker compose -f docker-compose.yml -f docker-compose.kafka.yml \
      up -d sales-consumer
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "pipeline" / "src"
for path in (ROOT, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from urban_data_explorer.streaming.config import kafka_bootstrap_servers, sales_topic
from urban_data_explorer.streaming.state import StreamingSalesState

STREAM_TABLE = "stream_sales_yearly"


def _write_aggregates(frame) -> None:
    """Ecrit les agregats temps reel dans MySQL si la base est joignable.

    En l'absence de base (demo hors Docker), on se contente d'afficher le
    resultat, pour que le consumer reste demontrable seul.
    """

    if frame.empty:
        return
    try:
        from sqlalchemy import create_engine
        from common.database import get_database_url

        engine = create_engine(get_database_url(), pool_pre_ping=True)
        frame.to_sql(STREAM_TABLE, engine, if_exists="replace", index=False)
        print(f"[consumer] {len(frame)} groupes ecrits dans `{STREAM_TABLE}`")
    except Exception as error:  # noqa: BLE001 - demo resiliente sans base
        print(f"[consumer] MySQL indisponible ({error}); agregats affiches seulement :")
        print(frame.head(10).to_string(index=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="Consommateur du flux de ventes DVF")
    parser.add_argument(
        "--window",
        type=int,
        default=50,
        help="recalcule et publie les agregats tous les N messages",
    )
    parser.add_argument(
        "--max-messages",
        type=int,
        default=None,
        help="arrete apres N messages (utile pour une demo bornee)",
    )
    args = parser.parse_args()

    from kafka import KafkaConsumer

    bootstrap = kafka_bootstrap_servers()
    topic = sales_topic()
    print(f"[consumer] broker={bootstrap} topic={topic} window={args.window}")

    consumer = KafkaConsumer(
        topic,
        bootstrap_servers=bootstrap,
        value_deserializer=lambda raw: json.loads(raw.decode("utf-8")),
        auto_offset_reset="earliest",
        enable_auto_commit=True,
        group_id="ude-sales-consumer",
        consumer_timeout_ms=30000,
    )

    state = StreamingSalesState()
    processed = 0

    for message in consumer:
        if state.add_event(message.value):
            processed += 1

        if processed and processed % args.window == 0:
            aggregates = state.compute_aggregates()
            print(
                f"[consumer] fenetre @ {processed} transactions -> "
                f"{len(aggregates)} groupes recalcules"
            )
            _write_aggregates(aggregates)

        if args.max_messages and processed >= args.max_messages:
            break

    # Publication finale de la fenetre courante.
    final_aggregates = state.compute_aggregates()
    print(f"[consumer] arret : {processed} transactions traitees au total")
    _write_aggregates(final_aggregates)
    consumer.close()


if __name__ == "__main__":
    main()
