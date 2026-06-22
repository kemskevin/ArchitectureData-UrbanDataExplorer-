from fastapi import APIRouter, HTTPException

from common.database import ping_sql_database
from common.document_store import ping_document_store


router = APIRouter(tags=["health"])


@router.get("/health")
def healthcheck() -> dict[str, str]:
    try:
        ping_sql_database()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"MySQL indisponible: {exc}") from exc

    try:
        ping_document_store()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"MongoDB indisponible: {exc}") from exc

    return {
        "status": "ok",
        "sql": "mysql",
        "nosql": "mongodb",
        "mysql": "ok",
        "mongodb": "ok",
    }
