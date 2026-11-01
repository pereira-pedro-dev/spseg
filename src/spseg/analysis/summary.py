"""Monta o `BairroSummary` a partir do cache de fatos + referência."""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd

from spseg.analysis.aggregate import summarize_categories, total_incidents
from spseg.analysis.period import resolve_period
from spseg.config import DEFAULT_MUNICIPIO, Settings
from spseg.data.cache import cached_years, load_manifest, read_facts
from spseg.data.reference import (
    DOMICILIOS_FILE,
    POPULACAO_FILE,
    ReferenceData,
    load_reference,
)
from spseg.data.schema import normalize_municipio
from spseg.geo.resolve import (
    BairroResolver,
    registry_from_entries_frame,
    registry_from_frame,
)
from spseg.models import BairroSummary, QualityFlags, RegistryEntry

RESOLVED_METHODS = {"exact", "alias", "fuzzy", "geo"}


class CacheMissing(RuntimeError):
    pass


class BairroNotFound(LookupError):
    def __init__(self, query: str, suggestions: list[tuple[str, float]]) -> None:
        self.query = query
        self.suggestions = suggestions
        super().__init__(f"Bairro não encontrado: {query}")


def _bairro_entries(facts: pd.DataFrame, reference: ReferenceData) -> list[RegistryEntry]:
    entries = registry_from_entries_frame(facts)
    if entries:
        return entries
    if reference.has_registry:
        return reference.entries
    return registry_from_frame(facts)


def build_summary(
    settings: Settings,
    query: str,
    *,
    municipio: str = DEFAULT_MUNICIPIO,
    since: object = None,
    until: object = None,
    years: int | None = None,
    today: date | None = None,
) -> BairroSummary:
    if not cached_years(settings, "facts"):
        raise CacheMissing(
            "Nenhum cache encontrado. Rode `uv run spseg ingest` antes de consultar."
        )

    facts = read_facts(settings)
    target_municipio = normalize_municipio(municipio)
    if "municipio" in facts.columns:
        facts = facts[facts["municipio"] == target_municipio]
    if facts.empty:
        raise CacheMissing(f"Não há registros para o município '{municipio}' no cache.")

    manifest = load_manifest(settings)
    reference = load_reference(settings)
    entries = _bairro_entries(facts, reference)
    resolver = BairroResolver(entries, aliases=reference.aliases)

    hit = resolver.find(query)
    if hit is None:
        raise BairroNotFound(query, resolver.suggestions(query))
    entry, match_method, _confidence = hit

    if "crime_category" not in facts.columns:
        taxonomy = reference.taxonomy
        facts["crime_category"] = taxonomy.classify(facts) if taxonomy else pd.NA

    period = resolve_period(
        facts["data_ocorrencia"],
        since=since,
        until=until,
        years=years,
        today=today,
        coverage_start=facts["data_registro"].min() if "data_registro" in facts.columns else None,
        coverage_end=facts["data_registro"].max() if "data_registro" in facts.columns else None,
    )
    dates = pd.to_datetime(facts["data_ocorrencia"], errors="coerce")
    in_bairro = facts["bairro_id"] == entry.bairro_id
    in_period = (
        in_bairro
        & (dates >= pd.Timestamp(period.start))
        & (dates < pd.Timestamp(period.end) + pd.Timedelta(days=1))
    )
    frame = facts[in_period]

    population = reference.population_for(entry)
    households = reference.households_for(entry)
    taxonomy = reference.taxonomy
    if taxonomy is None:  # pragma: no cover - load_reference sempre devolve taxonomia
        raise RuntimeError("Taxonomia indisponível.")

    categories = summarize_categories(
        frame,
        taxonomy,
        period,
        population=population.value,
        households=households.value,
    )

    method_counts = {
        str(method): int(count) for method, count in frame["bairro_method"].value_counts().items()
    }
    rows = len(frame)
    resolved = sum(method_counts.get(method, 0) for method in RESOLVED_METHODS)
    resolution_rate = resolved / rows if rows else None
    suppressed_city = int((facts["bairro_method"] == "suppressed").sum())

    notes: list[str] = []
    notes.extend(period.notes)
    years_cached = cached_years(settings, "facts")
    if len(years_cached) < 3:
        notes.append(
            "cache cobre apenas "
            + ", ".join(str(year) for year in years_cached)
            + "; períodos e tendências ficam incompletos até os outros anos serem ingeridos."
        )
    if match_method in ("fuzzy", "alias"):
        notes.append(f"'{query}' interpretado como '{entry.bairro_nome}' ({match_method}).")
    if not reference.status.populacao:
        notes.append(f"Sem {POPULACAO_FILE} em data/reference: taxas por habitante ficam 'n/d'.")
    if not reference.status.domicilios:
        notes.append(f"Sem {DOMICILIOS_FILE} em data/reference: taxas por domicílio ficam 'n/d'.")
    if not reference.status.distritos:
        notes.append(
            "Sem distritos_sp.geojson: resolução usa apenas o texto do campo BAIRRO "
            "(sem fallback por coordenadas)."
        )
    if reference.status.issues:
        notes.extend(reference.status.issues)
    if reference.has_registry and reference.version != manifest.get("reference_version"):
        notes.append(
            "A referência mudou desde o último `ingest`; rode novamente para "
            "aplicar aliases/população novas."
        )
    if suppressed_city:
        notes.append(
            f"{suppressed_city:,} registros da base têm o local suprimido pelo SSP "
            "(não entram em nenhum bairro).".replace(",", ".")
        )
    if rows and resolution_rate is not None and resolution_rate < 1:
        unresolved = method_counts.get("unresolved", 0)
        notes.append(
            f"{unresolved:,} registros do bairro não tiveram local resolvido "
            f"({resolution_rate:.0%} resolvidos).".replace(",", ".")
        )
    if rows and "tipo_local" in frame.columns:
        missing_tipo = float(frame["tipo_local"].isna().mean())
        if missing_tipo >= 0.25:
            notes.append(
                f"tipo de local ausente em {missing_tipo:.0%} dos registros do período "
                "(2024 não traz DESCR_TIPOLOCAL); 'Invasão de residência' fica subestimada."
            )
    if taxonomy.provisional:
        notes.append(
            "Taxonomia provisória: as categorias ainda não foram validadas "
            "na sessão de metodologia."
        )

    denominator_level = population.level or households.level
    quality = QualityFlags(
        rows_in_bairro=rows,
        method_counts=method_counts,
        resolution_rate=resolution_rate,
        suppressed_city=suppressed_city,
        reference_status=reference.status.as_dict(),
        notes=tuple(notes),
    )

    return BairroSummary(
        bairro_nome=entry.bairro_nome,
        bairro_id=entry.bairro_id,
        municipio=municipio,
        period=period,
        total_occurrences=rows,
        total_incidents=total_incidents(frame),
        population=population.value,
        households=households.value,
        denominator_level=denominator_level,
        categories=categories,
        quality=quality,
        taxonomy_provisional=taxonomy.provisional,
        generated_at=datetime.now(),
    )
