"""Contrato de colunas: drift entre anos, tipos e filtro da capital."""

from __future__ import annotations

import pandas as pd
import pytest

from spseg.data.schema import (
    SchemaError,
    canonicalize_columns,
    filter_municipio,
    municipio_key,
    normalize_header,
    normalize_municipio,
    year_from_filename,
)


def _base_frame(**overrides) -> pd.DataFrame:
    data = {
        "NUM BO": ["123", "456"],
        "ANO BO": [2024, 2024],
        "DATA REGISTRO": ["2024-01-02", "2024-01-03"],
        "DATA OCORRENCIA BO": ["2024-01-01", "2024-01-02"],
        "BAIRRO": ["Pinheiros", "Vila Mariana"],
        "NATUREZA APURADA": ["FURTO - OUTROS", "ROUBO - OUTROS"],
        "NOME MUNICIPIO": ["São Paulo", "Campinas"],
    }
    data.update(overrides)
    return pd.DataFrame(data)


def test_normalize_header_removes_accents_and_separators():
    assert normalize_header("Nome_Município") == "NOME MUNICIPIO"
    assert normalize_header("  DATA   OCORRÊNCIA  ") == "DATA OCORRENCIA"


def test_canonicalize_2024_and_later_drift():
    frame = _base_frame(
        **{
            "CD IBGE": ["3550308", "3550308"],
            "NOME DELEGACIA CIRCUNCRIÇÃO": ["1º DP", "2º DP"],
        }
    )
    out, _warnings = canonicalize_columns(frame, source="2024")
    assert "cod_ibge" in out.columns
    assert "delegacia_circunscricao" in out.columns
    assert out["cod_ibge"].tolist() == ["3550308", "3550308"]
    assert out["delegacia_circunscricao"].tolist() == ["1º DP", "2º DP"]


def test_canonicalize_2026_spelling_with_s():
    frame = _base_frame(
        **{
            "COD IBGE": ["3550308", "3550308"],
            "NOME DELEGACIA CIRCUNSCRIÇÃO": ["1º DP", "2º DP"],
        }
    )
    out, _warnings = canonicalize_columns(frame, source="2026")
    assert out["delegacia_circunscricao"].tolist() == ["1º DP", "2º DP"]


def test_canonicalize_later_years_cod_ibge():
    frame = _base_frame(**{"COD IBGE": ["3550308", "3550308"]})
    out, _warnings = canonicalize_columns(frame)
    assert "cod_ibge" in out.columns
    assert "CD IBGE" not in out.columns


def test_missing_optional_columns_are_created_and_reported():
    out, warnings = canonicalize_columns(_base_frame())
    for column in ("tipo_local", "conduta", "logradouro", "latitude", "longitude"):
        assert column in out.columns
    assert any("opcionais ausentes" in warning for warning in warnings)


def test_unknown_columns_are_reported_not_fatal():
    frame = _base_frame(**{"COLUNA NOVA": [1, 2]})
    out, warnings = canonicalize_columns(frame)
    assert "COLUNA NOVA" not in out.columns
    assert any("desconhecidas" in warning for warning in warnings)


def test_missing_required_column_raises_with_source():
    frame = _base_frame().drop(columns=["NATUREZA APURADA"])
    with pytest.raises(SchemaError, match="2026"):
        canonicalize_columns(frame, source="2026")


def test_dates_numbers_and_bo_key_are_typed():
    out, _warnings = canonicalize_columns(_base_frame())
    assert str(out["data_ocorrencia"].dtype).startswith("datetime64")
    assert out["ano_bo"].tolist() == [2024, 2024]
    assert out["bo_key"].tolist() == ["2024/123", "2024/456"]


def test_municipio_normalization_and_key():
    assert municipio_key("S.PAULO") == "S PAULO"
    assert municipio_key("São Paulo") == "SAO PAULO"
    assert normalize_municipio("S.PAULO") == "São Paulo"
    assert normalize_municipio("SAO PAULO") == "São Paulo"
    assert normalize_municipio("Campinas") == "Campinas"


def test_filter_municipio_keeps_only_capital():
    out, _warnings = canonicalize_columns(_base_frame())
    capital = filter_municipio(out)
    assert len(capital) == 1
    assert capital["municipio"].tolist() == ["São Paulo"]


def test_year_from_filename():
    assert year_from_filename("SPDadosCriminais_2025.xlsx") == 2025
    assert year_from_filename("sem_ano.xlsx") is None
