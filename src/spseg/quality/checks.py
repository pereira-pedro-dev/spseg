"""Checagens de qualidade da base, independentes da CLI.

As funções devolvem seções com texto pronto para impressão. Elas não alteram
o DataFrame recebido.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from spseg.config import LAT_MAX, LAT_MIN, LON_MAX, LON_MIN
from spseg.geo.text import looks_like_mojibake, normalize_key, suppressed_mask


@dataclass(frozen=True)
class CheckSection:
    title: str
    lines: tuple[str, ...]


def _pct(value: float) -> str:
    return f"{value * 100:.2f}%".replace(".", ",")


def _int(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def check_structure(df: pd.DataFrame, *, context: str, warnings: list[str]) -> CheckSection:
    lines = [f"Origem: {context}", f"Linhas: {_int(len(df))} | Colunas: {len(df.columns)}"]
    if "source_sheet" in df.columns:
        sheets = df["source_sheet"].dropna().unique().tolist()
        lines.append(f"Abas: {sheets}")
    dates = pd.to_datetime(df.get("data_ocorrencia"), errors="coerce")
    if dates.notna().any():
        lines.append(f"Ocorrências de {dates.min():%d/%m/%Y} a {dates.max():%d/%m/%Y}")
    lines.extend(warnings)
    return CheckSection("1. Estrutura e proveniência", tuple(lines))


def check_nulls(df: pd.DataFrame) -> CheckSection:
    nulls = (df.isna().mean() * 100).sort_values(ascending=False)
    lines = [
        f"{column:<32} {pct:6.2f}%" + ("  <--" if pct > 0 else "") for column, pct in nulls.items()
    ]
    return CheckSection("2. Proporção de nulos por coluna", tuple(lines))


def check_bairro_nulls(df: pd.DataFrame) -> CheckSection:
    if "bairro_raw" not in df.columns:
        return CheckSection("3. Nulos em BAIRRO", ("Coluna BAIRRO não encontrada.",))

    total = len(df)
    bairro_null = df["bairro_raw"].isna()
    suppressed = suppressed_mask(df["bairro_raw"])
    lines = [
        f"Total de linhas: {_int(total)}",
        f"BAIRRO nulo: {_int(int(bairro_null.sum()))} ({_pct(bairro_null.mean())})",
        f"BAIRRO suprimido pela SSP (aviso de vedação): {_int(int(suppressed.sum()))}",
    ]
    for column in ("logradouro", "latitude", "longitude"):
        if column not in df.columns:
            continue
        null_column = df[column].isna()
        both = int((bairro_null & null_column).sum())
        only_bairro = int((bairro_null & ~null_column).sum())
        lines.append(
            f"BAIRRO e {column} nulos juntos: {_int(both)} | só BAIRRO nulo: {_int(only_bairro)}"
        )
    if "tipo_local" in df.columns and bairro_null.any():
        lines.append("Top tipos de local com BAIRRO nulo:")
        counts = df.loc[bairro_null, "tipo_local"].fillna("(vazio)").value_counts().head(10)
        lines.extend(f"  {str(name):<30} {_int(int(count))}" for name, count in counts.items())
    return CheckSection("3. Nulos em BAIRRO", tuple(lines))


def check_bairro_text(df: pd.DataFrame) -> CheckSection:
    if "bairro_raw" not in df.columns:
        return CheckSection("4. Texto em BAIRRO", ("Coluna BAIRRO não encontrada.",))
    values = df["bairro_raw"].dropna().astype(str)
    values = values[values.str.strip() != ""]
    keys = values.map(normalize_key)
    mojibake = sorted({value for value in values if looks_like_mojibake(value)})
    lines = [
        f"Valores únicos (brutos): {_int(values.nunique())}",
        f"Valores com possível mojibake: {len(mojibake)}",
        f"Valores únicos (normalizados): {_int(keys.nunique())}",
    ]
    collapsed = values.nunique() - keys.nunique()
    lines.append(f"Variantes colapsadas pela normalização: {_int(max(collapsed, 0))}")
    for value in mojibake[:10]:
        lines.append(f"  mojibake: {value!r}")

    grouped = (
        pd.DataFrame({"key": keys, "raw": values}).drop_duplicates().groupby("key")["raw"].agg(list)
    )
    groups = grouped[grouped.map(len) > 1]
    lines.append(f"{_int(len(groups))} chaves têm mais de uma grafia. Exemplos:")
    for key, variants in list(groups.items())[:10]:
        lines.append(f"  {key}: {variants}")
    return CheckSection("4. Texto em BAIRRO (acentos, caixa, abreviações)", tuple(lines))


def check_duplicate_bo(df: pd.DataFrame) -> CheckSection:
    if "bo_key" not in df.columns:
        return CheckSection("5. BOs duplicados", ("Coluna de chave do BO não encontrada.",))
    counts = df["bo_key"].value_counts()
    total = len(counts)
    repeated = int((counts > 1).sum())
    lines = [
        f"BOs distintos: {_int(total)}",
        f"BOs com mais de uma linha: {_int(repeated)} ({_pct(repeated / total if total else 0)})",
        "Distribuição de linhas por BO:",
    ]
    distribution = counts.value_counts().sort_index()
    lines.extend(
        f"  {int(rows)} linha(s): {_int(int(bos))} BO(s)" for rows, bos in distribution.items()
    )
    return CheckSection("5. Boletins de ocorrência duplicados", tuple(lines))


def check_geolocation(df: pd.DataFrame) -> CheckSection:
    if "latitude" not in df.columns or "longitude" not in df.columns:
        return CheckSection("6. Latitude/longitude", ("Colunas de coordenadas não encontradas.",))
    lat = pd.to_numeric(df["latitude"], errors="coerce")
    lon = pd.to_numeric(df["longitude"], errors="coerce")
    zero_zero = int(((lat == 0) & (lon == 0)).sum())
    outside = int(
        (
            lat.notna()
            & lon.notna()
            & ~(lat.between(LAT_MIN, LAT_MAX) & lon.between(LON_MIN, LON_MAX))
            & ~((lat == 0) & (lon == 0))
        ).sum()
    )
    valid = int(
        (
            lat.notna()
            & lon.notna()
            & lat.between(LAT_MIN, LAT_MAX)
            & lon.between(LON_MIN, LON_MAX)
            & ~((lat == 0) & (lon == 0))
        ).sum()
    )
    lines = [
        f"Lat/long = (0, 0) — possível valor sentinela: {_int(zero_zero)}",
        f"Fora do bounding box aproximado de SP: {_int(outside)}",
        f"Coordenadas válidas: {_int(valid)} ({_pct(valid / len(df) if len(df) else 0)})",
    ]
    return CheckSection("6. Latitude/longitude", tuple(lines))


def check_freshness(df: pd.DataFrame) -> CheckSection:
    lines: list[str] = []
    dates = {}
    for column in ("data_ocorrencia", "data_registro"):
        if column not in df.columns:
            lines.append(f"{column}: coluna não encontrada.")
            continue
        parsed = pd.to_datetime(df[column], errors="coerce")
        dates[column] = parsed
        lines.append(
            f"{column}: {parsed.min():%d/%m/%Y} a {parsed.max():%d/%m/%Y} "
            f"({_int(int(parsed.isna().sum()))} nulos/inválidos)"
        )

    if len(dates) == 2:
        lag = (dates["data_registro"] - dates["data_ocorrencia"]).dt.days
        lines.append(
            f"Atraso registro-fato: mediana {lag.median():.0f} dias | máximo {lag.max():.0f} dias "
            f"| mesmo dia {_pct((lag == 0).mean())}"
        )

    if "data_ocorrencia" in dates:
        by_month = dates["data_ocorrencia"].dt.to_period("M").value_counts().sort_index()
        lines.append("Ocorrências por mês do fato (últimos 12 meses da base):")
        for month, count in by_month.tail(12).items():
            lines.append(f"  {month}: {_int(int(count))}")
        lines.append("Queda nos últimos meses pode ser atraso de inserção, não redução real.")
    return CheckSection("7. Atualidade da base", tuple(lines))


def check_resolution(df: pd.DataFrame) -> CheckSection:
    if "bairro_method" not in df.columns:
        return CheckSection("8. Resolução de bairro", ("Cache sem coluna de resolução.",))
    counts = df["bairro_method"].value_counts()
    lines = [
        f"{str(method):<14} {_int(int(count))} ({_pct(count / len(df))})"
        for method, count in counts.items()
    ]
    return CheckSection("8. Resolução de bairro", tuple(lines))


def run_all(
    df: pd.DataFrame, *, context: str, warnings: list[str] | None = None
) -> list[CheckSection]:
    return [
        check_structure(df, context=context, warnings=warnings or []),
        check_nulls(df),
        check_bairro_nulls(df),
        check_bairro_text(df),
        check_duplicate_bo(df),
        check_geolocation(df),
        check_freshness(df),
        check_resolution(df),
    ]
