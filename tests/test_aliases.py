"""Derivação e gravação de aliases bairro→distrito."""

from __future__ import annotations

import pandas as pd
import pytest

from spseg.analysis.aliases import (
    DERIVED_PREFIX,
    derive_aliases,
    merge_alias_rows,
    read_alias_rows,
    write_alias_rows,
)
from spseg.models import RegistryEntry


def _entries() -> list[RegistryEntry]:
    return [
        RegistryEntry("d1", "Distrito Um", "d1"),
        RegistryEntry("d2", "Distrito Dois", "d2"),
    ]


def _facts(rows: list[tuple[str, str, str]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"bairro_raw": raw, "bairro_id": bairro_id, "bairro_method": method}
            for raw, bairro_id, method in rows
        ]
    )


def test_derives_alias_with_support_and_share():
    rows = [("JD TESTE", "d1", "geo")] * 10 + [("JD TESTE", "d2", "geo")]
    report = derive_aliases(_facts(rows), _entries())

    assert len(report.derived) == 1
    alias = report.derived[0]
    assert alias.raw == "JD TESTE"
    assert alias.key == "JARDIM TESTE"
    assert alias.bairro_id == "d1"
    assert alias.n == 10
    assert alias.total == 11
    assert round(alias.share, 3) == 0.909
    assert alias.fonte.startswith(DERIVED_PREFIX)
    assert "n=10" in alias.fonte


def test_rejects_low_share():
    rows = [("BAIRRO DIVIDIDO", "d1", "geo")] * 6 + [("BAIRRO DIVIDIDO", "d2", "geo")] * 4
    report = derive_aliases(_facts(rows), _entries())

    assert not report.derived
    assert [item.reason for item in report.rejected] == ["share_baixo"]


def test_rejects_low_occurrences():
    rows = [("RARO", "d1", "geo")] * 4
    report = derive_aliases(_facts(rows), _entries(), min_n=5)

    assert not report.derived
    assert [item.reason for item in report.rejected] == ["poucas_ocorrencias"]


def test_skips_canonical_names_and_unknown_targets():
    rows = [("Distrito Um", "d1", "geo")] * 5 + [("OUTRO", "d9", "geo")] * 5
    report = derive_aliases(_facts(rows), _entries())

    reasons = {item.key: item.reason for item in report.rejected}
    assert reasons["DISTRITO UM"] == "canonico"
    assert reasons["OUTRO"] == "fora_referencia"


def test_rejects_ambiguous_tie_even_with_low_share_threshold():
    rows = [("EMPATE", "d1", "geo")] * 5 + [("EMPATE", "d2", "geo")] * 5
    report = derive_aliases(_facts(rows), _entries(), min_share=0.5)

    assert not report.derived
    assert [item.reason for item in report.rejected] == ["ambiguo"]


def test_coverage_counts_unresolved_rows_that_alias_would_fix():
    rows = (
        [("JD TESTE", "d1", "geo")] * 5
        + [("JD TESTE", None, "unresolved")] * 2
        + [("SEM PAR", None, "unresolved")]
    )
    frame = _facts(rows)
    frame["bairro_id"] = frame["bairro_id"].astype("string")
    report = derive_aliases(frame, _entries())

    assert report.unresolved_rows == 3
    assert report.covered_rows == 2
    assert report.coverage == pytest.approx(2 / 3)


def test_only_geo_rows_feed_aliases():
    rows = [("TEXTO", "d1", "exact")] * 10 + [("TEXTO", "d1", "alias")] * 10
    report = derive_aliases(_facts(rows), _entries())

    assert not report.derived
    assert not report.rejected


def test_missing_columns_and_bad_thresholds():
    empty = derive_aliases(pd.DataFrame(), _entries())
    assert empty.unresolved_rows == 0

    with pytest.raises(ValueError, match="min_n"):
        derive_aliases(_facts([]), _entries(), min_n=0)
    with pytest.raises(ValueError, match="min_share"):
        derive_aliases(_facts([]), _entries(), min_share=1.5)


def test_merge_preserves_curated_and_replaces_previous_derived():
    existing = [
        {"bairro_raw": "JD TESTE", "bairro_id": "d2", "fonte": "curado"},
        {"bairro_raw": "ANTIGO", "bairro_id": "d1", "fonte": f"{DERIVED_PREFIX} n=9 share=1.00"},
    ]
    rows = [("JD TESTE", "d1", "geo")] * 5 + [("NOVO", "d2", "geo")] * 5
    report = derive_aliases(_facts(rows), _entries())

    merged = merge_alias_rows(existing, report.derived)
    by_raw = {row["bairro_raw"]: row for row in merged}

    assert by_raw["JD TESTE"]["bairro_id"] == "d2"
    assert by_raw["JD TESTE"]["fonte"] == "curado"
    assert "ANTIGO" not in by_raw
    assert by_raw["NOVO"]["bairro_id"] == "d2"
    assert by_raw["NOVO"]["fonte"].startswith(DERIVED_PREFIX)


def test_write_and_read_alias_rows(tmp_path):
    path = tmp_path / "aliases.csv"
    written = write_alias_rows(
        path,
        [{"bairro_raw": "JD TESTE", "bairro_id": "d1", "fonte": "curado"}],
    )

    assert written == 1
    assert read_alias_rows(path) == [
        {"bairro_raw": "JD TESTE", "bairro_id": "d1", "fonte": "curado"}
    ]
    assert read_alias_rows(tmp_path / "missing.csv") == []
