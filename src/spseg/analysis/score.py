"""Score de segurança relativo à cidade (percentil/posto entre os distritos).

O score é um agregado provisório e explícito:
- taxa ponderada por natureza (pesos declarados em `crime_taxonomy.yml`);
- percentil da taxa entre os distritos elegíveis, na mesma janela;
- composição ponderada dos percentis, com renormalização quando uma
  categoria cai pelo piso de `n`.

Política de `n/d`: distrito sem população fica fora dos percentis (nunca
chutado). Exatamente 0 ocorrências é observação real e entra no percentil;
1–24 casos ficam fora do percentil daquela categoria, porque a taxa com
poucos casos é ruído. O score só sai quando sobra peso elegível o bastante.
"""

from __future__ import annotations

from collections import Counter

import pandas as pd

from spseg.analysis.taxonomy import NaturezaWeights, Taxonomy, natureza_key
from spseg.config import (
    SCORE_MIN_CATEGORY_CASES,
    SCORE_MIN_WEIGHT_COVERAGE,
    Settings,
)
from spseg.data.reference import ReferenceData
from spseg.geo.resolve import BairroResolver
from spseg.models import (
    CategoryScore,
    CityScores,
    DistrictScore,
    Period,
)

UNKNOWN_NATUREZA_LIMIT = 5


def _fmt_pct(value: float) -> str:
    return f"{value:.0%}".replace(".", ",")


def _empty_city_scores(
    municipio: str,
    period: Period,
    total_districts: int,
    weights: NaturezaWeights,
    taxonomy: Taxonomy,
    notes: list[str],
) -> CityScores:
    return CityScores(
        municipio=municipio,
        period=period,
        total_districts=total_districts,
        scored=0,
        weights=weights,
        taxonomy_provisional=taxonomy.provisional,
        districts={},
        notes=tuple(notes),
    )


def _dropped_notes(dropped: dict[str, int], minimum: int) -> tuple[str, ...]:
    return tuple(
        f"{label} com n={count} (abaixo do piso de {minimum}): fora do percentil dessa categoria."
        for label, count in sorted(dropped.items())
    )


def build_city_scores(
    settings: Settings,
    facts: pd.DataFrame,
    *,
    period: Period,
    resolver: BairroResolver,
    reference: ReferenceData,
    taxonomy: Taxonomy,
    municipio: str,
    min_category_cases: int = SCORE_MIN_CATEGORY_CASES,
    min_weight_coverage: float = SCORE_MIN_WEIGHT_COVERAGE,
) -> CityScores:
    """Baseline da cidade para o score relativo.

    `facts` já deve estar recortado por município e janela, com
    `crime_category` preenchido. Não reabre o parquet: recebe os insumos já
    carregados pelo chamador.
    """
    weights = taxonomy.weights or NaturezaWeights(padrao=1.0, declared=False)
    entries = list(resolver.entries.values())
    entry_by_id = {entry.bairro_id: entry for entry in entries}
    total_districts = len(entries)

    city_notes: list[str] = []
    if not weights.declared:
        city_notes.append(
            "Pesos não declarados em crime_taxonomy.yml: score calculado com "
            "peso 1 para todas as naturezas, o que trata homicídio como furto. "
            "Declare o bloco `pesos` para um score diferenciado."
        )

    population_by_id: dict[str, int | None] = {}
    for entry in entries:
        pop = reference.population_for(entry).value
        population_by_id[entry.bairro_id] = pop
        if pop is None:
            city_notes.append(
                f"Sem população para {entry.bairro_nome}: taxa n/d e distrito fora dos percentis."
            )

    registered = (
        facts[facts["bairro_id"].notna()] if "bairro_id" in facts.columns else facts.head(0)
    )
    if not registered.empty:
        registered = registered[registered["crime_category"].notna()]
    if not entries or registered.empty:
        return _empty_city_scores(municipio, period, total_districts, weights, taxonomy, city_notes)

    has_natureza = "natureza" in registered.columns
    natureza_raw = (
        registered["natureza"].astype("string").fillna("")
        if has_natureza
        else pd.Series("", index=registered.index, dtype="string")
    )
    natureza_keys = natureza_raw.map(natureza_key)
    mapped = weights.por_natureza

    subset = pd.DataFrame(
        {
            "bairro_id": registered["bairro_id"].astype("string"),
            "crime_category": registered["crime_category"].astype("string"),
            "_peso": (
                natureza_keys.map(lambda key: mapped.get(key))
                .fillna(weights.padrao)
                .astype("float64")
            ),
        }
    )
    unknown_counts = Counter(
        str(key)
        for key, is_unknown in zip(
            natureza_keys,
            natureza_keys.map(lambda key: key not in mapped),
            strict=True,
        )
        if is_unknown and key
    )
    if unknown_counts:
        top = ", ".join(
            f"{key} ({count})" for key, count in unknown_counts.most_common(UNKNOWN_NATUREZA_LIMIT)
        )
        city_notes.append(
            f"{len(unknown_counts)} naturezas fora da tabela de pesos recebem "
            f"peso padrão {weights.padrao:g}: {top}."
        )

    group = subset.groupby(["bairro_id", "crime_category"], dropna=True, observed=True)
    occurrences = group.size()
    weighted = group["_peso"].sum()
    if "bo_key" in registered.columns:
        incident_frame = pd.DataFrame(
            {
                "bairro_id": subset["bairro_id"],
                "crime_category": subset["crime_category"],
                "bo_key": registered["bo_key"].astype("string").fillna(""),
            }
        )
        incidents = incident_frame.groupby(
            ["bairro_id", "crime_category"], dropna=True, observed=True
        )["bo_key"].apply(lambda values: values.ne("").nunique())
    else:
        incidents = occurrences

    # naturezas observadas por categoria na cidade inteira — base do peso da
    # categoria, independente do distrito (n=0 não perde peso).
    unique_pairs = pd.DataFrame(
        {"crime_category": subset["crime_category"], "natureza": natureza_keys}
    ).drop_duplicates()
    natureza_by_category: dict[str, set[str]] = {}
    for category_id, natureza_value in zip(
        unique_pairs["crime_category"], unique_pairs["natureza"], strict=True
    ):
        if natureza_value:
            natureza_by_category.setdefault(str(category_id), set()).add(str(natureza_value))

    category_weight: dict[str, float] = {
        category.id: float(
            sum(
                mapped.get(key, weights.padrao)
                for key in natureza_by_category.get(category.id, set())
            )
        )
        for category in taxonomy.categories
    }
    total_weight = float(sum(category_weight.values()))

    if total_weight <= 0:
        city_notes.append("Sem naturezas com peso válido no período.")
        return _empty_city_scores(municipio, period, total_districts, weights, taxonomy, city_notes)

    all_ids = list(entry_by_id)

    # percentis por categoria: taxa ponderada entre os distritos elegíveis
    # (população presente e n == 0 ou n >= piso).
    percentile_by_category: dict[str, dict[str, float]] = {}
    for category in taxonomy.categories:
        category_id = category.id
        eligible_ids: list[str] = []
        rates: list[float] = []
        for district_id in all_ids:
            count = int(occurrences.get((district_id, category_id), 0))
            pop = population_by_id.get(district_id)
            if pop is None or not (count == 0 or count >= min_category_cases):
                continue
            eligible_ids.append(district_id)
            weight = float(weighted.get((district_id, category_id), 0.0))
            rates.append(weight / pop * 100_000.0)
        pool = pd.Series(rates, index=eligible_ids, dtype="float64")
        if len(pool) > 1:
            rank_pct = pool.rank(method="average", pct=True)
            percentile_by_category[category_id] = {
                district_id: float(rank_pct[district_id]) for district_id in eligible_ids
            }
        elif eligible_ids:
            percentile_by_category[category_id] = {eligible_ids[0]: 1.0}
        else:
            percentile_by_category[category_id] = {}

    values: dict[str, float] = {}
    district_scores: dict[str, DistrictScore] = {}
    for district_id, entry in entry_by_id.items():
        no_population = population_by_id.get(district_id) is None
        category_scores: list[CategoryScore] = []
        dropped: dict[str, int] = {}
        available_weight = 0.0
        weighted_total = 0.0

        for category in taxonomy.categories:
            category_id = category.id
            count = int(occurrences.get((district_id, category_id), 0))
            pop = population_by_id.get(district_id)
            percentile = percentile_by_category.get(category_id, {}).get(district_id)
            note: str | None = None
            if no_population:
                note = "Sem população na referência: taxa n/d e fora do percentil."
            elif 0 < count < min_category_cases:
                note = (
                    f"n={count} (abaixo do piso de {min_category_cases}): fora do "
                    "percentil dessa categoria."
                )
                dropped[category.label] = count
            weighted_occurrences = float(weighted.get((district_id, category_id), 0.0))
            category_scores.append(
                CategoryScore(
                    id=category_id,
                    label=category.label,
                    occurrences=count,
                    incidents=int(incidents.get((district_id, category_id), 0)),
                    rate_per_100k=(count / pop * 100_000.0) if pop else None,
                    weighted_occurrences=weighted_occurrences,
                    weighted_rate_per_100k=(
                        weighted_occurrences / pop * 100_000.0 if pop else None
                    ),
                    percentile=percentile,
                    eligible=percentile is not None,
                    notes=(note,) if note else (),
                )
            )
            if percentile is not None:
                available_weight += category_weight[category_id]
                weighted_total += percentile * category_weight[category_id]

        coverage = available_weight / total_weight if total_weight else None
        score_available = (
            not no_population
            and coverage is not None
            and coverage >= min_weight_coverage
            and available_weight > 0
        )
        if score_available:
            values[district_id] = weighted_total / available_weight

        notes: list[str] = []
        if no_population:
            notes.append("Sem população na referência: taxa n/d e fora dos percentis.")
        elif coverage is not None and coverage < min_weight_coverage:
            notes.append(
                f"Peso elegível {_fmt_pct(coverage)} abaixo do mínimo "
                f"({_fmt_pct(min_weight_coverage)}): score n/d para este distrito."
            )
        elif coverage is not None and coverage < 1:
            notes.append(f"Peso elegível {_fmt_pct(coverage)}: algumas categorias ficaram fora.")
        notes.extend(_dropped_notes(dropped, min_category_cases))

        district_scores[district_id] = DistrictScore(
            bairro_id=district_id,
            bairro_nome=entry.bairro_nome,
            available=score_available,
            value=values.get(district_id),
            rank=None,
            of=0,  # preenchido abaixo
            weight_coverage=coverage,
            weights=weights,
            categories=tuple(category_scores),
            notes=tuple(note for note in notes if note),
        )

    scored_count = len(values)
    rank_series = pd.Series(values, dtype="float64")
    ranking = rank_series.rank(method="min", ascending=True) if values else None
    for district_id, score in district_scores.items():
        value = values.get(district_id)
        district_scores[district_id] = DistrictScore(
            bairro_id=score.bairro_id,
            bairro_nome=score.bairro_nome,
            available=value is not None,
            value=value,
            rank=(int(ranking[district_id]) if ranking is not None and value is not None else None),
            of=scored_count,
            weight_coverage=score.weight_coverage,
            weights=score.weights,
            categories=score.categories,
            notes=score.notes,
        )

    return CityScores(
        municipio=municipio,
        period=period,
        total_districts=total_districts,
        scored=scored_count,
        weights=weights,
        taxonomy_provisional=taxonomy.provisional,
        districts=district_scores,
        notes=tuple(city_notes),
    )
