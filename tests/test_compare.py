"""`spseg compare`: mesma janela, scores e contrato JSON."""

from __future__ import annotations

import pytest

from spseg.analysis.compare import MAX_DISTRICTS, MIN_DISTRICTS, build_compare
from spseg.analysis.summary import BairroNotFound, CacheMissing, build_summary
from tests.helpers import (
    make_city_facts,
    write_facts,
    write_population_multi,
    write_taxonomy,
)

# Cidade sintética: três distritos com níveis bem distintos, todos elegíveis
# (n >= 25 nas duas categorias) e população de 100 mil.Taxas ponderadas por
# 100 mil: 5×n (violento) e 2×n (não violento).Com 3 distritos, os percentis
# das duas categorias coincidem: 1/3 / 2/3 / 1,0. Pesos 5:2 renormalizam para
# o mesmo valor → scores 1/3 (Itaim, 1º), 2/3 (Moema, 2º) e 1,0 (Pinheiros, 3º).
CITY = (
    ("pinheiros", "Pinheiros", 120, 120),
    ("moema", "Moema", 60, 60),
    ("itaim", "Itaim", 30, 30),
)
POPULATION = (
    ("pinheiros", "Pinheiros", 100_000, 50_000),
    ("moema", "Moema", 100_000, 50_000),
    ("itaim", "Itaim", 100_000, 50_000),
)


def _seed(settings) -> None:
    write_facts(settings, make_city_facts(CITY), 2024)
    write_population_multi(settings, POPULATION)
    write_taxonomy(settings)


def test_bounds_are_two_to_six():
    assert MIN_DISTRICTS == 2
    assert MAX_DISTRICTS == 6


def test_too_few_districts_raises():
    # A validação de aridade acontece antes de qualquer IO.
    with pytest.raises(ValueError, match="pelo menos 2"):
        build_compare(object(), ["Pinheiros"])


def test_too_many_districts_raises():
    queries = [f"Q{i:02d}" for i in range(MAX_DISTRICTS + 1)]
    with pytest.raises(ValueError, match="no máximo 6"):
        build_compare(object(), queries)


def test_compare_without_cache_raises(settings):
    with pytest.raises(CacheMissing, match="ingest"):
        build_compare(settings, ["Pinheiros", "Moema"])


def test_unknown_district_raises_with_suggestions(settings):
    _seed(settings)
    with pytest.raises(BairroNotFound) as excinfo:
        build_compare(settings, ["Pinheiros", "ZZZZZZZZ"])
    assert excinfo.value.query == "ZZZZZZZZ"


def test_compare_succeeds_with_three_districts(settings):
    _seed(settings)
    summary = build_compare(settings, ["Pinheiros", "Moema", "Itaim"])

    assert summary.municipio == "São Paulo"
    assert len(summary.districts) == 3
    assert [district.bairro_nome for district in summary.districts] == [
        "Pinheiros",
        "Moema",
        "Itaim",
    ]

    counts = {district.bairro_nome: district.total_occurrences for district in summary.districts}
    assert counts == {"Pinheiros": 240, "Moema": 120, "Itaim": 60}

    # Scores e postos coerentes com as taxas ponderadas.
    by_name = {district.bairro_nome: district for district in summary.districts}
    assert by_name["Pinheiros"].score.value == pytest.approx(1.0)
    assert by_name["Pinheiros"].score.rank == 3
    assert by_name["Moema"].score.value == pytest.approx(2 / 3)
    assert by_name["Moema"].score.rank == 2
    assert by_name["Itaim"].score.value == pytest.approx(1 / 3)
    assert by_name["Itaim"].score.rank == 1
    for district in summary.districts:
        assert district.score.of == 3
        assert district.score.weights.declared is True

    # Qualidade da cidade na janela (todos os registros resolvem para um distrito).
    assert summary.city_resolution_rate == pytest.approx(1.0)
    assert summary.city_suppressed == 0


def test_compare_category_below_floor_leaves_percentile(settings):
    # Itaim com violentos < 25: essa categoria sai do percentil dele e a
    # cobertura de peso cai para 2/7.
    write_facts(
        settings,
        make_city_facts((("pinheiros", "Pinheiros", 120, 120), ("itaim", "Itaim", 10, 30))),
        2024,
    )
    write_population_multi(settings, (POPULATION[0], POPULATION[2]))
    write_taxonomy(settings)
    summary = build_compare(settings, ["Pinheiros", "Itaim"])

    itaim = next(district for district in summary.districts if district.bairro_nome == "Itaim")
    by_id = {category.id: category for category in itaim.score.categories}
    assert by_id["crime_violento"].percentile is None
    assert by_id["crime_violento"].occurrences == 10
    assert itaim.score.weight_coverage == pytest.approx(2 / 7)


def test_compare_matches_summary_scores(settings):
    _seed(settings)
    compare_summary = build_compare(settings, ["Pinheiros", "Moema"])
    pinheiros_summary = build_summary(settings, "Pinheiros")
    moema_summary = build_summary(settings, "Moema")

    compare_pinheiros = next(
        district for district in compare_summary.districts if district.bairro_nome == "Pinheiros"
    )
    compare_moema = next(
        district for district in compare_summary.districts if district.bairro_nome == "Moema"
    )
    assert compare_pinheiros.score.value == pinheiros_summary.score.value
    assert compare_pinheiros.score.rank == pinheiros_summary.score.rank
    assert compare_moema.score.value == moema_summary.score.value
    assert compare_moema.score.rank == moema_summary.score.rank
