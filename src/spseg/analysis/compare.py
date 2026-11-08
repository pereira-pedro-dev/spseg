"""Comparação de distritos lado a lado, na mesma janela temporal.

O `spseg compare` resolve 2–6 distritos e apresenta, para cada um: contagens,
taxas (quando há denominador), score relativo (percentil/posto) e qualidade.
Uma única janela para todos os distritos — comparar janelas diferentes é
proibido. Sem denominador, a taxa fica `n/d`, nunca chutada.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import pandas as pd

from spseg.analysis.aggregate import summarize_categories, total_incidents
from spseg.analysis.period import resolve_period
from spseg.analysis.score import build_city_scores
from spseg.analysis.summary import BairroNotFound, CacheMissing, _bairro_entries
from spseg.config import DEFAULT_MUNICIPIO, Settings
from spseg.data.cache import cached_years, read_facts
from spseg.data.reference import load_reference
from spseg.data.schema import normalize_municipio
from spseg.geo.resolve import BairroResolver
from spseg.models import CompareDistrict, CompareSummary, DistrictScore

MIN_DISTRICTS = 2
MAX_DISTRICTS = 6

RESOLVED_METHODS = {"exact", "alias", "fuzzy", "geo"}


def build_compare(
    settings: Settings,
    queries: Sequence[str],
    *,
    municipio: str = DEFAULT_MUNICIPIO,
    since: object = None,
    until: object = None,
    years: int | None = None,
    today: object = None,
    min_districts: int = MIN_DISTRICTS,
    max_districts: int = MAX_DISTRICTS,
) -> CompareSummary:
    if len(queries) < min_districts:
        raise ValueError(f"Informe pelo menos {min_districts} distritos para comparar.")
    if len(queries) > max_districts:
        raise ValueError(f"Compare no máximo {max_districts} distritos por vez.")

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

    reference = load_reference(settings)
    taxonomy = reference.taxonomy
    if taxonomy is None:  # pragma: no cover - load_reference sempre devolve taxonomia
        raise RuntimeError("Taxonomia indisponível.")
    if "crime_category" not in facts.columns:
        facts["crime_category"] = taxonomy.classify(facts)
    elif facts["crime_category"].isna().any():
        facts["crime_category"] = facts["crime_category"].fillna(taxonomy.default_category.id)

    entries = _bairro_entries(facts, reference)
    resolver = BairroResolver(entries, aliases=reference.aliases)
    resolved = []
    for query in queries:
        hit = resolver.find(query)
        if hit is None:
            raise BairroNotFound(query, resolver.suggestions(query))
        entry, _method, _confidence = hit
        resolved.append(entry)

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
    in_period = (dates >= pd.Timestamp(period.start)) & (
        dates < pd.Timestamp(period.end) + pd.Timedelta(days=1)
    )
    period_frame = facts[in_period]

    city_scores = build_city_scores(
        settings,
        period_frame,
        period=period,
        resolver=resolver,
        reference=reference,
        taxonomy=taxonomy,
        municipio=municipio,
    )

    city_method_counts = period_frame["bairro_method"].value_counts()
    city_rows = len(period_frame)
    city_resolved = sum(int(city_method_counts.get(method, 0)) for method in RESOLVED_METHODS)
    city_resolution_rate = city_resolved / city_rows if city_rows else None
    city_suppressed = int(city_method_counts.get("suppressed", 0))

    districts = []
    for entry in resolved:
        frame = period_frame[period_frame["bairro_id"] == entry.bairro_id]
        population = reference.population_for(entry)
        households = reference.households_for(entry)
        districts.append(
            CompareDistrict(
                bairro_nome=entry.bairro_nome,
                bairro_id=entry.bairro_id,
                total_occurrences=len(frame),
                total_incidents=total_incidents(frame),
                population=population.value,
                categories=summarize_categories(
                    frame,
                    taxonomy,
                    period,
                    population=population.value,
                    households=households.value,
                ),
                score=(
                    city_scores.districts.get(entry.bairro_id)
                    or DistrictScore(bairro_id=entry.bairro_id, bairro_nome=entry.bairro_nome)
                ),
                method_counts={
                    str(method): int(count)
                    for method, count in frame["bairro_method"].value_counts().items()
                },
            )
        )

    return CompareSummary(
        municipio=municipio,
        period=period,
        districts=tuple(districts),
        weights=city_scores.weights,
        taxonomy_provisional=taxonomy.provisional,
        generated_at=datetime.now(),
        city_resolution_rate=city_resolution_rate,
        city_suppressed=city_suppressed,
    )


__all__ = [
    "MAX_DISTRICTS",
    "MIN_DISTRICTS",
    "build_compare",
]
