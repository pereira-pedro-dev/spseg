"""Resolução híbrida: exato, alias, fuzzy e coordenadas."""

from __future__ import annotations

import pandas as pd
import pytest

from spseg.geo.polygons import PolygonIndex
from spseg.geo.resolve import (
    BairroResolver,
    registry_from_entries_frame,
    registry_from_frame,
)
from spseg.models import RegistryEntry
from tests.helpers import write_polygons


@pytest.fixture
def entries() -> list[RegistryEntry]:
    return [
        RegistryEntry("pinheiros", "Pinheiros", "pinheiros"),
        RegistryEntry("vila-mariana", "Vila Mariana", "vila-mariana"),
    ]


def test_exact_match(entries):
    resolver = BairroResolver(entries)
    entry, method, confidence = resolver.find("pinheiros")
    assert entry.bairro_id == "pinheiros"
    assert method == "exact"
    assert confidence == 1.0


def test_exact_match_is_accent_and_case_insensitive(entries):
    resolver = BairroResolver(entries)
    entry, method, _confidence = resolver.find("VILA MARIANÁ")
    assert entry.bairro_id == "vila-mariana"
    assert method == "exact"


def test_alias_match(entries):
    resolver = BairroResolver(entries, aliases={"PIN": "pinheiros"})
    entry, method, _confidence = resolver.find("pin")
    assert entry.bairro_id == "pinheiros"
    assert method == "alias"


def test_alias_to_unknown_bairro_is_ignored(entries):
    resolver = BairroResolver(entries, aliases={"XPTO": "nao-existe"})
    assert resolver.find("XPTO") is None


def test_fuzzy_match_when_close_enough(entries):
    resolver = BairroResolver(entries, threshold=80, margin=1)
    entry, method, confidence = resolver.find("Pinhero")
    assert entry.bairro_id == "pinheiros"
    assert method == "fuzzy"
    assert confidence > 0.8


def test_no_match_returns_none(entries):
    resolver = BairroResolver(entries)
    assert resolver.find("ZZZZZZZZ") is None


def test_suggestions_for_misspelling(entries):
    resolver = BairroResolver(entries)
    suggestions = resolver.suggestions("Pinhero")
    assert suggestions
    assert suggestions[0][0] == "Pinheiros"


def test_resolve_frame_marks_resolved_and_unresolved(entries):
    frame = pd.DataFrame(
        {
            "bairro_raw": ["Pinheiros", "Lugar Nenhum"],
            "latitude": [None, None],
            "longitude": [None, None],
        }
    )
    resolved = BairroResolver(entries).resolve_frame(frame)
    assert resolved["bairro_method"].tolist() == ["exact", "unresolved"]
    assert resolved["bairro_id"].iloc[0] == "pinheiros"
    assert pd.isna(resolved["bairro_id"].iloc[1])


def test_resolve_frame_marks_suppressed_location(entries):
    frame = pd.DataFrame(
        {"bairro_raw": ["VEDAÇÃO DA DIVULGAÇÃO"], "latitude": [None], "longitude": [None]}
    )
    resolved = BairroResolver(entries).resolve_frame(frame)
    assert resolved["bairro_method"].tolist() == ["suppressed"]
    assert pd.isna(resolved["bairro_id"].iloc[0])


def test_resolve_frame_uses_geo_fallback(settings, entries):
    write_polygons(settings)
    polygons = PolygonIndex.from_geojson(settings.reference_dir / "bairros_sp.geojson")
    frame = pd.DataFrame(
        {
            "bairro_raw": ["Lugar Nenhum", "Outro Lugar"],
            "latitude": [-23.56, -23.59],
            "longitude": [-46.70, -46.63],
        }
    )
    resolved = BairroResolver(entries, polygons=polygons).resolve_frame(frame)
    assert resolved["bairro_method"].tolist() == ["geo", "geo"]
    assert resolved["bairro_id"].tolist() == ["pinheiros", "vila-mariana"]


def test_geo_fallback_ignores_invalid_coordinates(settings, entries):
    write_polygons(settings)
    polygons = PolygonIndex.from_geojson(settings.reference_dir / "bairros_sp.geojson")
    frame = pd.DataFrame(
        {
            "bairro_raw": ["Lugar Nenhum"],
            "latitude": [0.0],
            "longitude": [0.0],
        }
    )
    resolved = BairroResolver(entries, polygons=polygons).resolve_frame(frame)
    assert resolved["bairro_method"].tolist() == ["unresolved"]


def test_registry_from_frame_collapses_variants():
    frame = pd.DataFrame(
        {"bairro_raw": ["Pinheiros", "PINHEIROS", "Vila Mariana", "VEDAÇÃO DA DIVULGAÇÃO"]}
    )
    entries = registry_from_frame(frame)
    by_key = {entry.bairro_id for entry in entries}
    assert "pinheiros" in by_key
    assert "vila-mariana" in by_key
    assert len(entries) == 2


def test_registry_from_entries_frame_prefers_existing_ids():
    frame = pd.DataFrame(
        {
            "bairro_id": ["pinheiros", "pinheiros", None],
            "bairro_nome": ["Pinheiros", "Pinheiros", None],
            "distrito_id": ["pinheiros", "pinheiros", None],
        }
    )
    entries = registry_from_entries_frame(frame)
    assert len(entries) == 1
    assert entries[0].bairro_id == "pinheiros"


def test_registry_from_entries_frame_uses_most_common_spelling():
    frame = pd.DataFrame(
        {
            "bairro_id": ["pinheiros", "pinheiros", "pinheiros"],
            "bairro_nome": ["PINHEIROS", "Pinheiros", "Pinheiros"],
            "distrito_id": [None, "pinheiros", None],
        }
    )
    entries = registry_from_entries_frame(frame)
    assert entries[0].bairro_nome == "Pinheiros"
    assert entries[0].distrito_id == "pinheiros"
