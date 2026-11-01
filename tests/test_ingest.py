"""Ingestão ponta a ponta com uma planilha sintética minúscula."""

from __future__ import annotations

import pandas as pd
import pytest

from spseg.data.cache import (
    facts_cache_path,
    load_manifest,
    raw_cache_path,
    read_parquet,
)
from spseg.ingest import find_workbooks, ingest


def _synthetic_rows() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "NUM BO": ["1001", "1002", "1003"],
            "ANO BO": [2024, 2024, 2024],
            "DATA REGISTRO": pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"]),
            "DATA OCORRENCIA BO": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
            "BAIRRO": ["Pinheiros", "Pinheiros", "Centro"],
            "NATUREZA APURADA": ["FURTO - OUTROS", "ROUBO - OUTROS", "FURTO - OUTROS"],
            "NOME MUNICIPIO": ["São Paulo", "S.PAULO", "Campinas"],
            "LATITUDE": [-23.56, -23.57, -22.90],
            "LONGITUDE": [-46.70, -46.69, -47.06],
        }
    )


def _write_workbook(settings, name: str = "SPDadosCriminais_2024.xlsx") -> None:
    path = settings.raw_dir / name
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        _synthetic_rows().to_excel(writer, sheet_name="JAN-DEZ_2024", index=False)


def test_find_workbooks_maps_years(settings):
    _write_workbook(settings)
    workbooks = find_workbooks(settings.raw_dir)
    assert list(workbooks) == [2024]


def test_find_workbooks_rejects_duplicate_year(settings):
    _write_workbook(settings, "SPDadosCriminais_2024_a.xlsx")
    _write_workbook(settings, "SPDadosCriminais_2024_b.xlsx")
    with pytest.raises(ValueError, match="Mais de um arquivo"):
        find_workbooks(settings.raw_dir)


def test_ingest_writes_both_cache_stages_and_manifest(settings):
    _write_workbook(settings)

    results, reference = ingest(settings)

    assert len(results) == 1
    result = results[0]
    assert result.year == 2024
    assert result.rebuilt_raw is True
    assert result.rebuilt_facts is True
    assert result.raw_rows == 2  # capital only
    assert result.facts_rows == 2

    assert raw_cache_path(settings, 2024).exists()
    assert facts_cache_path(settings, 2024).exists()

    facts = read_parquet(facts_cache_path(settings, 2024))
    assert len(facts) == 2
    assert set(facts["municipio"]) == {"São Paulo"}
    assert facts["bairro_method"].tolist() == ["exact", "exact"]
    assert set(facts["bairro_id"]) == {"pinheiros"}
    assert facts["crime_category"].notna().all()
    assert facts["bo_key"].tolist() == ["2024/1001", "2024/1002"]

    manifest = load_manifest(settings)
    assert manifest["sources"]["2024"]["rows"] == 2
    assert manifest["facts"]["2024"]["rows"] == 2
    assert manifest["facts"]["2024"]["reference_version"] == reference.version
    assert manifest["facts"]["2024"]["method_counts"] == {"exact": 2}


def test_second_ingest_reuses_cache(settings):
    _write_workbook(settings)
    ingest(settings)

    results, _reference = ingest(settings)

    assert results[0].rebuilt_raw is False
    assert results[0].rebuilt_facts is False
    assert results[0].raw_rows == 2
    assert results[0].facts_rows == 2


def test_force_rebuilds_both_stages(settings):
    _write_workbook(settings)
    ingest(settings)

    results, _reference = ingest(settings, force=True)

    assert results[0].rebuilt_raw is True
    assert results[0].rebuilt_facts is True


def test_ingest_can_keep_all_municipalities(settings):
    _write_workbook(settings)

    results, _reference = ingest(settings, keep_all_municipalities=True)

    assert results[0].raw_rows == 3


def test_ingest_missing_workbook_raises(settings):
    with pytest.raises(FileNotFoundError, match="Nenhum workbook"):
        ingest(settings)


def test_ingest_year_filter(settings):
    _write_workbook(settings)
    _write_workbook(settings, "SPDadosCriminais_2025.xlsx")

    results, _reference = ingest(settings, years=[2024])

    assert [result.year for result in results] == [2024]
