from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def repo_path(relative_path: str) -> Path:
    return PROJECT_ROOT / relative_path

