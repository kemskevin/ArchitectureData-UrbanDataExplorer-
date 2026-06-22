from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import re
import tempfile
import unicodedata
import zipfile

import pandas as pd
from pyproj import Transformer
import requests
import shapefile
from shapely.geometry import MultiLineString, Point, mapping, shape
from shapely.ops import transform as shapely_transform
from shapely.prepared import prep
from shapely.strtree import STRtree

from common.database import write_table_dataset
from common.document_store import write_blob_dataset

from .paths import repo_path


BAN_PLUS_WFS_URL = "https://data.geopf.fr/wfs/ows"
BAN_PLUS_CACHE_PATH = repo_path("data/bronze/reference/ban-plus-lien-adresse-parcelle.csv")
QUALITY_OF_LIFE_WEIGHTS = {
    "noise_norm": 0.30,
    "air_norm": 0.30,
    "high_noise_norm": 0.25,
    "env_norm": 0.15,
}
NEUTRAL_ENVIRONMENT_DEFAULTS = {
    "noise_score": 2.0,
    "air_score": 2.0,
    "high_noise_share_pct": 50.0,
}


def build_gold(include_noise: bool = True) -> dict[str, str]:
    arr_reference = load_arrondissement_reference()
    quartier_reference = load_quartier_reference()
    street_reference = load_street_reference(arr_reference["geojson"])
    iris_reference = load_iris_reference()
    sales_transactions = load_sales_transactions()
    sales_yearly = build_sales_metrics(sales_transactions)
    spatial_sales = build_sales_spatial_outputs(sales_transactions, quartier_reference, iris_reference)
    income = build_income_metrics()
    rents_yearly = build_rent_metrics()
    social_yearly = build_social_metrics()
    noise = build_noise_metrics(arr_reference["geojson"]) if include_noise else build_empty_noise_metrics()
    sales_quartier_yearly = spatial_sales["sales_quartier_yearly"]
    sales_iris_yearly = spatial_sales["sales_iris_yearly"]
    sales_geocoded = spatial_sales["sales_geocoded"]
    sales_street_yearly = spatial_sales["sales_street_yearly"]
    sales_building_yearly = spatial_sales["sales_building_yearly"]
    spatial_coverage = spatial_sales["coverage"]

    latest_sales_year = int(sales_yearly["year"].max())
    latest_rent_year = int(rents_yearly["year"].max())
    latest_social_year = int(social_yearly["year"].max())

    sales_latest = sales_yearly.loc[sales_yearly["year"] == latest_sales_year].copy()
    rents_latest = rents_yearly.loc[rents_yearly["year"] == latest_rent_year].copy()
    social_latest = social_yearly.loc[social_yearly["year"] == latest_social_year].copy()
    social_5y = (
        social_yearly.loc[social_yearly["year"] >= latest_social_year - 4]
        .groupby("arrondissement", as_index=False)["social_units_financed"]
        .sum()
        .rename(columns={"social_units_financed": "social_units_financed_5y"})
    )

    summary = arr_reference["table"].merge(sales_latest, on="arrondissement", how="left")
    summary = summary.merge(income, on="arrondissement", how="left")
    summary = summary.merge(rents_latest, on="arrondissement", how="left", suffixes=("", "_rent"))
    summary = summary.merge(social_latest, on="arrondissement", how="left", suffixes=("", "_social"))
    summary = summary.merge(social_5y, on="arrondissement", how="left")
    summary = summary.merge(noise, on="arrondissement", how="left")

    summary["social_units_financed"] = summary["social_units_financed"].fillna(0)
    summary["social_units_financed_5y"] = summary["social_units_financed_5y"].fillna(0)
    summary["program_count"] = summary["program_count"].fillna(0)
    summary["reference_rent_eur_m2"] = summary["reference_rent_eur_m2"].fillna(summary["reference_rent_eur_m2"].median())
    summary["reference_rent_majorated_eur_m2"] = summary["reference_rent_majorated_eur_m2"].fillna(summary["reference_rent_majorated_eur_m2"].median())
    summary["reference_rent_minorated_eur_m2"] = summary["reference_rent_minorated_eur_m2"].fillna(summary["reference_rent_minorated_eur_m2"].median())
    summary["noise_score"] = fill_with_median_or_default(summary["noise_score"], NEUTRAL_ENVIRONMENT_DEFAULTS["noise_score"])
    summary["air_score"] = fill_with_median_or_default(summary["air_score"], NEUTRAL_ENVIRONMENT_DEFAULTS["air_score"])
    summary["high_noise_share_pct"] = fill_with_median_or_default(summary["high_noise_share_pct"], NEUTRAL_ENVIRONMENT_DEFAULTS["high_noise_share_pct"])

    for column in ["median_income_eur", "poverty_rate_pct", "first_quartile_income_eur", "third_quartile_income_eur", "share_taxable_pct"]:
        summary[column] = summary[column].fillna(summary[column].median())

    summary["months_income_for_1sqm"] = (
        summary["median_price_m2"] / (summary["median_income_eur"] / 12.0)
    ).round(2)
    summary["estimated_50m2_rent_effort_pct"] = (
        summary["reference_rent_majorated_eur_m2"] * 50 / (summary["median_income_eur"] / 12.0) * 100.0
    ).round(1)
    transaction_base = summary["transactions"].where(summary["transactions"] != 0)
    summary["social_units_per_100_sales"] = (
        summary["social_units_financed"] / transaction_base * 100.0
    ).fillna(0).round(1)
    summary["environmental_pressure_index"] = (
        ((summary["noise_score"] - 1.0) / 2.0) * 60.0
        + ((summary["air_score"] - 1.0) / 2.0) * 40.0
    ).clip(lower=0.0, upper=100.0).round(1)
    summary["quality_of_life_score"] = compute_quality_of_life_score(summary)

    summary["sales_year"] = latest_sales_year
    summary["rent_year"] = latest_rent_year
    summary["social_year"] = latest_social_year

    dashboard_payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "latest_sales_year": latest_sales_year,
        "latest_social_year": latest_social_year,
        "latest_rent_year": latest_rent_year,
        "available_sales_years": sorted(sales_yearly["year"].unique().tolist()),
        "available_social_years": sorted(social_yearly["year"].unique().tolist()),
        "available_rent_years": sorted(rents_yearly["year"].unique().tolist()),
        "city_summary": build_city_summary(summary),
        "arrondissements": json.loads(summary.to_json(orient="records")),
        "spatial_sales_coverage": spatial_coverage,
        "metrics": metric_catalog(),
    }

    return persist_outputs_to_storage(
        sales_yearly=sales_yearly,
        sales_quartier_yearly=sales_quartier_yearly,
        sales_iris_yearly=sales_iris_yearly,
        sales_geocoded=sales_geocoded,
        sales_street_yearly=sales_street_yearly,
        sales_building_yearly=sales_building_yearly,
        income=income,
        rents_yearly=rents_yearly,
        social_yearly=social_yearly,
        noise=noise,
        summary=summary,
        arrondissement_geojson=arr_reference["geojson"],
        quartier_geojson=quartier_reference["geojson"],
        street_geojson=street_reference["geojson"],
        iris_geojson=iris_reference["geojson"],
        spatial_coverage=spatial_coverage,
        dashboard_payload=dashboard_payload,
    )


def persist_outputs_to_storage(
    *,
    sales_yearly: pd.DataFrame,
    sales_quartier_yearly: pd.DataFrame,
    sales_iris_yearly: pd.DataFrame,
    sales_geocoded: pd.DataFrame,
    sales_street_yearly: pd.DataFrame,
    sales_building_yearly: pd.DataFrame,
    income: pd.DataFrame,
    rents_yearly: pd.DataFrame,
    social_yearly: pd.DataFrame,
    noise: pd.DataFrame,
    summary: pd.DataFrame,
    arrondissement_geojson: dict[str, object],
    quartier_geojson: dict[str, object],
    street_geojson: dict[str, object],
    iris_geojson: dict[str, object],
    spatial_coverage: dict[str, object],
    dashboard_payload: dict[str, object],
) -> dict[str, str]:
    return {
        "silver_sales": write_table_dataset("silver_sales", sales_yearly),
        "silver_sales_quartier": write_table_dataset("silver_sales_quartier", sales_quartier_yearly),
        "silver_sales_iris": write_table_dataset("silver_sales_iris", sales_iris_yearly),
        "silver_sales_geocoded": write_table_dataset("silver_sales_geocoded", sales_geocoded),
        "silver_sales_street": write_table_dataset("silver_sales_street", sales_street_yearly),
        "silver_sales_building": write_table_dataset("silver_sales_building", sales_building_yearly),
        "silver_income": write_table_dataset("silver_income", income),
        "silver_rents": write_table_dataset("silver_rents", rents_yearly),
        "silver_social": write_table_dataset("silver_social", social_yearly),
        "silver_noise": write_table_dataset("silver_noise", noise),
        "gold_summary": write_table_dataset("gold_summary", summary),
        "gold_sales": write_table_dataset("gold_sales", sales_yearly),
        "gold_sales_quartier": write_table_dataset("gold_sales_quartier", sales_quartier_yearly),
        "gold_sales_iris": write_table_dataset("gold_sales_iris", sales_iris_yearly),
        "gold_sales_geocoded": write_table_dataset("gold_sales_geocoded", sales_geocoded),
        "gold_sales_street": write_table_dataset("gold_sales_street", sales_street_yearly),
        "gold_sales_building": write_table_dataset("gold_sales_building", sales_building_yearly),
        "gold_social": write_table_dataset("gold_social", social_yearly),
        "gold_rents": write_table_dataset("gold_rents", rents_yearly),
        "gold_income": write_table_dataset("gold_income", income),
        "gold_noise": write_table_dataset("gold_noise", noise),
        "gold_geojson": write_blob_dataset("gold_geojson", arrondissement_geojson),
        "gold_quartiers_geojson": write_blob_dataset("gold_quartiers_geojson", quartier_geojson),
        "gold_streets_geojson": write_blob_dataset("gold_streets_geojson", street_geojson),
        "gold_iris_geojson": write_blob_dataset("gold_iris_geojson", iris_geojson),
        "gold_spatial_coverage": write_blob_dataset("gold_spatial_coverage", spatial_coverage),
        "gold_dashboard": write_blob_dataset("gold_dashboard", dashboard_payload),
    }


def load_arrondissement_reference() -> dict[str, object]:
    path = repo_path("data/bronze/reference/arrondissements.geojson")
    payload = json.loads(path.read_text(encoding="utf-8"))

    features = []
    rows = []
    for feature in sorted(payload["features"], key=lambda item: item["properties"]["c_ar"]):
        props = feature["properties"]
        arrondissement = int(props["c_ar"])
        features.append(
            {
                "type": "Feature",
                "geometry": feature["geometry"],
                "properties": {
                    "arrondissement": arrondissement,
                    "insee_code": int(props["c_arinsee"]),
                    "name": props["l_aroff"],
                    "label": props["l_ar"],
                    "surface_m2": round(float(props["surface"]), 2),
                    "perimeter_m": round(float(props["perimetre"]), 2),
                },
            }
        )
        rows.append(
            {
                "arrondissement": arrondissement,
                "name": props["l_aroff"],
                "label": props["l_ar"],
                "insee_code": int(props["c_arinsee"]),
                "postal_code": f"75{arrondissement:03d}",
                "surface_m2": round(float(props["surface"]), 2),
            }
        )

    return {
        "table": pd.DataFrame(rows),
        "geojson": {"type": "FeatureCollection", "features": features},
    }


def load_quartier_reference() -> dict[str, object]:
    path = repo_path("data/bronze/reference/quartier_paris.geojson")
    payload = json.loads(path.read_text(encoding="utf-8"))

    features = []
    rows = []
    for feature in sorted(payload["features"], key=lambda item: int(item["properties"]["c_quinsee"])):
        props = feature["properties"]
        quartier_id = str(props["c_quinsee"])
        standardized_props = {
            "quartier_id": quartier_id,
            "quartier_code": int(props["c_qu"]),
            "arrondissement": int(props["c_ar"]),
            "name": props["l_qu"],
            "surface_m2": round(float(props["surface"]), 2),
            "perimeter_m": round(float(props["perimetre"]), 2),
        }
        features.append(
            {
                "type": "Feature",
                "geometry": feature["geometry"],
                "properties": standardized_props,
            }
        )
        rows.append(standardized_props)

    return {
        "table": pd.DataFrame(rows),
        "geojson": {"type": "FeatureCollection", "features": features},
    }


def load_street_reference(arr_geojson: dict[str, object]) -> dict[str, object]:
    path = repo_path("data/bronze/reference/voie-paris.geojson")
    payload = json.loads(path.read_text(encoding="utf-8"))

    arrondissement_geometries = []
    for feature in arr_geojson["features"]:
        props = feature["properties"]
        arrondissement_geometries.append(
            {
                "arrondissement": int(props["arrondissement"]),
                "commune_insee": str(props["insee_code"]),
                "geometry": shape(feature["geometry"]),
            }
        )

    features = []
    rows = []
    for feature in payload["features"]:
        props = feature["properties"]
        raw_name = " ".join(
            part
            for part in [
                str(props.get("c_desi") or "").strip(),
                str(props.get("c_liaison") or "").strip(),
                str(props.get("l_voie") or "").strip(),
            ]
            if part
        )
        street_name = normalize_street_name(raw_name)
        if not street_name:
            continue

        geometry = shape(feature["geometry"])
        if geometry.is_empty:
            continue

        street_ref_id = str(props.get("n_sq_vo") or props.get("c_voie_vp") or props.get("c_voie") or props.get("objectid"))
        display_name = str(props.get("l_longmin") or raw_name).strip() or street_name

        for arrondissement in arrondissement_geometries:
            if not geometry.intersects(arrondissement["geometry"]):
                continue
            clipped_geometry = lineal_intersection(geometry, arrondissement["geometry"])
            if clipped_geometry is None or clipped_geometry.is_empty:
                continue

            street_key = f"{arrondissement['commune_insee']}|{street_name}"
            feature_props = {
                "street_ref_id": street_ref_id,
                "street_key": street_key,
                "street_name": street_name,
                "display_name": display_name,
                "arrondissement": arrondissement["arrondissement"],
                "commune_insee": arrondissement["commune_insee"],
            }
            features.append(
                {
                    "type": "Feature",
                    "geometry": mapping(clipped_geometry),
                    "properties": feature_props,
                }
            )
            rows.append(feature_props)

    return {
        "table": pd.DataFrame(rows),
        "geojson": {"type": "FeatureCollection", "features": features},
    }


def load_iris_reference() -> dict[str, object]:
    path = repo_path("data/bronze/reference/iris-paris.csv")
    data = pd.read_csv(path, sep=";", dtype=str, low_memory=False)
    data = data.loc[data["DEP"].eq("75")].copy()

    features = []
    rows = []
    for record in data.to_dict(orient="records"):
        iris_code = str(record["CODE_IRIS"])
        arrondissement = pd.to_numeric(iris_code[3:5], errors="coerce")
        standardized_props = {
            "iris_code": iris_code,
            "iris_name": record["NOM_IRIS"],
            "iris_type": record["TYP_IRIS"],
            "arrondissement": int(arrondissement) if pd.notna(arrondissement) else None,
            "commune_insee": str(record["INSEE_COM"]),
        }
        features.append(
            {
                "type": "Feature",
                "geometry": json.loads(record["Geo Shape"]),
                "properties": standardized_props,
            }
        )
        rows.append(standardized_props)

    return {
        "table": pd.DataFrame(rows),
        "geojson": {"type": "FeatureCollection", "features": features},
    }


def load_sales_transactions() -> pd.DataFrame:
    dvf_dir = repo_path("data/bronze/raw/dvf")
    files = sorted(dvf_dir.glob("valeursfoncieres-*-paris.csv"))
    if not files:
        raise FileNotFoundError("Aucun fichier DVF Paris n'a ete trouve dans data/bronze/raw/dvf.")

    frames = []
    usecols = [
        "Date mutation",
        "Nature mutation",
        "Valeur fonciere",
        "No voie",
        "B/T/Q",
        "Type de voie",
        "Voie",
        "Code postal",
        "Code departement",
        "Code commune",
        "Prefixe de section",
        "Section",
        "No plan",
        "Reference document",
        "Identifiant de document",
        "Type local",
        "Surface reelle bati",
        "Nombre pieces principales",
    ]

    for path in files:
        match = re.search(r"(20\d{2})", path.name)
        if not match:
            continue
        year = int(match.group(1))
        frame = pd.read_csv(path, usecols=usecols, dtype=str, low_memory=False)
        frame["year"] = year
        frames.append(frame)

    data = pd.concat(frames, ignore_index=True)
    data = data.loc[data["Nature mutation"] == "Vente"].copy()
    data["arrondissement"] = data["Code postal"].map(postal_code_to_arrondissement)
    data["sale_value_eur"] = french_to_float(data["Valeur fonciere"])
    data["built_surface_m2"] = french_to_float(data["Surface reelle bati"])
    data["rooms"] = french_to_float(data["Nombre pieces principales"])
    data = data.loc[data["arrondissement"].between(1, 20)]
    data = data.loc[data["Type local"].isin(["Appartement", "Maison"])]
    data = data.loc[data["built_surface_m2"].gt(10) & data["sale_value_eur"].gt(10000)].copy()
    data["price_per_m2"] = data["sale_value_eur"] / data["built_surface_m2"]
    data = data.loc[data["price_per_m2"].between(1000, 50000)].reset_index(drop=True)

    dep_digits = data["Code departement"].map(extract_digits).fillna("")
    commune_digits = data["Code commune"].map(extract_digits).fillna("").str.zfill(3)
    prefix_digits = data["Prefixe de section"].map(extract_digits).fillna("")
    section_codes = (
        data["Section"].fillna("").astype(str).str.upper().str.replace(" ", "", regex=False)
    )
    plan_digits = data["No plan"].map(extract_digits).fillna("")

    data["commune_insee"] = dep_digits + commune_digits
    data["house_number"] = data["No voie"].map(normalize_house_number)
    data["house_suffix"] = data["B/T/Q"].map(normalize_house_suffix)
    data["street_name"] = (
        data["Type de voie"].fillna("").astype(str).str.cat(data["Voie"].fillna("").astype(str), sep=" ")
    ).map(normalize_street_name)
    data["address_key"] = (
        data["commune_insee"].fillna("")
        + "|"
        + data["house_number"].fillna("")
        + "|"
        + data["house_suffix"].fillna("")
        + "|"
        + data["street_name"].fillna("")
    )
    data["address_key_no_suffix"] = (
        data["commune_insee"].fillna("")
        + "|"
        + data["house_number"].fillna("")
        + "|"
        + data["street_name"].fillna("")
    )

    parcel_prefix = prefix_digits.where(prefix_digits.ne(""), "000").str.zfill(3)
    data["parcel_id"] = dep_digits + commune_digits + parcel_prefix + section_codes + plan_digits.str.zfill(4)
    invalid_parcel = dep_digits.eq("") | commune_digits.eq("") | section_codes.eq("") | plan_digits.eq("")
    data.loc[invalid_parcel, "parcel_id"] = pd.NA
    data["transaction_id"] = (
        data["Date mutation"].fillna("").astype(str)
        + "|"
        + data["Valeur fonciere"].fillna("").astype(str)
        + "|"
        + data["parcel_id"].fillna("").astype(str)
        + "|"
        + data["house_number"].fillna("").astype(str)
        + "|"
        + data["street_name"].fillna("").astype(str)
        + "|"
        + data["Type local"].fillna("").astype(str)
        + "|"
        + data["Surface reelle bati"].fillna("").astype(str)
    )
    return data


def build_sales_metrics(transactions: pd.DataFrame | None = None) -> pd.DataFrame:
    data = load_sales_transactions() if transactions is None else transactions.copy()
    return aggregate_sales_metrics(data, ["arrondissement", "year"])


def build_sales_spatial_outputs(
    transactions: pd.DataFrame,
    quartier_reference: dict[str, object],
    iris_reference: dict[str, object],
) -> dict[str, object]:
    geocoded = geocode_sales_transactions(transactions, quartier_reference, iris_reference)
    geocoded = enrich_sales_micro_geography_keys(geocoded)

    sales_quartier_yearly = aggregate_sales_metrics(
        geocoded.loc[geocoded["quartier_id"].notna()].copy(),
        ["quartier_id", "quartier_name", "arrondissement", "year"],
    )

    iris_sales = geocoded.loc[geocoded["iris_code"].notna()].copy()
    sales_iris_yearly = aggregate_sales_metrics(
        iris_sales,
        ["iris_code", "iris_name", "iris_type", "arrondissement", "year"],
    )
    sales_street_yearly = build_street_sales_metrics(geocoded)
    sales_building_yearly = build_building_sales_metrics(geocoded)

    input_rows = int(len(geocoded))
    denominator = input_rows or 1
    adresses_ban_rows = int(geocoded["geocode_source"].eq("adresses-ban").sum())
    ban_plus_rows = int(geocoded["geocode_source"].eq("ban-plus").sum())
    geocoded_rows = int(geocoded["longitude"].notna().sum())
    quartier_rows = int(geocoded["quartier_id"].notna().sum())
    iris_rows = int(geocoded["iris_code"].notna().sum())
    street_rows = int(geocoded["street_key"].notna().sum())
    building_rows = int(geocoded["building_id"].notna().sum())
    coverage = {
        "input_rows": input_rows,
        "input_transactions": int(geocoded["transaction_id"].nunique()),
        "adresses_ban_rows": adresses_ban_rows,
        "ban_plus_rows": ban_plus_rows,
        "geocoded_rows": geocoded_rows,
        "quartier_rows": quartier_rows,
        "iris_rows": iris_rows,
        "street_rows": street_rows,
        "building_rows": building_rows,
        "street_count": int(sales_street_yearly["street_key"].nunique()) if not sales_street_yearly.empty else 0,
        "street_year_rows": int(len(sales_street_yearly)),
        "building_count": int(sales_building_yearly["building_id"].nunique()) if not sales_building_yearly.empty else 0,
        "building_year_rows": int(len(sales_building_yearly)),
        "adresses_ban_rate_pct": round(adresses_ban_rows / denominator * 100.0, 2),
        "ban_plus_rate_pct": round(ban_plus_rows / denominator * 100.0, 2),
        "geocoded_rate_pct": round(geocoded_rows / denominator * 100.0, 2),
        "quartier_rate_pct": round(quartier_rows / denominator * 100.0, 2),
        "iris_rate_pct": round(iris_rows / denominator * 100.0, 2),
        "street_rate_pct": round(street_rows / denominator * 100.0, 2),
        "building_rate_pct": round(building_rows / denominator * 100.0, 2),
    }

    geocoded_columns = [
        "year",
        "Date mutation",
        "Reference document",
        "Identifiant de document",
        "arrondissement",
        "commune_insee",
        "house_number",
        "house_suffix",
        "street_key",
        "street_name",
        "sale_value_eur",
        "built_surface_m2",
        "price_per_m2",
        "Type local",
        "parcel_id",
        "building_id",
        "building_id_source",
        "building_label",
        "matched_cle_interop",
        "geocode_source",
        "longitude",
        "latitude",
        "quartier_id",
        "quartier_name",
        "iris_code",
        "iris_name",
        "iris_type",
    ]
    return {
        "sales_geocoded": geocoded[[column for column in geocoded_columns if column in geocoded.columns]].copy(),
        "sales_quartier_yearly": sales_quartier_yearly,
        "sales_iris_yearly": sales_iris_yearly,
        "sales_street_yearly": sales_street_yearly,
        "sales_building_yearly": sales_building_yearly,
        "coverage": coverage,
    }


def geocode_sales_transactions(
    transactions: pd.DataFrame,
    quartier_reference: dict[str, object],
    iris_reference: dict[str, object],
) -> pd.DataFrame:
    geocoded = transactions.copy()
    ban_reference = load_ban_addresses_reference()

    with_suffix = ban_reference["with_suffix"]
    without_suffix = ban_reference["without_suffix"]
    by_interop = ban_reference["by_interop"]

    geocoded["matched_cle_interop"] = geocoded["address_key"].map(with_suffix["cle_interop"].to_dict())
    geocoded["longitude"] = geocoded["address_key"].map(with_suffix["long"].to_dict())
    geocoded["latitude"] = geocoded["address_key"].map(with_suffix["lat"].to_dict())
    geocoded["geocode_source"] = geocoded["matched_cle_interop"].notna().map(
        lambda matched: "adresses-ban" if matched else pd.NA
    )

    missing_mask = geocoded["longitude"].isna()
    if missing_mask.any():
        geocoded.loc[missing_mask, "matched_cle_interop"] = geocoded.loc[missing_mask, "address_key_no_suffix"].map(
            without_suffix["cle_interop"].to_dict()
        )
        geocoded.loc[missing_mask, "longitude"] = geocoded.loc[missing_mask, "address_key_no_suffix"].map(
            without_suffix["long"].to_dict()
        )
        geocoded.loc[missing_mask, "latitude"] = geocoded.loc[missing_mask, "address_key_no_suffix"].map(
            without_suffix["lat"].to_dict()
        )
        geocoded.loc[missing_mask & geocoded["matched_cle_interop"].notna(), "geocode_source"] = "adresses-ban"

    missing_mask = geocoded["longitude"].isna() & geocoded["parcel_id"].notna()
    if missing_mask.any():
        ban_plus_links = fetch_ban_plus_links(geocoded.loc[missing_mask, "parcel_id"].dropna().unique().tolist())
        if not ban_plus_links.empty:
            interop_by_parcel = ban_plus_links.set_index("idu")["id_adr"].to_dict()
            geocoded.loc[missing_mask, "matched_cle_interop"] = geocoded.loc[missing_mask, "parcel_id"].map(
                interop_by_parcel
            )
            geocoded.loc[missing_mask, "longitude"] = geocoded.loc[missing_mask, "matched_cle_interop"].map(
                by_interop["long"].to_dict()
            )
            geocoded.loc[missing_mask, "latitude"] = geocoded.loc[missing_mask, "matched_cle_interop"].map(
                by_interop["lat"].to_dict()
            )
            geocoded.loc[missing_mask & geocoded["longitude"].notna(), "geocode_source"] = "ban-plus"

    geocoded = join_points_to_reference(
        geocoded,
        quartier_reference["geojson"],
        lon_col="longitude",
        lat_col="latitude",
        property_mapping={
            "quartier_id": "quartier_id",
            "name": "quartier_name",
        },
    )
    geocoded = join_points_to_reference(
        geocoded,
        iris_reference["geojson"],
        lon_col="longitude",
        lat_col="latitude",
        property_mapping={
            "iris_code": "iris_code",
            "iris_name": "iris_name",
            "iris_type": "iris_type",
            "arrondissement": "iris_arrondissement",
        },
    )
    return geocoded


def load_ban_addresses_reference() -> dict[str, pd.DataFrame]:
    path = repo_path("data/bronze/reference/adresses-ban.csv")
    data = pd.read_csv(
        path,
        sep=";",
        encoding="utf-8-sig",
        dtype=str,
        usecols=[
            "cle_interop",
            "commune_insee",
            "voie_nom",
            "numero",
            "suffixe",
            "long",
            "lat",
            "certification_commune",
        ],
        low_memory=False,
    )
    data = data.loc[data["commune_insee"].str.startswith("751", na=False)].copy()
    data["street_name"] = data["voie_nom"].map(normalize_street_name)
    data["house_number"] = data["numero"].map(normalize_house_number)
    data["house_suffix"] = data["suffixe"].map(normalize_house_suffix)
    data["long"] = pd.to_numeric(data["long"], errors="coerce")
    data["lat"] = pd.to_numeric(data["lat"], errors="coerce")
    data["certification_commune"] = pd.to_numeric(data["certification_commune"], errors="coerce").fillna(0)
    data = data.loc[data["long"].notna() & data["lat"].notna()].copy()
    data["address_key"] = (
        data["commune_insee"].fillna("")
        + "|"
        + data["house_number"].fillna("")
        + "|"
        + data["house_suffix"].fillna("")
        + "|"
        + data["street_name"].fillna("")
    )
    data["address_key_no_suffix"] = (
        data["commune_insee"].fillna("")
        + "|"
        + data["house_number"].fillna("")
        + "|"
        + data["street_name"].fillna("")
    )
    data = data.sort_values(["certification_commune", "cle_interop"], ascending=[False, True]).reset_index(drop=True)
    return {
        "with_suffix": dedupe_ban_reference(data, "address_key"),
        "without_suffix": dedupe_ban_reference(data, "address_key_no_suffix"),
        "by_interop": dedupe_ban_reference(data, "cle_interop"),
    }


def dedupe_ban_reference(data: pd.DataFrame, key_column: str) -> pd.DataFrame:
    result = (
        data.groupby(key_column, as_index=False)
        .agg(
            cle_interop=("cle_interop", "first"),
            long=("long", "median"),
            lat=("lat", "median"),
        )
        .rename(columns={key_column: "lookup_key"})
    )
    return result.set_index("lookup_key")


def fetch_ban_plus_links(parcel_ids: list[str]) -> pd.DataFrame:
    cache_columns = ["idu", "id_adr", "type_lien", "nb_adr", "nb_parc"]
    if BAN_PLUS_CACHE_PATH.exists():
        cache = pd.read_csv(BAN_PLUS_CACHE_PATH, dtype=str)
    else:
        cache = pd.DataFrame(columns=cache_columns)

    known_ids = set(cache.get("idu", pd.Series(dtype=str)).dropna().tolist())
    missing_ids = sorted({parcel_id for parcel_id in parcel_ids if parcel_id} - known_ids)
    rows = []

    session = requests.Session()
    for batch in iter_chunks(missing_ids, 50):
        filter_values = "','".join(batch)
        response = session.get(
            BAN_PLUS_WFS_URL,
            params={
                "SERVICE": "WFS",
                "VERSION": "2.0.0",
                "REQUEST": "GetFeature",
                "TYPENAMES": "BAN-PLUS:lien_adresse_parcelle",
                "OUTPUTFORMAT": "application/json",
                "CQL_FILTER": f"idu IN ('{filter_values}')",
            },
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        batch_rows = []
        for feature in payload.get("features", []):
            props = feature.get("properties", {})
            batch_rows.append(
                {
                    "idu": props.get("idu"),
                    "id_adr": props.get("id_adr"),
                    "type_lien": props.get("type_lien"),
                    "nb_adr": props.get("nb_adr"),
                    "nb_parc": props.get("nb_parc"),
                }
            )
        rows.extend(batch_rows)
        returned_ids = {row["idu"] for row in batch_rows if row.get("idu")}
        for parcel_id in batch:
            if parcel_id not in returned_ids:
                rows.append({"idu": parcel_id, "id_adr": "", "type_lien": "", "nb_adr": "", "nb_parc": ""})

    if rows:
        cache = pd.concat([cache, pd.DataFrame(rows, columns=cache_columns)], ignore_index=True)
        cache = cache.drop_duplicates(subset=["idu", "id_adr", "type_lien"], keep="last")
        BAN_PLUS_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        cache.to_csv(BAN_PLUS_CACHE_PATH, index=False)

    valid = cache.loc[cache["id_adr"].notna() & cache["id_adr"].ne("")].copy()
    if valid.empty:
        return valid

    link_priority = {"GEO": 0, "BAN": 1}
    valid["priority"] = valid["type_lien"].map(link_priority).fillna(9)
    valid["nb_adr_num"] = pd.to_numeric(valid["nb_adr"], errors="coerce").fillna(999999)
    valid = valid.sort_values(["idu", "priority", "nb_adr_num", "id_adr"])
    valid = valid.groupby("idu", as_index=False).first()
    return valid[["idu", "id_adr", "type_lien"]]


def join_points_to_reference(
    data: pd.DataFrame,
    reference_geojson: dict[str, object],
    lon_col: str,
    lat_col: str,
    property_mapping: dict[str, str],
) -> pd.DataFrame:
    if data.empty:
        for output_column in property_mapping.values():
            data[output_column] = pd.NA
        return data

    result = data.copy()
    geometries = [shape(feature["geometry"]) for feature in reference_geojson["features"]]
    tree = STRtree(geometries)
    output_values = {output_column: [pd.NA] * len(result) for output_column in property_mapping.values()}

    for index, (lon, lat) in enumerate(result[[lon_col, lat_col]].itertuples(index=False, name=None)):
        if pd.isna(lon) or pd.isna(lat):
            continue
        point = Point(float(lon), float(lat))
        for candidate_index in tree.query(point):
            geometry = geometries[int(candidate_index)]
            if geometry.covers(point):
                props = reference_geojson["features"][int(candidate_index)]["properties"]
                for source_property, output_column in property_mapping.items():
                    output_values[output_column][index] = props.get(source_property)
                break

    for output_column, values in output_values.items():
        result[output_column] = values
    return result


def lineal_intersection(source_geometry, mask_geometry):
    intersection = source_geometry.intersection(mask_geometry)
    if intersection.is_empty:
        return None
    if intersection.geom_type in {"LineString", "MultiLineString"}:
        return intersection
    if intersection.geom_type != "GeometryCollection":
        return None

    segments = []
    for part in intersection.geoms:
        if part.is_empty:
            continue
        if part.geom_type == "LineString":
            segments.append(part)
        elif part.geom_type == "MultiLineString":
            segments.extend(list(part.geoms))

    if not segments:
        return None
    if len(segments) == 1:
        return segments[0]
    return MultiLineString([list(segment.coords) for segment in segments])


def enrich_sales_micro_geography_keys(data: pd.DataFrame) -> pd.DataFrame:
    result = data.copy()
    street_name = result["street_name"].fillna("").astype(str)
    commune_insee = result["commune_insee"].fillna("").astype(str)
    house_number = result["house_number"].fillna("").astype(str)
    house_suffix = result["house_suffix"].fillna("").astype(str)
    matched_cle_interop = result["matched_cle_interop"].fillna("").astype(str)
    parcel_id = result["parcel_id"].fillna("").astype(str)
    address_key = result["address_key"].fillna("").astype(str)

    result["street_key"] = commune_insee.str.cat(street_name, sep="|")
    result.loc[street_name.eq(""), "street_key"] = pd.NA

    result["building_id"] = pd.NA
    result["building_id_source"] = pd.NA

    ban_mask = matched_cle_interop.ne("")
    result.loc[ban_mask, "building_id"] = matched_cle_interop[ban_mask]
    result.loc[ban_mask, "building_id_source"] = "ban_address"

    parcel_mask = result["building_id"].isna() & parcel_id.ne("")
    result.loc[parcel_mask, "building_id"] = parcel_id[parcel_mask]
    result.loc[parcel_mask, "building_id_source"] = "parcel"

    address_mask = result["building_id"].isna() & address_key.ne("")
    result.loc[address_mask, "building_id"] = address_key[address_mask]
    result.loc[address_mask, "building_id_source"] = "address_key"

    address_number = house_number.str.cat(house_suffix, sep=" ").str.replace(r"\s+", " ", regex=True).str.strip()
    result["building_label"] = address_number.str.cat(street_name, sep=" ").str.replace(r"\s+", " ", regex=True).str.strip()
    result.loc[result["building_label"].eq(""), "building_label"] = pd.NA
    empty_label_mask = result["building_label"].isna() & result["building_id"].notna()
    result.loc[empty_label_mask, "building_label"] = result.loc[empty_label_mask, "building_id"]
    return result


def build_street_sales_metrics(data: pd.DataFrame) -> pd.DataFrame:
    group_columns = ["street_key", "street_name", "arrondissement", "commune_insee", "year"]
    extra_columns = ["buildings", "geocoded_transactions", "longitude", "latitude"]
    metric_columns = [
        "transactions",
        "median_price_m2",
        "median_sale_value_eur",
        "median_surface_m2",
        "median_rooms",
        "apartment_share_pct",
        "house_share_pct",
    ]
    output_columns = [*group_columns, *extra_columns, *metric_columns]

    streets = data.loc[data["street_key"].notna()].copy()
    if streets.empty:
        return pd.DataFrame(columns=output_columns)

    metrics = aggregate_sales_metrics(streets, group_columns)
    context = (
        streets.groupby(group_columns)
        .agg(
            buildings=("building_id", "nunique"),
            longitude=("longitude", "median"),
            latitude=("latitude", "median"),
        )
        .reset_index()
    )
    geocoded_transactions = (
        streets.loc[streets["longitude"].notna(), group_columns + ["transaction_id"]]
        .groupby(group_columns)["transaction_id"]
        .nunique()
        .reset_index(name="geocoded_transactions")
    )
    result = metrics.merge(context, on=group_columns, how="left")
    result = result.merge(geocoded_transactions, on=group_columns, how="left")
    result["buildings"] = result["buildings"].fillna(0).astype(int)
    result["geocoded_transactions"] = result["geocoded_transactions"].fillna(0).astype(int)
    return result[output_columns].sort_values(group_columns).reset_index(drop=True)


def build_building_sales_metrics(data: pd.DataFrame) -> pd.DataFrame:
    group_columns = [
        "building_id",
        "building_id_source",
        "building_label",
        "arrondissement",
        "commune_insee",
        "street_name",
        "house_number",
        "house_suffix",
        "year",
    ]
    extra_columns = ["geocoded_transactions", "longitude", "latitude", "parcel_count"]
    metric_columns = [
        "transactions",
        "median_price_m2",
        "median_sale_value_eur",
        "median_surface_m2",
        "median_rooms",
        "apartment_share_pct",
        "house_share_pct",
    ]
    output_columns = [*group_columns, *extra_columns, *metric_columns]

    buildings = data.loc[data["building_id"].notna()].copy()
    if buildings.empty:
        return pd.DataFrame(columns=output_columns)

    metrics = aggregate_sales_metrics(buildings, group_columns)
    context = (
        buildings.groupby(group_columns)
        .agg(
            longitude=("longitude", "median"),
            latitude=("latitude", "median"),
            parcel_count=("parcel_id", "nunique"),
        )
        .reset_index()
    )
    geocoded_transactions = (
        buildings.loc[buildings["longitude"].notna(), group_columns + ["transaction_id"]]
        .groupby(group_columns)["transaction_id"]
        .nunique()
        .reset_index(name="geocoded_transactions")
    )
    result = metrics.merge(context, on=group_columns, how="left")
    result = result.merge(geocoded_transactions, on=group_columns, how="left")
    result["geocoded_transactions"] = result["geocoded_transactions"].fillna(0).astype(int)
    result["parcel_count"] = result["parcel_count"].fillna(0).astype(int)
    return result[output_columns].sort_values(group_columns).reset_index(drop=True)


def aggregate_sales_metrics(
    data: pd.DataFrame,
    group_columns: list[str],
    engine: str | None = None,
) -> pd.DataFrame:
    """Agrege les metriques de ventes par groupe.

    Le moteur de calcul est selectionnable (competence C2.2) :
    - `pandas` (defaut) : calcul mono-machine en memoire ;
    - `dask` : calcul distribue via un cluster Dask local ;
    - `spark` : calcul distribue via un cluster Spark (local ou Docker).

    Le moteur peut etre impose par l'argument `engine`, sinon par la variable
    d'environnement `UDE_AGG_ENGINE`. Toutes les implementations renvoient un
    resultat identique (memes colonnes, memes valeurs, meme tri), ce qui est
    verifie par les tests d'equivalence. Pandas reste le defaut pour ne jamais
    modifier le comportement du build existant.
    """

    chosen = (engine or os.environ.get("UDE_AGG_ENGINE") or "pandas").strip().lower()

    if chosen == "dask":
        from .distributed.dask_aggregation import aggregate_sales_metrics_distributed

        return aggregate_sales_metrics_distributed(data, group_columns)
    if chosen == "spark":
        from .distributed.spark_aggregation import aggregate_sales_metrics_spark

        return aggregate_sales_metrics_spark(data, group_columns)

    return _aggregate_sales_metrics_pandas(data, group_columns)


def _aggregate_sales_metrics_pandas(data: pd.DataFrame, group_columns: list[str]) -> pd.DataFrame:
    metric_columns = [
        "median_price_m2",
        "median_sale_value_eur",
        "median_surface_m2",
        "median_rooms",
        "apartment_share_pct",
        "house_share_pct",
    ]
    if data.empty:
        return pd.DataFrame(columns=[*group_columns, "transactions", *metric_columns])

    result = (
        data.groupby(group_columns)
        .agg(
            transactions=("transaction_id", "nunique"),
            median_price_m2=("price_per_m2", "median"),
            median_sale_value_eur=("sale_value_eur", "median"),
            median_surface_m2=("built_surface_m2", "median"),
            median_rooms=("rooms", "median"),
        )
        .reset_index()
    )

    shares = (
        data.assign(is_apartment=data["Type local"].eq("Appartement"), is_house=data["Type local"].eq("Maison"))
        .groupby(group_columns)
        .agg(
            apartment_share_pct=("is_apartment", "mean"),
            house_share_pct=("is_house", "mean"),
        )
        .reset_index()
    )
    shares["apartment_share_pct"] = (shares["apartment_share_pct"] * 100.0).round(1)
    shares["house_share_pct"] = (shares["house_share_pct"] * 100.0).round(1)

    result = result.merge(shares, on=group_columns, how="left")
    result[metric_columns] = result[metric_columns].round(2)
    return result.sort_values(group_columns).reset_index(drop=True)


def iter_chunks(items: list[str], chunk_size: int) -> list[list[str]]:
    return [items[index : index + chunk_size] for index in range(0, len(items), chunk_size)]


def extract_digits(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return "".join(character for character in str(value) if character.isdigit())


def normalize_house_number(value: object) -> str:
    digits = extract_digits(value)
    return digits.lstrip("0") or digits


def normalize_house_suffix(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    suffix = normalize_text(value)
    suffix_aliases = {
        "B": "BIS",
        "BIS": "BIS",
        "T": "TER",
        "TER": "TER",
        "Q": "QUATER",
        "QUATER": "QUATER",
    }
    return suffix_aliases.get(suffix, suffix)


def normalize_street_name(value: object) -> str:
    token_aliases = {
        "ALL": "ALLEE",
        "AV": "AVENUE",
        "BD": "BOULEVARD",
        "BLD": "BOULEVARD",
        "CHE": "CHEMIN",
        "CRS": "COURS",
        "FG": "FAUBOURG",
        "IMP": "IMPASSE",
        "PAS": "PASSAGE",
        "PL": "PLACE",
        "QU": "QUAI",
        "RLE": "RUELLE",
        "RTE": "ROUTE",
        "SQ": "SQUARE",
        "VLA": "VILLA",
    }
    normalized = normalize_text(value)
    if not normalized:
        return ""
    return " ".join(token_aliases.get(token, token) for token in normalized.split())


def normalize_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.upper().replace("-", " ").replace("'", " ")
    text = re.sub(r"[^A-Z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def build_income_metrics() -> pd.DataFrame:
    path = repo_path("data/bronze/raw/insee/filosofi-iris-2021.csv.zip")
    with zipfile.ZipFile(path) as archive:
        csv_name = [name for name in archive.namelist() if name.lower().endswith(".csv") and not name.startswith("meta_")][0]
        with archive.open(csv_name) as handle:
            text = io.TextIOWrapper(handle, encoding="utf-8-sig")
            data = pd.read_csv(text, sep=";", dtype=str)

    data = data.loc[data["IRIS"].str.startswith("751", na=False)].copy()
    data["arrondissement"] = pd.to_numeric(data["IRIS"].str[3:5], errors="coerce")

    for column in ["DEC_MED21", "DEC_TP6021", "DEC_Q121", "DEC_Q321", "DEC_PIMP21"]:
        data[column] = french_to_float(data[column])

    result = (
        data.groupby("arrondissement")
        .agg(
            iris_count=("IRIS", "count"),
            median_income_eur=("DEC_MED21", "median"),
            poverty_rate_pct=("DEC_TP6021", "mean"),
            first_quartile_income_eur=("DEC_Q121", "median"),
            third_quartile_income_eur=("DEC_Q321", "median"),
            share_taxable_pct=("DEC_PIMP21", "mean"),
        )
        .reset_index()
    )
    numeric_cols = [
        "median_income_eur",
        "poverty_rate_pct",
        "first_quartile_income_eur",
        "third_quartile_income_eur",
        "share_taxable_pct",
    ]
    result[numeric_cols] = result[numeric_cols].round(2)
    return result


def build_rent_metrics() -> pd.DataFrame:
    path = repo_path("data/bronze/raw/paris/encadrement-loyers.csv")
    data = pd.read_csv(
        path,
        sep=";",
        encoding="utf-8-sig",
        dtype=str,
        usecols=[
            "Année",
            "Loyers de référence",
            "Loyers de référence majorés",
            "Loyers de référence minorés",
            "Numéro INSEE du quartier",
        ],
        low_memory=False,
    )

    data["year"] = pd.to_numeric(data["Année"], errors="coerce")
    quartier_code = data["Numéro INSEE du quartier"].astype(str).str.zfill(7)
    data["arrondissement"] = pd.to_numeric(quartier_code.str[3:5], errors="coerce")
    data["reference_rent_eur_m2"] = french_to_float(data["Loyers de référence"])
    data["reference_rent_majorated_eur_m2"] = french_to_float(data["Loyers de référence majorés"])
    data["reference_rent_minorated_eur_m2"] = french_to_float(data["Loyers de référence minorés"])

    result = (
        data.groupby(["arrondissement", "year"])
        .agg(
            reference_rent_eur_m2=("reference_rent_eur_m2", "mean"),
            reference_rent_majorated_eur_m2=("reference_rent_majorated_eur_m2", "mean"),
            reference_rent_minorated_eur_m2=("reference_rent_minorated_eur_m2", "mean"),
            rent_reference_count=("reference_rent_eur_m2", "count"),
        )
        .reset_index()
    )
    result[["reference_rent_eur_m2", "reference_rent_majorated_eur_m2", "reference_rent_minorated_eur_m2"]] = (
        result[["reference_rent_eur_m2", "reference_rent_majorated_eur_m2", "reference_rent_minorated_eur_m2"]].round(2)
    )
    return result


def build_social_metrics() -> pd.DataFrame:
    path = repo_path("data/bronze/raw/paris/logements-sociaux-finances.csv")
    data = pd.read_csv(path, sep=";", encoding="utf-8-sig", dtype=str, low_memory=False)

    data["arrondissement"] = pd.to_numeric(data["Arrondissement"], errors="coerce")
    data["year"] = pd.to_numeric(data["Année du financement - agrément"], errors="coerce")
    data["social_units_financed"] = pd.to_numeric(data["Nombre total de logements financés"], errors="coerce")
    data["pla_i_units"] = pd.to_numeric(data["Dont nombre de logements PLA I"], errors="coerce")
    data["plus_units"] = pd.to_numeric(data["Dont nombre de logements PLUS"], errors="coerce")
    data["pls_units"] = pd.to_numeric(data["Dont nombre de logements PLS"], errors="coerce")

    data = data.loc[data["arrondissement"].between(1, 20) & data["year"].notna()].copy()
    result = (
        data.groupby(["arrondissement", "year"])
        .agg(
            program_count=("Identifiant livraison", "nunique"),
            social_units_financed=("social_units_financed", "sum"),
            pla_i_units=("pla_i_units", "sum"),
            plus_units=("plus_units", "sum"),
            pls_units=("pls_units", "sum"),
        )
        .reset_index()
    )
    numeric_cols = ["social_units_financed", "pla_i_units", "plus_units", "pls_units"]
    result[numeric_cols] = result[numeric_cols].round(0)
    result["program_count"] = result["program_count"].fillna(0).astype(int)
    return result


def build_noise_metrics(arr_geojson: dict[str, object]) -> pd.DataFrame:
    zip_path = repo_path("data/bronze/raw/bruitparif/couches-sig-air-bruit-2024.zip")
    if not zip_path.exists():
        raise FileNotFoundError("La couche Bruitparif 2024 est introuvable.")

    transformer = Transformer.from_crs("EPSG:4326", "EPSG:2154", always_xy=True)

    arrondissement_polygons = []
    for feature in arr_geojson["features"]:
        geom_wgs84 = shape(feature["geometry"])
        geom_l93 = shapely_transform(transformer.transform, geom_wgs84)
        arrondissement_polygons.append(
            {
                "arrondissement": int(feature["properties"]["arrondissement"]),
                "bbox": geom_l93.bounds,
                "prepared": prep(geom_l93),
            }
        )

    paris_bounds = [
        min(item["bbox"][0] for item in arrondissement_polygons),
        min(item["bbox"][1] for item in arrondissement_polygons),
        max(item["bbox"][2] for item in arrondissement_polygons),
        max(item["bbox"][3] for item in arrondissement_polygons),
    ]

    accumulators: dict[int, dict[str, float]] = {
        item["arrondissement"]: defaultdict(float) for item in arrondissement_polygons
    }

    with tempfile.TemporaryDirectory() as tmp_dir:
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(tmp_dir)

        shp_path = Path(tmp_dir) / "AirBruit_2024.shp"
        reader = shapefile.Reader(str(shp_path))
        try:
            for shp, record in zip(reader.iterShapes(), reader.iterRecords()):
                bbox = shp.bbox
                if bbox[2] < paris_bounds[0] or bbox[0] > paris_bounds[2] or bbox[3] < paris_bounds[1] or bbox[1] > paris_bounds[3]:
                    continue

                category = int(record[0])
                center_x = (bbox[0] + bbox[2]) / 2.0
                center_y = (bbox[1] + bbox[3]) / 2.0
                area = max((bbox[2] - bbox[0]) * (bbox[3] - bbox[1]), 0.0)
                if area <= 0:
                    continue

                point = Point(center_x, center_y)
                for arrondissement in arrondissement_polygons:
                    minx, miny, maxx, maxy = arrondissement["bbox"]
                    if center_x < minx or center_x > maxx or center_y < miny or center_y > maxy:
                        continue
                    if arrondissement["prepared"].covers(point):
                        bucket = accumulators[arrondissement["arrondissement"]]
                        bucket["cell_count"] += 1
                        bucket["total_area"] += area
                        bucket["noise_area_weight"] += (category % 10) * area
                        bucket["air_area_weight"] += (category // 10) * area
                        bucket[f"class_{category}_area"] += area
                        if category % 10 == 3:
                            bucket["high_noise_area"] += area
                        break
        finally:
            reader.close()

    rows = []
    for arrondissement, bucket in sorted(accumulators.items()):
        total_area = bucket["total_area"] or 1.0
        rows.append(
            {
                "arrondissement": arrondissement,
                "noise_score": round(bucket["noise_area_weight"] / total_area, 3),
                "air_score": round(bucket["air_area_weight"] / total_area, 3),
                "high_noise_share_pct": round(bucket["high_noise_area"] / total_area * 100.0, 2),
                "noise_cell_count": int(bucket["cell_count"]),
            }
        )
    return pd.DataFrame(rows)


def build_empty_noise_metrics() -> pd.DataFrame:
    rows = []
    for arrondissement in range(1, 21):
        rows.append(
            {
                "arrondissement": arrondissement,
                "noise_score": NEUTRAL_ENVIRONMENT_DEFAULTS["noise_score"],
                "air_score": NEUTRAL_ENVIRONMENT_DEFAULTS["air_score"],
                "high_noise_share_pct": NEUTRAL_ENVIRONMENT_DEFAULTS["high_noise_share_pct"],
                "noise_cell_count": 0,
            }
        )
    return pd.DataFrame(rows)


def build_city_summary(summary: pd.DataFrame) -> dict[str, float | int]:
    return {
        "arrondissement_count": int(summary["arrondissement"].nunique()),
        "median_price_m2": round(float(summary["median_price_m2"].median()), 2),
        "median_income_eur": round(float(summary["median_income_eur"].median()), 2),
        "reference_rent_majorated_eur_m2": round(float(summary["reference_rent_majorated_eur_m2"].median()), 2),
        "social_units_financed": int(summary["social_units_financed"].sum()),
        "social_units_financed_5y": int(summary["social_units_financed_5y"].sum()),
        "quality_of_life_score": round(float(summary["quality_of_life_score"].median()), 2),
        "months_income_for_1sqm": round(float(summary["months_income_for_1sqm"].median()), 2),
        "estimated_50m2_rent_effort_pct": round(float(summary["estimated_50m2_rent_effort_pct"].median()), 1),
    }


def metric_catalog() -> dict[str, dict[str, object]]:
    return {
        "median_price_m2": {"label": "Prix median au m²", "unit": "EUR/m²", "supports_year": True},
        "transactions": {"label": "Transactions retenues", "unit": "count", "supports_year": True},
        "median_sale_value_eur": {"label": "Valeur mediane de vente", "unit": "EUR", "supports_year": True},
        "median_surface_m2": {"label": "Surface mediane", "unit": "m²", "supports_year": True},
        "median_rooms": {"label": "Pieces medianes", "unit": "pieces", "supports_year": True},
        "apartment_share_pct": {"label": "Part appartements", "unit": "%", "supports_year": True},
        "house_share_pct": {"label": "Part maisons", "unit": "%", "supports_year": True},
        "median_income_eur": {"label": "Revenu median", "unit": "EUR/an", "supports_year": False},
        "reference_rent_majorated_eur_m2": {"label": "Loyer majore moyen", "unit": "EUR/m²", "supports_year": False},
        "social_units_financed": {"label": "Logements sociaux finances", "unit": "count", "supports_year": False},
        "social_units_financed_5y": {"label": "Logements sociaux finances sur 5 ans", "unit": "count", "supports_year": False},
        "months_income_for_1sqm": {"label": "Mois de revenu pour 1 m²", "unit": "months", "supports_year": False},
        "estimated_50m2_rent_effort_pct": {"label": "Effort locatif estime pour 50 m²", "unit": "%", "supports_year": False},
        "quality_of_life_score": {"label": "Qualite de vie", "unit": "/10", "supports_year": False},
        "environmental_pressure_index": {"label": "Pression environnementale", "unit": "/100", "supports_year": False},
        "high_noise_share_pct": {"label": "Part de forte exposition au bruit", "unit": "%", "supports_year": False},
        "noise_score": {"label": "Score bruit", "unit": "class", "supports_year": False},
        "air_score": {"label": "Score air", "unit": "class", "supports_year": False},
    }


def fill_with_median_or_default(series: pd.Series, default: float) -> pd.Series:
    median = series.median()
    fallback = default if pd.isna(median) else float(median)
    return series.fillna(fallback)


def compute_quality_of_life_score(summary: pd.DataFrame) -> pd.Series:
    noise_norm = (1.0 - ((summary["noise_score"] - 1.0) / 2.0)).clip(lower=0.0, upper=1.0)
    air_norm = (1.0 - ((summary["air_score"] - 1.0) / 2.0)).clip(lower=0.0, upper=1.0)
    high_noise_norm = (1.0 - (summary["high_noise_share_pct"] / 100.0)).clip(lower=0.0, upper=1.0)
    env_norm = (1.0 - (summary["environmental_pressure_index"] / 100.0)).clip(lower=0.0, upper=1.0)
    return (
        10.0
        * (
            QUALITY_OF_LIFE_WEIGHTS["noise_norm"] * noise_norm
            + QUALITY_OF_LIFE_WEIGHTS["air_norm"] * air_norm
            + QUALITY_OF_LIFE_WEIGHTS["high_noise_norm"] * high_noise_norm
            + QUALITY_OF_LIFE_WEIGHTS["env_norm"] * env_norm
        )
    ).round(2)


def french_to_float(series: pd.Series) -> pd.Series:
    return pd.to_numeric(
        series.astype(str)
        .str.replace("\xa0", "", regex=False)
        .str.replace(" ", "", regex=False)
        .str.replace(",", ".", regex=False),
        errors="coerce",
    )


def postal_code_to_arrondissement(value: object) -> int | None:
    if value is None or pd.isna(value):
        return None
    digits = "".join(character for character in str(value) if character.isdigit())
    if not digits:
        return None
    if digits == "75116":
        return 16
    if digits.startswith("75") and len(digits) >= 5:
        arrondissement = int(digits[-2:])
        if 1 <= arrondissement <= 20:
            return arrondissement
    return None
