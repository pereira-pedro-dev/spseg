"""Janela temporal do resumo, com avisos de cobertura."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from spseg.models import Period


def _to_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, pd.Timestamp):
        return value
    try:
        return pd.Timestamp(value).date()
    except (TypeError, ValueError):
        return None


def shift_years(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year + years)
    except ValueError:  # 29 de fevereiro
        return value.replace(year=value.year + years, day=28)


def resolve_period(
    dates: pd.Series,
    *,
    since: object = None,
    until: object = None,
    years: int | None = None,
    today: date | None = None,
    coverage_start: object = None,
    coverage_end: object = None,
) -> Period:
    parsed = pd.to_datetime(dates, errors="coerce")
    minimum = parsed.min()
    maximum = parsed.max()
    if pd.isna(minimum) or pd.isna(maximum):
        raise ValueError("Não há datas de ocorrência válidas no período consultado.")

    data_start = _to_date(coverage_start) or minimum.date()
    data_end = maximum.date()
    coverage_note_end = _to_date(coverage_end) or data_end
    today = today or date.today()
    notes: list[str] = []

    end = _to_date(until) or data_end
    if years:
        start = shift_years(end, -years) + timedelta(days=1)
    else:
        start = _to_date(since) or data_start

    if start < data_start:
        notes.append(
            f"início pedido ({start:%d/%m/%Y}) antes da base; usando {data_start:%d/%m/%Y}"
        )
        start = data_start
    if end > data_end:
        notes.append(f"fim pedido ({end:%d/%m/%Y}) depois da base; usando {data_end:%d/%m/%Y}")
        end = data_end
    if start > end:
        raise ValueError(f"Período vazio: início {start:%d/%m/%Y} depois do fim {end:%d/%m/%Y}.")

    partial = end.year >= today.year and end < date(today.year, 12, 31)
    if partial:
        notes.append(
            f"o ano de {end.year} está incompleto: dados até {end:%d/%m/%Y}, "
            "então os últimos meses têm menos ocorrências do que um ano fechado."
        )
    notes.append(f"cobertura dos arquivos: {data_start:%d/%m/%Y} a {coverage_note_end:%d/%m/%Y}.")

    label = f"{start:%d/%m/%Y} → {end:%d/%m/%Y} ({_months(start, end):.0f} meses)"
    return Period(start=start, end=end, label=label, partial=partial, notes=tuple(notes))


def _months(start: date, end: date) -> float:
    return ((end - start).days + 1) / 30.4375
