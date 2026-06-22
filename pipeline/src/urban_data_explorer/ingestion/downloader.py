from __future__ import annotations

import csv
import io
import time
import zipfile
from pathlib import Path

import requests

from ..config import SourceConfig


CHUNK_SIZE = 1024 * 1024


def _download_file(url: str, target_path: Path, force: bool = False) -> Path:
    if target_path.exists() and not force:
        return target_path

    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target_path.with_suffix(target_path.suffix + ".part")

    last_error: Exception | None = None
    for attempt in range(1, 5):
        try:
            with requests.get(url, stream=True, timeout=180) as response:
                response.raise_for_status()
                with temp_path.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                        if chunk:
                            handle.write(chunk)
            break
        except requests.RequestException as exc:
            last_error = exc
            if temp_path.exists():
                temp_path.unlink()
            if attempt == 4:
                raise
            time.sleep(attempt * 2)
    else:
        if last_error is not None:
            raise last_error

    temp_path.replace(target_path)
    return target_path


def _filter_dvf_department(source: SourceConfig, archive_path: Path, force: bool = False) -> Path:
    if source.filtered_path is None:
        raise ValueError("filtered_path manquant pour la source DVF")

    output_path = source.filtered_path
    if output_path.exists() and not force:
        return output_path

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_suffix(".tmp")

    with zipfile.ZipFile(archive_path) as archive:
        text_members = [name for name in archive.namelist() if name.lower().endswith(".txt")]
        if not text_members:
            raise FileNotFoundError("Aucun fichier texte trouve dans l'archive DVF.")

        with archive.open(text_members[0]) as raw_handle:
            text_handle = io.TextIOWrapper(raw_handle, encoding="utf-8")
            reader = csv.DictReader(text_handle, delimiter=source.delimiter)

            writer = None
            with temp_path.open("w", encoding="utf-8", newline="") as output_handle:
                for row in reader:
                    if row.get("Code departement") != source.department_code:
                        continue

                    if writer is None:
                        writer = csv.DictWriter(output_handle, fieldnames=reader.fieldnames)
                        writer.writeheader()

                    writer.writerow(row)

    temp_path.replace(output_path)
    return output_path


def download_source(source: SourceConfig, force: bool = False) -> Path:
    downloaded_path = _download_file(source.url, source.target_path, force=force)

    if source.kind == "dvf_zip":
        return _filter_dvf_department(source, downloaded_path, force=force)

    return downloaded_path
