"""Carrega a referência opcional: distritos oficiais, população, domicílios, aliases e taxonomia."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from spseg.analysis.taxonomy import Taxonomy, load_taxonomy
from spseg.config import Settings
from spseg.data.cache import reference_fingerprint
from spseg.geo.polygons import PolygonIndex
from spseg.geo.text import normalize_key
from spseg.models import RegistryEntry

DISTRITOS_FILE = "distritos_sp.geojson"
POPULACAO_FILE = "populacao_bairro.csv"
DOMICILIOS_FILE = "domicilios_bairro.csv"
ALIASES_FILE = "bairro_aliases.csv"
TAXONOMY_FILE = "crime_taxonomy.yml"

# Recorte da v1: capital de São Paulo (Lei 11.220/1992).
EXPECTED_DISTRITOS = 96

REFERENCE_FILES = (
    DISTRITOS_FILE,
    POPULACAO_FILE,
    DOMICILIOS_FILE,
    ALIASES_FILE,
    TAXONOMY_FILE,
)


@dataclass(frozen=True)
class Denominator:
    value: int | None
    level: str | None = None
    source: str | None = None


@dataclass(frozen=True)
class ReferenceStatus:
    distritos: bool = False
    populacao: bool = False
    domicilios: bool = False
    aliases: bool = False
    taxonomia: bool = False
    issues: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, bool]:
        return {
            DISTRITOS_FILE: self.distritos,
            POPULACAO_FILE: self.populacao,
            DOMICILIOS_FILE: self.domicilios,
            ALIASES_FILE: self.aliases,
            TAXONOMY_FILE: self.taxonomia,
        }

    @property
    def has_geo(self) -> bool:
        return self.distritos

    @property
    def has_rates(self) -> bool:
        return self.populacao or self.domicilios


@dataclass
class ReferenceData:
    entries: list[RegistryEntry] = field(default_factory=list)
    polygons: PolygonIndex | None = None
    population: dict[tuple[str, str], Denominator] = field(default_factory=dict)
    households: dict[tuple[str, str], Denominator] = field(default_factory=dict)
    aliases: dict[str, str] = field(default_factory=dict)
    taxonomy: Taxonomy | None = None
    status: ReferenceStatus = field(default_factory=ReferenceStatus)
    version: str = "empty"

    @property
    def has_registry(self) -> bool:
        return bool(self.entries)

    def population_for(self, entry: RegistryEntry) -> Denominator:
        return _lookup(self.population, entry)

    def households_for(self, entry: RegistryEntry) -> Denominator:
        return _lookup(self.households, entry)


def _lookup(table: dict[tuple[str, str], Denominator], entry: RegistryEntry) -> Denominator:
    for level, key in (("bairro", entry.bairro_id), ("distrito", entry.distrito_id)):
        if key and (level, key) in table:
            return table[(level, key)]
    return Denominator(None)


def _load_csv(path: Path, required: tuple[str, ...], issues: list[str]) -> pd.DataFrame | None:
    if not path.exists():
        return None
    try:
        frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    except (OSError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        issues.append(f"{path.name}: não foi possível ler ({exc}).")
        return None
    missing = [column for column in required if column not in frame.columns]
    if missing:
        issues.append(f"{path.name}: colunas obrigatórias ausentes {missing}; arquivo ignorado.")
        return None
    return frame


def _load_denominators(
    path: Path, value_column: str, issues: list[str]
) -> dict[tuple[str, str], Denominator]:
    frame = _load_csv(path, ("bairro_id", value_column), issues)
    if frame is None:
        return {}
    table: dict[tuple[str, str], Denominator] = {}
    for row in frame.itertuples(index=False):
        identifier = str(row.bairro_id).strip()
        if not identifier:
            continue
        level = str(getattr(row, "nivel", "bairro") or "bairro").strip().lower()
        if level not in ("bairro", "distrito"):
            layer = "bairro"
        else:
            layer = level
        raw_value = str(getattr(row, value_column)).strip()
        try:
            value = int(float(raw_value.replace(".", "").replace(",", ".")))
        except ValueError:
            continue
        source = str(getattr(row, "fonte", "") or "").strip() or None
        table[(layer, identifier)] = Denominator(value=value, level=layer, source=source)
    return table


def _load_aliases(path: Path, issues: list[str]) -> dict[str, str]:
    frame = _load_csv(path, ("bairro_raw", "bairro_id"), issues)
    if frame is None:
        return {}
    aliases: dict[str, str] = {}
    for row in frame.itertuples(index=False):
        raw = str(row.bairro_raw).strip()
        target = str(row.bairro_id).strip()
        if raw and target:
            aliases[raw] = target
    return aliases


def _entries_from_files(
    polygons: PolygonIndex | None,
    population: dict[tuple[str, str], Denominator],
    households: dict[tuple[str, str], Denominator],
    issues: list[str],
) -> list[RegistryEntry]:
    entries: dict[str, RegistryEntry] = {}
    if polygons is not None:
        if len(polygons.units) != EXPECTED_DISTRITOS:
            issues.append(
                f"{DISTRITOS_FILE}: {len(polygons.units)} unidades (esperado "
                f"{EXPECTED_DISTRITOS} distritos da capital)."
            )
        missing_distrito = [unit.bairro_nome for unit in polygons.units if not unit.distrito_id]
        if missing_distrito:
            issues.append(
                f"{DISTRITOS_FILE}: {len(missing_distrito)} unidades sem distrito_id; "
                "as taxas por população/domicílios ficam 'n/d' para elas."
            )
        for unit in polygons.units:
            entries[unit.bairro_id] = RegistryEntry(
                bairro_id=unit.bairro_id,
                bairro_nome=unit.bairro_nome,
                distrito_id=unit.distrito_id,
            )
        known = set(entries)
        for table in (population, households):
            for level, identifier in table:
                if level == "bairro" and identifier not in known:
                    issues.append(
                        f"Referência tem o bairro '{identifier}' sem polígono no GeoJSON; "
                        "ele não receberá fallback por coordenadas."
                    )
    else:
        for table in (population, households):
            for level, identifier in table:
                if level != "bairro" or identifier in entries:
                    continue
                entries[identifier] = RegistryEntry(bairro_id=identifier, bairro_nome=identifier)
    return list(entries.values())


def load_reference(settings: Settings) -> ReferenceData:
    reference_dir = settings.reference_dir
    issues: list[str] = []
    taxonomy, taxonomy_issues = load_taxonomy(
        reference_dir / TAXONOMY_FILE if reference_dir.exists() else None
    )
    issues.extend(taxonomy_issues)

    polygons = None
    geojson_path = reference_dir / DISTRITOS_FILE
    if geojson_path.exists():
        try:
            polygons = PolygonIndex.from_geojson(geojson_path)
            if not polygons.units:
                issues.append(f"{DISTRITOS_FILE}: nenhuma unidade válida encontrada.")
                polygons = None
        except (OSError, ValueError, KeyError) as exc:
            issues.append(
                f"{DISTRITOS_FILE}: GeoJSON inválido ({exc}); fallback por geo desativado."
            )

    population = _load_denominators(reference_dir / POPULACAO_FILE, "populacao", issues)
    households = _load_denominators(reference_dir / DOMICILIOS_FILE, "domicilios", issues)
    aliases = _load_aliases(reference_dir / ALIASES_FILE, issues)
    entries = _entries_from_files(polygons, population, households, issues)

    if aliases and entries:
        known = {entry.bairro_id for entry in entries}
        unknown = sorted({target for target in aliases.values() if target not in known})
        if unknown:
            issues.append(
                f"{ALIASES_FILE}: {len(unknown)} aliases apontam para bairros fora da referência."
            )

    status = ReferenceStatus(
        distritos=polygons is not None,
        populacao=bool(population),
        domicilios=bool(households),
        aliases=bool(aliases),
        taxonomia=(reference_dir / TAXONOMY_FILE).exists(),
        issues=tuple(issues),
    )
    return ReferenceData(
        entries=entries,
        polygons=polygons,
        population=population,
        households=households,
        aliases=aliases,
        taxonomy=taxonomy,
        status=status,
        version=reference_fingerprint(settings),
    )


def reference_paths(settings: Settings) -> dict[str, Path]:
    return {name: settings.reference_dir / name for name in REFERENCE_FILES}


def normalize_bairro_name(value: str) -> str:
    return normalize_key(value)
