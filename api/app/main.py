from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .routes.dashboard import router as dashboard_router
from .routes.health import router as health_router
from .routes.sources import router as sources_router


def create_app() -> FastAPI:
    frontend_dir = Path(__file__).resolve().parents[2] / "frontend"
    app = FastAPI(
        title="Urban Data Explorer API",
        version="0.1.0",
        description="API et frontend statique pour explorer les dynamiques du logement parisien.",
    )
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")
    app.include_router(health_router)
    app.include_router(sources_router)
    app.include_router(dashboard_router)

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(frontend_dir / "index.html")

    return app


app = create_app()
