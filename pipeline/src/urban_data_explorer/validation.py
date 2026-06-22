from __future__ import annotations

from collections.abc import Mapping, Sequence

from sqlalchemy import inspect

from common.database import TABULAR_DATASETS, get_engine, table_exists
from common.document_store import blob_exists, read_blob_dataset

from .build import metric_catalog


REQUIRED_TABLE_COLUMNS: dict[str, tuple[str, ...]] = {
    "gold_summary": (
        "arrondissement",
        "median_price_m2",
        "median_income_eur",
        "reference_rent_majorated_eur_m2",
        "social_units_financed",
        "quality_of_life_score",
    ),
    "gold_sales": (
        "arrondissement",
        "year",
        "transactions",
        "median_price_m2",
        "median_sale_value_eur",
        "median_surface_m2",
        "median_rooms",
        "apartment_share_pct",
        "house_share_pct",
    ),
    "gold_sales_quartier": ("quartier_id", "arrondissement", "year", "transactions", "median_price_m2"),
    "gold_sales_street": ("street_key", "arrondissement", "year", "transactions", "median_price_m2"),
    "gold_sales_building": ("building_id", "arrondissement", "year", "transactions", "median_price_m2"),
}

REQUIRED_BLOBS = (
    "gold_dashboard",
    "gold_spatial_coverage",
    "gold_geojson",
    "gold_quartiers_geojson",
    "gold_streets_geojson",
)

REQUIRED_DASHBOARD_KEYS = (
    "generated_at",
    "latest_sales_year",
    "available_sales_years",
    "metrics",
    "spatial_sales_coverage",
)

REQUIRED_COVERAGE_KEYS = (
    "input_rows",
    "input_transactions",
    "geocoded_rows",
    "quartier_rows",
    "iris_rows",
    "street_rows",
    "building_rows",
    "street_count",
    "building_count",
    "adresses_ban_rate_pct",
    "ban_plus_rate_pct",
    "geocoded_rate_pct",
    "quartier_rate_pct",
    "iris_rate_pct",
    "street_rate_pct",
    "building_rate_pct",
)


def missing_items(available: Sequence[str] | set[str], required: Sequence[str]) -> list[str]:
    available_set = set(available)
    return [item for item in required if item not in available_set]


def validate_mapping_keys(name: str, payload: Mapping[str, object], required: Sequence[str]) -> list[str]:
    missing = missing_items(set(payload.keys()), required)
    return [f"{name}: cle manquante `{key}`" for key in missing]


def validate_gold_outputs() -> list[str]:
    issues: list[str] = []
    inspector = inspect(get_engine())

    for dataset_name, required_columns in REQUIRED_TABLE_COLUMNS.items():
        table_name = TABULAR_DATASETS[dataset_name]
        if not table_exists(table_name):
            issues.append(f"{dataset_name}: table SQL `{table_name}` introuvable")
            continue

        columns = [column["name"] for column in inspector.get_columns(table_name)]
        for column in missing_items(columns, required_columns):
            issues.append(f"{dataset_name}: colonne manquante `{column}`")

    for dataset_name in REQUIRED_BLOBS:
        if not blob_exists(dataset_name):
            issues.append(f"{dataset_name}: document ou collection MongoDB introuvable")

    if not issues and blob_exists("gold_dashboard"):
        dashboard = read_blob_dataset("gold_dashboard")
        if not isinstance(dashboard, Mapping):
            issues.append("gold_dashboard: payload invalide")
        else:
            issues.extend(validate_mapping_keys("gold_dashboard", dashboard, REQUIRED_DASHBOARD_KEYS))
            metrics = dashboard.get("metrics", {})
            if not isinstance(metrics, Mapping):
                issues.append("gold_dashboard: catalogue de metriques invalide")
            else:
                for metric in metric_catalog():
                    if metric not in metrics:
                        issues.append(f"gold_dashboard: metrique manquante `{metric}`")

    if not issues and blob_exists("gold_spatial_coverage"):
        coverage = read_blob_dataset("gold_spatial_coverage")
        if not isinstance(coverage, Mapping):
            issues.append("gold_spatial_coverage: payload invalide")
        else:
            issues.extend(validate_mapping_keys("gold_spatial_coverage", coverage, REQUIRED_COVERAGE_KEYS))

    return issues
