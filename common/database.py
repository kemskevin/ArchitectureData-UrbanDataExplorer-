from __future__ import annotations

from functools import lru_cache
import os
from typing import Any
from urllib.parse import quote_plus

import pandas as pd
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine


TABULAR_DATASETS = {
    "silver_sales": "silver_sales_yearly",
    "silver_sales_quartier": "silver_sales_quartier_yearly",
    "silver_sales_iris": "silver_sales_iris_yearly",
    "silver_sales_geocoded": "silver_sales_geocoded",
    "silver_sales_street": "silver_sales_street_yearly",
    "silver_sales_building": "silver_sales_building_yearly",
    "silver_income": "silver_income_arrondissement",
    "silver_rents": "silver_rents_yearly",
    "silver_social": "silver_social_yearly",
    "silver_noise": "silver_noise_arrondissement",
    "gold_summary": "gold_arrondissement_summary",
    "gold_sales": "gold_sales_yearly",
    "gold_sales_quartier": "gold_sales_quartier_yearly",
    "gold_sales_iris": "gold_sales_iris_yearly",
    "gold_sales_geocoded": "gold_sales_geocoded",
    "gold_sales_street": "gold_sales_street_yearly",
    "gold_sales_building": "gold_sales_building_yearly",
    "gold_social": "gold_social_yearly",
    "gold_rents": "gold_rents_yearly",
    "gold_income": "gold_income_arrondissement",
    "gold_noise": "gold_noise_arrondissement",
}


def get_database_url() -> str:
    explicit_url = os.getenv("DATABASE_URL")
    if explicit_url:
        return explicit_url

    host = os.getenv("MYSQL_HOST", "localhost")
    port = os.getenv("MYSQL_PORT", "3306")
    database = os.getenv("MYSQL_DATABASE", "urban_data_explorer")
    username = quote_plus(os.getenv("MYSQL_USER", "urban"))
    password = quote_plus(os.getenv("MYSQL_PASSWORD", "urban"))
    return f"mysql+pymysql://{username}:{password}@{host}:{port}/{database}?charset=utf8mb4"


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return create_engine(get_database_url(), pool_pre_ping=True)


def ping_sql_database() -> None:
    with get_engine().connect() as connection:
        connection.execute(text("SELECT 1"))


def ping_database() -> None:
    ping_sql_database()


def table_exists(table_name: str) -> bool:
    return inspect(get_engine()).has_table(table_name)


def write_table_dataset(dataset_name: str, dataframe: pd.DataFrame) -> str:
    table_name = TABULAR_DATASETS[dataset_name]
    dataframe.to_sql(
        table_name,
        con=get_engine(),
        if_exists="replace",
        index=False,
        chunksize=1000,
        method="multi",
    )
    return table_name


def read_table_dataset(dataset_name: str, **kwargs: Any) -> pd.DataFrame:
    table_name = TABULAR_DATASETS[dataset_name]
    return pd.read_sql_table(table_name, con=get_engine(), **kwargs)
