"""Resolve `BAIRRO` (texto livre) e/ou coordenadas para um distrito canônico."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import pandas as pd
from rapidfuzz import fuzz, process

from spseg.config import (
    BATCH_FUZZY,
    FUZZY_MARGIN,
    FUZZY_SUGGESTION_LIMIT,
    FUZZY_THRESHOLD,
    LAT_MAX,
    LAT_MIN,
    LON_MAX,
    LON_MIN,
)
from spseg.geo.polygons import PolygonIndex
from spseg.geo.text import normalize_key, slugify, suppressed_mask
from spseg.models import RegistryEntry

METHOD_LABELS = {
    "exact": "nome exato",
    "alias": "alias curado",
    "fuzzy": "nome aproximado",
    "geo": "coordenadas",
    "unresolved": "não resolvido",
    "suppressed": "local suprimido",
}


@dataclass(frozen=True)
class _Hit:
    entry: RegistryEntry
    method: str
    confidence: float


class BairroResolver:
    def __init__(
        self,
        entries: Iterable[RegistryEntry],
        *,
        aliases: dict[str, str] | None = None,
        polygons: PolygonIndex | None = None,
        threshold: float = FUZZY_THRESHOLD,
        margin: float = FUZZY_MARGIN,
    ) -> None:
        self.entries: dict[str, RegistryEntry] = {e.bairro_id: e for e in entries}
        self.by_key: dict[str, str] = {}
        for entry in self.entries.values():
            self.by_key.setdefault(normalize_key(entry.bairro_nome), entry.bairro_id)
        self.keys: tuple[str, ...] = tuple(self.by_key)
        self.aliases: dict[str, str] = {
            normalize_key(raw): bairro_id
            for raw, bairro_id in (aliases or {}).items()
            if bairro_id in self.entries and normalize_key(raw)
        }
        self.polygons = polygons
        self.threshold = threshold
        self.margin = margin

    # ------------------------------------------------------------------ consulta

    def find(self, query: str) -> tuple[RegistryEntry, str, float] | None:
        """Resolve um nome digitado pelo usuário (exato, alias ou aproximado)."""
        hit = self._resolve_key(normalize_key(query), fuzzy=True)
        if hit is None:
            return None
        return hit.entry, hit.method, hit.confidence

    def suggestions(
        self, query: str, limit: int = FUZZY_SUGGESTION_LIMIT
    ) -> list[tuple[str, float]]:
        if not self.keys:
            return []
        matches = process.extract(
            normalize_key(query), self.keys, scorer=fuzz.WRatio, limit=limit, score_cutoff=60
        )
        return [(self.entries[self.by_key[key]].bairro_nome, score) for key, score, _ in matches]

    # ------------------------------------------------------------- resolução em lote

    def resolve_frame(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Devolve as colunas de bairro resolvidas, alinhadas ao índice de `frame`."""
        raw = (
            frame["bairro_raw"]
            if "bairro_raw" in frame.columns
            else pd.Series(pd.NA, index=frame.index)
        )
        keys = raw.map(lambda value: normalize_key(value) if pd.notna(value) else "")
        suppressed = suppressed_mask(raw) | keys.eq("").astype(bool)

        unique_keys = pd.Series(keys[~suppressed].unique(), dtype="string")
        resolved: dict[str, tuple] = {}
        for key in unique_keys:
            hit = self._resolve_key(str(key), fuzzy=BATCH_FUZZY)
            if hit is not None:
                resolved[str(key)] = (
                    hit.entry.bairro_id,
                    hit.entry.bairro_nome,
                    hit.entry.distrito_id,
                    hit.method,
                    hit.confidence,
                )

        if resolved:
            resolved_frame = pd.DataFrame(
                [(key, *values) for key, values in resolved.items()],
                columns=[
                    "__key",
                    "bairro_id",
                    "bairro_nome",
                    "distrito_id",
                    "bairro_method",
                    "bairro_confidence",
                ],
            ).set_index("__key")
            joined = pd.DataFrame({"__key": keys.to_numpy()}, index=frame.index).join(
                resolved_frame, on="__key"
            )
        else:
            joined = pd.DataFrame(
                {
                    "bairro_id": pd.NA,
                    "bairro_nome": pd.NA,
                    "distrito_id": pd.NA,
                    "bairro_method": "unresolved",
                    "bairro_confidence": 0.0,
                },
                index=frame.index,
            )

        joined["bairro_method"] = joined["bairro_method"].fillna("unresolved")
        joined["bairro_confidence"] = joined["bairro_confidence"].fillna(0.0)
        joined.loc[suppressed, "bairro_method"] = "suppressed"
        joined.loc[suppressed, "bairro_id"] = pd.NA

        self._apply_geo(frame, suppressed, joined)

        return pd.DataFrame(
            {
                "bairro_id": joined["bairro_id"].astype("string"),
                "bairro_nome": joined["bairro_nome"].astype("string"),
                "distrito_id": joined["distrito_id"].astype("string"),
                "bairro_method": joined["bairro_method"].astype("string"),
                "bairro_confidence": joined["bairro_confidence"].astype("float64"),
            },
            index=frame.index,
        )

    # ------------------------------------------------------------------ internos

    def _resolve_key(self, key: str, *, fuzzy: bool) -> _Hit | None:
        if not key:
            return None
        if key in self.by_key:
            return _Hit(self.entries[self.by_key[key]], "exact", 1.0)
        if key in self.aliases:
            return _Hit(self.entries[self.aliases[key]], "alias", 1.0)
        if not fuzzy or not self.keys:
            return None

        matches = process.extract(key, self.keys, scorer=fuzz.WRatio, limit=2)
        if not matches:
            return None
        best_key, best_score, _ = matches[0]
        if best_score < self.threshold:
            return None
        if len(matches) > 1 and (best_score - matches[1][1]) < self.margin:
            return None  # ambíguo: prefere geo ou "não resolvido"
        entry = self.entries[self.by_key[best_key]]
        return _Hit(entry, "fuzzy", best_score / 100.0)

    def _apply_geo(
        self,
        frame: pd.DataFrame,
        suppressed: pd.Series,
        joined: pd.DataFrame,
    ) -> None:
        """Sobrepõe a resolução por texto quando a coordenada cai num polígono.

        A coordenada é o sinal mais confiável (D3): mesmo que `BAIRRO` case com
        outro distrito, o hit geográfico vence. O texto fica como fallback.
        """
        if self.polygons is None or "latitude" not in frame.columns:
            return
        lat = pd.to_numeric(frame["latitude"], errors="coerce").astype("float64")
        lon = pd.to_numeric(frame["longitude"], errors="coerce").astype("float64")
        inside = (
            lat.between(LAT_MIN, LAT_MAX)
            & lon.between(LON_MIN, LON_MAX)
            & ~((lat == 0) & (lon == 0))
        )
        geo_candidates = ~suppressed & inside
        if not geo_candidates.any():
            return

        pairs = pd.DataFrame({"lat": lat[geo_candidates], "lon": lon[geo_candidates]})
        pairs = pairs.drop_duplicates()
        located: dict[tuple[float, float], object] = {}
        for lat_value, lon_value in pairs.itertuples(index=False, name=None):
            unit = self.polygons.locate(float(lat_value), float(lon_value))
            if unit is not None:
                located[(float(lat_value), float(lon_value))] = unit

        if not located:
            return

        coords = pd.Series(list(zip(lat, lon, strict=False)), index=frame.index)
        units = coords.map(located)
        found = units.notna() & geo_candidates
        if not found.any():
            return

        joined.loc[found, "bairro_id"] = units[found].map(lambda unit: unit.bairro_id)
        joined.loc[found, "bairro_nome"] = units[found].map(lambda unit: unit.bairro_nome)
        joined.loc[found, "distrito_id"] = units[found].map(lambda unit: unit.distrito_id)
        joined.loc[found, "bairro_method"] = "geo"
        joined.loc[found, "bairro_confidence"] = 0.9


def registry_from_frame(frame: pd.DataFrame) -> list[RegistryEntry]:
    """Fallback sem referência: usa as grafias observadas no próprio cache."""
    if "bairro_raw" not in frame.columns:
        return []
    raw = frame["bairro_raw"].dropna().astype("string")
    raw = raw[~suppressed_mask(raw)]
    keys = raw.map(normalize_key)
    valid = keys.ne("")
    if not valid.any():
        return []

    grouped = pd.DataFrame({"key": keys[valid], "raw": raw[valid].str.strip()})
    entries: dict[str, RegistryEntry] = {}
    for key, group in grouped.groupby("key", sort=False):
        display = group["raw"].value_counts().index[0]
        entries[str(key)] = RegistryEntry(
            bairro_id=slugify(str(key)),
            bairro_nome=str(display),
            distrito_id=None,
        )
    return list(entries.values())


def registry_from_entries_frame(frame: pd.DataFrame) -> list[RegistryEntry]:
    """Reconstrói o registro a partir do cache de fatos já enriquecido.

    Quando o mesmo `bairro_id` aparece com grafias diferentes entre anos, usa a
    grafia mais frequente, para o resumo não herdar um "PINHEIROS" maiúsculo.
    """
    if "bairro_id" not in frame.columns or "bairro_nome" not in frame.columns:
        return registry_from_frame(frame)
    subset = frame[["bairro_id", "bairro_nome", "distrito_id"]].dropna(subset=["bairro_id"])
    subset = subset[subset["bairro_nome"].notna()]
    if subset.empty:
        return registry_from_frame(frame)

    entries: list[RegistryEntry] = []
    for bairro_id, group in subset.groupby("bairro_id", sort=False):
        display = group["bairro_nome"].value_counts().index[0]
        districts = group["distrito_id"].dropna()
        entries.append(
            RegistryEntry(
                bairro_id=str(bairro_id),
                bairro_nome=str(display),
                distrito_id=str(districts.iloc[0]) if not districts.empty else None,
            )
        )
    return entries
