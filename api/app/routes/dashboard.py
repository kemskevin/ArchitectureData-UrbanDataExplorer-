from fastapi import APIRouter

from ..dashboard_data import (
    compare_arrondissements,
    compare_quartiers,
    map_geojson,
    metadata,
    overview_for_year,
    quartiers_for_year,
    reference_geojson,
    timeline_for_arrondissement,
)


router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/meta")
def meta() -> dict[str, object]:
    return metadata()


@router.get("/overview")
def overview(sales_year: int | None = None) -> dict[str, object]:
    return overview_for_year(sales_year=sales_year)


@router.get("/timeline")
def timeline(arrondissement: int) -> dict[str, object]:
    return timeline_for_arrondissement(arrondissement)


@router.get("/compare")
def compare(left: int, right: int, sales_year: int | None = None) -> dict[str, object]:
    return compare_arrondissements(left=left, right=right, sales_year=sales_year)


@router.get("/quartiers")
def quartiers(sales_year: int | None = None) -> dict[str, object]:
    return quartiers_for_year(sales_year=sales_year)


@router.get("/quartiers/compare")
def compare_q(left: str, right: str, sales_year: int | None = None) -> dict[str, object]:
    return compare_quartiers(left=left, right=right, sales_year=sales_year)


@router.get("/map")
def map_layer(
    metric: str = "median_price_m2",
    year: int | None = None,
    level: str = "arrondissement",
) -> dict[str, object]:
    return map_geojson(metric=metric, year=year, level=level)


@router.get("/reference/{level}")
def reference_layer(level: str) -> dict[str, object]:
    return reference_geojson(level=level)
