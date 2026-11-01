"""Contrato de colunas: nomes canônicos, tipos e drift entre anos da SSP."""

from __future__ import annotations

import re
import unicodedata

import pandas as pd

from spseg.config import DEFAULT_MUNICIPIO


class SchemaError(ValueError):
    """A planilha não tem as colunas mínimas esperadas."""


# chave = cabeçalho normalizado (sem acento, maiúsculo, "_" -> espaço)
COLUMN_ALIASES: dict[str, str] = {
    "NOME DEPARTAMENTO": "departamento",
    "NOME SECCIONAL": "seccional",
    "NOME DELEGACIA": "delegacia",
    "NOME MUNICIPIO": "municipio",
    "NUM BO": "num_bo",
    "ANO BO": "ano_bo",
    "DATA REGISTRO": "data_registro",
    "DATA OCORRENCIA BO": "data_ocorrencia",
    "HORA OCORRENCIA BO": "hora_ocorrencia",
    "DESC PERIODO": "periodo_dia",
    "DESCR TIPOLOCAL": "tipo_local",
    "DESCR SUBTIPOLOCAL": "subtipo_local",
    "BAIRRO": "bairro_raw",
    "LOGRADOURO": "logradouro",
    "NUMERO LOGRADOURO": "numero_logradouro",
    "LATITUDE": "latitude",
    "LONGITUDE": "longitude",
    "NOME DELEGACIA CIRCUNSCRICAO": "delegacia_circunscricao",
    "NOME DEPARTAMENTO CIRCUNSCRICAO": "departamento_circunscricao",
    "NOME SECCIONAL CIRCUNSCRICAO": "seccional_circunscricao",
    "NOME MUNICIPIO CIRCUNSCRICAO": "municipio_circunscricao",
    # 2024/2025 trazem a grafia sem o "S" (CIRCUNCRIÇÃO).
    "NOME DELEGACIA CIRCUNCRICAO": "delegacia_circunscricao",
    "NOME DEPARTAMENTO CIRCUNCRICAO": "departamento_circunscricao",
    "NOME SECCIONAL CIRCUNCRICAO": "seccional_circunscricao",
    "NOME MUNICIPIO CIRCUNCRICAO": "municipio_circunscricao",
    "RUBRICA": "rubrica",
    "DESCR CONDUTA": "conduta",
    "NATUREZA APURADA": "natureza",
    "MES ESTATISTICA": "mes_estatistica",
    "ANO ESTATISTICA": "ano_estatistica",
    "CMD": "cmd",
    "BTL": "btl",
    "CIA": "cia",
    "COD IBGE": "cod_ibge",
    "CD IBGE": "cod_ibge",
}

REQUIRED_COLUMNS = ("num_bo", "ano_bo", "data_ocorrencia", "bairro_raw", "natureza", "municipio")
TEXT_COLUMNS = (
    "departamento",
    "seccional",
    "delegacia",
    "num_bo",
    "hora_ocorrencia",
    "periodo_dia",
    "tipo_local",
    "subtipo_local",
    "bairro_raw",
    "logradouro",
    "numero_logradouro",
    "delegacia_circunscricao",
    "departamento_circunscricao",
    "seccional_circunscricao",
    "municipio_circunscricao",
    "rubrica",
    "conduta",
    "natureza",
    "cod_ibge",
    "cmd",
    "btl",
    "cia",
)
DATE_COLUMNS = ("data_registro", "data_ocorrencia")
INT_COLUMNS = ("ano_bo", "mes_estatistica", "ano_estatistica")
FLOAT_COLUMNS = ("latitude", "longitude")

# Municípios da capital, em grafias que aparecem na base.
MUNICIPIO_CANONICAL: dict[str, str] = {
    "SAO PAULO": DEFAULT_MUNICIPIO,
    "S PAULO": DEFAULT_MUNICIPIO,
    "SP": DEFAULT_MUNICIPIO,
}

_SPACES_RE = re.compile(r"\s+")


def normalize_header(name: object) -> str:
    text = unicodedata.normalize("NFKD", str(name))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.upper().replace("_", " ")
    return _SPACES_RE.sub(" ", text).strip()


def municipio_key(value: object) -> str:
    """Chave de comparação de município (ex.: 'S.PAULO' -> 'SAO PAULO')."""
    if value is None or (isinstance(value, float) and value != value):
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^A-Za-z ]+", " ", text).upper()
    return _SPACES_RE.sub(" ", text).strip()


def normalize_municipio(value: object) -> str:
    key = municipio_key(value)
    return MUNICIPIO_CANONICAL.get(key, str(value).strip().title() if key else "")


def canonicalize_columns(
    df: pd.DataFrame, *, source: str = "planilha"
) -> tuple[pd.DataFrame, list[str]]:
    """Renomeia para o vocabulário canônico, adiciona colunas ausentes e avisa."""
    rename: dict[object, str] = {}
    used: set[str] = set()
    unknown: list[str] = []
    for column in df.columns:
        target = COLUMN_ALIASES.get(normalize_header(column))
        if target is None:
            unknown.append(str(column))
            continue
        if target in used:
            continue
        rename[column] = target
        used.add(target)

    out = df.rename(columns=rename)
    out = out.loc[:, [c for c in out.columns if c in set(rename.values())]]

    warnings: list[str] = []
    missing_required = [c for c in REQUIRED_COLUMNS if c not in out.columns]
    if missing_required:
        raise SchemaError(
            f"{source}: colunas obrigatórias ausentes: {missing_required}. "
            f"Colunas não reconhecidas: {unknown or 'nenhuma'}."
        )

    for column in (*TEXT_COLUMNS, *DATE_COLUMNS, *INT_COLUMNS, *FLOAT_COLUMNS):
        if column not in out.columns:
            out[column] = pd.NA

    for column in TEXT_COLUMNS:
        out[column] = out[column].astype("string").str.strip()

    for column in DATE_COLUMNS:
        out[column] = pd.to_datetime(out[column], errors="coerce", format="mixed")

    for column in INT_COLUMNS:
        out[column] = pd.to_numeric(out[column], errors="coerce").astype("Int64")

    for column in FLOAT_COLUMNS:
        out[column] = pd.to_numeric(out[column], errors="coerce")

    out["municipio"] = out["municipio"].where(
        out["municipio"].isna(), out["municipio"].map(normalize_municipio)
    )
    out["municipio_key"] = out["municipio"].map(municipio_key)
    out["bo_key"] = out["ano_bo"].astype("string").fillna("") + "/" + out["num_bo"].fillna("")

    missing_optional = [
        c for c in ("tipo_local", "conduta", "logradouro", "latitude", "longitude") if c not in used
    ]
    if missing_optional:
        warnings.append(
            f"{source}: colunas opcionais ausentes, preenchidas vazias: {missing_optional}"
        )
    if unknown:
        warnings.append(f"{source}: colunas ignoradas (desconhecidas): {unknown}")
    return out, warnings


def filter_municipio(df: pd.DataFrame, municipio: str = DEFAULT_MUNICIPIO) -> pd.DataFrame:
    target = normalize_municipio(municipio)
    return df[df["municipio"] == target].copy()


def year_from_filename(path: object) -> int | None:
    match = re.search(r"(\d{4})", str(path))
    return int(match.group(1)) if match else None
