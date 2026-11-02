"""Montagem do resumo a partir do cache sintético."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from spseg.analysis.summary import BairroNotFound, CacheMissing, build_summary
from tests.helpers import make_facts, write_facts, write_population


def _seed(settings, *, with_category: bool = False) -> None:
    frame = make_facts()
    if not with_category:
        frame = frame.drop(columns=["crime_category"])
    write_facts(settings, frame, 2024)


def test_cache_missing_raises(settings):
    with pytest.raises(CacheMissing, match="ingest"):
        build_summary(settings, "Pinheiros")


def test_summary_without_denominators(settings):
    _seed(settings)
    summary = build_summary(settings, "pinheiros", today=date(2026, 11, 1))

    assert summary.bairro_id == "pinheiros"
    assert summary.bairro_nome == "Pinheiros"
    assert summary.nivel == "distrito"
    assert summary.total_occurrences == 60
    assert summary.total_incidents == 60
    assert summary.population is None
    assert summary.households is None
    assert summary.denominator_level is None
    assert all(category.rate_per_100k is None for category in summary.categories)
    assert summary.quality.rows_in_bairro == 60
    assert summary.quality.resolution_rate == 1.0
    assert summary.quality.method_counts == {"exact": 60}
    assert summary.taxonomy_provisional is True
    assert any("populacao_bairro.csv" in note for note in summary.quality.notes)
    assert any("cache cobre apenas 2024" in note for note in summary.quality.notes)


def test_summary_with_denominators_computes_rates(settings):
    _seed(settings)
    write_population(settings)

    summary = build_summary(settings, "Pinheiros", today=date(2026, 11, 1))

    assert summary.population == 100_000
    assert summary.households == 50_000
    assert summary.denominator_level == "bairro"
    assert summary.denominator_source == "Censo teste"
    assert round(sum(c.rate_per_100k for c in summary.categories), 6) == 60.0
    assert round(sum(c.rate_per_10k_households for c in summary.categories), 6) == 12.0
    assert not any("populacao_bairro.csv" in note for note in summary.quality.notes)


def test_summary_uses_period_window(settings):
    _seed(settings)
    summary = build_summary(
        settings,
        "Pinheiros",
        since=date(2025, 1, 1),
        until=date(2025, 12, 31),
        today=date(2026, 11, 1),
    )
    assert summary.period.start == date(2025, 1, 1)
    assert summary.period.end == date(2025, 12, 31)
    assert summary.period.partial is False
    assert summary.total_occurrences == 24


def test_unknown_bairro_raises_with_suggestions(settings):
    _seed(settings)
    with pytest.raises(BairroNotFound) as excinfo:
        build_summary(settings, "ZZZZZZZZ", today=date(2026, 11, 1))
    assert excinfo.value.query == "ZZZZZZZZ"
    assert excinfo.value.suggestions == []


def test_other_municipality_is_empty(settings):
    _seed(settings)
    with pytest.raises(CacheMissing, match="município"):
        build_summary(settings, "Pinheiros", municipio="Campinas")


def test_summary_notes_missing_tipo_local(settings):
    frame = make_facts()
    frame.loc[frame.index[:40], "tipo_local"] = pd.NA
    write_facts(settings, frame.drop(columns=["crime_category"]), 2024)

    summary = build_summary(settings, "Pinheiros", today=date(2026, 11, 1))

    assert any("tipo de local ausente" in note for note in summary.quality.notes)


def test_summary_uses_distrito_level_denominator(settings):
    frame = make_facts(bairro_id="355030862")
    frame["distrito_id"] = "355030862"
    write_facts(settings, frame, 2024)
    write_population(settings, bairro_id="355030862", nivel="distrito")

    summary = build_summary(settings, "Pinheiros", today=date(2026, 11, 1))

    assert summary.bairro_id == "355030862"
    assert summary.denominator_level == "distrito"
    assert summary.denominator_source == "Censo teste"
    assert summary.population == 100_000
    assert all(category.rate_per_100k is not None for category in summary.categories)


def test_summary_flags_low_city_resolution_as_floor(settings):
    frame = make_facts()
    frame.loc[frame.index[:10], "bairro_method"] = "unresolved"
    frame.loc[frame.index[:10], "bairro_id"] = pd.NA
    write_facts(settings, frame, 2024)

    summary = build_summary(settings, "Pinheiros", today=date(2026, 11, 1))

    assert summary.quality.resolution_rate is not None
    assert summary.quality.resolution_rate < 0.98
    assert any("piso" in note for note in summary.quality.notes)
