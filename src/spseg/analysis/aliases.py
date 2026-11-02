"""Deriva aliases de bairro a partir de registros resolvidos por coordenada.

A coordenada é a fonte de verdade do mapeamento bairro→distrito (D5). O script
`scripts/build_aliases.py` usa este módulo para gerar `bairro_aliases.csv` sem
inventar mapeamentos: só entram grafias com suporte mínimo e maioria clara.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from spseg.geo.text import normalize_key, suppressed_mask
from spseg.models import RegistryEntry

DERIVED_PREFIX = "derivado:geo"
MIN_OCCURRENCES = 5
MIN_SHARE = 0.85

REASON_LABELS = {
    "poucas_ocorrencias": "ocorrências abaixo do mínimo",
    "share_baixo": "distrito modal abaixo do share mínimo",
    "canonico": "já é nome canônico (exato)",
    "fora_referencia": "distrito fora da referência",
    "ambiguo": "empate entre distritos",
}


@dataclass(frozen=True)
class DerivedAlias:
    raw: str
    key: str
    bairro_id: str
    n: int
    total: int
    share: float

    @property
    def fonte(self) -> str:
        return f"{DERIVED_PREFIX} n={self.n} share={self.share:.2f}"


@dataclass(frozen=True)
class RejectedAlias:
    raw: str
    key: str
    bairro_id: str
    n: int
    total: int
    share: float
    reason: str


@dataclass(frozen=True)
class AliasReport:
    derived: tuple[DerivedAlias, ...]
    rejected: tuple[RejectedAlias, ...]
    candidate_shares: tuple[float, ...]
    unresolved_rows: int
    covered_rows: int

    @property
    def coverage(self) -> float | None:
        if not self.unresolved_rows:
            return None
        return self.covered_rows / self.unresolved_rows


def _empty_report(unresolved_rows: int = 0) -> AliasReport:
    return AliasReport((), (), (), unresolved_rows, 0)


def derive_aliases(
    facts: pd.DataFrame,
    entries: Iterable[RegistryEntry],
    *,
    min_n: int = MIN_OCCURRENCES,
    min_share: float = MIN_SHARE,
) -> AliasReport:
    """Agrupa grafias resolvidas por geo e devolve aliases com suporte mínimo."""
    if min_n < 1:
        raise ValueError("min_n deve ser >= 1.")
    if not 0 < min_share <= 1:
        raise ValueError("min_share deve estar entre 0 e 1.")

    required = {"bairro_raw", "bairro_id", "bairro_method"}
    if facts.empty or not required.issubset(facts.columns):
        return _empty_report()

    registry = list(entries)
    known_ids = {entry.bairro_id for entry in registry}
    canonical = {normalize_key(entry.bairro_nome): entry.bairro_id for entry in registry}

    eligible = facts.loc[
        facts["bairro_method"].eq("geo") & facts["bairro_id"].notna() & facts["bairro_raw"].notna(),
        ["bairro_raw", "bairro_id"],
    ].copy()
    eligible["raw"] = eligible["bairro_raw"].astype("string").str.strip()
    eligible = eligible[eligible["raw"].ne("") & ~suppressed_mask(eligible["raw"])]
    eligible["key"] = eligible["raw"].map(normalize_key)
    eligible = eligible[eligible["key"].ne("")]

    derived: list[DerivedAlias] = []
    rejected: list[RejectedAlias] = []
    shares: list[float] = []
    if not eligible.empty:
        for key, group in eligible.groupby("key", sort=True):
            total = len(group)
            by_id = group["bairro_id"].astype(str).value_counts()
            top = by_id[by_id == by_id.max()]
            target = str(top.index[0])
            n = int(top.iloc[0])
            share = n / total
            shares.append(share)

            spellings = group["raw"].value_counts()
            raw = sorted(spellings[spellings == spellings.max()].index)[0]

            reason = None
            if known_ids and target not in known_ids:
                reason = "fora_referencia"
            elif key in canonical:
                reason = "canonico"
            elif len(top) > 1:
                reason = "ambiguo"
            elif n < min_n:
                reason = "poucas_ocorrencias"
            elif share < min_share:
                reason = "share_baixo"

            candidate = DerivedAlias(
                raw=str(raw),
                key=str(key),
                bairro_id=target,
                n=n,
                total=total,
                share=share,
            )
            if reason is None:
                derived.append(candidate)
            else:
                rejected.append(
                    RejectedAlias(
                        raw=candidate.raw,
                        key=candidate.key,
                        bairro_id=candidate.bairro_id,
                        n=candidate.n,
                        total=candidate.total,
                        share=candidate.share,
                        reason=reason,
                    )
                )

    unresolved = facts["bairro_method"].eq("unresolved")
    unresolved_rows = int(unresolved.sum())
    covered_rows = 0
    if unresolved_rows:
        keys = facts.loc[unresolved, "bairro_raw"].astype("string").fillna("").map(normalize_key)
        derived_keys = {alias.key for alias in derived}
        covered_rows = int(keys.isin(derived_keys).sum())

    return AliasReport(
        derived=tuple(derived),
        rejected=tuple(rejected),
        candidate_shares=tuple(sorted(shares)),
        unresolved_rows=unresolved_rows,
        covered_rows=covered_rows,
    )


def merge_alias_rows(
    existing: Iterable[dict[str, str]], derived: Iterable[DerivedAlias]
) -> list[dict[str, str]]:
    """Mantém aliases curados e substitui apenas os gerados anteriormente."""
    rows: list[dict[str, str]] = []
    seen: set[str] = set()

    for row in existing:
        raw = str(row.get("bairro_raw") or "").strip()
        target = str(row.get("bairro_id") or "").strip()
        source = str(row.get("fonte") or "").strip()
        key = normalize_key(raw)
        if not raw or not target or not key or key in seen:
            continue
        if source.startswith(DERIVED_PREFIX):
            continue
        seen.add(key)
        rows.append({"bairro_raw": raw, "bairro_id": target, "fonte": source})

    for alias in sorted(derived, key=lambda item: item.key):
        if alias.key in seen:
            continue
        seen.add(alias.key)
        rows.append(
            {
                "bairro_raw": alias.raw,
                "bairro_id": alias.bairro_id,
                "fonte": alias.fonte,
            }
        )

    rows.sort(key=lambda row: normalize_key(row["bairro_raw"]))
    return rows


def read_alias_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader]


def write_alias_rows(path: Path, rows: Iterable[dict[str, str]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    materialized = list(rows)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["bairro_raw", "bairro_id", "fonte"])
        writer.writeheader()
        writer.writerows(materialized)
    return len(materialized)
