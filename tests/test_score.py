"""Score relativo à cidade: percentis, piso por categoria, renormalização, posto."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from spseg.analysis.score import build_city_scores
from spseg.analysis.taxonomy import (
    DEFAULT_TAXONOMY_DATA,
    taxonomy_from_dict,
)
from spseg.data.reference import ReferenceData
from spseg.geo.resolve import BairroResolver
from spseg.models import Period, RegistryEntry
from tests.helpers import make_city_facts

# Pesos de teste: violento 5, não violento 2 (total 7).
WEIGHTED_TAXONOMY = taxonomy_from_dict(
    {
        **DEFAULT_TAXONOMY_DATA,
        "pesos": {
            "peso_padrao": 1,
            "por_natureza": {"ROUBO - OUTROS": 5, "FURTO - OUTROS": 2},
        },
    }
)

PERIOD = Period(start=date(2024, 1, 1), end=date(2024, 12, 31), label="2024")

# Cidade A: todos os distritos elegíveis nas duas categorias.
# Taxas ponderadas por 100 mil (pop 100.000): 5×n e 2×n.
# Percentis idênticos nas duas categorias → score = percentil:
# vazia 0,25 / baixa 0,50 / media 0,75 / alta 1,00.
CITY_A = (
    ("vazia", "Vazia", 0, 0),
    ("baixa", "Baixa", 30, 30),
    ("media", "Media", 60, 60),
    ("alta", "Alta", 120, 120),
)


def _reference(districts, *, missing_population: str | None = None) -> ReferenceData:
    from spseg.data.reference import Denominator

    population = {}
    for district_id, _nome, _v, _nv in districts:
        if district_id == missing_population:
            continue
        population[("bairro", district_id)] = Denominator(
            value=100_000, level="bairro", source="Censo teste"
        )
    return ReferenceData(population=population, taxonomy=WEIGHTED_TAXONOMY)


def _resolver(districts) -> BairroResolver:
    entries = [
        RegistryEntry(bairro_id=district_id, bairro_nome=nome, distrito_id=district_id)
        for district_id, nome, _v, _nv in districts
    ]
    return BairroResolver(entries, aliases={})


def _run(
    districts,
    facts=None,
    *,
    taxonomy=WEIGHTED_TAXONOMY,
    missing_population: str | None = None,
    **kwargs,
):
    if facts is None:
        facts = make_city_facts(districts)
    return build_city_scores(
        object(),  # settings não é usado pelo motor
        facts,
        period=PERIOD,
        resolver=_resolver(districts),
        reference=_reference(districts, missing_population=missing_population),
        taxonomy=taxonomy,
        municipio="São Paulo",
        **kwargs,
    )


def test_percentiles_and_ranking():
    scores = _run(CITY_A)

    assert scores.total_districts == 4
    assert scores.scored == 4
    assert not scores.notes

    expected = {"vazia": 0.25, "baixa": 0.5, "media": 0.75, "alta": 1.0}
    for district_id, value in expected.items():
        score = scores.districts[district_id]
        assert score.available is True
        assert score.value == pytest.approx(value)
        assert score.of == 4

    # Posto ascendente: 1º = mais seguro (menor score).
    assert scores.districts["vazia"].rank == 1
    assert scores.districts["baixa"].rank == 2
    assert scores.districts["media"].rank == 3
    assert scores.districts["alta"].rank == 4

    alta = scores.districts["alta"].categories
    by_id = {category.id: category for category in alta}
    assert by_id["crime_violento"].occurrences == 120
    assert by_id["crime_violento"].percentile == pytest.approx(1.0)
    assert by_id["crime_violento"].weighted_rate_per_100k == pytest.approx(600.0)
    assert by_id["crime_violento"].rate_per_100k == pytest.approx(120.0)


def test_zero_occurrences_is_eligible_and_protects_the_top():
    scores = _run(CITY_A)

    score = scores.districts["vazia"]
    assert score.available is True
    assert score.value == pytest.approx(0.25)
    assert score.rank == 1

    by_id = {category.id: category for category in score.categories}
    assert by_id["crime_violento"].occurrences == 0
    assert by_id["crime_violento"].eligible is True
    assert by_id["crime_violento"].percentile == pytest.approx(0.25)
    assert not by_id["crime_violento"].notes


def test_below_floor_drops_category_and_renormalizes():
    # Cidade B: acrescenta um distrito com 10 violentos (< 25) e 40 não violentos.
    city_b = (*CITY_A, ("pequena", "Pequena", 10, 40))
    facts = make_city_facts(city_b)

    # Cobertura default (60%): 5/7 do peso fica fora → score n/d.
    scores = _run(city_b, facts, min_weight_coverage=0.6)
    pequena = scores.districts["pequena"]
    assert pequena.available is False
    assert pequena.value is None
    assert pequena.weight_coverage == pytest.approx(2 / 7)
    assert any("abaixo do mínimo" in note for note in pequena.notes)
    # Categoria com 1 <= n < 25 sai do percentil, com nota.
    by_id = {category.id: category for category in pequena.categories}
    assert by_id["crime_violento"].percentile is None
    assert by_id["crime_violento"].eligible is False
    assert any("n=10" in note for note in by_id["crime_violento"].notes)
    assert by_id["crime_nao_violento"].eligible is True

    # Cobertura mínima menor (25%): o peso restante é renormalizado e o score sai.
    scores_minor = _run(city_b, facts, min_weight_coverage=0.25)
    assert scores_minor.districts["pequena"].available is True
    # Só o percentil de crime_nao_violento (0,6 entre 5 distritos) entra.
    assert scores_minor.districts["pequena"].value == pytest.approx(0.6)
    assert scores_minor.districts["pequena"].weight_coverage == pytest.approx(2 / 7)
    # Posto: vazia ≈ 0,236 ; baixa ≈ 0,471 ; pequena 0,6 → 3º mais seguro.
    assert scores_minor.districts["vazia"].rank == 1
    assert scores_minor.districts["baixa"].rank == 2
    assert scores_minor.districts["pequena"].rank == 3


def test_taxonomia_sem_pesos_usa_peso_igual_com_nota():
    taxonomy = taxonomy_from_dict(DEFAULT_TAXONOMY_DATA)  # sem bloco pesos
    city = (*CITY_A, ("pequena", "Pequena", 10, 40))
    facts = make_city_facts(city)
    scores = _run(
        city,
        facts,
        taxonomy=taxonomy,
        min_category_cases=5,
        min_weight_coverage=0.5,
    )
    # Sem pesos declarados: nota na cidade; com min_category_cases=5, pequena
    # fica elegível nas duas categorias (10 e 40) e entra no percentil.
    assert any("Pesos não declarados" in note for note in scores.notes)
    pequena = scores.districts["pequena"]
    assert pequena.available is True
    assert pequena.weights.declared is False


def test_district_without_population_stays_out_and_gets_n_d():
    scores = _run(CITY_A, missing_population="alta")

    alta = scores.districts["alta"]
    assert alta.available is False
    assert alta.value is None
    assert alta.rank is None
    assert any("Sem população" in note for note in alta.notes)
    by_id = {category.id: category for category in alta.categories}
    assert by_id["crime_violento"].rate_per_100k is None
    assert by_id["crime_violento"].percentile is None

    # Os demais distritos continuam com percentis entre os 3 elegíveis.
    vazia = scores.districts["vazia"]
    assert vazia.available is True
    assert vazia.value == pytest.approx(1 / 3)

    # Nota de cidade registra o distrito sem população.
    assert any("Alta" in note for note in scores.notes)


def test_score_is_deterministic():
    # Chamadas idênticas produzem os mesmos valores e postos.
    city = (*CITY_A, ("pequena", "Pequena", 10, 40))
    facts = make_city_facts(city)
    taxonomy = taxonomy_from_dict(
        {
            **DEFAULT_TAXONOMY_DATA,
            "pesos": {"peso_padrao": 1, "por_natureza": {"ROUBO - OUTROS": 5, "FURTO - OUTROS": 2}},
        }
    )
    left = _run(city, facts, taxonomy=taxonomy, min_weight_coverage=0.25)
    right = _run(city, facts, taxonomy=taxonomy, min_weight_coverage=0.25)
    for district_id in left.districts:
        assert left.districts[district_id].value == right.districts[district_id].value
        assert left.districts[district_id].rank == right.districts[district_id].rank


def test_unknown_natureza_gets_default_weight_with_note():
    facts = make_city_facts(CITY_A)
    extra = pd.DataFrame(
        {
            "bairro_id": ["baixa"] * 5,
            "crime_category": ["outros"] * 5,
            "natureza": ["TRAFICO DE ENTORPECENTES"] * 5,
            "bo_key": [f"2024/X{i}" for i in range(5)],
        }
    )
    combined = pd.concat([facts, extra], ignore_index=True)
    scores = _run(CITY_A, combined, min_weight_coverage=0.3)

    assert any("TRAFICO DE ENTORPECENTES" in note for note in scores.notes)
    baixa = scores.districts["baixa"]
    by_id = {category.id: category for category in baixa.categories}
    assert by_id["outros"].occurrences == 5
    # n=5 < 25 → fora do percentil; pesos das demais categorias renormalizam.
    assert by_id["outros"].percentile is None
    assert baixa.available is True


def test_no_registered_facts_returns_empty_scores():
    empty = make_city_facts((("vazia", "Vazia", 0, 0),))
    resolver = _resolver(CITY_A)
    scores = build_city_scores(
        object(),
        empty[empty["bairro_id"].isna()] if "bairro_id" in empty.columns else empty,
        period=PERIOD,
        resolver=resolver,
        reference=_reference(CITY_A),
        taxonomy=WEIGHTED_TAXONOMY,
        municipio="São Paulo",
    )
    assert scores.scored == 0
    assert scores.districts == {}
