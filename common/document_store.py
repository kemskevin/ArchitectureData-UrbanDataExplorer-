from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
import os
from typing import Any
from urllib.parse import quote_plus

from pymongo import MongoClient
from pymongo.database import Database


GEOJSON_DATASETS = {
    "gold_geojson": "gold_arrondissements_geojson",
    "gold_quartiers_geojson": "gold_quartiers_geojson",
    "gold_streets_geojson": "gold_streets_geojson",
    "gold_iris_geojson": "gold_iris_geojson",
}

DOCUMENT_DATASETS = {
    "gold_dashboard": "gold_dashboard_metadata",
    "gold_spatial_coverage": "gold_sales_spatial_coverage",
}

BLOB_DATASETS = {**GEOJSON_DATASETS, **DOCUMENT_DATASETS}
DOCUMENT_COLLECTION_NAME = "gold_documents"


def get_mongo_url() -> str:
    explicit_url = os.getenv("MONGODB_URL") or os.getenv("MONGO_URL")
    if explicit_url:
        return explicit_url

    host = os.getenv("MONGO_HOST", "localhost")
    port = os.getenv("MONGO_PORT", "27017")
    username = os.getenv("MONGO_USER")
    password = os.getenv("MONGO_PASSWORD")
    auth_database = os.getenv("MONGO_AUTH_DATABASE", "admin")

    if username and password:
        return (
            f"mongodb://{quote_plus(username)}:{quote_plus(password)}@{host}:{port}/"
            f"?authSource={quote_plus(auth_database)}"
        )

    return f"mongodb://{host}:{port}/"


def get_mongo_database_name() -> str:
    return os.getenv("MONGO_DATABASE", "urban_data_explorer")


@lru_cache(maxsize=1)
def get_mongo_client() -> MongoClient:
    return MongoClient(get_mongo_url(), serverSelectionTimeoutMS=5000)


def get_mongo_database() -> Database:
    return get_mongo_client()[get_mongo_database_name()]


def ping_document_store() -> None:
    get_mongo_client().admin.command("ping")


def _is_geojson_dataset(dataset_name: str) -> bool:
    return dataset_name in GEOJSON_DATASETS


def blob_exists(dataset_name: str) -> bool:
    database = get_mongo_database()
    if _is_geojson_dataset(dataset_name):
        return database[GEOJSON_DATASETS[dataset_name]].find_one() is not None
    document_id = DOCUMENT_DATASETS[dataset_name]
    return database[DOCUMENT_COLLECTION_NAME].find_one({"_id": document_id}) is not None


def write_blob_dataset(dataset_name: str, payload: Any) -> str:
    if _is_geojson_dataset(dataset_name):
        return write_geojson_dataset(dataset_name, payload)
    return write_document_dataset(dataset_name, payload)


def read_blob_dataset(dataset_name: str) -> Any:
    if _is_geojson_dataset(dataset_name):
        return read_geojson_dataset(dataset_name)
    return read_document_dataset(dataset_name)


def write_geojson_dataset(dataset_name: str, payload: dict[str, Any]) -> str:
    collection_name = GEOJSON_DATASETS[dataset_name]
    features = payload.get("features", [])
    collection = get_mongo_database()[collection_name]
    collection.delete_many({})

    if features:
        collection.insert_many(
            [
                {
                    "feature_index": index,
                    "type": "Feature",
                    "geometry": feature["geometry"],
                    "properties": feature.get("properties", {}),
                    "updated_at": datetime.now(timezone.utc),
                }
                for index, feature in enumerate(features)
            ]
        )

    return collection_name


def read_geojson_dataset(dataset_name: str) -> dict[str, Any]:
    collection_name = GEOJSON_DATASETS[dataset_name]
    features = list(
        get_mongo_database()[collection_name]
        .find({}, {"_id": False, "feature_index": False, "updated_at": False})
        .sort("feature_index", 1)
    )
    return {"type": "FeatureCollection", "features": features}


def write_document_dataset(dataset_name: str, payload: Any) -> str:
    document_id = DOCUMENT_DATASETS[dataset_name]
    get_mongo_database()[DOCUMENT_COLLECTION_NAME].replace_one(
        {"_id": document_id},
        {
            "_id": document_id,
            "payload": payload,
            "updated_at": datetime.now(timezone.utc),
        },
        upsert=True,
    )
    return f"{DOCUMENT_COLLECTION_NAME}/{document_id}"


def read_document_dataset(dataset_name: str) -> Any:
    document_id = DOCUMENT_DATASETS[dataset_name]
    document = get_mongo_database()[DOCUMENT_COLLECTION_NAME].find_one({"_id": document_id})
    if document is None:
        raise KeyError(document_id)
    return document["payload"]
