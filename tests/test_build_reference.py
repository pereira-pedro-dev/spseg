"""Contrato e validações de `scripts/build_reference.py`."""

from __future__ import annotations

import csv
import io
import json
import zipfile
from pathlib import Path

import pytest

from scripts import build_reference as builder


def _feature(name: str, *, lon: float = -46.70, lat: float = -23.56) -> dict:
    size = 0.02
    ring = [
        [lon - size, lat - size],
        [lon + size, lat - size],
        [lon + size, lat + size],
        [lon - size, lat + size],
        [lon - size, lat - size],
    ]
    return {
        "type": "Feature",
        "properties": {"nm_distrito_municipal": name},
        "geometry": {"type": "Polygon", "coordinates": [ring]},
    }


def _write_geojson(path: Path, features: list[dict]) -> None:
    payload = {"type": "FeatureCollection", "features": features}
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_ibge_zip(path: Path, rows: list[list[str]]) -> None:
    header = ["CD_MUN", "CD_DIST", "NM_DIST", "v0001", "v0007", "v0002"]
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", quoting=csv.QUOTE_ALL)
    writer.writerow(header)
    writer.writerows(rows)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("agregados.csv", buffer.getvalue().encode("latin-1"))


@pytest.fixture
def expected_two(monkeypatch):
    monkeypatch.setattr(builder, "EXPECTED_UNITS", 2)


def test_load_geosampa_reads_features(tmp_path, expected_two):
    path = tmp_path / "distritos.geojson"
    _write_geojson(path, [_feature("Um"), _feature("Dois")])

    units = builder.load_geosampa(path)

    assert [name for name, _geometry in units] == ["Um", "Dois"]


def test_load_geosampa_rejects_duplicate_and_incomplete(tmp_path, expected_two):
    duplicate = tmp_path / "duplicado.geojson"
    _write_geojson(duplicate, [_feature("Um"), _feature("UM")])
    with pytest.raises(SystemExit, match="duplicado"):
        builder.load_geosampa(duplicate)

    incomplete = tmp_path / "incompleto.geojson"
    no_geometry = _feature("Um")
    no_geometry["geometry"] = None
    _write_geojson(incomplete, [no_geometry, _feature("Dois")])
    with pytest.raises(SystemExit, match="sem nome ou geometria"):
        builder.load_geosampa(incomplete)


def test_load_ibge_parses_latin1_semicolon_and_decimal_comma(tmp_path, expected_two):
    path = tmp_path / "ibge.zip"
    _write_ibge_zip(
        path,
        [
            ["3550308", "355030801", "Um", "1.234", "567", "600"],
            ["3550308", "355030802", "Dois", "2.345,0", "678", "700"],
            ["9999999", "999999999", "Outro", "10", "10", "10"],
        ],
    )

    distritos = builder.load_ibge(path)

    assert set(distritos) == {"UM", "DOIS"}
    assert distritos["UM"] == builder.Distrito("355030801", "Um", 1234, 567)
    assert distritos["DOIS"].populacao == 2345


def test_load_ibge_rejects_missing_column(tmp_path, expected_two):
    path = tmp_path / "ibge.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("agregados.csv", "CD_MUN;CD_DIST;NM_DIST;v0001\n".encode("latin-1"))

    with pytest.raises(SystemExit, match="colunas ausentes"):
        builder.load_ibge(path)


def test_join_requires_exact_name_sets(tmp_path, expected_two):
    geosampa = [("Um", _feature("Um")["geometry"]), ("Dois", _feature("Dois")["geometry"])]
    ibge = {
        "UM": builder.Distrito("355030801", "Um", 100, 10),
        "DOIS": builder.Distrito("355030802", "Dois", 200, 20),
    }
    joined = builder.join_sources(geosampa, ibge)
    assert [item.distrito.distrito_id for item in joined] == ["355030801", "355030802"]

    del ibge["DOIS"]
    with pytest.raises(SystemExit, match="não batem por nome"):
        builder.join_sources(geosampa, ibge)


def test_write_geojson_contract_and_check(tmp_path, expected_two, capsys):
    joins = [
        builder.Joining("Dois", _feature("Dois")["geometry"], builder.Distrito("2", "Dois", 20, 2)),
        builder.Joining("Um", _feature("Um")["geometry"], builder.Distrito("1", "Um", 10, 1)),
    ]
    geojson_path = tmp_path / builder.GEOJSON_FILE
    builder.write_geojson(geojson_path, joins, simplify=0.0)
    builder.write_denominators(tmp_path / builder.POPULACAO_FILE, joins, "populacao", "fonte")
    builder.write_denominators(tmp_path / builder.DOMICILIOS_FILE, joins, "domicilios", "fonte")

    payload = json.loads(geojson_path.read_text(encoding="utf-8"))
    properties = [feature["properties"] for feature in payload["features"]]
    assert [item["bairro_nome"] for item in properties] == ["Dois", "Um"]
    assert properties[0]["bairro_id"] == properties[0]["distrito_id"] == "2"
    assert properties[0]["nivel"] == "distrito"

    assert builder.check(tmp_path) == 0
    assert "2 distritos" in capsys.readouterr().out


def test_check_flags_missing_distrito_id(tmp_path, expected_two, capsys):
    joins = [
        builder.Joining("Um", _feature("Um")["geometry"], builder.Distrito("1", "Um", 10, 1)),
        builder.Joining("Dois", _feature("Dois")["geometry"], builder.Distrito("2", "Dois", 20, 2)),
    ]
    geojson_path = tmp_path / builder.GEOJSON_FILE
    builder.write_geojson(geojson_path, joins, simplify=0.0)
    builder.write_denominators(tmp_path / builder.POPULACAO_FILE, joins, "populacao", "fonte")
    builder.write_denominators(tmp_path / builder.DOMICILIOS_FILE, joins, "domicilios", "fonte")

    payload = json.loads(geojson_path.read_text(encoding="utf-8"))
    payload["features"][0]["properties"].pop("distrito_id")
    geojson_path.write_text(json.dumps(payload), encoding="utf-8")

    assert builder.check(tmp_path) == 1
    assert "sem distrito_id" in capsys.readouterr().out


def test_check_without_files_returns_error(tmp_path):
    assert builder.check(tmp_path) == 1


def test_download_offline_uses_existing_or_fails(tmp_path):
    existing = tmp_path / "fonte.bin"
    existing.write_bytes(b"conteudo")

    source = builder.download("https://example.invalid/fonte", existing, force=False, offline=True)
    assert source.size == len(b"conteudo")
    assert source.sha256 == builder._sha256(existing)

    with pytest.raises(SystemExit, match="offline"):
        builder.download(
            "https://example.invalid/fonte",
            tmp_path / "ausente.bin",
            force=False,
            offline=True,
        )
