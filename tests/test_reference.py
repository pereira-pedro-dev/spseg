"""Loader da referência por distrito."""

from __future__ import annotations

import json

from spseg.data.reference import load_reference
from tests.helpers import polygon_features


def _write_geojson(settings, features: list[dict]) -> None:
    payload = {"type": "FeatureCollection", "features": features}
    (settings.reference_dir / "distritos_sp.geojson").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def test_load_reference_reads_distritos_and_flags_count(settings):
    _write_geojson(settings, polygon_features())
    reference = load_reference(settings)

    assert reference.status.distritos
    assert {entry.bairro_id for entry in reference.entries} == {"pinheiros", "vila-mariana"}
    assert any("esperado 96" in issue for issue in reference.status.issues)


def test_load_reference_flags_missing_distrito_id(settings):
    features = polygon_features()
    for feature in features:
        feature["properties"].pop("distrito_id")
    _write_geojson(settings, features)

    reference = load_reference(settings)

    assert reference.status.distritos
    assert any("sem distrito_id" in issue for issue in reference.status.issues)
