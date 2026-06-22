from pathlib import Path
import yaml

from fastapi import APIRouter


router = APIRouter(tags=["sources"])


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


@router.get("/sources")
def list_sources() -> dict[str, object]:
    config_path = _repo_root() / "config" / "sources.yaml"
    with config_path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}

    sources = []
    for name, source in payload.get("sources", {}).items():
        sources.append(
            {
                "name": name,
                "label": source["label"],
                "group": source["group"],
                "summary": source["summary"],
                "url": source["url"],
                "target_file": source["target_file"],
            }
        )

    return {"project": payload.get("project", {}), "sources": sources}
