"""Point-in-polygon sobre os bairros oficiais de São Paulo."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from shapely.geometry import Point, shape
from shapely.strtree import STRtree
from shapely.validation import make_valid

from spseg.config import LAT_MAX, LAT_MIN, LON_MAX, LON_MIN
from spseg.geo.text import normalize_key, slugify

_ID_KEYS = ("bairro_id", "id", "codigo", "cod_bairro", "cd_bairro")
_NAME_KEYS = ("bairro_nome", "nome", "name", "nm_bairro", "bairro")
_DISTRICT_KEYS = ("distrito_id", "cod_distrito", "cd_distrito", "distrito")


@dataclass(frozen=True)
class GeoUnit:
    bairro_id: str
    bairro_nome: str
    distrito_id: str | None = None


def valid_coordinates(lat: float | None, lon: float | None) -> bool:
    if lat is None or lon is None:
        return False
    try:
        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError):
        return False
    if lat == 0 and lon == 0:
        return False
    return LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX


def _first(props: dict, keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = props.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return None


class PolygonIndex:
    """Índice espacial imutável construído a partir de um GeoJSON de bairros."""

    def __init__(self, units: list[GeoUnit], geometries: list) -> None:
        self.units = units
        self._geometries = geometries
        self._tree = STRtree(geometries) if geometries else None

    @classmethod
    def from_geojson(cls, path: Path) -> PolygonIndex:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("type") == "FeatureCollection":
            features = payload.get("features", [])
        elif payload.get("type") == "Feature":
            features = [payload]
        else:
            features = []

        units: list[GeoUnit] = []
        geometries: list = []
        seen: set[str] = set()
        for feature in features:
            geometry = feature.get("geometry")
            if not geometry:
                continue
            properties = feature.get("properties") or {}
            nome = _first(properties, _NAME_KEYS)
            if not nome:
                continue
            bairro_id = _first(properties, _ID_KEYS) or slugify(normalize_key(nome))
            if bairro_id in seen:
                continue
            try:
                geom = shape(geometry)
            except Exception:  # geometria malformada no arquivo de referência
                continue
            if not geom.is_valid:
                geom = make_valid(geom)
            if geom.is_empty:
                continue
            seen.add(bairro_id)
            units.append(
                GeoUnit(
                    bairro_id=bairro_id,
                    bairro_nome=nome,
                    distrito_id=_first(properties, _DISTRICT_KEYS),
                )
            )
            geometries.append(geom)

        return cls(units, geometries)

    def locate(self, lat: float, lon: float) -> GeoUnit | None:
        if self._tree is None:
            return None
        point = Point(lon, lat)
        hits = self._tree.query(point, predicate="intersects")
        if len(hits) == 0:
            return None
        return self.units[int(hits[0])]
