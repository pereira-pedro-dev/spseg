"""Cache Parquet em dois estágios + manifesto de proveniência."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from spseg.config import SCHEMA_VERSION, Settings

MANIFEST_SCHEMA_VERSION = 1


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def empty_manifest() -> dict:
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "reference_version": None,
        "sources": {},
        "facts": {},
        "updated_at": None,
    }


def load_manifest(settings: Settings) -> dict:
    path = settings.manifest_path
    if not path.exists():
        return empty_manifest()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return empty_manifest()
    manifest = empty_manifest()
    manifest.update(payload)
    return manifest


def save_manifest(settings: Settings, manifest: dict) -> None:
    manifest["updated_at"] = _utcnow()
    settings.cache_dir.mkdir(parents=True, exist_ok=True)
    settings.manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def raw_cache_path(settings: Settings, year: int) -> Path:
    return settings.raw_cache_dir / f"{year}.parquet"


def facts_cache_path(settings: Settings, year: int) -> Path:
    return settings.facts_cache_dir / f"{year}.parquet"


def source_fingerprint(path: Path) -> dict:
    stat = path.stat()
    return {
        "file": path.name,
        "path": str(path.resolve()),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def reference_fingerprint(settings: Settings) -> str:
    """Hash dos arquivos de referência, para saber quando o estágio 2 ficou velho."""
    reference_dir = settings.reference_dir
    if not reference_dir.exists():
        return "empty"
    digest = hashlib.sha1()
    for path in sorted(reference_dir.rglob("*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        stat = path.stat()
        digest.update(f"{path.name}:{stat.st_size}:{stat.st_mtime_ns}\n".encode())
    return digest.hexdigest()[:16]


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, engine="pyarrow", compression="zstd", index=False)


def read_parquet(path: Path, columns: list[str] | None = None) -> pd.DataFrame:
    return pd.read_parquet(path, engine="pyarrow", columns=columns)


def cached_years(settings: Settings, kind: str = "facts") -> list[int]:
    directory = settings.facts_cache_dir if kind == "facts" else settings.raw_cache_dir
    if not directory.exists():
        return []
    years = []
    for path in directory.glob("*.parquet"):
        try:
            years.append(int(path.stem))
        except ValueError:
            continue
    return sorted(years)


def latest_year(settings: Settings, kind: str = "facts") -> int | None:
    years = cached_years(settings, kind)
    return years[-1] if years else None


def read_facts(
    settings: Settings,
    years: list[int] | None = None,
    columns: list[str] | None = None,
) -> pd.DataFrame:
    selected = years or cached_years(settings, "facts")
    if not selected:
        raise FileNotFoundError(
            "Nenhum cache de fatos encontrado. Rode `uv run spseg ingest` primeiro."
        )
    frames = [read_parquet(facts_cache_path(settings, year), columns) for year in selected]
    return pd.concat(frames, ignore_index=True)


def is_raw_stale(settings: Settings, manifest: dict, year: int, source: Path) -> bool:
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        return True
    if not Path(source).exists():
        return True
    entry = manifest.get("sources", {}).get(str(year))
    if not entry or not raw_cache_path(settings, year).exists():
        return True
    if entry.get("schema_version") != SCHEMA_VERSION:
        return True
    current = source_fingerprint(Path(source))
    return entry.get("size") != current["size"] or entry.get("mtime_ns") != current["mtime_ns"]


def is_facts_stale(settings: Settings, manifest: dict, year: int, reference_version: str) -> bool:
    entry = manifest.get("facts", {}).get(str(year))
    if not entry or not facts_cache_path(settings, year).exists():
        return True
    if entry.get("schema_version") != SCHEMA_VERSION:
        return True
    if entry.get("reference_version") != reference_version:
        return True
    raw_entry = manifest.get("sources", {}).get(str(year), {})
    return entry.get("raw_built_at") != raw_entry.get("built_at")
