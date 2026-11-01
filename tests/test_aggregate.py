"""Contagens, incidentes distintos, taxas e tendência por categoria."""

from __future__ import annotations

from datetime import date

import pandas as pd

from spseg.analysis.aggregate import rate, summarize_categories, total_incidents
from spseg.analysis.taxonomy import DEFAULT_TAXONOMY_DATA, taxonomy_from_dict


def _taxonomy():
    return taxonomy_from_dict(DEFAULT_TAXONOMY_DATA)


def _frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _row(bo: str, date: str, *, category: str = "crime_violento") -> dict:
    return {
        "bo_key": bo,
        "data_ocorrencia": pd.Timestamp(date),
        "crime_category": category,
        "natureza": "ROUBO - OUTROS",
    }


def test_rate_requires_positive_denominator():
    assert rate(10, 100_000, 100_000) == 10.0
    assert rate(10, None, 100_000) is None
    assert rate(10, 0, 100_000) is None


def test_total_incidents_counts_distinct_bo_keys():
    frame = pd.DataFrame({"bo_key": ["1/1", "1/1", "1/2"]})
    assert total_incidents(frame) == 2


def test_summarize_counts_rates_and_top_natures():
    frame = _frame(
        [
            _row("1/1", "2024-06-01"),
            _row("1/2", "2024-06-02"),
            _row("1/3", "2024-06-03"),
            _row("1/4", "2024-06-04", category="crime_nao_violento"),
        ]
    )
    frame.loc[frame["crime_category"] == "crime_nao_violento", "natureza"] = "FURTO - OUTROS"
    period = type("P", (), {"start": date(2024, 1, 1), "end": date(2024, 12, 31), "days": 366})()

    summaries = summarize_categories(
        frame, _taxonomy(), period, population=100_000, households=50_000
    )
    by_id = {summary.id: summary for summary in summaries}

    violent = by_id["crime_violento"]
    assert violent.occurrences == 3
    assert violent.incidents == 3
    assert violent.rate_per_100k == 3.0
    assert violent.rate_per_10k_households == 0.6
    assert violent.top_natures == (("ROUBO - OUTROS", 3),)

    assert by_id["crime_nao_violento"].occurrences == 1
    assert by_id["outros"].occurrences == 0


def test_short_window_skips_trend():
    frame = _frame([_row("1/1", "2024-06-01")])
    period = type("P", (), {"start": date(2024, 1, 1), "end": date(2024, 3, 1), "days": 61})()
    summaries = summarize_categories(frame, _taxonomy(), period, population=None, households=None)
    summary = {item.id: item for item in summaries}["crime_violento"]
    assert summary.trend is None
    assert summary.trend_note == "janela menor que 24 meses"


def test_trend_up_between_years():
    rows = [_row(f"2/{index}", "2024-06-01") for index in range(40)]
    rows += [_row(f"1/{index}", "2023-06-01") for index in range(20)]
    frame = _frame(rows)
    period = type("P", (), {"start": date(2023, 1, 1), "end": date(2025, 1, 1), "days": 732})()

    summaries = summarize_categories(frame, _taxonomy(), period, population=None, households=None)
    summary = {item.id: item for item in summaries}["crime_violento"]
    assert summary.trend == "up"
    assert summary.trend_pct is not None
    assert summary.trend_pct > 10


def test_trend_flat_when_change_is_small():
    rows = [_row(f"2/{index}", "2024-06-01") for index in range(20)]
    rows += [_row(f"1/{index}", "2023-06-01") for index in range(20)]
    frame = _frame(rows)
    period = type("P", (), {"start": date(2023, 1, 1), "end": date(2025, 1, 1), "days": 732})()

    summaries = summarize_categories(frame, _taxonomy(), period, population=None, households=None)
    summary = {item.id: item for item in summaries}["crime_violento"]
    assert summary.trend == "flat"
    assert summary.trend_pct == 0.0
