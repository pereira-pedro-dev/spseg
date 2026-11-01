"""Orquestra a ingestão: Excel → parquet bruto → parquet enriquecido."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from spseg.config import DATA_FILES_GLOB, DEFAULT_MUNICIPIO, SCHEMA_VERSION, Settings
from spseg.data.cache import (
    facts_cache_path,
    is_facts_stale,
    is_raw_stale,
    load_manifest,
    raw_cache_path,
    read_parquet,
    save_manifest,
    source_fingerprint,
    write_parquet,
)
from spseg.data.excel import read_workbook
from spseg.data.reference import ReferenceData, load_reference
from spseg.data.schema import year_from_filename
from spseg.geo.resolve import BairroResolver, registry_from_frame

Progress = Callable[[str], None]


@dataclass
class IngestResult:
    year: int
    raw_rows: int
    facts_rows: int
    rebuilt_raw: bool
    rebuilt_facts: bool
    warnings: list[str] = field(default_factory=list)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def find_workbooks(raw_dir: Path) -> dict[int, Path]:
    workbooks: dict[int, Path] = {}
    for path in sorted(Path(raw_dir).glob(DATA_FILES_GLOB)):
        year = year_from_filename(path.name)
        if year is None:
            continue
        if year in workbooks:
            raise ValueError(
                f"Mais de um arquivo para {year}: {workbooks[year].name} e {path.name}. "
                "Mantenha apenas um por ano em data/raw."
            )
        workbooks[year] = path
    return workbooks


def ingest(
    settings: Settings,
    *,
    force: bool = False,
    years: list[int] | None = None,
    keep_all_municipalities: bool = False,
    progress: Progress | None = None,
) -> tuple[list[IngestResult], ReferenceData]:
    log = progress or print
    settings.ensure_dirs()
    workbooks = find_workbooks(settings.raw_dir)
    if years:
        workbooks = {year: path for year, path in workbooks.items() if year in set(years)}
    if not workbooks:
        raise FileNotFoundError(
            f"Nenhum workbook encontrado em {settings.raw_dir} (padrão: {DATA_FILES_GLOB})."
        )

    manifest = load_manifest(settings)
    if manifest.get("schema_version") != 1:
        manifest["schema_version"] = 1
    reference = load_reference(settings)
    log(f"Referência: {len(reference.entries)} bairros | versão {reference.version}")
    for issue in reference.status.issues:
        log(f"  aviso: {issue}")

    results: list[IngestResult] = []
    for year in sorted(workbooks):
        source = workbooks[year]
        log(f"\n[{year}] {source.name}")
        result = IngestResult(
            year=year,
            raw_rows=0,
            facts_rows=0,
            rebuilt_raw=False,
            rebuilt_facts=False,
            warnings=list(reference.status.issues),
        )

        rebuild_raw = force or is_raw_stale(settings, manifest, year, source)
        raw_frame: pd.DataFrame | None = None
        if rebuild_raw:
            log("  estágio 1: lendo Excel...")
            raw_frame, warnings = read_workbook(
                source,
                municipio=None if keep_all_municipalities else DEFAULT_MUNICIPIO,
                progress=log,
            )
            write_parquet(raw_frame, raw_cache_path(settings, year))
            fingerprint = source_fingerprint(source)
            manifest.setdefault("sources", {})[str(year)] = {
                **fingerprint,
                "rows": len(raw_frame),
                "sheets": sorted(raw_frame["source_sheet"].dropna().unique().tolist()),
                "warnings": warnings,
                "built_at": _utcnow(),
                "schema_version": SCHEMA_VERSION,
            }
            result.rebuilt_raw = True
            result.warnings.extend(warnings)
            log(f"  estágio 1 concluído: {len(raw_frame):,} linhas".replace(",", "."))
        else:
            log("  estágio 1: cache válido, pulando Excel")

        raw_entry = manifest.setdefault("sources", {}).get(str(year), {})
        result.raw_rows = int(raw_entry.get("rows", 0))

        rebuild_facts = force or is_facts_stale(settings, manifest, year, reference.version)
        if rebuild_facts:
            if raw_frame is None:
                raw_frame = read_parquet(raw_cache_path(settings, year))
            log("  estágio 2: resolvendo bairros e categorias...")
            registry = (
                reference.entries if reference.has_registry else registry_from_frame(raw_frame)
            )
            resolver = BairroResolver(
                registry,
                aliases=reference.aliases,
                polygons=reference.polygons,
            )
            resolved = resolver.resolve_frame(raw_frame)
            facts = pd.concat([raw_frame, resolved], axis=1)
            if reference.taxonomy is not None:
                facts["crime_category"] = reference.taxonomy.classify(facts)
            else:  # pragma: no cover - load_reference sempre devolve taxonomia
                facts["crime_category"] = "outros"
            write_parquet(facts, facts_cache_path(settings, year))

            method_counts = {
                str(method): int(count)
                for method, count in resolved["bairro_method"].value_counts().items()
            }
            manifest.setdefault("facts", {})[str(year)] = {
                "rows": len(facts),
                "reference_version": reference.version,
                "raw_built_at": raw_entry.get("built_at"),
                "built_at": _utcnow(),
                "schema_version": SCHEMA_VERSION,
                "method_counts": method_counts,
            }
            result.rebuilt_facts = True
            result.facts_rows = len(facts)
            log(
                f"  estágio 2 concluído: {len(facts):,} linhas | "
                f"{_format_methods(method_counts)}".replace(",", ".")
            )
        else:
            log("  estágio 2: cache válido, pulando enriquecimento")
            entry = manifest.get("facts", {}).get(str(year), {})
            result.facts_rows = int(entry.get("rows", 0))

        manifest["reference_version"] = reference.version
        save_manifest(settings, manifest)
        results.append(result)

    return results, reference


def _format_methods(counts: dict[str, int]) -> str:
    return ", ".join(f"{method}={count}" for method, count in sorted(counts.items()))
