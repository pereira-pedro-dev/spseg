"""Montagem do resumo por rua a partir do cache sintético."""

from __future__ import annotations

import pytest

from spseg.analysis.street_summary import (
    STREET_EXCLUDED_CATEGORIES,
    NoStreetData,
    build_street_summary,
)
from spseg.analysis.summary import BairroNotFound, CacheMissing
from spseg.geo.street import StreetAmbiguous, StreetNotFound
from tests.helpers import make_street_facts, write_facts


def _seed(settings) -> None:
    write_facts(settings, make_street_facts(), 2024)


def _build(settings, rua: str = "Mourato Coelho", distrito: str = "Pinheiros"):
    return build_street_summary(settings, rua, distrito)


def test_cache_missing_raises(settings):
    with pytest.raises(CacheMissing, match="ingest"):
        _build(settings)


def test_district_not_found_raises(settings):
    _seed(settings)
    with pytest.raises(BairroNotFound):
        _build(settings, distrito="ZZZZZZZZ")


def test_street_summary_counts(settings):
    _seed(settings)
    summary = _build(settings)

    assert summary.nivel == "rua"
    assert summary.rua == "Mourato Coelho"
    assert summary.rua_raw == "RUA MOURATO COELHO"
    assert summary.rua_key == "RUA MOURATO COELHO"
    assert summary.rua_tipo == "RUA"
    assert summary.distrito == "Pinheiros"
    assert summary.distrito_id == "pinheiros"
    assert summary.total_occurrences == 8
    assert summary.total_incidents == 7

    assert summary.district_total_occurrences == 18
    assert summary.district_visible_occurrences == 13
    assert summary.district_coverage == pytest.approx(13 / 18)
    assert summary.share_of_district == pytest.approx(8 / 13)
    assert summary.quality.rows_in_street == 8
    assert summary.quality.rows_in_district == 18
    assert summary.quality.rows_visible == 13
    assert summary.quality.suppressed_logradouro == 2
    assert summary.quality.missing_logradouro == 1
    assert summary.quality.not_visible_occurrences == 5
    assert any("n pequeno" in note for note in summary.quality.notes)


def test_category_shares_and_exclusions(settings):
    _seed(settings)
    summary = _build(settings)

    by_id = {category.id: category for category in summary.categories}
    assert set(by_id) == {"crime_violento", "crime_nao_violento", "outros"}
    assert STREET_EXCLUDED_CATEGORIES.isdisjoint(by_id)

    violent = by_id["crime_violento"]
    assert violent.occurrences == 3
    assert violent.share_of_street == pytest.approx(3 / 8)
    assert violent.share_of_district == pytest.approx(3 / 4)
    assert violent.district_visible_occurrences == 4
    assert violent.top_natures[0] == ("ROUBO - OUTROS", 2)

    assert by_id["crime_nao_violento"].occurrences == 5
    assert by_id["outros"].occurrences == 0
    assert by_id["outros"].share_of_district is None


def test_district_context_has_all_categories(settings):
    _seed(settings)
    summary = _build(settings)

    by_id = {category.id: category for category in summary.district_categories}
    assert set(by_id) == {
        "invasao_residencia",
        "violencia_sexual",
        "crime_violento",
        "crime_nao_violento",
        "outros",
    }
    assert by_id["invasao_residencia"].occurrences == 1
    assert by_id["invasao_residencia"].visible_occurrences == 0
    assert by_id["invasao_residencia"].coverage == 0.0
    assert by_id["violencia_sexual"].occurrences == 1
    assert by_id["crime_violento"].occurrences == 6
    assert by_id["crime_violento"].visible_occurrences == 4
    assert by_id["crime_violento"].coverage == pytest.approx(4 / 6)

    assert summary.district_not_visible_by_category == {
        "invasao_residencia": 1,
        "violencia_sexual": 1,
        "crime_violento": 2,
        "outros": 1,
    }


def test_street_raw_and_fuzzy_note(settings):
    _seed(settings)
    summary = _build(settings, rua="Mourato Coehlo")

    assert summary.rua_key == "RUA MOURATO COELHO"
    assert any("nome aproximado" in note for note in summary.quality.notes)


def test_capri_equipment_note(settings):
    _seed(settings)
    summary = _build(settings, rua="Avenida Capri")

    assert summary.total_occurrences == 5
    assert summary.top_tipo_local[0] == ("Terminal/Estação", 5)
    assert any("equipamento" in note for note in summary.quality.notes)


def test_street_not_found_suggests_same_district(settings):
    _seed(settings)
    with pytest.raises(StreetNotFound) as info:
        _build(settings, rua="Mourato")
    assert info.value.distrito == "Pinheiros"
    assert info.value.suggestions
    assert info.value.suggestions[0][0] == "Rua Mourato Coelho"


def test_street_ambiguous(settings):
    import pandas as pd

    frame = make_street_facts()
    extra = frame.iloc[[0, 0]].copy()
    extra["logradouro"] = ["RUA PAULISTA", "AVENIDA PAULISTA"]
    extra["bo_key"] = ["2024/BO901", "2024/BO902"]
    frame = pd.concat([frame, extra], ignore_index=True)
    write_facts(settings, frame, 2024)

    with pytest.raises(StreetAmbiguous) as info:
        _build(settings, rua="Paulista")
    assert info.value.candidates == ("AVENIDA PAULISTA", "RUA PAULISTA")
    assert info.value.counts == {"AVENIDA PAULISTA": 1, "RUA PAULISTA": 1}


def test_district_without_visible_street_raises(settings):
    frame = make_street_facts()
    frame = frame[frame["crime_category"].isin(STREET_EXCLUDED_CATEGORIES)]
    write_facts(settings, frame, 2024)

    with pytest.raises(NoStreetData):
        _build(settings)


def test_street_in_two_districts(settings):
    import pandas as pd

    frame = make_street_facts()
    extra = frame.iloc[[0]].copy()
    extra["bairro_raw"] = "Vila Mariana"
    extra["bairro_nome"] = "Vila Mariana"
    extra["bairro_id"] = "vila-mariana"
    extra["distrito_id"] = "vila-mariana"
    extra["bo_key"] = "2024/BO902"
    write_facts(settings, pd.concat([frame, extra], ignore_index=True), 2024)

    pinheiros = _build(settings, rua="Rua Mourato Coelho", distrito="Pinheiros")
    vila_mariana = _build(settings, rua="Rua Mourato Coelho", distrito="Vila Mariana")

    assert pinheiros.total_occurrences == 8
    assert vila_mariana.total_occurrences == 1
    assert pinheiros.distrito == "Pinheiros"
    assert vila_mariana.distrito == "Vila Mariana"


def test_no_rates_or_trend_on_street_summary(settings):
    _seed(settings)
    summary = _build(settings)

    assert not hasattr(summary, "population")
    assert not hasattr(summary, "households")
    for category in summary.categories:
        assert not hasattr(category, "rate_per_100k")
        assert not hasattr(category, "trend")
