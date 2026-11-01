"""Contagens, taxas e tendência por categoria de crime."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd

from spseg.analysis.taxonomy import Taxonomy
from spseg.models import CategorySummary, Period

TREND_THRESHOLD_PCT = 10.0
MIN_CASES_FOR_TREND = 30


def rate(numerator: int, denominator: int | None, per: int) -> float | None:
    if not denominator or denominator <= 0:
        return None
    return numerator / denominator * per


def _trend(dates: pd.Series, period: Period) -> tuple[str | None, float | None, str | None]:
    if dates.empty:
        return None, None, None
    if period.days < 730:
        return None, None, "janela menor que 24 meses"

    end = pd.Timestamp(period.end)
    recent_start = end - timedelta(days=364)
    previous_start = recent_start - timedelta(days=365)
    recent = int(((dates >= recent_start) & (dates <= end)).sum())
    previous = int(((dates >= previous_start) & (dates < recent_start)).sum())

    if recent + previous < MIN_CASES_FOR_TREND:
        return None, None, "poucos casos para tendência"
    if previous == 0:
        return ("up" if recent > 0 else None), None, "sem casos nos 12 meses anteriores"

    change = (recent - previous) / previous * 100
    if change >= TREND_THRESHOLD_PCT:
        return "up", change, "últimos 12 meses vs. 12 anteriores"
    if change <= -TREND_THRESHOLD_PCT:
        return "down", change, "últimos 12 meses vs. 12 anteriores"
    return "flat", change, "últimos 12 meses vs. 12 anteriores"


def summarize_categories(
    frame: pd.DataFrame,
    taxonomy: Taxonomy,
    period: Period,
    *,
    population: int | None,
    households: int | None,
) -> tuple[CategorySummary, ...]:
    dates = pd.to_datetime(frame.get("data_ocorrencia"), errors="coerce")
    categories = frame.get("crime_category")
    summaries: list[CategorySummary] = []

    for category in taxonomy.categories:
        if categories is None:
            subset = frame if category.is_default else frame.iloc[0:0]
        else:
            subset = frame[categories == category.id]
        occurrences = int(len(subset))
        incidents = int(subset["bo_key"].nunique()) if "bo_key" in subset.columns else occurrences
        trend, trend_pct, trend_note = _trend(dates.loc[subset.index], period)

        top = ()
        if "natureza" in subset.columns and occurrences:
            counts = subset["natureza"].fillna("(sem natureza)").value_counts().head(3)
            top = tuple((str(name), int(count)) for name, count in counts.items())

        summaries.append(
            CategorySummary(
                id=category.id,
                label=category.label,
                occurrences=occurrences,
                incidents=incidents,
                rate_per_100k=rate(occurrences, population, 100_000),
                rate_per_10k_households=rate(occurrences, households, 10_000),
                trend=trend,
                trend_pct=trend_pct,
                trend_note=trend_note,
                top_natures=top,
            )
        )
    return tuple(summaries)


def total_incidents(frame: pd.DataFrame) -> int:
    if "bo_key" not in frame.columns:
        return len(frame)
    return int(frame["bo_key"].nunique())
